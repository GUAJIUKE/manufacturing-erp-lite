# Manufacturing ERP Lite — Data Integrity Review

> 版本：v1.0 ｜ 日期：2026-09-01 ｜ 阶段：Phase 2 · 数据库设计评审
> 配套文档：[`docs/database-design.md`](./database-design.md) ｜ [`docs/ERD.md`](./ERD.md)

---

## 0. 审查范围与结论

本次评审针对 `docs/database-design.md` 定义的 **22 张表**，按 11 个维度检查数据完整性风险。

| 维度 | 检查项数 | 高危项 | 结论 |
|---|---|---|---|
| 10.1 重复数据风险 | 8 | 3 | 全部有唯一约束覆盖 |
| 10.2 孤儿记录风险 | 6 | 4 | 全部由 `RESTRICT` FK + 禁删策略覆盖 |
| 10.3 并发风险 | 8 | 3 | 全部由 CAS 条件更新覆盖，需 Phase 12 补并发测试 |
| 10.4 金额精度 | 6 | 1 | DECIMAL(18,4) + 生成列，需代码审查禁 float |
| 10.5 数量精度 | 4 | 2 | DECIMAL(18,4) + CHECK 约束 |
| 10.6 唯一性 | 12 | — | 12 项唯一索引全部明确 |
| 10.7 业务状态一致性 | 9 | 5 | 状态机白名单 + Schema 不含 status |
| 10.8 PR/PO 数量一致性 | 6 条不变量 | — | 需 Phase 12 提供对账脚本验证 |
| 10.9 库存账实逻辑 | 6 条不变量 | — | `SUM(quantity)` 可一键校验 |
| 10.10 冲销逻辑 | 7 | 3 | 需补充"是否已冲销"前置校验 |
| 10.11 删除策略 | 3 | — | 见 database-design.md §1.4 |

**总体结论**：设计层面无阻断性缺陷，可进入 Phase 3。以下 3 项需在 Phase 3/9 实现时重点落实：

1. **C-01/C-02**（并发超收）：必须严格使用条件更新 + `rowcount` 校验，不允许"先 SELECT 判断再 UPDATE"
2. **R-01**（重复冲销）：冲销前必须先查 `PURCHASE_IN_REVERSAL` 流水是否已存在
3. **S-01**（状态被前端篡改）：Pydantic Create/Update Schema 中**严禁出现 `status` 字段**

---


## 1. 重复数据风险

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| D-01 | 同一 PO 明细重复引用同一 PR 明细（多行累加导致超转） | 高 | `uk_pois(po_item_id, pr_item_id)` 唯一约束，数据库层阻断 |
| D-02 | 同一入库单内同一 PO 明细多行（绕过超收校验） | 高 | `uk_ri_poi(receipt_id, po_item_id)` 唯一约束 |
| D-03 | 同一 PR 内行号重复 | 中 | `uk_pri_line(pr_id, line_no)`；`uk_poi_line`、`uk_ri_line` 同理 |
| D-04 | 重复授权（同一角色同一权限多条） | 低 | `uk_role_perm(role_id, permission_id)` |
| D-05 | 同一部门重复指定同一主管 | 低 | `uk_deptmgr(dept_id, user_id)` |
| D-06 | 物料/供应商/仓库编码重复 | 高 | `uk_mat_code` / `uk_sup_code` / `uk_wh_code` |
| D-07 | 单据编号重复（并发或序列重置） | 高 | `uk_pr_no` / `uk_po_no` / `uk_receipt_no` / `uk_txn_no` + Service 冲突重试 3 次 |
| D-08 | 重复提交审批（同一单据同一步骤并发审批） | 中 | Service 内对 PR 行加 `SELECT ... FOR UPDATE`（审批是短事务，锁竞争可接受），再次校验状态 = PENDING |

## 2. 孤儿记录风险

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| O-01 | `inventory_transactions.source_id` 指向的 Receipt 被删除 | 高 | **Receipt 禁止物理删除**（§1.4）；且 `purchase_receipts` 被 `fk_ri_receipt` 级联保护。source_id 永不失效 |
| O-02 | `approval_records.document_id` 指向的 PR 被删除 | 高 | PR 在 `PENDING` 之后禁止物理删除；`DRAFT` 阶段的 PR 若被删除，此时尚未产生审批记录（SUBMIT 才写记录） |
| O-03 | `operation_logs.document_id` 悬空 | 中 | 日志为**历史快照**，即使单据被删也应保留。字段设计为非 FK，`username_snapshot` 同理保留账号快照 |
| O-04 | `purchase_order_item_sources.pr_item_id` 指向的 PR 明细被删除 | 高 | FK 设 `ON DELETE RESTRICT`，数据库层禁止删除已被转单的 PR 明细 |
| O-05 | 物料/供应商被删除导致单据悬空 | 高 | 所有主数据 FK 均 `ON DELETE RESTRICT` + 只能 `DISABLE`，不物理删除 |
| O-06 | 用户被删除导致 `created_by` 悬空 | 中 | 用户只能 `DISABLE`；`operation_logs.operator_id` 设 `ON DELETE SET NULL` 兜底 |

> **source_id 为什么不加 FK？** 因为 `source_type` 多态（可指向 Receipt / 生产单据 / 调整单），MySQL 无法对同一列建多表外键。这是**有意的设计选择**，通过「源单据禁止物理删除」在业务层保证引用完整性，而非依赖数据库外键。

## 3. 并发风险

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| C-01 | 并发入库导致超收 | **极高** | 条件更新 `UPDATE po_items SET received_quantity = received_quantity + :qty WHERE id = :id AND received_quantity + :qty <= ordered_quantity`，校验 `rowcount == 1`。同时 DB CHECK 兜底 |
| C-02 | 并发入库导致余额重复增加 | **极高** | 与 C-01 同一事务；余额用条件 UPSERT，且 `quantity >= 0` CHECK 兜底 |
| C-03 | 并发转单导致 PR 超转 | 高 | `UPDATE pr_items SET converted_quantity = converted_quantity + :qty WHERE id = :id AND converted_quantity + :qty <= requested_quantity` + rowcount 校验 + CHECK 兜底 |
| C-04 | 重复入库单提交（前端重复点击 / 网络重试） | 高 | ① 前端按钮防抖；② `uk_ri_poi` + `uk_receipt_no` 唯一约束；③ 建议 Phase 9 增加幂等键（`request_id` 唯一索引） |
| C-05 | 并发审批同一单据 | 中 | 审批前对 PR 行 `SELECT ... FOR UPDATE`，事务内二次校验状态 |
| C-06 | 编号生成锁竞争 | 中 | 取号用独立短事务 + `ON DUPLICATE KEY UPDATE`，锁持有时间为单语句级（§6.2）。**不嵌套在业务事务内** |
| C-07 | 余额更新丢失（ABA） | 中 | `version` 乐观锁字段预留；第一阶段入库用条件更新（原子），暂不依赖 version。若未来引入"先读后写"逻辑必须启用 version |
| C-08 | 冲销与入库并发 | 高 | 冲销与入库均对 `po_item` / `inventory_balance` 做条件更新，且 Receipt 冲销前校验状态 = POSTED（状态机天然互斥） |

**并发测试用例（Phase 12 必测）**：

```python
async def test_concurrent_receipt_no_oversell():
    # PO 采购 100，两个请求同时入库 60
    # 期望：一个成功，一个失败（RECEIPT_EXCEEDS_REMAINING）
    # 断言：po_item.received_quantity == 60，库存 == 60，流水只有 1 条
```

## 4. 金额精度

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| M-01 | float 计算金额导致精度丢失 | 高 | 全链路 `DECIMAL(18,4)`；Python 侧 `decimal.Decimal`，`prec=28`，`ROUND_HALF_UP`；**代码审查禁止 float** |
| M-02 | 明细金额与「数量 × 单价」不一致 | 中 | 全部使用 **STORED 生成列**，数据库强制一致，应用层无法写入不一致值 |
| M-03 | 单据总额与明细合计不一致 | 中 | 服务端重算（`SUM(明细.amount)`）覆盖，不接受前端传值（需求 R13） |
| M-04 | 移动加权平均成本舍入误差累积 | 中 | `total_amount` 为权威值；余额归零时强制清零；文档中明确约定（§5.3） |
| M-05 | MySQL DECIMAL 除法精度不足 | 中 | 显式 `ROUND(x, 4)`；MySQL 8 除法默认精度 4 位以上，但显式 ROUND 更可控 |
| M-06 | 冲销金额与原始金额不一致 | 中 | 冲销取原始流水的 `amount`（带符号取反），不重新计算 |

## 5. 数量精度

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| Q-01 | 数量用整数类型无法表达 kg/m | 高 | 统一 `DECIMAL(18,4)` |
| Q-02 | 浮点累加导致余额与流水不符 | 高 | DECIMAL + `SUM()` 聚合；提供对账脚本（§10.9） |
| Q-03 | 数量为 0 或负数的明细行 | 中 | CHECK `requested_quantity > 0`、`ordered_quantity > 0`、`received_quantity > 0`、`sources.quantity > 0` |
| Q-04 | 累计收货量精度溢出 | 低 | DECIMAL(18,4) 整数位 14 位，制造业量级足够 |

## 6. 唯一性

| # | 对象 | 约束 |
|---|---|---|
| U-01 | 物料编码 | `uk_mat_code(material_code)` |
| U-02 | 供应商编码 / 仓库编码 | `uk_sup_code` / `uk_wh_code` |
| U-03 | 部门编码 / 角色编码 / 权限编码 | `uk_dept_code` / `uk_role_code` / `uk_perm_code` |
| U-04 | 用户名 | `uk_user_username(username)` |
| U-05 | 单据编号 | `uk_pr_no` / `uk_po_no` / `uk_receipt_no` / `uk_txn_no` |
| U-06 | 库存余额（仓库+物料） | `uk_ib(warehouse_id, material_id)` |
| U-07 | 库存策略（仓库+物料） | `uk_invpol(warehouse_id, material_id)` |
| U-08 | PO-PR 来源映射 | `uk_pois(po_item_id, pr_item_id)` |
| U-09 | 明细行号 | `uk_pri_line` / `uk_poi_line` / `uk_ri_line` |
| U-10 | 入库单内 PO 明细 | `uk_ri_poi(receipt_id, po_item_id)` |
| U-11 | 角色权限 | `uk_role_perm(role_id, permission_id)` |
| U-12 | 序列键 | `uk_seq(sequence_key, sequence_date)` |

## 7. 业务状态一致性

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| S-01 | 状态被前端直接修改 | 高 | API 层 **Schema 中不含 `status` 字段**（Create/Update schema 均无）；状态只能由 Service 方法变更 |
| S-02 | 非法状态转换 | 高 | Service 状态机显式校验（白名单式转换表），非法转换抛 `INVALID_STATUS_TRANSITION` |
| S-03 | `PENDING` 状态下修改内容 | 高 | Service 校验 `status == DRAFT` 才允许 update（需求 R1/R2） |
| S-04 | PR 状态与 `converted_quantity` 不一致 | 中 | 转换/取消时原子更新状态与数量（同一事务，§9.2） |
| S-05 | PO 状态与 `received_quantity` 不一致 | 中 | 入库/冲销后统一调用 `recompute_po_status()`（§9.3） |
| S-06 | 已收货的 PO 被取消 | 高 | 取消前校验 `SUM(received_quantity) == 0` |
| S-07 | 已转单的 PR 被取消 | 高 | 取消前校验不存在有效 PO（Q2，§8） |
| S-08 | `REJECTED` 直接跳到 `PENDING` | 高 | 状态机只允许 `REJECTED → DRAFT`，`DRAFT → PENDING`（Q1） |
| S-09 | 非本部门主管审批 | 高 | `department_managers` 表查询判定（§3.6），不写死 user_id |

**状态转换白名单（Service 层实现）**：

```python
PR_TRANSITIONS = {
    PrStatus.DRAFT:     {PrStatus.PENDING, PrStatus.CANCELLED},
    PrStatus.PENDING:   {PrStatus.APPROVED, PrStatus.REJECTED, PrStatus.CANCELLED},
    PrStatus.APPROVED:  {PrStatus.CONVERTED, PrStatus.CANCELLED},
    PrStatus.REJECTED:  {PrStatus.DRAFT},
    PrStatus.CANCELLED: set(),
    PrStatus.CONVERTED: set(),
}

PO_TRANSITIONS = {
    PoStatus.DRAFT:              {PoStatus.CONFIRMED, PoStatus.CANCELLED},
    PoStatus.CONFIRMED:          {PoStatus.PARTIALLY_RECEIVED, PoStatus.RECEIVED, PoStatus.CANCELLED},
    PoStatus.PARTIALLY_RECEIVED: {PoStatus.PARTIALLY_RECEIVED, PoStatus.RECEIVED},
    PoStatus.RECEIVED:           set(),
    PoStatus.CANCELLED:          set(),
}

RECEIPT_TRANSITIONS = {
    ReceiptStatus.POSTED:   {ReceiptStatus.REVERSED},
    ReceiptStatus.REVERSED: set(),
}
```

## 8. PR / PO 数量一致性

| # | 不变量 | 验证方式 |
|---|---|---|
| N-01 | `pr_item.converted_quantity <= pr_item.requested_quantity` | DB CHECK + 单元测试 |
| N-02 | `pr_item.converted_quantity == SUM(po_item_sources.quantity WHERE pr_item_id = X)`（仅统计非 CANCELLED 的 PO） | 对账脚本 |
| N-03 | `po_item.received_quantity <= po_item.ordered_quantity` | DB CHECK + 单元测试 |
| N-04 | `SUM(po_item_sources.quantity WHERE po_item_id = Y) <= po_item.ordered_quantity` | 转单 Service 校验 + 对账脚本 |
| N-05 | `po_item.received_quantity == SUM(receipt_items.received_quantity WHERE po_item_id = Y)`（仅统计 POSTED 的 Receipt） | 对账脚本 |
| N-06 | 若某 PR 所有明细 `converted == requested`，则 PR 状态 ∈ {CONVERTED, CANCELLED} | 对账脚本 |

**对账脚本（Phase 12 提供 `backend/scripts/reconcile.py`）**

```sql
-- N-02 校验：PR 明细已转数量 vs 来源表汇总
SELECT pri.id, pri.converted_quantity,
       COALESCE(SUM(pois.quantity), 0) AS sourced
FROM purchase_requisition_items pri
LEFT JOIN purchase_order_item_sources pois ON pois.pr_item_id = pri.id
LEFT JOIN purchase_order_items poi        ON poi.id = pois.po_item_id
LEFT JOIN purchase_orders po              ON po.id = poi.po_id AND po.status <> 'CANCELLED'
GROUP BY pri.id
HAVING pri.converted_quantity <> COALESCE(SUM(CASE WHEN po.id IS NOT NULL THEN pois.quantity ELSE 0 END), 0);
```

## 9. 库存账实逻辑

| # | 不变量 | 验证方式 |
|---|---|---|
| I-01 | `inventory_balance.quantity == SUM(inventory_transactions.quantity)` 按 (warehouse, material) 分组 | 对账脚本（核心校验） |
| I-02 | `inventory_balance.total_amount == SUM(inventory_transactions.amount)` | 对账脚本（允许 4 位小数内误差） |
| I-03 | `inventory_balance.quantity >= 0` | DB CHECK |
| I-04 | 同一 (warehouse, material) 余额行唯一 | `uk_ib` |
| I-05 | 每条流水 `balance_after` 单调递增序列正确 | 入库时按当前余额 + 本次数量写入；对账脚本按时间序重放验证 |
| I-06 | 流水数量符号与类型一致 | DB CHECK `ck_it_sign` |

**核心对账 SQL**：

```sql
SELECT b.warehouse_id, b.material_id, b.quantity AS balance_qty,
       COALESCE(t.txn_sum, 0) AS txn_qty
FROM inventory_balances b
LEFT JOIN (
    SELECT warehouse_id, material_id, SUM(quantity) AS txn_sum
    FROM inventory_transactions
    GROUP BY warehouse_id, material_id
) t ON t.warehouse_id = b.warehouse_id AND t.material_id = b.material_id
WHERE b.quantity <> COALESCE(t.txn_sum, 0);
-- 期望返回 0 行
```

## 10. 冲销逻辑

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| R-01 | 重复冲销导致库存变负 | **极高** | 冲销前查询是否已存在 `PURCHASE_IN_REVERSAL` 流水（source_id = receipt.id）；`inventory_balance` CHECK `quantity >= 0` 兜底 |
| R-02 | 用 `ADJUST_OUT` 冲销采购入库，丢失业务语义 | 高 | 独立枚举 `PURCHASE_IN_REVERSAL`；Code Review 检查项 |
| R-03 | 冲销数量超过原入库数量 | 高 | 冲销按**整单**进行，数量取自原入库明细，不手工输入 |
| R-04 | 冲销后 PO 状态未回退 | 中 | 冲销事务内调用 `recompute_po_status()`（§9.4 步骤 5） |
| R-05 | 冲销后 PR `converted_quantity` 未回退 | 中 | **设计决策：不回退**。冲销是仓库端纠错，PR→PO 的采购关系依然成立。若需重新采购，应新建 PO 而非回退 PR。需在 UI 与文档明确告知 |
| R-06 | 原始流水被 UPDATE/DELETE | 高 | append-only 触发器（§5.4） |
| R-07 | 冲销流水的 `unit_cost` 与原流水不一致 | 中 | 冲销流水复制原流水的 `unit_cost`，保证金额精确反向 |

## 11. 删除策略

见 §1.4 总表。补充：

| # | 风险 | 缓解措施 |
|---|---|---|
| X-01 | 应用层误调用 `session.delete()` 删除受保护单据 | 所有 `ON DELETE RESTRICT` FK 会阻断；Service 层不提供 delete 方法 |
| X-02 | 明细被单独删除导致单头金额不更新 | 明细 FK `ON DELETE CASCADE`（随头删除）；不允许单独删明细而不更新头（Service 层统一处理） |
| X-03 | 库存流水被清理脚本误删 | append-only 触发器；运维文档中标注禁止对 `inventory_transactions` 执行 DML |

---

---

*Review 完成。发现的高危项已纳入 Phase 3/9 实现检查清单。*
