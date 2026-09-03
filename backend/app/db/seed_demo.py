"""Demo business-story seed (Phase 11 交付物 §seed_demo_data).

可重复初始化的演示数据：清空既有业务链路与主数据后，通过真实 HTTP API
（in-process TestClient，与 smoke 脚本同路径）重放一段完整的业务故事 ——
研发部样机物料从 PR → 审批 → 转 PO → 确认 → 分批入库，得到与
``tests/test_dashboard.py`` module fixture 完全一致的确定性结果：

* PR1(100@M1) 全收 40@W1 + 60@W2          → PO1 RECEIVED
* PR2(M2 20) 已提交待审批                   → PENDING（zhangsan）
* PR3(M3 10) 已批准未转                     → 待转采购需求
* PR4(D 200) 部分收 80@W2                  → PO2 PARTIALLY_RECEIVED
* PR5(M1 30) 只转 10 且 PO 未确认(DRAFT)    → 待转 + 待确认并存
* PR6(M2 10) 已提交待审批                   → PENDING（lisi 自己）
* PR7 已取消（不进趋势）
* PR9(M3 10) 分两批 6+4 收 @W1             → PO4 RECEIVED
* 策略：M1@W1 安全库存 50（现 40 → 低）、M3@W1 安全库存 15（现 10 → 低）

预期（admin 视角）：待审批 PR=2、待转=2、待确认 PO=1、待收货 PO=1、
低库存=2、库存账面金额=1190.00。
运行：``python -m app.db.seed_demo``（幂等：每次先复位业务数据）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 复用测试清库 helper（含 append-only trigger 处理与 FK 安全顺序）。
# 仅供开发/演示库使用 —— 生产环境的业务数据由业务接口维护。
_tests_dir = Path(__file__).resolve().parents[2] / "tests"
sys.path.insert(0, str(_tests_dir))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from cleanup_helper import wipe_business_data  # noqa: E402

CLIENT = TestClient(app)
P = print


# ----------------------------------------------------------------------
# HTTP helpers（与 tests/test_dashboard.py 相同的链式构建器）
# ----------------------------------------------------------------------
def _login(username: str, password: str = "demo123") -> dict[str, str]:
    r = CLIENT.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _ok(r) -> dict:
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    return body["data"]


def _create_material(h, name: str, unit: str, category: str = "电子件") -> int:
    return _ok(CLIENT.post("/api/v1/materials", headers=h,
                           json={"material_name": name, "unit": unit, "category": category}))["id"]


def _mk_pr(h, material_id: int, qty: str, price: str, reason: str) -> dict:
    return _ok(CLIENT.post("/api/v1/purchase-requisitions", headers=h, json={
        "reason": reason,
        "items": [{"material_id": material_id, "requested_quantity": qty,
                   "estimated_unit_price": price}],
    }))


def _submit(h, pr_id: int) -> dict:
    return _ok(CLIENT.post(f"/api/v1/purchase-requisitions/{pr_id}/submit", headers=h))


def _approve(h, pr_id: int, version: int) -> dict:
    return _ok(CLIENT.post(f"/api/v1/purchase-requisitions/{pr_id}/approve",
                           headers=h, json={"version": version}))


def _approved_pr(zh, li, material_id: int, qty: str, price: str, reason: str) -> dict:
    pr = _mk_pr(zh, material_id, qty, price, reason)
    v = _submit(zh, pr["id"])["version"]
    return _approve(li, pr["id"], v)


def _mk_po(buyer, supplier_id: int, pr: dict, ordered_qty: str,
           source_qty: str, price: str) -> dict:
    detail = _ok(CLIENT.get(f"/api/v1/purchase-requisitions/{pr['id']}", headers=buyer))
    line = detail["items"][0]
    return _ok(CLIENT.post("/api/v1/purchase-orders", headers=buyer, json={
        "supplier_id": supplier_id,
        "items": [{
            "material_id": line["material_id"],
            "ordered_quantity": ordered_qty,
            "unit_price": price,
            "sources": [{"pr_item_id": line["id"], "quantity": source_qty}],
        }],
    }))


def _confirm_po(buyer, po_id: int, version: int) -> dict:
    return _ok(CLIENT.post(f"/api/v1/purchase-orders/{po_id}/confirm",
                           headers=buyer, json={"version": version}))


def _receive(wh, po_id: int, warehouse_id: int, po_item_id: int, qty: str) -> None:
    _ok(CLIENT.post("/api/v1/purchase-receipts", headers=wh, json={
        "po_id": po_id, "warehouse_id": warehouse_id,
        "items": [{"po_item_id": po_item_id, "received_quantity": qty}],
    }))


# ----------------------------------------------------------------------
# 业务故事
# ----------------------------------------------------------------------
def seed() -> dict:
    P("=== seed_demo_data：复位业务数据（触发器等由 cleanup_helper 处理）===")
    wipe_business_data()

    admin = _login("admin", "admin123")
    zh, li, ww, zl = _login("zhangsan"), _login("lisi"), _login("wangwu"), _login("zhaoliu")

    # 1) 主数据
    P("-- 主数据：物料 / 供应商 / 仓库 / 安全库存策略")
    m_esp = _create_material(admin, "ESP32-WROOM 模组", "pcs", "电子件")
    m_stm = _create_material(admin, "STM32F103 芯片", "pcs", "电子件")
    m_brg = _create_material(admin, "微型滚珠轴承", "套", "机械件")
    m_wire = _create_material(admin, "屏蔽连接线", "米", "线材")
    sup = _ok(CLIENT.post("/api/v1/suppliers", headers=admin,
                          json={"supplier_name": "天津宏远电子", "contact_person": "王采购"}))["id"]
    w_raw = _ok(CLIENT.post("/api/v1/warehouses", headers=admin,
                            json={"warehouse_name": "原材料仓"}))["id"]
    w_fin = _ok(CLIENT.post("/api/v1/warehouses", headers=admin,
                            json={"warehouse_name": "成品仓"}))["id"]
    for wh_id, mat_id, safety in ((w_raw, m_esp, "50"), (w_raw, m_brg, "15")):
        _ok(CLIENT.post("/api/v1/inventory-policies", headers=ww, json={
            "warehouse_id": wh_id, "material_id": mat_id, "safety_stock": safety}))
    P(f"   ✔ 物料×4 / 供应商 / 仓库×2 / 策略×2")

    # 2) PR1 -> PO1：ESP32 100 只，分两仓收齐（RECEIVED）
    P("-- 故事：研发样机备料 ESP32（PR1 → PO1 全量收货）")
    pr1 = _approved_pr(zh, li, m_esp, "100", "10", "研发样机 ESP32 备料")
    po1 = _mk_po(ww, sup, pr1, "100", "100", "10")
    po1 = _confirm_po(ww, po1["id"], po1["version"])
    poi1 = po1["items"][0]["id"]
    _receive(zl, po1["id"], w_raw, poi1, "40")
    _receive(zl, po1["id"], w_fin, poi1, "60")

    # 3) PR2/PR6：两条待审批（zhangsan / lisi 各一）
    P("-- 故事：两条已提交待审批的采购申请")
    pr2 = _mk_pr(zh, m_stm, "20", "5", "STM32 芯片补充")
    _submit(zh, pr2["id"])
    pr6 = _mk_pr(li, m_stm, "10", "5", "部门内备用芯片")
    _submit(li, pr6["id"])

    # 4) PR3：已批准，尚未转 PO（待转采购需求）
    P("-- 故事：已批准待转单（PR3）")
    pr3 = _approved_pr(zh, li, m_brg, "10", "3", "轴承小批量备货")

    # 5) PR4 -> PO2：连接线 200 米，只收 80（PARTIALLY_RECEIVED）
    P("-- 故事：连接线 200 米到货 80（PO2 部分收货）")
    pr4 = _approved_pr(zh, li, m_wire, "200", "2", "车间连线替换")
    po2 = _mk_po(ww, sup, pr4, "200", "200", "2")
    po2 = _confirm_po(ww, po2["id"], po2["version"])
    _receive(zl, po2["id"], w_fin, po2["items"][0]["id"], "80")

    # 6) PR5 -> PO3：只转 10、PO 未确认（DRAFT）→ 待转 + 待确认并存
    P("-- 故事：ESP32 加急 30 只只转 10，PO 待确认（PR5 / PO3）")
    pr5 = _approved_pr(zh, li, m_esp, "30", "10", "加急补料")
    po3 = _mk_po(ww, sup, pr5, "10", "10", "10")
    assert po3["status"] == "DRAFT"

    # 7) PR7：草稿直接取消（不进趋势/待办）
    P("-- 故事：一条取消的申请（PR7，排除在趋势外）")
    pr7 = _mk_pr(zh, m_esp, "5", "10", "误创建后取消")
    _ok(CLIENT.post(f"/api/v1/purchase-requisitions/{pr7['id']}/cancel", headers=zh))

    # 8) PR9 -> PO4：轴承 10 套分 6+4 两次入库（RECEIVED，触发低库存）
    P("-- 故事：轴承分两批到货（PO4 分批收货，M3@W1 低库存）")
    pr9 = _approved_pr(zh, li, m_brg, "10", "3", "轴承补货")
    po4 = _mk_po(ww, sup, pr9, "10", "10", "3")
    po4 = _confirm_po(ww, po4["id"], po4["version"])
    poi4 = po4["items"][0]["id"]
    _receive(zl, po4["id"], w_raw, poi4, "6")
    _receive(zl, po4["id"], w_raw, poi4, "4")

    return {
        "headers": {"admin": admin, "zhangsan": zh, "lisi": li, "wangwu": ww, "zhaoliu": zl},
        "materials": {"esp": m_esp, "stm": m_stm, "brg": m_brg, "wire": m_wire},
        "warehouses": {"raw": w_raw, "fin": w_fin},
        "pos": {"po1": po1, "po2": po2, "po3": po3, "po4": po4},
    }


def _summary(h) -> dict:
    return _ok(CLIENT.get("/api/v1/dashboard/summary", headers=h))


def verify(result: dict) -> None:
    """Seed 完成后做一次 dashboard 自检（口径一致性，失败即抛异常）。"""
    h = result["headers"]
    P("\n=== 自检：admin 视角 KPI（期望 2 / 2 / 1 / 1 / 2 / 1190.00）===")
    s = _summary(h["admin"])
    expect = {
        "pending_pr_count": 2, "pending_purchase_count": 2, "draft_po_count": 1,
        "pending_po_count": 1, "low_stock_count": 2, "inventory_total_amount": "1190.00",
    }
    for k, want in expect.items():
        got = s[k]
        mark = "✔" if str(got) == str(want) else "✘"
        P(f"   {mark} {k} = {got}" + ("" if str(got) == str(want) else f"（期望 {want}）"))
        assert str(got) == str(want), f"{k} 口径不一致: got={got} want={want}"

    # 角色隔离自检
    P("\n=== 自检：角色隔离 ===")
    wh = _summary(h["zhaoliu"])
    assert wh["pending_pr_count"] == 0 and wh["draft_po_count"] == 0
    assert wh["pending_po_count"] == 1
    P("   ✔ WAREHOUSE：无 pr:view → PR KPI=0；收货视角 pending_po=1")
    zh_s = _summary(h["zhangsan"])
    assert zh_s["pending_pr_count"] == 1
    P("   ✔ APPLICANT：只见自己 PENDING PR=1（lisi 的 PR6 不可见）")

    todos = _ok(CLIENT.get("/api/v1/dashboard/todos", headers=h["zhangsan"]))
    assert todos == [], todos
    P("   ✔ APPLICANT：无待办（待办按执行角色收敛）")
    P("\n=== seed_demo_data 完成：业务故事与仪表盘口径自检通过 ===")


if __name__ == "__main__":
    res = seed()
    verify(res)
