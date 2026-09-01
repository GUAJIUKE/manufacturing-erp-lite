"""Phase 4 auth & RBAC tests (Q14: run against erp_lite_test)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import verify_password
from app.models import OperationLog, Role, User
from app.utils.enums import AuditAction, RoleCode, UserStatus

# 与 app/core/security.py 的 ACCESS_TOKEN_EXPIRE_MINUTES 无关；断言仅用相对语义
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
APPLICANT_USERNAME = "zhangsan"
APPLICANT_PASSWORD = "demo123"


# ----------------------------------------------------------------------
# 登录
# ----------------------------------------------------------------------
def test_login_success(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["message"] == "登录成功"
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["access_token"]
    assert body["data"]["expires_in"] > 0


def test_login_wrong_password(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": "wrong-pass"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == 2003  # INVALID_CREDENTIALS


def test_login_unknown_user(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "no_such_user", "password": "whatever1"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == 2003


def test_login_disabled_user(client: TestClient, db) -> None:
    """停用账号不允许登录 → 403 USER_DISABLED."""
    from app.core.security import hash_password

    username = "t_disabled"
    role = db.execute(
        select(Role).where(Role.role_code == RoleCode.APPLICANT)
    ).scalar_one()
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password("demo123"),
            real_name="测试停用账号",
            role_id=role.id,
            status=UserStatus.DISABLED,
        )
        db.add(user)
    else:
        user.status = UserStatus.DISABLED
    db.commit()

    r = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo123"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == 2004  # USER_DISABLED


# ----------------------------------------------------------------------
# 鉴权依赖（401 / 403）
# ----------------------------------------------------------------------
def test_me_without_token(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == 2001  # UNAUTHORIZED


def test_me_with_invalid_token(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["code"] == 2001


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def test_me_returns_permissions(client: TestClient) -> None:
    token = _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["username"] == ADMIN_USERNAME
    assert data["role_code"] == "ADMIN"
    assert data["department_name"] is not None
    perms = data["permissions"]
    assert "role:assign" in perms
    assert "pr:approve" in perms
    assert len(perms) >= 40  # ADMIN 拥有全部 44 个权限点


def test_no_permission_403(client: TestClient) -> None:
    """APPLICANT 无 user:view，访问用户列表应 403 PERMISSION_DENIED."""
    token = _login(client, APPLICANT_USERNAME, APPLICANT_PASSWORD)
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["code"] == 2005


# ----------------------------------------------------------------------
# 密码哈希（Q：明文永不落库）
# ----------------------------------------------------------------------
def test_password_hash_not_plaintext(db) -> None:
    user = db.execute(
        select(User).where(User.username == ADMIN_USERNAME)
    ).scalar_one()
    assert user.password_hash != ADMIN_PASSWORD
    assert user.password_hash.startswith("$2b$")
    assert verify_password(ADMIN_PASSWORD, user.password_hash)
    assert not verify_password("wrong-pass", user.password_hash)


# ----------------------------------------------------------------------
# Q15 审计日志
# ----------------------------------------------------------------------
def test_login_failed_audit_written(client: TestClient, db) -> None:
    before = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.LOGIN_FAILED,
            OperationLog.username_snapshot == ADMIN_USERNAME,
        )
    ).scalar_one()

    client.post(
        "/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": "wrong-pass"},
    )

    # 结束 db fixture 会话的 REPEATABLE READ 快照，才能看到另一会话新提交的审计记录
    db.rollback()

    after = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.LOGIN_FAILED,
            OperationLog.username_snapshot == ADMIN_USERNAME,
        )
    ).scalar_one()
    assert after == before + 1


def test_login_success_audit_written(client: TestClient, db) -> None:
    before = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.LOGIN
        )
    ).scalar_one()

    _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)

    # 结束 REPEATABLE READ 快照，读取最新提交
    db.rollback()

    after = db.execute(
        select(func.count()).select_from(OperationLog).where(
            OperationLog.action == AuditAction.LOGIN
        )
    ).scalar_one()
    assert after == before + 1
