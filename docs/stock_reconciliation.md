# 库存盘点（Stock Reconciliation）— Implementation A

> Reality Hardening Sprint 1 / Implementation A 实现文档（代码事实来源：
> `backend/app/services/stock_reconciliation_service.py`、`backend/app/models/reconciliation.py`、
> `backend/app/api/v1/stock_reconciliations.py`；设计依据：`docs/sprint1-inventory-reality-design.md` v2）。
> 已含 Code Review CR-A-001~010 修订（流水水印 Event Guard、权限化 SoD override、编号回归等）。

---

## 1. 为什么禁止直接 `UPDATE inventory_balances`

库存余额是**派生快照**，唯一权威是 append-only 流水：

```
SUM(inventory_transactions.quantity) == inventory_balances.quantity
SUM(inventory_transactions.amount)   == inventory_balances.total_amount
```

任何"直接把 quantity 改成 97"都会打破恒等式：审计断链、冲销无据、诊断无法解释差异来源。
因此账实校正一律走**盘点单据**：创建（固化三快照）→ 编辑 → 提交 → 审批即过账
（写带符号 `ADJUST_IN/ADJUST_OUT` 流水 + 更新余额 + 审计，单事务）。

## 2. Snapshot Guard（快照守卫）= Event Guard + State Guard

创建盘点行时固化**四快照**：`book_quantity_snapshot` / `book_total_amount_snapshot` /
`book_avg_cost_snapshot`，外加 **`book_last_transaction_id_snapshot`（流水水印）** ——
快照瞬间该 (仓,料) 最新 `inventory_transactions.id`（无流水为 NULL，绝不为此造流水）。

快照**不静默刷新**；只有"删除该行后重新添加"才会取新快照。过账（POST）前先
`lock_balances` 统一 `(warehouse_id, material_id)` 升序锁余额，然后在锁内读取每个键的
当前流水水印，做**两层独立守卫**（CR-A-001/003）：

```
1) Ledger Event Guard（事件守卫）
   当前水印 != 快照水印  →  盘点窗口期内发生过库存流水 → stale → 7005

2) Balance State Guard（状态守卫）
   当前 quantity != book_quantity_snapshot      → stale → 7005
   当前 total_amount != book_total_amount_snapshot → stale → 7005
```

关键现实语义（round-trip 案例，CR-A-005）：账面 100 / 金额 1000 时创建盘点；
窗口期内先 +10 入库、再整单冲销 -10，**状态回到 100 / 1000**——State Guard 认为未漂移，
但水印已经 +2，**Event Guard 仍然判 stale**。因为"盘点结果对应的是哪个时间点"已经失效：
期间发生过 movement，只是碰巧被对冲，物理盘点与账面不再处于同一业务时点。任何一层
不一致 → `7005 RECONCILIATION_BALANCE_CHANGED`，整单回滚，不重算差异、不部分过账、
不静默继续。

## 3. ADJUST_IN / ADJUST_OUT 语义

| 方向 | TxnType | quantity | unit_cost | amount |
|---|---|---|---|---|
| 盘盈（账面 100 → 实盘 103） | `ADJUST_IN` | `+3` | `valuation_rate`（显式确认） | `+money(3×rate)`，如 rate=12 → +36 |
| 盘亏（账面 100 → 实盘 97） | `ADJUST_OUT` | `-3` | `book_avg_cost_snapshot` | `-money(3×10)` = -30 |

- 不与 `PURCHASE_IN_REVERSAL` 混用：后者撤销的是"某笔采购"，按**原始单笔金额**回滚；
  盘亏按**余额快照均价**（守卫保证 = 过账时当前均价），两者语义不同。
- 流水来源类型 `TxnSourceType.STOCK_RECONCILIATION`；符号约束沿用 `it_sign` CHECK。

## 4. 盘盈入账单价必须显式确认（DA-002）

- 后端规则：凡差异 > 0 的行（含账面 0 / 实盘 > 0），`valuation_rate` **必填且 > 0**，
  缺失或 ≤ 0 → `7017 RECONCILIATION_VALUATION_RATE_REQUIRED`；后端**绝不**静默取当前均价。
- 前端允许预填 **Suggested Valuation Rate = book_avg_cost_snapshot**（一次性建议，OQ-11），
  标注"建议值"、可改可清空；它不是权威默认。
- 零库存盘盈（账面 0 → 实盘 5 @ 12）：余额行由 `lock_balance` upsert 自动创建，结果
  qty 5 / total 60.00 / avg 12.0000。

## 5. SoD（职责分离）与权限

- 权限点（无新角色，ADMIN 全量；WAREHOUSE 建/编/提，审批仅 ADMIN）：
  `reconcile:view/create/update/submit/approve/reject` +
  `reconcile:self_approve_override`（自审 override 专用权限点，仅 seed 授予 ADMIN）。
- 默认禁止 `approved_by == counted_by`（自盘自审）→ `7007`。
- **override 的闸门是权限而非角色**（CR-A-007）：服务层校验当前角色是否持有
  `reconcile:self_approve_override`，缺失时即使带标志位也返回 `7007`；通过后仍需
  `override_self_approval + override_reason`（缺理由 → `7008`），落库 +
  `STOCK_COUNT_APPROVE` 审计描述含理由（RD-006）。

## 6. 事务边界（POST 一步完成，失败全回滚）

```
CAS 认领 PENDING→POSTED（并发幂等闸门）
→ 校验全部明细
→ lock_balances（统一锁序，仅差异行）
→ 锁内读取当前流水水印 + 余额
→ Snapshot Guard：① Event Guard（水印）② State Guard（qty AND amount）
→ write_transaction(ADJUST_IN/OUT，带符号)
→ apply_inbound / apply_outbound（更新移动平均）
→ 单据 POSTED 字段 + 审计 STOCK_COUNT_APPROVE
→ 调用方统一 COMMIT
```

任一行失败（例如 B 物料 stale）→ A 物料的流水/余额一并回滚，单据保持非 POSTED。

**锁序一致性（CR-A-004）**：Receipt 过账、Receipt 冲销与本盘点过账共用同一个
`inventory_service.lock_balances` 入口，均按 `(warehouse_id, material_id)` 升序、且在写
流水**之前**持有对应余额 X 锁并保持到事务提交。因此一旦盘点过账持有目标键的余额锁，
并发 Receipt 无法在水印校验与过账之间插入新流水——水印读取与过账天然原子。

## 7. 已知边界

- **Short Count Window + Snapshot Guard 不是完整 Count Cutoff / As-Of 库存**：
  盘点创建后该仓该料一旦发生任何库存流水（即使状态被对冲回原值，Event Guard 仍拦截），
  该盘点即 stale，需重盘（保守正确性优先）。
- 本版本支持 **Late Entry / Backdated Business Date**（单据业务日早于过账日、库存影响在过账时），
  **不**支持 True Backdated Posting / 历史重放 / 冻结 / 诊断（后续 Sprint）。
- 零差异行允许过账但**不产生流水**（作为盘点留痕）。
- 库存成本 Demo：不生成 GL / 会计凭证 / 财务过账。

## 8. 补充修正（实施中发现并修复的既有缺陷）

- `numbering_service.next_sequence_value`：MySQL 对真实 INSERT（含 AUTO_INCREMENT）会把
  `LAST_INSERT_ID()` 覆盖为自增主键，导致每个 (key, date) 的**首次取号**返回错误大号；
  改为"写后回读该行 current_value"（唯一索引行锁内，并发语义不变）。
