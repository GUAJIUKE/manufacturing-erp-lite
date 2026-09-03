"""Phase 12 coverage hardening: master-data edge branches.

Baseline run showed supplier_service 35% / warehouse_service 46% /
inventory_policy_service 66% — the API tests only exercised create paths.
These tests walk update / disable / enable / detail-404 / list-filters for
suppliers & warehouses and update + order-validation for inventory policies,
closing the service-side gaps that drive the low numbers.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_material(client, headers) -> dict:
    r = client.post("/api/v1/materials", headers=headers,
                    json={"material_name": "P12 覆盖测试物料", "unit": "pcs", "category": "电子件"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_supplier(client, headers, name: str) -> dict:
    r = client.post("/api/v1/suppliers", headers=headers,
                    json={"supplier_name": name, "contact_person": "王工", "phone": "022-00000000"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_warehouse(client, headers, name: str) -> dict:
    r = client.post("/api/v1/warehouses", headers=headers,
                    json={"warehouse_name": name, "remark": "P12 初建"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ----------------------------------------------------------------------
# 供应商：update / detail / enable / 404 / 列表筛选
# ----------------------------------------------------------------------
def test_supplier_update_disable_enable_detail_404_and_filters(client: TestClient) -> None:
    h = _auth(_login(client))
    sup = _create_supplier(client, h, "P12 供应商更新测试")
    code_before = sup["supplier_code"]

    # detail
    r = client.get(f"/api/v1/suppliers/{sup['id']}", headers=h)
    assert r.status_code == 200 and r.json()["data"]["supplier_name"] == "P12 供应商更新测试"

    # update（supplier_code 不可改）
    r = client.put(f"/api/v1/suppliers/{sup['id']}", headers=h, json={
        "supplier_name": "P12 供应商更新测试-改", "contact_person": "赵工",
        "phone": "022-11111111", "email": "a@b.cn", "address": "天津西青", "remark": "P12 更新",
    })
    assert r.status_code == 200, r.text
    upd = r.json()["data"]
    assert upd["supplier_code"] == code_before
    assert upd["supplier_name"] == "P12 供应商更新测试-改"
    assert upd["contact_person"] == "赵工" and upd["phone"] == "022-11111111"
    assert upd["email"] == "a@b.cn" and upd["address"] == "天津西青" and upd["remark"] == "P12 更新"

    # disable -> 状态筛选命中 -> enable
    r = client.post(f"/api/v1/suppliers/{sup['id']}/disable", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "DISABLED"
    r = client.get("/api/v1/suppliers?status=DISABLED&page=1&page_size=100", headers=h)
    codes = [x["supplier_code"] for x in r.json()["data"]["items"]]
    assert code_before in codes
    r = client.post(f"/api/v1/suppliers/{sup['id']}/enable", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "ACTIVE"

    # name 模糊筛选
    r = client.get("/api/v1/suppliers?name=%E6%9B%B4%E6%96%B0%E6%B5%8B%E8%AF%95-%E6%94%B9", headers=h)
    assert any(x["id"] == sup["id"] for x in r.json()["data"]["items"])

    # 404
    assert client.get("/api/v1/suppliers/999999", headers=h).status_code == 404


# ----------------------------------------------------------------------
# 仓库：update / disable(空仓) / enable / 404 / 状态筛选
# ----------------------------------------------------------------------
def test_warehouse_update_disable_empty_enable_404_and_filters(client: TestClient) -> None:
    h = _auth(_login(client))
    wh = _create_warehouse(client, h, "P12 仓库更新测试")
    wh_id = wh["id"]

    r = client.put(f"/api/v1/warehouses/{wh_id}", headers=h,
                   json={"warehouse_name": "P12 仓库更新测试-改", "remark": "P12 改名"})
    assert r.status_code == 200, r.text
    upd = r.json()["data"]
    assert upd["warehouse_name"] == "P12 仓库更新测试-改" and upd["remark"] == "P12 改名"

    # 空仓可停用
    r = client.post(f"/api/v1/warehouses/{wh_id}/disable", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "DISABLED"
    r = client.get("/api/v1/warehouses?status=DISABLED&page=1&page_size=100", headers=h)
    assert any(x["id"] == wh_id for x in r.json()["data"]["items"])
    r = client.post(f"/api/v1/warehouses/{wh_id}/enable", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "ACTIVE"

    assert client.get(f"/api/v1/warehouses/{wh_id}", headers=h).status_code == 200
    assert client.get("/api/v1/warehouses/999999", headers=h).status_code == 404


# ----------------------------------------------------------------------
# 库存策略：update / 顺序校验 / 404
# ----------------------------------------------------------------------
def test_policy_update_success_order_validation_and_404(client: TestClient) -> None:
    h = _auth(_login(client))
    mat = _create_material(client, h)
    wh = _create_warehouse(client, h, "P12 策略仓")

    r = client.post("/api/v1/inventory-policies", headers=h, json={
        "warehouse_id": wh["id"], "material_id": mat["id"],
        "safety_stock": "10", "reorder_point": "20", "max_stock": "30",
    })
    assert r.status_code == 200, r.text
    policy = r.json()["data"]
    pid = policy["id"]

    # update 数值与 remark
    r = client.put(f"/api/v1/inventory-policies/{pid}", headers=h, json={
        "safety_stock": "5", "reorder_point": "15", "max_stock": "40", "remark": "P12 调整",
    })
    assert r.status_code == 200, r.text
    upd = r.json()["data"]
    assert str(upd["safety_stock"]) == "5" and str(upd["reorder_point"]) == "15"
    assert str(upd["max_stock"]) == "40" and upd["remark"] == "P12 调整"

    # 顺序违规 safety > reorder / > max -> 422
    r = client.put(f"/api/v1/inventory-policies/{pid}", headers=h,
                   json={"safety_stock": "50", "reorder_point": "15", "max_stock": "40"})
    assert r.status_code == 422, r.text
    r = client.put(f"/api/v1/inventory-policies/{pid}", headers=h,
                   json={"reorder_point": "60", "max_stock": "40"})
    assert r.status_code == 422, r.text

    # 404
    assert client.get("/api/v1/inventory-policies/999999", headers=h).status_code == 404
