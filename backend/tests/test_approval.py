"""Phase 7 purchase-requisition approval workflow tests.

Covers the acceptance list from the Phase 7 spec (§二十): department-manager
approval, the full approve validation chain (re-validate business data after
submit), reject with mandatory comment, revise (REJECTED -> DRAFT), approval
history scoping, department-scoped list ranges, optimistic-lock 409s,
concurrent approve-vs-approve and approve-vs-reject atomicity, and the
append-only nature of approval_records (no write API surface).

Helper users (from init_data):
- zhangsan: APPLICANT @ RD (creates PRs)
- lisi:     DEPT_MANAGER @ RD (RD department manager, can approve)
- wangwu:   BUYER @ PUR (pr:view but no pr:approve / pr:reject)
- zhaoliu:  WAREHOUSE @ WH (no pr:view at all)
- admin:    ADMIN (full permissions + admin override)
Tests additionally create ``purmgr`` (DEPT_MANAGER @ PUR) so a manager of an
UNRELATED department exists for 403 scenarios.
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    ApprovalRecord,
    DepartmentManager,
    OperationLog,
    PurchaseRequisitionItem,
    Role,
    User,
)
from app.utils.enums import AuditAction, RoleCode
from cleanup_helper import wipe_chain


# ----------------------------------------------------------------------
# helpers (same patterns as test_purchase_requisition.py)
# ----------------------------------------------------------------------
def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clean_prs() -> None:
    """Wipe PR + items + approval_records (and any leftover PO data: sources
    FK RESTRICT blocks PR item deletion, Phase 8; receipts + ledger rows block
    PO deletion, Phase 9) before each test."""
    with SessionLocal() as s:
        wipe_chain(s, with_balances=False)
        s.commit()


def _create_material(client: TestClient, headers: dict, name: str = "PR审批测试物料") -> dict:
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": name, "unit": "pcs"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _disable_material(client: TestClient, headers: dict, material_id: int) -> None:
    r = client.post(f"/api/v1/materials/{material_id}/disable", headers=headers)
    assert r.status_code == 200, r.text


def _mk_pr(client: TestClient, headers: dict, material_id: int, qty="10", price="12.3456", **kw) -> dict:
    payload = {"items": [{"material_id": material_id, "requested_quantity": qty,
                          "estimated_unit_price": price}], **kw}
    r = client.post("/api/v1/purchase-requisitions", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _submit(client: TestClient, headers: dict, pr_id: int) -> dict:
    r = client.post(f"/api/v1/purchase-requisitions/{pr_id}/submit", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk_pending_pr(client: TestClient, z_headers: dict, mid: int, **kw) -> dict:
    """Create + submit → PENDING (version becomes 2)."""
    pr = _mk_pr(client, z_headers, mid, **kw)
    submitted = _submit(client, z_headers, pr["id"])
    assert submitted["status"] == "PENDING"
    return submitted


def _audit_actions(pr_no: str) -> set[str]:
    with SessionLocal() as s:
        s.rollback()  # 结束 REPEATABLE READ 快照，看到 API 会话新提交
        rows = s.execute(
            select(OperationLog.action).where(OperationLog.document_no == pr_no)
        ).scalars().all()
    return {a.value for a in rows}


def _role_id(code: RoleCode) -> int:
    with SessionLocal() as s:
        return s.execute(select(Role.id).where(Role.role_code == code)).scalar_one()


def _dept_id(code: str) -> int:
    from app.models import Department

    with SessionLocal() as s:
        return s.execute(select(Department.id).where(Department.dept_code == code)).scalar_one()


def _ensure_purmgr(client: TestClient) -> None:
    """Create a DEPT_MANAGER of PUR (unrelated to RD) once per session run."""
    admin_h = _auth(_login(client))
    pur_id = _dept_id("PUR")
    mgr_role_id = _role_id(RoleCode.DEPT_MANAGER)
    with SessionLocal() as s:
        exists = s.execute(select(User.id).where(User.username == "purmgr")).scalar_one_or_none()
    if exists is None:
        r = client.post("/api/v1/users", headers=admin_h, json={
            "username": "purmgr", "password": "demo123", "real_name": "采购部主管",
            "department_id": pur_id, "role_id": mgr_role_id,
        })
        assert r.status_code == 200, r.text
        uid = r.json()["data"]["id"]
        with SessionLocal() as s:
            link = s.execute(select(DepartmentManager.id).where(
                DepartmentManager.dept_id == pur_id,
                DepartmentManager.user_id == uid,
            )).scalar_one_or_none()
            if link is None:
                s.add(DepartmentManager(dept_id=pur_id, user_id=uid, is_primary=True))
                s.commit()


def _approval_records(pr_id: int) -> list[ApprovalRecord]:
    with SessionLocal() as s:
        s.rollback()
        return list(s.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.document_id == pr_id)
            .order_by(ApprovalRecord.created_at.asc(), ApprovalRecord.id.asc())
        ).scalars().all())


# ----------------------------------------------------------------------
# 1-5: approve happy path
# ----------------------------------------------------------------------
def test_dept_manager_approve_success(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "APPROVED"
    assert d["version"] == pr["version"] + 1


def test_approve_transition_pending_to_approved(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "APPROVED"


def test_approve_writes_approval_record(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200
    recs = _approval_records(pr["id"])
    assert len(recs) == 1
    rec = recs[0]
    assert rec.action.value == "APPROVE"
    assert rec.from_status == "PENDING"
    assert rec.to_status == "APPROVED"
    assert rec.result_status == "APPROVED"
    assert rec.document_no == pr["pr_no"]
    assert rec.step_name == "部门主管审批"


def test_approve_writes_pr_approve_audit(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200
    actions = _audit_actions(pr["pr_no"])
    assert AuditAction.PR_APPROVE.value in actions
    assert AuditAction.PR_SUBMIT.value in actions
    assert AuditAction.PR_CREATE.value in actions


def test_approve_comment_optional(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    # 不带 comment
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200
    recs = _approval_records(pr["id"])
    assert recs[0].comment is None
    # 带 comment 也成功
    pr2 = _mk_pending_pr(client, z, mid)
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr2['id']}/approve", headers=lisi,
                     json={"version": pr2["version"], "comment": "同意"})
    assert r2.status_code == 200
    assert _approval_records(pr2["id"])[0].comment == "同意"


# ----------------------------------------------------------------------
# 6-8: approve 403 matrix
# ----------------------------------------------------------------------
def test_approve_by_manager_of_other_department_403(client: TestClient, db) -> None:
    _clean_prs()
    _ensure_purmgr(client)
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # RD PR
    purmgr = _auth(_login(client, "purmgr", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=purmgr,
                    json={"version": pr["version"]})
    assert r.status_code == 403
    assert r.json()["code"] == 4007  # PR_NOT_APPROVER


def test_approve_by_plain_applicant_403(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    # zhangsan 是 APPLICANT，无 pr:approve → RBAC 第一层 403
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=z,
                    json={"version": pr["version"]})
    assert r.status_code == 403


def test_approve_without_permission_403(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    wangwu = _auth(_login(client, "wangwu", "demo123"))  # BUYER 无 pr:approve
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=wangwu,
                    json={"version": pr["version"]})
    assert r.status_code == 403


# ----------------------------------------------------------------------
# 9-12: approve business validation
# ----------------------------------------------------------------------
def test_approve_draft_409(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pr(client, z, mid)  # DRAFT, version=1
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 409
    assert r.json()["code"] == 4002  # PR_INVALID_STATUS_TRANSITION


def test_approve_approved_again_409(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r1 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                     json={"version": pr["version"]})
    assert r1.status_code == 200
    new_version = r1.json()["data"]["version"]
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                     json={"version": new_version})
    assert r2.status_code == 409
    assert r2.json()["code"] == 4002


def test_approve_fails_when_material_disabled_after_submit(client: TestClient, db) -> None:
    _clean_prs()
    admin_h = _auth(_login(client))
    mid = _create_material(client, admin_h)["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    _disable_material(client, admin_h, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 409
    assert r.json()["code"] == 3009  # MASTER_DATA_DISABLED


def test_approve_recomputes_amount(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid, qty="10", price="12.3456")  # 123.46
    # 篡改 DB 中的金额，approve 必须服务端重算恢复权威值
    with SessionLocal() as s:
        it = s.execute(
            select(PurchaseRequisitionItem).where(PurchaseRequisitionItem.pr_id == pr["id"])
        ).scalar_one()
        it.estimated_amount = Decimal("999.99")
        s.commit()
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total_estimated_amount"] == "123.46"


# ----------------------------------------------------------------------
# 13-19: reject
# ----------------------------------------------------------------------
def test_reject_success_pending_to_rejected(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"], "comment": "价格不合理"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "REJECTED"
    assert d["version"] == pr["version"] + 1


def test_reject_comment_required(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"]})  # 缺 comment
    assert r.status_code == 422


def test_reject_blank_comment_fails(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    for blank in ("", "   ", "\t\n"):
        r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                        json={"version": pr["version"], "comment": blank})
        assert r.status_code == 422, repr(blank)


def test_reject_writes_approval_record(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"], "comment": "数量需调整"})
    assert r.status_code == 200
    recs = _approval_records(pr["id"])
    assert len(recs) == 1
    rec = recs[0]
    assert rec.action.value == "REJECT"
    assert rec.from_status == "PENDING"
    assert rec.to_status == "REJECTED"
    assert rec.comment == "数量需调整"


def test_reject_writes_pr_reject_audit(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"], "comment": "驳回"})
    assert r.status_code == 200
    assert AuditAction.PR_REJECT.value in _audit_actions(pr["pr_no"])


def test_reject_by_manager_of_other_department_403(client: TestClient, db) -> None:
    _clean_prs()
    _ensure_purmgr(client)
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # RD PR
    purmgr = _auth(_login(client, "purmgr", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=purmgr,
                    json={"version": pr["version"], "comment": "不是本部门"})
    assert r.status_code == 403
    assert r.json()["code"] == 4007


def test_reject_allowed_even_when_material_disabled(client: TestClient, db) -> None:
    _clean_prs()
    admin_h = _auth(_login(client))
    mid = _create_material(client, admin_h)["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    _disable_material(client, admin_h, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"], "comment": "物料已停用，驳回"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "REJECTED"


# ----------------------------------------------------------------------
# 20-27: revise (REJECTED -> DRAFT) + resubmit
# ----------------------------------------------------------------------
def _mk_rejected_pr(client: TestClient, z: dict, mid: int) -> tuple[dict, dict]:
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                    json={"version": pr["version"], "comment": "驳回"})
    assert r.status_code == 200
    return pr, lisi


def test_revise_success_rejected_to_draft(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    rejected_version = pr["version"] + 1
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": rejected_version})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "DRAFT"
    assert d["version"] == rejected_version + 1


def test_revise_clears_submitted_at(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    assert pr["submitted_at"] is not None
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    assert r.json()["data"]["submitted_at"] is None


def test_revise_increments_version(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    assert r.json()["data"]["version"] == pr["version"] + 2


def test_revise_by_non_applicant_403(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=lisi,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 403
    assert r.json()["code"] == 4005  # PR_NOT_APPLICANT


def test_revise_approved_409(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": pr["version"]})
    assert r.status_code == 200
    new_version = r.json()["data"]["version"]
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                     json={"version": new_version})
    assert r2.status_code == 409
    assert r2.json()["code"] == 4002


def test_revise_then_edit(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    draft_version = r.json()["data"]["version"]
    # 编辑必须引用稳定行 id（_sync_items 语义：id 缺失视为追加新行）
    detail = client.get(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z).json()["data"]
    item_id = detail["items"][0]["id"]
    r2 = client.put(f"/api/v1/purchase-requisitions/{pr['id']}", headers=z, json={
        "version": draft_version,
        "items": [{"id": item_id, "material_id": mid,
                   "requested_quantity": "5", "estimated_unit_price": "2"}],
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "DRAFT"


def test_revise_then_resubmit(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    draft_version = r.json()["data"]["version"]
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "PENDING"
    assert r2.json()["data"]["version"] == draft_version + 1


def test_resubmit_sets_new_submitted_at(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr, _ = _mk_rejected_pr(client, z, mid)
    first_submitted_at = datetime.fromisoformat(pr["submitted_at"].replace("Z", "+00:00"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r2.status_code == 200
    second_submitted_at = datetime.fromisoformat(
        r2.json()["data"]["submitted_at"].replace("Z", "+00:00")
    )
    assert second_submitted_at > first_submitted_at


# ----------------------------------------------------------------------
# 28-29: approval history
# ----------------------------------------------------------------------
def test_approval_history_ordered(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    # reject → revise → resubmit → approve：历史应为 [REJECT, APPROVE] 升序
    pr, _ = _mk_rejected_pr(client, z, mid)
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/revise", headers=z,
                    json={"version": pr["version"] + 1})
    assert r.status_code == 200
    r2 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/submit", headers=z)
    assert r2.status_code == 200
    new_pending = r2.json()["data"]
    lisi = _auth(_login(client, "lisi", "demo123"))
    r3 = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                     json={"version": new_pending["version"]})
    assert r3.status_code == 200
    r4 = client.get(f"/api/v1/purchase-requisitions/{pr['id']}/approvals", headers=z)
    assert r4.status_code == 200
    items = r4.json()["data"]
    assert [i["action"] for i in items] == ["REJECT", "APPROVE"]
    times = [datetime.fromisoformat(i["created_at"].replace("Z", "+00:00")) for i in items]
    assert times == sorted(times)
    assert items[0]["comment"] == "驳回"
    assert items[0]["from_status"] == "PENDING" and items[0]["to_status"] == "REJECTED"
    assert items[1]["from_status"] == "PENDING" and items[1]["to_status"] == "APPROVED"


def test_approval_history_requires_pr_view_permission(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    # zhaoliu（WAREHOUSE）无 pr:view → RBAC 403
    zhaoliu = _auth(_login(client, "zhaoliu", "demo123"))
    r = client.get(f"/api/v1/purchase-requisitions/{pr['id']}/approvals", headers=zhaoliu)
    assert r.status_code == 403
    # zhangsan 有 pr:view 但只能看自己的 PR：看别人 PR 的历史 → 对象级 403
    _ensure_purmgr(client)
    purmgr = _auth(_login(client, "purmgr", "demo123"))
    other = _mk_pending_pr(client, purmgr, mid)  # PUR 部门 PR
    r2 = client.get(f"/api/v1/purchase-requisitions/{other['id']}/approvals", headers=z)
    assert r2.status_code == 403
    assert r2.json()["code"] == 4005


# ----------------------------------------------------------------------
# 30-32: list scoping
# ----------------------------------------------------------------------
def test_dept_manager_sees_own_dept_pending_prs(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # RD
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.get("/api/v1/purchase-requisitions", headers=lisi, params={"status": "PENDING"})
    assert r.status_code == 200
    nos = [i["pr_no"] for i in r.json()["data"]["items"]]
    assert pr["pr_no"] in nos


def test_dept_manager_cannot_see_unrelated_dept_prs(client: TestClient, db) -> None:
    _clean_prs()
    _ensure_purmgr(client)
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # RD PR
    purmgr = _auth(_login(client, "purmgr", "demo123"))
    r = client.get("/api/v1/purchase-requisitions", headers=purmgr, params={"status": "PENDING"})
    assert r.status_code == 200
    nos = [i["pr_no"] for i in r.json()["data"]["items"]]
    assert pr["pr_no"] not in nos


def test_admin_sees_all_prs(client: TestClient, db) -> None:
    _clean_prs()
    _ensure_purmgr(client)
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    purmgr = _auth(_login(client, "purmgr", "demo123"))
    pr2 = _mk_pending_pr(client, purmgr, mid)
    admin_h = _auth(_login(client))
    r = client.get("/api/v1/purchase-requisitions", headers=admin_h, params={"status": "PENDING"})
    assert r.status_code == 200
    nos = {i["pr_no"] for i in r.json()["data"]["items"]}
    assert pr["pr_no"] in nos and pr2["pr_no"] in nos


# ----------------------------------------------------------------------
# 33-35: optimistic lock + concurrency
# ----------------------------------------------------------------------
def test_approve_stale_version_409(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # version=2
    lisi = _auth(_login(client, "lisi", "demo123"))
    r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                    json={"version": 1})  # 旧 version
    assert r.status_code == 409
    assert r.json()["code"] == 4011  # PR_VERSION_CONFLICT


def test_concurrent_approve_only_one_succeeds(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    version = pr["version"]
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                        json={"version": version})
        results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1
    assert results.count(409) == 7


def test_concurrent_approve_vs_reject_only_one_succeeds(client: TestClient, db) -> None:
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi = _auth(_login(client, "lisi", "demo123"))
    version = pr["version"]
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        barrier.wait()
        if i % 2 == 0:
            r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                            json={"version": version})
        else:
            r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/reject", headers=lisi,
                            json={"version": version, "comment": "并发驳回"})
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 1
    assert results.count(409) == 7


# ----------------------------------------------------------------------
# 36: append-only approval records (no write API surface)
# ----------------------------------------------------------------------
def test_approval_records_have_no_write_api(client: TestClient, db) -> None:
    _clean_prs()
    paths = set(client.app.openapi()["paths"].keys())
    assert not any("/approval-records" in p for p in paths)
    assert not any(p.endswith("/approvals") and not p.endswith("/{pr_id}/approvals") for p in paths)


# ----------------------------------------------------------------------
# 安全 Review（Phase 7 §二十三.7/8）：inactive 用户 / 停用部门不能审批
# ----------------------------------------------------------------------
def test_inactive_user_cannot_approve(client: TestClient, db) -> None:
    """DB 层用户被停用后，即使持有有效 JWT 也无法审批（服务层复查 ACTIVE）。"""
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)
    lisi_token = _login(client, "lisi", "demo123")
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.username == "lisi")).scalar_one()
        u.status = "DISABLED"
        s.commit()
    try:
        lisi = _auth(lisi_token)
        r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                        json={"version": pr["version"]})
        # JWT 中间件先拦（user.status != ACTIVE → 403）
        assert r.status_code == 403
    finally:
        with SessionLocal() as s:
            u = s.execute(select(User).where(User.username == "lisi")).scalar_one()
            u.status = "ACTIVE"
            s.commit()


def test_inactive_department_cannot_approve(client: TestClient, db) -> None:
    """申请部门被停用后，主管也无法审批（服务层复查部门 ACTIVE）。"""
    _clean_prs()
    mid = _create_material(client, _auth(_login(client)))["id"]
    z = _auth(_login(client, "zhangsan", "demo123"))
    pr = _mk_pending_pr(client, z, mid)  # RD 部门
    from app.models import Department

    with SessionLocal() as s:
        dept = s.execute(select(Department).where(Department.dept_code == "RD")).scalar_one()
        dept.status = "INACTIVE"
        s.commit()
    try:
        lisi = _auth(_login(client, "lisi", "demo123"))
        r = client.post(f"/api/v1/purchase-requisitions/{pr['id']}/approve", headers=lisi,
                        json={"version": pr["version"]})
        assert r.status_code == 409
        assert r.json()["code"] == 3009  # MASTER_DATA_DISABLED
    finally:
        with SessionLocal() as s:
            dept = s.execute(select(Department).where(Department.dept_code == "RD")).scalar_one()
            dept.status = "ACTIVE"
            s.commit()
