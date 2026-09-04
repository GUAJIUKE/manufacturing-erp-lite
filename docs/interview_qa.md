# 项目追问与回答（Interview Q&A）

> 面向「Manufacturing ERP Lite」的项目追问 22 问。**所有回答严格基于仓库真实
> 实现**（标注了对应代码文件/测试），不包装任何不存在的技术。
> 建议面试前通读一遍，能用自己的话讲清「为什么」即可。

---

### 1. 为什么 PENDING 状态的 PR 不允许修改？

提交 = 内容冻结，保证审批人看到的与申请人提交的是**同一版本**。实现上：
编辑接口只接受 DRAFT（`update_pr` 的状态前提），且 PR/PO 的 Create/Update
Schema **刻意不含 `status` 字段**——前端根本提交不了状态，只能调 submit 让
服务端白名单流转（`_TRANSITIONS`）。若允许审批中改内容，会出现"批完发现需求
被改"的扯皮，审计也说不清。

### 2. 为什么用乐观锁？乐观锁和事务有什么区别？

单据编辑是低频操作，悲观锁（SELECT FOR UPDATE 锁整单到提交）持有窗口长、
体验差；乐观锁只在提交瞬间用 `WHERE version = :v` 条件更新比版本，冲突概率低，
失败提示"刷新后重试"即可。区别：**事务保证原子性**（一组写入要么全成要么全败），
**乐观锁保证不拿旧版本覆盖新版本**；乐观锁不替代事务——本项目的乐观锁更新
本身就在事务里，与 CAS、余额行锁叠加使用，各解决一层（docs/transaction.md §5）。

### 3. 为什么 PO 的来源数量必须严格等于订购数量？

`create_po` 校验 `SUM(sources.quantity) == ordered_quantity`，多一分少一分都
拒绝（`PO_SOURCE_QUANTITY_MISMATCH`）。因为本项目只支持「APPROVED PR 转单」，
没有无来源手工采购——PO 的每一件都必须能追溯到某张 PR 的需求。来源对不上 =
脏数据，宁可拒绝。这也让 PO→PR 的可见性与审计链路（sources 映射表）始终成立。

### 4. `converted_quantity` 有什么作用？

它是「这张 PR 明细已转出多少采购量」的累计值，是**拆单/部分转单**的物理基础：
一张 100 件的 PR 可以先转 60 给 PO-A，converted=60，剩下 40 仍可被后续 PO 转。
它同时也是防超转的 CAS 比较基准（`converted + qty <= requested`），并参与
PR 头 CONVERTED 的原子判定（全部明细转完才置位）。没有它，"一张 PR 是否还有
未转需求"就无法表达（docs/quantity_chain.md）。

### 5. 为什么 Receipt 不能 DELETE？为什么创建即 POSTED？

实物收货是不可逆业务事实：入库单一旦过账就影响库存、PO 数量与审计。
所以阶段一无 DRAFT、创建即 POSTED；错误不用 DELETE 撤销（DELETE 会留下
"曾经有货后来凭空消失"的黑洞），而是**整单冲销**置 REVERSED + 写负向流水，
让"入过、又冲了"全程留痕、可对账（SUM 恒等式不受影响）。

### 6. 为什么 Inventory Transaction 是 append-only？

流水是账本（ledger），改/删流水等于改历史。实现上不止"约定不删"：Alembic
迁移里建了 **MySQL 触发器 `trg_it_no_update` / `trg_it_no_delete`**，任何
UPDATE/DELETE（包括绕过应用直接改库）都被数据库拒绝。错误一律通过反向流水
（`PURCHASE_IN_REVERSAL`，带 `reversed_transaction_id` 指回原记录）纠正。

### 7. 为什么同时需要 Transaction 和 Balance？

流水回答"库存怎么来的"（审计/对账/追溯），余额回答"现在有多少"（高频查询）。
只留流水：每次查库存 SUM 全表，慢；只留余额：无历史、无对账。二者通过
**同一事务写入 + 符号同号规则**保证 `SUM(流水) == 余额` 恒成立
（数量与金额两条都成立，见 docs/inventory_design.md §4）。

### 8. 为什么库存金额不能用「库存数量 × 最新采购价」？

10 件 × 10 元 + 10 件 × 20 元：数量 × 最新价 = 20 × 20 = 400，凭空多出 100，
既没付款也不对应实物批次；移动加权平均 = (100+200)/20 = 15，金额 300 与累计
付款一致，且可被流水 SUM 验证。`total_amount` 是权威值（Decimal(18,2)
ROUND_HALF_UP），`average_unit_cost` 只是派生的显示值。冲销也按原始金额回滚，
保证任意时点账实一致。

### 9. 如何防止并发超收？

收货不是「SELECT 剩余量 → UPDATE」，而是把防超条件放进 UPDATE 的 WHERE：
`UPDATE ... SET received_quantity = received_quantity + :qty WHERE id=:id AND
received_quantity + :qty <= ordered_quantity`，`rowcount == 0` → 锁定读给出
准确剩余量后报 `RECEIPT_EXCEEDS_REMAINING`。两个仓库员对同一明细并发收货，
数据库行锁保证只有一个成功。转单的 `converted_quantity` 是同一套 CAS 思路。

### 10. SELECT FOR UPDATE 用在哪里？

用于**库存余额行**（`inventory_service.lock_balance`）：先
`INSERT ... ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)`（对已存在行取排他锁，
同时让首次并发创建不撞唯一键），再 `SELECT ... FOR UPDATE` 穿透 MVCC 快照读到
最新值，持锁到 COMMIT 完成移动平均计算——否则两笔并发入库会互相覆盖（丢更新）。
PO/PR 单头走乐观锁（version），不需要行锁。

### 11. 为什么还需要固定锁顺序？

两个多物料入库单若按"行序"锁余额：单 1 锁 A 等 B、单 2 锁 B 等 A → 死锁。
更隐蔽的：先插单头再锁余额时，单头 INSERT 的 FK 检查会对 PO/仓库行加共享锁
持到提交，两个并发入库同一 PO 会形成交叉等待。解法是**余额锁必须是事务内
第一组行锁，且全量去重后按 (warehouse_id, material_id) 升序一次取齐**
（`lock_balances` 唯一入口，按构造成立）。冲销例外：先原子 claim 自己的
receipt 行，再走同一锁序。

### 12. 为什么不同单位不能统计"总待收货数量"？

物料单位各异：芯片论 pcs、线材论米、轴承论套——100 pcs + 200 米相加毫无
业务意义。所以待收/待转只统计**单据数**（COUNT PR/PO），不 SUM 数量；涉及
数量的指标（低库存、库存金额）也都限定在明确单位/金额维度。跨单位求和是
管理看板最常见的假指标，项目里刻意不做（docs/dashboard_metrics.md 口径红线）。

### 13. Dashboard 为什么也需要对象级权限？

Dashboard 不是"所有人看同一份数字"，而是先按角色算范围再聚合：申请人只统计
自己的 PR，主管统计所管部门，采购的"待确认 PO"只数自己名下创建的 DRAFT
（与 confirm 的对象级规则一致），仓库看不到 PR 类指标（权限门返回 0 而非报错）。
若看板绕过业务域的范围函数另写一套统计，KPI 与列表页数字会不一致——所以
统计层**复用** `visible_pr_condition` / `visible_po_id_stmt`（P2 原则）。

### 14. 为什么 APPROVED PR ≠ 待采购？

系统支持拆单：一张 100 件的 APPROVED PR 可能已转 60、还剩 40。"待转采购需求"
的口径是 `status = APPROVED AND EXISTS(明细 converted_quantity <
requested_quantity)` 且 COUNT(DISTINCT PR)；全部转完的 PR 头会原子翻转为
CONVERTED，自动退出该口径。所以看板上"待转 2"是精确的业务含义，不是状态快照。

### 15. 状态机放在哪一层？为什么 Schema 不含 status？

状态机白名单（`_TRANSITIONS`）在 **Service 层**。若允许 API 直接写 status，
就没有"合法流转"可言；而放 Service 能被多条接口复用（收货/冲销推导 PO 状态
的 `recompute_po_status` 被两处调用）。Pydantic Create/Update Schema 不含
status 是同一决策的另一面：**客户端无从提交状态**（S-01），所有变更走
submit/approve/confirm/reverse 等业务动词。

### 16. 「有 pr:approve 权限」= 能批任意 PR 吗？

不能。`require_perm("pr:approve")` 只证明你是主管**角色**（菜单/功能级）；
Service 层 `_assert_approver` 会查 `department_managers`，必须是**这张 PR
申请部门的主管**才能批，否则 403 `PR_NOT_APPROVER`；ADMIN 可 override 但审计
显式标注。同理：BUYER 只能确认/取消**自己创建**的 PO（`_assert_buyer_or_admin`）。
这就是 RBAC 权限点 / 对象级权限 / 单据状态三层模型的叠加（docs/rbac.md）。

### 17. 冲销为什么要按「原始金额」而不是「当前均价」回滚？

第一笔 10×10=100、第二笔 10×20=200（均价 15）。若冲第一笔按均价扣 150，
余额剩 150，但实物只剩第二笔（成本 200）——账实不符。按原始金额扣 100 →
余额 200、数量 10、均价 20，与实物完全一致。这也是 `SUM(金额) == 余额金额`
恒等式成立的前提之一。实现：冲销流水的 amount 取 `-original.amount`，
unit_cost 取原始流水的 unit_cost。

### 18. PO 的 PARTIALLY_RECEIVED / RECEIVED 是怎么来的？

不是人工选的，是**推导**的：每次收货/冲销后执行 `recompute_po_status`——
按明细 `received_quantity` 全 0 → CONFIRMED、全满 → RECEIVED、否则
PARTIALLY_RECEIVED。好处：冲销最后一笔收货，PO 自动从 RECEIVED 退回
PARTIALLY_RECEIVED 再退回 CONFIRMED，不存在"记住的状态"与数据脱节。

### 19. 测试怎么写的？91% 覆盖率怎么做到的？

后端 pytest 229 项：15 类场景映射到既有测试文件 + 一条确定性端到端故事
（tests/test_workflow_e2e.py：五角色登录 → 物料 → PR → 审批 → PO → 两次收货
→ 超收拒绝 → 冲销 → 双冲拒绝 → `SUM(ledger)==balance` 断言），另外对
supplier/warehouse/role 补边界用例把实测覆盖推到 91%（门禁 >70%）。
**不造假**：部分低覆盖率来自闭合枚举的不可达分支（如角色集固定、无新增角色
接口），在 roadmap 里说明不强行造测试。前端 vitest 47 项 + vue-tsc + build。

### 20. 审计是怎么做的？能回答"这张库存怎么来的"？

三层留痕：单据状态流转写 `approval_records`（PR 每轮 提交/审批/驳回 都是记录，
REJECTED→DRAFT→重提是合法历史）；关键业务动作写 `audit_logs`
（RECEIPT_POST/REVERSE 等，含 operator 快照与 PO 状态变化）；
库存流水写 `inventory_transactions`（每行 balance_after 快照 + source 指向入库单
+ reversed_transaction_id 指向被冲销的原始流水）。三者结合可从余额一路追回
到最初那张 PR。

### 21. Dashboard 的 KPI 与列表页如何保证口径一致？

统计层**直接复用**列表页的范围函数（P2 原则，禁止在统计层复制第二套规则），
低库存 KPI 与库存页 `below_safety_stock=true` 查询是同一条件（有策略行且
`quantity < safety_stock` 严格小于）；`test_dashboard.py` 21 项 + seed_demo
自检锚定数字（待审批 2/待转 2/待确认 1/待收货 1/低库存 2/金额 1190.00），
前端点击 KPI 下钻到列表也带同一组筛选条件。

### 22. 为什么 Demo 数据能"可重复准备"？测试会不会污染演示库？

`python -m app.db.seed_demo`：先**清空业务数据**（专用 cleanup helper 处理
触发器与 FK 顺序）再通过真实 HTTP 链（in-process TestClient）重放确定性业务
故事，最后跑 KPI 自检，幂等可重复。测试套件独立走 `erp_lite_test` 库
（ENV=test 强制，且 config 校验禁止 dev/prod 指向 `_test` 库），与演示库隔离；
演示库的 seed 是显式命令，不会默认跑。

---

## 追问提示（如果面试官想深挖）

- 想看代码：`backend/app/services/*` 的 Service 层注释按 Phase 编号写清了
  每条规则的动机（如 `purchase_receipt_service.py` 头注释就是并发/事务设计摘要）。
- 想看数据库：docs/database-design.md（22 张表约束）+ docs/ERD.md。
- 想看取舍记录：docs/roadmap.md 的 Q1–Q16 决策（如 Q1 驳回路径、Q7 只做移动
  平均、Q11 单级审批预留 step_no）。
