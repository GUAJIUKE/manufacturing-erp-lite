# 库存设计（Inventory Design）

> 两个核心概念 + 一套成本算法 + 一个恒等式。代码事实来源：
> `backend/app/models/inventory.py`、`backend/app/services/inventory_service.py`、
> `backend/app/services/purchase_receipt_service.py`。

---

## 1. 两个概念，绝不混淆

```
Inventory Transaction（流水）   =  append-only ledger（历史账本，事实的真相）
Inventory Balance（余额）      =  当前快照（派生缓存，永远不是权威）
```

| 维度 | Transaction | Balance |
|---|---|---|
| 语义 | 每一次库存变化的**历史记录** | 当前时点的**聚合结果** |
| 键 | 无业务唯一键（txn_no 唯一） | `UNIQUE(warehouse_id, material_id)` |
| 写入 | 只增（INSERT） | 随流水同事务更新 |
| 修改 | **禁止** UPDATE/DELETE（MySQL 触发器强制） | 仅由记账逻辑改 |
| 查询 | 历史审计、对账 | 库存页高频查询 |
| 权威性 | 事实来源 | 缓存，靠恒等式保证与流水一致 |

为什么需要两套而不是只留一套：

- 只留流水：每次看库存都要 `SUM` 全表，量大了慢；也没有"当前值"的快速读。
- 只留余额：没有历史，冲销无据、审计无链、无法回答"这个库存怎么来的"。
- 两个都留，靠**同事务写入 + SUM 恒等式**让它们永远一致（见 §4）。

## 2. 表结构与不可变约束

### 2.1 InventoryTransaction（流水）

关键列与约束：

```sql
transaction_type  -- ENUM：PURCHASE_IN / PURCHASE_IN_REVERSAL / ADJUST_IN /
                  --      ADJUST_OUT / PRODUCTION_OUT / PRODUCTION_IN
quantity          -- 带符号：入库 > 0；出库/冲销 < 0
amount            -- 与 quantity 同号：入库 ≥ 0（正常 > 0）；冲销 ≤ 0
unit_cost         -- 恒 ≥ 0（成本单价不是带符号量）
balance_after     -- 该笔后的余额快照（审计用）
source_type/id/item_id  -- 来源单据（PURCHASE_RECEIPT 等，逻辑引用非 FK）
reversed_transaction_id -- 指向被冲销的原始流水
```

- `CHECK it_sign`：入库类 `quantity > 0 AND amount >= 0`；出库/冲销类
  `quantity < 0 AND amount <= 0`。
- **append-only 由 MySQL 触发器强制**：`trg_it_no_update` / `trg_it_no_delete`
  在 Alembic 迁移中创建——不依赖应用层自觉。ORM/Service 层面没有任何
  UPDATE/DELETE 路径，但即使有人绕过应用直接改库，触发器也会拒绝。

### 2.2 InventoryBalance（余额）

```sql
UNIQUE(warehouse_id, material_id)  -- uk_ib
CHECK quantity >= 0                -- Q8 禁止负库存
CHECK total_amount >= 0
CHECK average_unit_cost >= 0
version INTEGER                     -- 行版本号（余额域乐观锁，备用）
last_transaction_at                 -- 最近变动时间
```

## 3. 符号约定与业务类型

| 业务 | Transaction 类型 | quantity | amount | 含义 |
|---|---|---|---|---|
| 采购入库 | `PURCHASE_IN` | `+qty` | `+amount` | 库存增加 |
| 冲销入库 | `PURCHASE_IN_REVERSAL` | `-qty` | `-amount` | 撤销一笔入库（反向流水） |

要点：

- 冲销使用**专用类型** `PURCHASE_IN_REVERSAL`，绝不借用 `ADJUST_OUT`——
  前者表达「撤销一笔采购入库」的业务语义，可被报表/审计直接区分。
- 冲销的 `amount` 取**原始流水的金额取负**（`-original.amount`），而不是
  `当前平均成本 × 数量`——之后若又有不同单价的入库，不应影响这笔历史冲销的
  回滚金额（见 §6 移动平均）。
- 错误纠正 = 写反向流水，原始记录永不删除/修改（审计链完整）。

## 4. 对账恒等式（账实一致）

```
SUM(inventory_transactions.quantity)  ==  inventory_balances.quantity
SUM(inventory_transactions.amount)    ==  inventory_balances.total_amount
```

成立前提（设计上保证，而非事后核对）：

1. 流水与余额**在同一事务**写入（receipt posting / reversal 全程一个
   `session_scope()`）。
2. 金额与数量**同号**（Review Fix §1 + `CHECK it_sign`），所以两条 SUM 各自成立。
3. 余额行首次出现用 `INSERT ... ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)`
   原子创建（并发首单不撞唯一键）。
4. Phase 9 业务边界内只有采购入库/冲销两条路径写库存（`ADJUST/PRODUCTION` 类型
   为枚举预留、未开放接口），恒等式在此边界内可验证——Phase 12 测试
   （test_workflow_e2e.py 的 `ledger SUM == balance` 断言）与 seed_demo 自检
   持续守护它。

> 该边界在「当前 Phase 9 业务边界」成立：若未来开放领料/生产入库等多路径，
> 每条新路径都必须走同一套 lock + write + apply 通道，恒等式不破。

## 5. 移动加权平均成本（Moving Weighted Average Cost）

### 5.1 定义

每次入库后重新计算平均成本：

```
新平均成本 = (原总金额 + 本次入库金额) / (原数量 + 本次入库数量)
```

### 5.2 简单案例（真实代码同款逻辑）

第一次采购：`10 件 × 10 元 = 100 元`
第二次采购：`10 件 × 20 元 = 200 元`

```
quantity      = 10 + 10 = 20
total_amount  = 100 + 200 = 300
average_unit_cost = 300 / 20 = 15.0000
```

第三次入库时若均价仍是 15，其成本按「(300 + 本次金额)/(20 + 本次数量)」继续
加权，而不是按最新采购价。

### 5.3 精度规则（money 工具）

- `total_amount`：`Decimal(18,2)`，每步 **ROUND_HALF_UP**（四舍五入）——是**权威值**。
- `average_unit_cost`：`Decimal(18,4)` 派生显示值，仅作展示/出库参考价。
- 数量与金额的舍入在**服务端**完成（`app/utils/money.py`），DB 不做隐式舍入；
  入库明细金额 = `ROUND_HALF_UP(quantity × unit_price, 2)`。
- 余额归零（冲销到 0）时平均成本强制清 0，避免移动平均尾差残留。

### 5.4 为什么库存金额不能用「库存数量 × 最新采购价」？（面试重点）

反例：先买 10 件 × 10 元（100 元），后买 10 件 × 20 元（200 元）。

- 用「数量 × 最新价」算：`20 × 20 = 400` —— 库存账面凭空多出 100 元，这 100 元
  既没有付出去，也不对应任何实物批次。
- 移动加权平均：`20 × 15 = 300 = 100 + 200` —— **与累计实际付款一致**，
  可被流水 SUM 对账验证。

更进一步，冲销/出库时若按「数量 × 当前均价」扣减，早期高/低价批次会被错误摊薄。
本项目冲销一律按**原始流水金额**回滚，确保任意时点：
`SUM(流水金额) == 余额总金额` 恒成立——这比任何「近似均价」都硬。

## 6. 冲销的成本语义（为什么要按原始金额）

场景：第一笔 10 件 × 10 元入库，第二笔 10 件 × 20 元入库（均价 15）。
现在冲销第一笔：

- 若按当前均价：扣 `10 × 15 = 150` → 余额剩 `300 - 150 = 150`，但实物上只剩
  第二笔 10 件（成本 200）——账实不符。
- 本项目实现：按原始金额扣 `-100` → 余额 `300 - 100 = 200`，数量 10，
  均价 20 ——与「只剩第二笔」完全一致。

这就是 `inventory_service.apply_outbound` 的 `amount` 参数语义：
**冲销金额 = 原始事务金额取负，永远不是 current_average × qty**。

## 7. 读路径（库存页 / Dashboard）

- 余额列表：`Balance + Warehouse + Material + 安全库存策略` 一次 join；无策略行
  时 `is_below_safety_stock = False`（没有策略就不告警），低库存判定
  `quantity < safety_stock`（严格小于，等于不算）。
- 流水列表：倒序（`transaction_at DESC, id DESC`），支持按仓库/物料/类型/
  来源/参考单号/时间过滤。
- 库存金额 KPI：`SUM(balances.total_amount)`（权威 2 位金额求和），不与
  「Σ 数量 × 均价」混算。

## 8. 一致性守护清单（测试锚点）

- `tests/test_purchase_receipt.py`：入库/冲销/并发/负库存拒绝
- `tests/test_inventory.py`：余额查询、低库存口径、流水过滤
- Phase 12 `test_workflow_e2e.py`：`ledger SUM == balance`（数量与金额双断言）
- `seed_demo.verify`：Dashboard KPI 自检（含 `inventory_total_amount == 1190.00`）
