# 数量链设计（Quantity Chain）

> 回答一个问题：**从需求数量到库存数量之间，为什么需要这么多字段，为什么不能合并？**
> 代码事实来源：`backend/app/models/purchase.py` / `inventory.py` 的字段与
> CHECK 约束、`purchase_order_service` / `purchase_receipt_service` 的 CAS 更新。

---

## 1. 数量链全貌

```
PR item.requested_quantity  ① 需求数量（申请要多少）
        │
        │  转单时 CAS 累加（可拆单/可部分转）
        ▼
PR item.converted_quantity  ② 已转采购执行数量（这张申请已经转出去多少）
        │
        ▼（purchase_order_item_sources 明细级映射，quantity = 本次转出量）
PO item.ordered_quantity    ③ 采购订单数量（向供应商订多少）
        │
        │  收货时 CAS 累加（可分批收）
        ▼
PO item.received_quantity   ④ 累计实际收货数量（这张 PO 已经收了多少）
        │
        ▼（Receipt 明细快照本次到货）
ReceiptItem.received_quantity ⑤ 单次实际收货数量（这次收了什么、多少、什么价）
        │
        ▼（同事务写流水）
InventoryTransaction.quantity ⑥ 库存变化历史（带符号，append-only）
        │
        ▼（同事务更新余额）
InventoryBalance.quantity     ⑦ 当前库存（快照）
```

字段精度均为 `Decimal(18,4)`；金额字段 `Decimal(18,2)` 服务端 ROUND_HALF_UP。

## 2. 每个字段「为什么存在」

| 字段 | 语义 | 它独立存在的理由 |
|---|---|---|
| ① requested_quantity | 需求数量，一经提交即冻结 | 是审批与执行的**基准**，不能随着后续转单/收货被改写 |
| ② converted_quantity | 已转执行数量 | 支持**部分转单/拆单**：一张 PR 可分批转给多张 PO。没有它，系统不知道 PR 还欠多少未转 |
| ③ ordered_quantity | 订购数量 | PO 与供应商的合同口径 |
| ④ received_quantity | 累计已收 | 支持**分批收货**：判断还能收多少（`ordered - received`）必须来自累计值 |
| ⑤ ReceiptItem.received_quantity | 单次收货 | 业务事实（一次到货事件），是流水与成本快照的源头 |
| ⑥ Transaction.quantity | 带符号流水量 | 历史记录，可对账（`SUM(quantity) == balance.quantity`） |
| ⑦ Balance.quantity | 当前余额 | 高频查询快照，不必每次 SUM 全表 |

## 3. 为什么这些字段不能合并？（面试重点）

### 3.1 `converted_quantity` 不能省（拆单场景）

一张「100 件」的 PR 可能被拆成 PO-A 60 件 + PO-B 40 件两张单。若没有
`converted_quantity`，第二张 PO 创建时无法判断「还剩 40 可转」；若直接比较
PR 状态（APPROVED/CONVERTED），则**部分转单**（如只转 60、留 40 待后续）无法表达
——这正是 Phase 9 需要区分「APPROVED 的 PR」与「真正待转采购」的原因
（Dashboard 口径，见 dashboard_metrics.md）。

数据库约束：`converted_quantity >= 0 AND converted_quantity <= requested_quantity`
（`pri_converted_not_exceed`）。转单用 CAS 更新：

```sql
UPDATE purchase_requisition_items
SET converted_quantity = converted_quantity + :qty
WHERE id = :id AND converted_quantity + :qty <= requested_quantity
-- rowcount == 0 → 并发超转被拒（4009）
```

### 3.2 `received_quantity` 不能省（分批收货场景）

PO 订 100，可能先到 40、再到 60。`received_quantity` 是「累计已收」，
判断剩余可收 = `ordered_quantity - received_quantity`。若只保留最后一次收货量，
无法防止「另一张并发入库单重复占用剩余量」，也无法推导 PO 状态。

数据库约束：`received_quantity >= 0 AND received_quantity <= ordered_quantity`
（`poi_received_not_exceed`）。收货 CAS 更新（见 docs/concurrency.md）。

### 3.3 数量链 ≠ 金额链，但二者平行

每条数量边上都挂着金额（PR 预估金额、PO 订购金额、Receipt 入库金额、
Transaction 金额、Balance 总金额）。数量用于「防超」，金额用于「成本」——
**数量不能超，金额由数量 × 单价服务端重算**，客户端提交的金额一律忽略。

### 3.4 `source 映射表` 的价值（拆单 + 合单）

`purchase_order_item_sources` 以 `(po_item_id, pr_item_id, quantity)` 记录
「这张 PO 明细用了哪张 PR 明细的多少数量」：

- 一张 PO 明细可引用多张 PR 明细（**合单**）
- 一张 PR 明细可出现在多张 PO 明细中（**拆单**）
- `UNIQUE(po_item_id, pr_item_id)` 防止同一来源重复累加绕过校验
- 全链路可追溯：PO → sources → PR item → PR → 申请人/部门（这也是 PO 与
  Receipt 对象级可见性查询的物理基础）

**转单硬规则**：`SUM(sources.quantity) 必须严格等于 ordered_quantity`
（`PO_SOURCE_QUANTITY_MISMATCH`）——本项目不支持无来源手工采购，小于或大于
都不允许，杜绝「订单数量与需求来源对不上」的脏数据。

## 4. 数量链上的状态推导（闭环）

| 推导 | 规则 | 触发点 |
|---|---|---|
| PR → CONVERTED | 所有明细 `converted_quantity == requested_quantity`（原子 NOT EXISTS 判定，防 REPEATABLE READ 快照漏置） | PO 创建事务内 |
| PR → APPROVED（回退） | 取消 PO 后存在未全转明细 | PO 取消事务内 |
| PO 状态 | 按明细 `received_quantity` 全 0 / 全满 / 部分 → CONFIRMED / RECEIVED / PARTIALLY_RECEIVED | 每次收货与冲销后 |

## 5. 一致性自检（测试锚点）

Phase 12 端到端测试（tests/test_workflow_e2e.py）与 seed_demo 自检保证：

```
PR(requested)  ≥ Σ 各 PO 从该 PR 转出的量（CAS 防超）
PO(ordered)    ≥ PO(received)（CAS 防超收）
PO(received)   == Σ 该 PO 所有 Receipt 明细数量
Balance.quantity == SUM(Transaction.quantity)   # 账实一致
Balance.total_amount == SUM(Transaction.amount)  # 金额一致（同号规则）
```
