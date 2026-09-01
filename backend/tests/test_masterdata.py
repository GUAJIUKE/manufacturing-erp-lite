"""Phase 5 master-data tests: materials / suppliers / warehouses / policies.

Covers the 18 acceptance items from the Phase 5 spec plus a multi-threaded
code-generation race test (§五 编码生成: 并发验证无重复).
"""

from __future__ import annotations

import re
import threading
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.init_data import run as run_seed
from app.db.session import SessionLocal
from app.models import InventoryBalance, InventoryPolicy, Material, NumberSequence, Supplier, Warehouse
from app.schemas.material import MaterialCreate
from app.services import material_service


def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_material(client, headers, name="电阻 10K", **kw) -> dict:
    payload = {"material_name": name, "unit": "pcs", **kw}
    r = client.post("/api/v1/materials", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_supplier(client, headers, name="测试供应商", **kw) -> dict:
    r = client.post("/api/v1/suppliers", headers=headers, json={"supplier_name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_warehouse(client, headers, name="成品仓", **kw) -> dict:
    r = client.post("/api/v1/warehouses", headers=headers, json={"warehouse_name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ----------------------------------------------------------------------
# 物料
# ----------------------------------------------------------------------
def test_create_material_auto_code_and_unique_codes(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m1 = _create_material(client, headers, "电阻 10K", category="电子件")
    m2 = _create_material(client, headers, "钣金外壳", category="结构件")
    assert re.fullmatch(r"MAT-\d{6}", m1["material_code"])
    assert re.fullmatch(r"MAT-\d{6}", m2["material_code"])
    assert m1["material_code"] != m2["material_code"]  # 唯一（DB UNIQUE 兜底）
    assert m1["status"] == "ACTIVE"


def test_material_code_db_unique(client: TestClient, db) -> None:
    """DB-level backstop: inserting the same code twice must fail."""
    from sqlalchemy.exc import IntegrityError

    db.add(Material(material_code="MAT-999999", material_name="重复编码A", unit="pcs"))
    db.commit()
    db.add(Material(material_code="MAT-999999", material_name="重复编码B", unit="pcs"))
    try:
        db.commit()
        raise AssertionError("expected IntegrityError")
    except IntegrityError:
        db.rollback()
    finally:
        db.execute(delete(Material).where(Material.material_code == "MAT-999999"))
        db.commit()


def test_update_material_code_immutable(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "电容 100uF")
    r = client.put(
        f"/api/v1/materials/{m['id']}",
        headers=headers,
        json={"material_name": "电容 100uF 改名", "material_code": "MAT-000000"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["material_code"] == m["material_code"]  # 不可修改
    assert data["material_name"] == "电容 100uF 改名"


def test_material_list_filters(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    # 清理历史同名残留（API 会话提交无法被 fixture rollback 回滚）
    db.rollback()
    db.execute(delete(Material).where(Material.material_name.in_(["电阻 10K", "电阻 100K", "钣金外壳"])))
    db.commit()

    m1 = _create_material(client, headers, "电阻 10K", category="电子件")
    _create_material(client, headers, "电阻 100K", category="电子件")
    _create_material(client, headers, "钣金外壳", category="结构件")

    # 分页
    r = client.get("/api/v1/materials?page=1&page_size=2", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["data"]["items"]) == 2
    assert r.json()["data"]["total"] >= 3
    assert r.json()["data"]["total_pages"] >= 2

    # code 搜索（精确段）
    r = client.get(f"/api/v1/materials?code={m1['material_code'][-3:]}", headers=headers)
    assert all(m1["material_code"] in i["material_code"] for i in r.json()["data"]["items"])

    # name 模糊
    r = client.get("/api/v1/materials?name=钣金", headers=headers)
    assert len(r.json()["data"]["items"]) == 1
    assert r.json()["data"]["items"][0]["material_name"] == "钣金外壳"

    # category 筛选
    r = client.get("/api/v1/materials?category=电子件", headers=headers)
    assert all(i["category"] == "电子件" for i in r.json()["data"]["items"])

    # status 筛选
    r = client.get("/api/v1/materials?status=DISABLED", headers=headers)
    assert all(i["status"] == "DISABLED" for i in r.json()["data"]["items"])


def test_disable_enable_material(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "二极管 1N4148")
    r = client.post(f"/api/v1/materials/{m['id']}/disable", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "DISABLED"
    r = client.post(f"/api/v1/materials/{m['id']}/enable", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ACTIVE"


def test_policy_creation_fails_for_disabled_material(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "不可用物料")
    wh = _create_warehouse(client, headers, "停用料测试仓")
    client.post(f"/api/v1/materials/{m['id']}/disable", headers=headers)

    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": wh["id"], "material_id": m["id"], "safety_stock": 10},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3009  # MASTER_DATA_DISABLED


# ----------------------------------------------------------------------
# 供应商
# ----------------------------------------------------------------------
def test_create_supplier_auto_code(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    s1 = _create_supplier(client, headers, "深圳华强电子")
    s2 = _create_supplier(client, headers, "东莞五金厂")
    assert re.fullmatch(r"SUP-\d{6}", s1["supplier_code"])
    assert s1["supplier_code"] != s2["supplier_code"]
    assert s1["status"] == "ACTIVE"


def test_disable_supplier(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    s = _create_supplier(client, headers, "停用测试供应商")
    r = client.post(f"/api/v1/suppliers/{s['id']}/disable", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "DISABLED"
    # 历史单据可查：列表仍能返回该供应商
    r = client.get(f"/api/v1/suppliers/{s['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "DISABLED"


# ----------------------------------------------------------------------
# 仓库
# ----------------------------------------------------------------------
def test_create_warehouse_auto_code(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    w1 = _create_warehouse(client, headers, "原料仓")
    w2 = _create_warehouse(client, headers, "成品仓")
    assert re.fullmatch(r"WH-\d{6}", w1["warehouse_code"])
    assert w1["warehouse_code"] != w2["warehouse_code"]


def test_disable_warehouse_with_stock_forbidden(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    wh = _create_warehouse(client, headers, "有库存仓")
    mat = _create_material(client, headers, "有库存物料")

    # 构造非零库存余额（Service 校验依据 inventory_balances）
    db.add(
        InventoryBalance(
            warehouse_id=wh["id"],
            material_id=mat["id"],
            quantity=Decimal("5.0000"),
        )
    )
    db.commit()

    r = client.post(f"/api/v1/warehouses/{wh['id']}/disable", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == 3010  # WAREHOUSE_HAS_STOCK

    # 库存清零后可停用
    db.execute(
        delete(InventoryBalance).where(
            InventoryBalance.warehouse_id == wh["id"], InventoryBalance.material_id == mat["id"]
        )
    )
    db.commit()
    r = client.post(f"/api/v1/warehouses/{wh['id']}/disable", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "DISABLED"


# ----------------------------------------------------------------------
# 库存策略
# ----------------------------------------------------------------------
def test_policy_create_and_unique_pair(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "策略唯一物料")
    w = _create_warehouse(client, headers, "策略唯一仓")

    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 10, "reorder_point": 20, "max_stock": 100},
    )
    assert r.status_code == 200, r.text
    p = r.json()["data"]
    assert float(p["safety_stock"]) == 10.0
    assert float(p["reorder_point"]) == 20.0
    assert float(p["max_stock"]) == 100.0

    # 同一 wh+mat 重复策略 -> 409 INVENTORY_POLICY_DUPLICATE
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 1},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3011

    # 筛选
    r = client.get(f"/api/v1/inventory-policies?material_id={m['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 1


def test_policy_negative_and_range_validation(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "校验物料")
    w = _create_warehouse(client, headers, "校验仓")

    # safety_stock 为负 -> 422
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": -1},
    )
    assert r.status_code == 422

    # max_stock = 0 -> 422（须 > 0）
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 0, "max_stock": 0},
    )
    assert r.status_code == 422

    # safety > reorder -> 422（业务校验）
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 50, "reorder_point": 10},
    )
    assert r.status_code == 422

    # reorder > max -> 422
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 1, "reorder_point": 99, "max_stock": 50},
    )
    assert r.status_code == 422


def test_policy_creation_fails_for_disabled_warehouse(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "停用仓测试物料")
    w = _create_warehouse(client, headers, "停用测试仓")
    client.post(f"/api/v1/warehouses/{w['id']}/disable", headers=headers)

    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 10},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3009


def test_policy_update_forbidden_after_disable(client: TestClient, db) -> None:
    headers = _auth(_login(client))
    m = _create_material(client, headers, "更新被禁物料")
    w = _create_warehouse(client, headers, "更新被禁仓")
    r = client.post(
        "/api/v1/inventory-policies",
        headers=headers,
        json={"warehouse_id": w["id"], "material_id": m["id"], "safety_stock": 5},
    )
    pid = r.json()["data"]["id"]

    client.post(f"/api/v1/materials/{m['id']}/disable", headers=headers)
    r = client.put(
        f"/api/v1/inventory-policies/{pid}",
        headers=headers,
        json={"safety_stock": 6},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 3009


# ----------------------------------------------------------------------
# 权限 & 幂等 & 并发
# ----------------------------------------------------------------------
def test_master_data_no_permission_403(client: TestClient, db) -> None:
    """APPLICANT 无 material:create，POST 应 403（有 view 可读列表）。"""
    token = _login(client, "zhangsan", "demo123")
    headers = _auth(token)
    r = client.get("/api/v1/materials", headers=headers)
    assert r.status_code == 200
    r = client.post("/api/v1/materials", headers=headers, json={"material_name": "越权", "unit": "pcs"})
    assert r.status_code == 403
    assert r.json()["code"] == 2005
    # 无 inventory_policy 权限（APPLICANT 未分配）
    r = client.get("/api/v1/inventory-policies", headers=headers)
    assert r.status_code == 403


def test_init_data_idempotent(client: TestClient, db) -> None:
    """重跑种子脚本：第二次必须全 0 新增（幂等）。"""
    run_seed()  # 先跑一次，吸收历史差异（如新增权限点）
    stats = run_seed()
    assert stats == {
        "departments": 0,
        "roles": 0,
        "permissions": 0,
        "role_permissions": 0,
        "users": 0,
        "dept_managers": 0,
    }


def test_concurrent_material_code_generation_unique(client: TestClient, db) -> None:
    """并发创建物料：8 线程 × 5 个 = 40 个编码必须全部唯一（§五 并发安全）。"""
    results: list[str] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def _worker(worker_id: int) -> None:
        try:
            s = SessionLocal()
            try:
                for i in range(5):
                    m = material_service.create_material(
                        s,
                        MaterialCreate(
                            material_name=f"并发物料{worker_id}-{i}",
                            unit="pcs",
                        ),
                    )
                    with lock:
                        results.append(m.material_code)
                s.commit()
            finally:
                s.close()
        except Exception as exc:  # pragma: no cover - failure path
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发创建失败: {errors}"
    assert len(results) == 40
    assert len(set(results)) == 40, f"存在重复编码: {len(results) - len(set(results))} 个重复"

    # cleanup: 删除并发创建的物料，保持测试库可重复执行。
    # 注意：不能重置 number_sequences —— 序列重置会让后续创建与历史残留撞码
    #（编码唯一性依赖序列单调不减；跳号允许）。
    db.rollback()
    db.execute(delete(Material).where(Material.material_name.like("并发物料%")))
    db.commit()
