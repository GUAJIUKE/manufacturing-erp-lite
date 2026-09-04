# 并发控制设计（Concurrency）

> 只讲本项目**真正实现**的五类并发机制，每个回答三个问题：
> 解决什么问题、怎么做、代码在哪。
> 代码事实来源：`app/services/purchase_requisition_service.py`、
> `purchase_order_service.py`、`purchase_receipt_service.py`、`inventory_service.py`。

---

## 0. 总原则

**禁止「先 SELECT 判断，再 UPDATE」**。任何「判断剩余量 → 更新」的经典写法在
并发下必然竞态：两个请求都读到剩余 50，各自减 30，最终超卖/超收 10。
本项目所有写前判断一律用**条件更新 + rowcount 校验**（CAS），把校验放进
UPDATE 的 WHERE 里，让数据库裁决。

## 1. PR 乐观锁（Optimistic Locking）

- **解决什么**：多人（申请人自己 + ADMIN）对同一张草稿/单据的编辑冲突——
  A 基于 version 3 编辑保存，B 也基于 version 3 保存，后提交者不应覆盖前者。
- **怎么做**：`purchase_requisitions.version`（默认 1）随每次
  update/submit/cancel/approve/reject/revise 递增。客户端每次操作携带
  `version`，Service 条件更新：

```sql
UPDATE purchase_requisitions
SET ..., version = version + 1
WHERE id = :id AND version = :version AND status = :expected_status
```

  `rowcount == 0` 后执行 `SELECT ... FOR UPDATE`（锁定读，穿透 REPEATABLE READ
  快照）区分两种原因：
  - 状态已被并发动作改走 → `4012 PR_ALREADY_PROCESSED`
  - 仅版本过期 → `4011 PR_VERSION_CONFLICT`（提示刷新后重试）

- **为什么用乐观锁而非悲观锁**：单据编辑是低频短操作，行锁持有窗口越短越好；
  version 冲突概率低，失败后前端提示刷新重试即可。PO 同款（`5012`）。
- **代码**：`_assert_version` / `_raise_if_concurrent_change`，
  `update_pr` / `submit_pr` / `approve_pr` / `reject_pr` / `revise_pr` / `cancel_pr`。

## 2. PO `converted_quantity` CAS（防并发超转）

- **解决什么**：同一张 APPROVED PR 被两个采购员**同时**转单。PR1 转 60、
  PR2 转 60，PR 只有 100——没有 CAS，两单都创建成功，总转出 120 > 100。
- **怎么做**：PO 创建事务内，对每个来源明细执行：

```sql
UPDATE purchase_requisition_items
SET converted_quantity = converted_quantity + :qty
WHERE id = :id
  AND converted_quantity + :qty <= requested_quantity
```

  `rowcount == 0` → 整单回滚，报 `4009 PR_ITEM_CONVERT_EXCEEDED`
  （"可能已被其他采购订单占用"）。
- **PR 头 CONVERTED 判定**同步原子化：用 `NOT EXISTS(未全转明细)` 的 UPDATE
  判定，避免两个并发转单事务各自基于快照漏置/重复置状态。
- **代码**：`create_po` 内逐 source CAS；`_flip_pr_to_converted` /
  `_flip_pr_back_to_approved`（PO 取消时的回退 CAS，条件 `converted_quantity >= qty`）。

## 3. Receipt `received_quantity` CAS（防并发超收）

- **解决什么**：两个仓库管理员同时对同一 PO 明细收货。剩余 60，A 收 40、
  B 收 40——没有 CAS，累计 80 > 60，超收。
- **怎么做**：

```sql
UPDATE purchase_order_items
SET received_quantity = received_quantity + :qty
WHERE id = :id AND received_quantity + :qty <= ordered_quantity
```

  `rowcount == 0` → 锁定读给出**准确剩余量**再报错：
  `6002 RECEIPT_EXCEEDS_REMAINING`（明细 N 入库 X 超过剩余可收 Y）。
- **多行入库单第二行超收**：第一行已做的 PO CAS + 流水 + 余额全部随事务回滚
  ——这正是「整单事务」的意义（详见 docs/transaction.md）。
- **冲销侧**：`received_quantity - 原始量 >= 0` 条件回退；找不到原始流水或
  已被冲销 → 拒绝（防数据异常下的错误回退）。
- **代码**：`create_receipt` / `reverse_receipt`。

## 4. 库存余额 SELECT FOR UPDATE（余额行锁）

- **解决什么**：余额「读-改-写」丢更新。两笔并发入库对同一
  (warehouse, material)：都读到 quantity=10，各自 +5，最后都写 15，
  正确答案应为 20。
- **怎么做**（`lock_balance`，两段式）：

```sql
-- ① 原子 upsert：对已存在行在 duplicate 分支取排他锁；
--    首次并发创建同一 key 的两事务在此串行化，不会撞唯一键报错
INSERT INTO inventory_balances (...)
VALUES (:wh, :mat, 0, 0, 0, 0, NOW(3), NOW(3))
ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)

-- ② 锁定读拿到最新已提交值（穿透 MVCC 快照）
SELECT * FROM inventory_balances
WHERE warehouse_id = :wh AND material_id = :mat
FOR UPDATE
```

  持有该行锁直到 COMMIT → 第二笔事务等待后从第一笔的结果继续算移动平均，
  不存在丢更新。锁内完成：校验非负 → 更新 quantity/total_amount → 重算
  `average_unit_cost` → `version+1`。
- **代码**：`inventory_service.lock_balance` / `lock_balances` / `apply_inbound` /
  `apply_outbound`。

## 5. 统一余额锁顺序（防死锁）

- **解决什么**：两个多物料入库单（单据 1：物料 A+B；单据 2：物料 B+A）若按
  行序锁余额，1 持 A 锁等 B、2 持 B 锁等 A → InnoDB 死锁回滚一个。更隐蔽的
  变体：先插单头再锁余额时，单头 INSERT 的 FK 检查会对 PO/仓库行加共享锁并
  持有到 COMMIT，两个并发入库同一 PO 可能形成
  「持 S(PO) 等余额锁 / 持余额锁等 X(PO)」的交叉等待。
- **怎么做**：余额锁必须是**事务内第一组行锁**，且**全量去重后按
  `(warehouse_id, material_id)` 升序一次取齐**（`lock_balances` 统一入口）：

  ```
  create_receipt： lock_balances(全 key 排序) → 插单头 → 逐行 PO CAS（按
                   po_item_id 升序）→ 流水 → 按同序写余额 → 推导 PO 状态
  reverse_receipt：先原子 claim 自己的 receipt 行（status POSTED→REVERSED），
                   再 lock_balances（同序）→ 回退 PO 行 → 反向流水 → 写余额
  ```

  全局只有这一个取锁入口，新路径（ADJUST/PRODUCTION 预留）天然遵守，
  规则「按构造成立」而非靠约定。
- **代码**：`inventory_service.sort_keys` / `lock_balances`；
  `purchase_receipt_service.create_receipt` / `reverse_receipt` 的调用位置注释
  （Review Fix §2）。

## 6. 并发冲销保护（Reversal Protection）

- **解决什么**：同一张 POSTED 入库单被两人同时点冲销 → 双冲（库存回退两次）。
- **怎么做**（两道闸）：
  1. **状态先原子 claim**：

     ```sql
     UPDATE purchase_receipts
     SET status='REVERSED', reversed_by=..., reversed_at=NOW(3), reverse_reason=...
     WHERE id = :id AND status = 'POSTED'
     ```

     `rowcount == 0` → 已被他人冲销（`6005/6006` 域），拒绝。
  2. **流水级防重**：冲销事务内查询
     `reversed_transaction_id == 原始流水 id` 是否已存在——即使绕过状态闸
     （理论防御），也无法对同一流水写两条反向记录。

## 7. 机制速查表

| 机制 | 保护对象 | 手段 | 失败表现（错误码） |
|---|---|---|---|
| 乐观锁 | PR / PO 单据编辑与流转 | `version` 条件更新 + 锁定读归因 | PR 4011/4012、PO 5012/5013 |
| converted CAS | PR 可转数量（防超转） | `converted_quantity + qty <= requested` | 4009 |
| received CAS | PO 可收数量（防超收） | `received_quantity + qty <= ordered` | 6002 |
| 余额行锁 | Balance 丢更新 / 首行并发 | upsert 取锁 + `SELECT FOR UPDATE` | 6009 负库存等 |
| 统一锁顺序 | 多余额死锁 | 全量排序一次取锁（事务第一组行锁） | 死锁消除 |
| 冲销保护 | Receipt 双冲 | 状态原子 claim + 流水反向存在性检查 | 6005/6006 |
