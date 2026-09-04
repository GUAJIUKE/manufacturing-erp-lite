# 事务设计（Transaction：采购入库原子性）

> 说明「一次收货为什么必须是一笔事务」，并用一个真实失败案例解释回滚。
> 代码事实来源：`app/services/purchase_receipt_service.py::create_receipt` /
> `reverse_receipt` + `app/db/session.py` 的 `session_scope()`。

---

## 1. 一次入库 = 7 类写入，同生共死

`create_receipt` 在**调用方的一个事务**（`session_scope()`）内完成：

| # | 写入 | 说明 |
|---|---|---|
| 1 | Receipt 单头 | `purchase_receipts`（receipt_no / PO / 仓库 / 收货人 / POSTED） |
| 2 | Receipt 明细 | `purchase_receipt_items`（行 × po_item / 数量 / 成本单价快照 / 金额） |
| 3 | PO 明细已收量 | `purchase_order_items.received_quantity` CAS 累加 |
| 4 | 库存流水 | `inventory_transactions` 追加 `PURCHASE_IN` 行（含 balance_after） |
| 5 | 库存余额 | `inventory_balances` 更新 quantity / total_amount / 平均成本 |
| 6 | PO 状态 | `recompute_po_status` 推导（CONFIRMED → PARTIALLY_RECEIVED / RECEIVED） |
| 7 | 审计 | `audit_logs` 写 `RECEIPT_POST`（含 PO 状态变化 from → to） |

**必须一起成功、一起失败**：API 层只在所有 Service 调用完成后提交一次。
任一环节抛异常（业务校验 / CAS rowcount=0 / DB 约束 / 死锁回滚），整笔事务
ROLLBACK——界面上表现为「入库失败」，数据库不留任何半成品。

## 2. 为什么必须是一个事务（而不是逐行提交）

仓库收到一张多明细入库单，实物是一次到货事件。若逐行提交：

1. **部分成功 = 数据自相矛盾**：第 1 行入库成功、第 2 行超收失败——PO 已收
   数量、流水、余额停留在「只收了第 1 行」的状态，但用户看到的是整单失败。
   重试会重复收第 1 行（因为没有"整单"概念可判重）。
2. **对账恒等式被打破的窗口**：`SUM(流水) == 余额` 在任何中间态都不成立。
3. **失败恢复无从下手**：要么人工冲销第 1 行（又引入一笔操作），要么把
   "部分入库"当结果（业务不接受）。

单事务 + 整体回滚让「失败 = 无痕」，重试天然安全（幂等由 CAS 与状态前提保证）。

## 3. 失败案例：多行入库单第二行超收

```
PO 明细：L1 订 60（已收 0）   L2 订 40（已收 30，剩余 10）
入库请求：L1 收 40，L2 收 30（超收）
```

事务执行轨迹：

```
1. lock_balances((W, M1), (W, M2))      ← 全量排序取锁
2. INSERT receipt 单头                  ← flush 得到 receipt.id
3. L1：CAS 成功 received 0→40           ← 行锁 + 写回
      INSERT receipt_item L1
      INSERT transaction  PURCHASE_IN +40（balance_after=40）
4. L2：CAS 失败（30 > 剩余 10）rowcount=0
      → 锁定读：剩余 10 → 抛 RECEIPT_EXCEEDS_REMAINING（6002）
5. ── 异常向上传播，session_scope() ROLLBACK ──
```

**回滚效果**：第 3 步对 L1 做的**所有**修改（received_quantity 40、入库明细、
流水 +40、余额聚合）全部撤销——L1 的 PO 仍显示已收 0，库存无变化，无审计记录。
用户修正 L2 数量后整单重提即可。

这正是 §1 表格 7 类写入同事务的意义：**回滚的单位是"整张入库单"，不是"出错的
那一行"**。

## 4. 冲销（reverse）同样是单事务

`reverse_receipt` 在同一事务内：

1. 状态原子 claim：`UPDATE ... SET status='REVERSED' WHERE id=? AND status='POSTED'`
   （防并发双冲，rowcount=0 即拒绝）
2. 逐明细：PO 行回退 CAS（`received_quantity - 原始量 >= 0`）→ 定位**原始流水**
   → 校验未被冲销 → 追加 `PURCHASE_IN_REVERSAL` 反向流水（金额 = -原始金额）
3. 余额按原始金额扣减（归零时平均成本清 0）
4. `recompute_po_status` 推导 PO 状态（RECEIVED → PARTIALLY_RECEIVED → CONFIRMED）
5. 审计 `RECEIPT_REVERSE`

任一步失败（如找不到原始流水 `INVENTORY_BALANCE_MISMATCH`）→ 整体回滚，
receipt 仍是 POSTED，可重试/人工核查。

## 5. 事务与乐观锁的区别（面试高频）

| | 事务（Transaction） | 乐观锁（Optimistic Locking） |
|---|---|---|
| 解决的问题 | **原子性**：一组写入要么全成要么全败 | **并发冲突**：基于过期版本覆盖他人修改 |
| 粒度 | 一次业务操作（整张入库单） | 单张单据的版本校验 |
| 手段 | `session_scope()` 提交点 + ROLLBACK | `version` 列条件更新 |
| 失败表现 | 无痕回滚，可安全重试 | 拒绝本次提交，提示刷新后基于新版本重做 |
| 关系 | 事务是前提：CAS 只是事务内防超的一种 WHERE 写法 | 乐观锁本身不保证原子性，需要事务承载多行写入 |

一句话：**事务保证"要么全做要么不做"，乐观锁保证"不能拿旧版本覆盖新版本"；
CAS 是事务内把并发判断下沉到数据库行的实现手段。** 三者在本项目叠加使用，
各自解决一层问题。

## 6. 测试锚点

- `tests/test_purchase_receipt.py`：超收回滚、并发收货、冲销回退、双冲拒绝
- `tests/test_workflow_e2e.py`：端到端故事里完整走
  收 40 → 部分 → 收 60 → 已收完 → 冲销 60 → 回到部分收货，并断言
  `SUM(ledger) == balance`（数量 40 / 金额 400.00）与流水条数。
