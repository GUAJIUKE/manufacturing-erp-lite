"""Demo 录屏前置：复位 seed 基线并造一条「轴承 100 CONFIRMED@成品仓可收」PO。

用法（backend/.venv 内）：
    python scripts_prep_demo.py reset          # 仅 seed 复位（demo-01 用）
    python scripts_prep_demo.py prep-receive   # seed 复位 + 造可收货 PO（demo-02/03 用）
    python scripts_prep_demo.py verify         # 打印当前关键单据（定位用）

说明：
- seed_demo 幂等复位；单据编号按日递增（不归零），故脚本内一律按「物料名/金额」语义定位。
- 造数走真实 HTTP API（127.0.0.1:8000），与 UI 录屏完全同一条后端。
"""
import json
import subprocess
import sys
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000/api/v1"
C = httpx.Client(base_url=API, timeout=30)

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
SEED_CMD = [
    sys.executable, "-m", "app.db.seed_demo",
]


def login(user: str, pw: str = "demo123") -> dict:
    r = C.post("/auth/login", json={"username": user, "password": pw})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["data"]["access_token"]}


def get(h, url):
    r = C.get(url, headers=h)
    r.raise_for_status()
    body = r.json()
    assert body["code"] == 0, body
    return body["data"]


def post(h, url, payload):
    r = C.post(url, headers=h, json=payload)
    r.raise_for_status()
    body = r.json()
    assert body["code"] == 0, body
    return body["data"]


def seed_reset() -> None:
    subprocess.run(SEED_CMD, cwd=BACKEND_DIR, check=True)


def find_material(h, name: str) -> int:
    data = get(h, "/materials?page=1&page_size=100")
    for m in data.get("items", []):
        if m["material_name"] == name:
            return m["id"]
    raise SystemExit(f"material not found: {name}")


def find_supplier(h, name: str) -> int:
    data = get(h, "/suppliers?page=1&page_size=100")
    for s in data.get("items", []):
        if s["supplier_name"] == name:
            return s["id"]
    raise SystemExit(f"supplier not found: {name}")


def prep_receive() -> None:
    """造：轴承 100 CONFIRMED 可收 PO（走完整业务链：zhangsan 建 PR→lisi 批→wangwu 转 PO→确认）。
    供 demo-02/03：zhaoliu 收 40 → 收 60 → 库存 100 → 冲销 60。"""
    seed_reset()
    zh = login("zhangsan")
    li = login("lisi")
    ww = login("wangwu")
    mid = find_material(zh, "微型滚珠轴承")
    sid = find_supplier(ww, "天津宏远电子")

    # 1) zhangsan 建 PR 并提交
    pr = post(zh, "/purchase-requisitions", {
        "reason": "录屏演示：轴承整批到货（40+60 分批收货）",
        "items": [{"material_id": mid, "requested_quantity": "100",
                   "estimated_unit_price": "3"}],
    })
    pr = post(zh, f"/purchase-requisitions/{pr['id']}/submit", {})
    # 2) lisi 审批
    pr = post(li, f"/purchase-requisitions/{pr['id']}/approve",
              {"version": pr["version"]})
    assert pr["status"] == "APPROVED", pr
    # 3) wangwu 转 PO（带来源 100）并确认
    detail = get(ww, f"/purchase-requisitions/{pr['id']}")
    pr_item_id = detail["items"][0]["id"]
    po = post(ww, "/purchase-orders", {
        "supplier_id": sid,
        "remark": "录屏演示：分批收货（40+60）",
        "items": [{
            "material_id": mid,
            "ordered_quantity": "100",
            "unit_price": "3",
            "sources": [{"pr_item_id": pr_item_id, "quantity": "100"}],
        }],
    })
    confirmed = post(ww, f"/purchase-orders/{po['id']}/confirm",
                     {"version": po["version"], "comment": "录屏演示确认"})
    print(f"[prep] PR {pr['pr_no']} APPROVED → PO {confirmed['po_no']} "
          f"id={confirmed['id']} status={confirmed['status']} total={confirmed['total_amount']}")


def verify() -> None:
    """打印可定位的关键单据（demo 用）。"""
    admin = login("admin", "admin123")
    ww = login("wangwu")
    zl = login("zhaoliu")
    prs = get(admin, "/purchase-requisitions?page=1&page_size=20")
    print("\n-- PR（admin）--")
    for p in prs.get("items", [])[:12]:
        print(f"  {p['pr_no']} {p.get('requester_name','')} {p['status']} "
              f"{p['reason'][:18]} {p['items'][0]['material_name'] if p.get('items') else ''}")
    pos = get(ww, "/purchase-orders?page=1&page_size=20")
    print("\n-- PO（wangwu）--")
    for p in pos.get("items", [])[:8]:
        print(f"  {p['po_no']} {p['status']} total={p['total_amount']} items={p.get('item_count','?')}")
    txs = get(zl, "/inventory/transactions?page=1&page_size=10")
    print("\n-- 最近库存流水（zhaoliu）--")
    for t in txs.get("items", [])[:8]:
        print(f"  {t['transaction_type']} {t['quantity']} {t.get('material_name','')} "
              f"{t.get('warehouse_name','')} bal={t.get('balance_after')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "reset":
        seed_reset()
        print("[reset] seed_demo done")
    elif cmd == "prep-receive":
        prep_receive()
    elif cmd == "verify":
        verify()
    else:
        raise SystemExit(f"unknown cmd {cmd}")
