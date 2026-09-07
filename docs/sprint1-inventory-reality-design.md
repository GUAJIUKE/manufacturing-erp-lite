# Reality Hardening Sprint 1 — Inventory Reality Design Report

> 阶段：Manufacturing ERP Lite · Reality Hardening Sprint 1（**DESIGN ONLY**）
> 日期：2026-09-04 ｜ 状态：待 Review，禁止实现
>
> 本报告为纯设计交付：未修改任何 Python / Vue / 数据库 / Alembic / API / 测试代码，
> 未执行 git commit。Review 通过前不进入实现。

> **修订 v2（Sprint 1 Design Review · 有条件通过 → 已应用 DA-001~DA-007，2026-09-04）**：
> ① DA-001 快照语义命名为 **Short Count Window + Snapshot Guard**，明细补 `book_total_amount_snapshot`，
> 创建后至 POST 前有 movement → item **stale** → 7005，禁止静默 rebase；② DA-002 盘盈 `valuation_rate`
> **后端必填显式确认**（>0，缺失拒绝），不再静默取均价；③ DA-003 时间语义三分离
> `business_date / created_at / posted_at`，能力命名 **Late Entry / Backdated Business Date**，
> 禁止称 True Backdated Inventory Posting；④ DA-004 冻结重定义：不拦旧 business_date，
> 落入冻结期仅标 **LATE_ENTRY**，未来 gate `effective_inventory_date`；⑤ DA-005 诊断 L2 按
> **physical posting order** 重放；⑥ DA-006 测试矩阵新增 7 项（T-46~T-52）；⑦ DA-007 Decision Log
> 修订 RD-002/004/007/015、新增 RD-018~RD-020。仍为 **DESIGN ONLY**：未实现、未提交。

---

## 0. 阅读指引（与任务书映射）

| 任务书节 | 内容 | 报告章节 |
|---|---|---|
| 一/二/三 | 范围、现实案例、账实偏差成因 | §1、§2 |
| 四/三十 | Reconciliation 模型 / 审计事件 | §3 |
| 五 | 状态机（审批与过账是否同一步） | §4 |
| 六/七 | 权限 / Self-Approval / SoD | §5 |
| 八/九 | Snapshot / Count Cutoff | §6 |
| 十/十一/十二/十三 | Adjustment Txn / 盘盈盘亏成本 | §7 |
| 十四 | Reversal | §8 |
| 十五/十六/十七/二十一 | Backdate（Late Entry / True Backdate 界定） | §9 |
| 十八/十九/二十 | Period Freeze | §10 |
| 二十四/二十五 | Ledger Ordering / Identity | §11 |
| 二十二/二十三/二十六/二十七/二十八/二十九 | Diagnostic | §12 |
| 三十一/三十二/三十三/三十四 | Concurrency / 锁 / 事务 / 幂等 | §13–§15 |
| 三十五/三十六/三十七 | 错误码 / API / UX | §16–§18 |
| 四十六/四十七 | 测试矩阵 / UAT | §19–§20 |
| 四十八/四十九/五十 | Decision Log / Limitations / 交付 | §21–§25 |

---

## 1. Current System Assessment（现状盘点）

### 1.1 已实现的业务链与不变量

```
PR → Approval → PO → Receipt → Inventory Transaction → Inventory Balance → Dashboard
```

已有关键事实（代码事实来源：`app/models/inventory.py`、`app/services/inventory_service.py`、
`app/services/purchase_receipt_service.py`、`docs/inventory_design.md`）：

| 项 | 现状 |
|---|---|
| 库存账本 | `inventory_transactions` **append-only**（MySQL 触发器禁 UPDATE/DELETE），`amount` 与 `quantity` 同号 |
| 余额 | `inventory_balances`，`UNIQUE(warehouse_id, material_id)`，`quantity/total_amount/avg` 均 ≥ 0，含 `version` 乐观锁列 |
| 恒等式 | `SUM(流水.quantity) == 余额.quantity` 且 `SUM(流水.amount) == 余额.total_amount`（同事务写入保证） |
| 成本 | 移动加权平均；`total_amount`(2 位, ROUND_HALF_UP) 权威，`average_unit_cost`(4 位) 派生；冲销按**原始流水金额**回滚，不按当前均价 |
| 并发 | `lock_balances()` 统一入口：去重后按 `(warehouse_id, material_id)` 升序一次性 `INSERT...ON DUPLICATE + SELECT FOR UPDATE`；PO 行/PR 行用条件 UPDATE + rowcount 校验 |
| 冲销 | 整单冲销，先 CAS 状态翻转（`POSTED→REVERSED`），再锁余额回滚 |
| 单据状态 | 均无 DRAFT 直过账（Receipt）或白名单状态机 + 版本号 CAS（PR/PO） |
| 审计 | `operation_logs` 关键业务动作（`RECEIPT_POST` 等），与业务同事务 |
| 主数据 | Material / Warehouse 均只有 ACTIVE / DISABLED（DISABLED 即"停用"，无物理删除） |
| 角色 | ADMIN / APPLICANT / DEPT_MANAGER / BUYER / **WAREHOUSE**（共 5 个，**无 WAREHOUSE_MANAGER**） |
| 流水类型 | `PURCHASE_IN / PURCHASE_IN_REVERSAL / ADJUST_IN / ADJUST_OUT / PRODUCTION_IN / PRODUCTION_OUT` —— **ADJUST_IN/OUT 已在 DB ENUM 与 `it_sign` CHECK 中预留，但无任何接口/服务使用** |
| 来源类型 | `PURCHASE_RECEIPT / PURCHASE_RECEIPT_REVERSAL / MANUAL_ADJUST / PRODUCTION_*`（同前：MANUAL_ADJUST 预留未用） |
| 业务日期 | Receipt **已支持 `receipt_date` 补录到过去日期**：`occurred_at = combine(receipt_date, now.time())`，按业务日取号；但**不做历史重算**，直接在当前余额上追加 |
| 时区 | 无业务时区配置，`date.today()` 即服务器本地"今天"；DB 时间列按 UTC 注释存储 |

### 1.2 现状与"账实现实"之间的鸿沟（Sprint 动机）

1. **没有任何"盘点/账实校正"入口**：库存只随采购业务被动变化，实物损耗、漏录、误拿无法入账。
2. **没有任何"冻结/期间"基础设施**：`stock_frozen_upto` 不存在；Late Entry 单据无 LATE_ENTRY 标记；
   也没有历史重算（True Backdate NOT IMPLEMENTED）。
3. **没有任何"账实一致性诊断"**：恒等式只在测试与 seed 自检里被验证，运行期无人检查。
4. 并发/锁/事务基建（§1.1）是**可复用的**：盘点过账路径应完全复用，而不是另起炉灶。

---

## 2. Reality Problem Statement（现实问题陈述）

### 2.1 核心现实案例（贯穿全报告）

- Warehouse：原材料仓；Material：ESP32。
- 账面（Book Quantity）= 100；实盘（Physical Quantity）= 97；差异 −3。

**禁止** `UPDATE inventory_balances SET quantity = 97`。必须走：
`Inventory Transaction`（账本）＋ `Inventory Balance`（余额）＋ 成本 ＋ 审计 ＋ 审批 ＋ 权限 ＋
并发 ＋ 历史时间 ＋ 冻结期间 ＋ 冲销/纠错 ＋ Dashboard 的完整约束。

### 2.2 为什么账实会不一致（不是"系统写错了"）

现实原因清单（按可能性分组）：

| 类别 | 现实原因 | 系统/流程侧归因 |
|---|---|---|
| 实物层 | 实物损耗（破损/过期/挥发）、仓库误拿、错料（发错料后混放）、丢失/被盗 | 无 |
| 记录层 | 漏录出库、漏录入库、历史单据补录（先货后单）、单位换算错误 | 业务漏记/晚记 |
| 流程层 | 盘点误差（数错/漏数/重复数）、人为操作失误、录入错误 | 盘点质量 |
| 系统层 | 系统集成失败（自动收货未同步）、数据迁移问题、接口重试/超时 | 系统缺陷 |

### 2.3 两类差异必须区分（A/B 分类与区分策略）

| | A. Physical Adjustment（实物调整） | B. Missing Business Transaction（漏录业务） |
|---|---|---|
| 本质 | **现实真的少了/多了**，账是对的 | **业务真实发生过**（领料/收货/报废），只是系统没记 |
| 例子 | 损耗 3 个 → 账面 100、实物 97 | 昨天实际领走 3 个但忘录 → 账面 100、实物 97 |
| 修复语义 | 校正现实与账面的差异（Adjustment） | 补记真实业务单据（Receipt / Issue / Transfer） |
| 副作用 | 校正的是库存**状态** | 补录会连带影响采购/生产单据链、成本流水链 |

**区分策略（流程 + 数据双层）**：

1. **单据层**：Reconciliation 只表达"某时点某仓某料实盘与账面之差"，不假装是业务单据；盘点明细必须填 `reason_code` + `remark`，把"为什么差"固化下来。
2. **操作指导层**（§16 前置文档 + UI 提示，见 §4.2 与 §21 RD-016）：把"这 −3 是昨天实际领料但忘录"这类诉求导向**补录真实业务链**（本系统当前唯一可补的是采购收货：走 PR→PO→Receipt），而不是一律开盘点单。只有"无对应业务单据可补 / 纯实物差异"才走 Reconciliation。
3. **审计层**：`reason_code = DATA_CORRECTION` 的行在审批时高亮、审计描述自动带"疑似可补录业务单据"提示
   （§3.5、§21 RD-016、§23 OQ-3）。

> **结论**：第一版用**同一张盘点单 + 强制的 reason_code/remark 引导**承载两类差异的"录入"，
> 但**语义上只认 A（实物校正）**；B 在文档/UI/审计上被显式引导去补真实单据。
> 不引入第二套"补录领料/报废"功能（超出 Sprint 范围，见 §22）。

---

## 3. Stock Reconciliation Model（盘点模型）

### 3.1 为什么需要一张"盘点单"而不是直接调余额

1. **审批与权限**：实物校正影响资产价值，不能由盘点人一键直达。
2. **审计链**：谁盘的、谁审的、按什么成本、差多少——都要有据。
3. **快照固化**：盘点针对的是"某个时间点的账面"，必须把该时点账面值固化（§6）。
4. **与现有单据文化一致**：PR/PO/Receipt 都是单据 + 状态机 + 版本号，盘点单沿用同一模式。

### 3.2 表设计草案：`stock_reconciliations`（单头）

沿用项目命名约定（与 `purchase_receipts` 同构），`PKMixin + TimestampMixin`：

| 字段 | 类型/约束 | 说明（为什么需要） |
|---|---|---|
| `id` | PK | 主键 |
| `reconciliation_no` | String(32), UNIQUE | `CNT-20260904-0001`；按**过账/创建业务日**取号（`number_sequences` 复用） |
| `warehouse_id` | FK warehouses, RESTRICT | 盘哪个仓 |
| `counted_by` | FK users, RESTRICT | 盘点人（服务端取自 token，客户端不可伪造） |
| `counted_on` | **Date** | 盘点业务日期。**v1 强制 = 今天**（RD-001，见 §9.5） |
| `status` | ENUM，见 §4 | 状态机 |
| `reason` | String(500) | 单头级盘点原因（可选） |
| `remark` | String(255) | 备注 |
| `submitted_at` | DATETIME(3) NULL | 提交审批时间（审计用） |
| `posted_at` | DATETIME(3) NULL | 过账时间 |
| `approved_by` | FK users NULL | 审批/过账人 |
| `approve_comment` | String(1000) NULL | 审批意见；驳回时必填 |
| `override_self_approval` | Boolean, default 0 | SoD override 标志（RD-006，§5.3） |
| `override_reason` | String(500) NULL | override 必填理由（审计用） |
| `freeze_override_reason` | String(500) NULL | 冻结期 override 理由。**v1 盘点 counted_on = 今天，不触发**；字段为未来 effective_inventory_date 门禁预留（DA-004，§10.4） |
| `reversed_by` / `reversed_at` / `reverse_reason` | 同 Receipt 冲销三件套 | 整单冲销（§8） |
| `version` | INT, default 1 | 乐观锁（DRAFT 编辑 / 状态 CAS 用） |

索引：`uk_reconciliation_no`；`ix_rc_wh_status`（warehouse_id, status）；
`ix_rc_counted_on`；`ix_rc_status`。

### 3.3 表设计草案：`stock_reconciliation_items`（明细）

| 字段 | 类型/约束 | 说明（为什么需要） |
|---|---|---|
| `reconciliation_id` | FK CASCADE | 从属单头 |
| `line_no` | INT | 行号，单内唯一 |
| `material_id` | FK materials, RESTRICT | 被盘物料 |
| `book_quantity_snapshot` | DECIMAL(18,4) ≥ 0 | **关键**：录入本行时固化的账面数量（§6 方案 A）。取数用普通 SELECT（建单期不制造余额行），行锁与建行只发生在过账时 |
| `book_total_amount_snapshot` | DECIMAL(18,2) ≥ 0 | 固化账面总金额（**DA-001 三快照之一**；守卫/审计对账用） |
| `book_avg_cost_snapshot` | DECIMAL(18,4) ≥ 0 | 固化账面移动平均价（决定盘亏金额，§7.2；**DA-001 三快照之一**） |
| `physical_quantity` | DECIMAL(18,4) **≥ 0** | 实盘数；**禁止负数**（§4.1/四十一） |
| `difference_quantity` | DECIMAL(18,4) | 服务端计算 = physical − book_snapshot（不为"权威输入"，只作一致性与展示） |
| `valuation_rate` | DECIMAL(18,4) > 0 NULL | **盘盈（ADJUST_IN）行必填且 > 0（DA-002）**：后端缺失即拒绝，**绝不静默取当前均价**；前端可预填 Suggested Valuation Rate（§7.3） |
| `adjustment_amount` | DECIMAL(18,2) | 服务端计算：盘亏 `money(\|diff\| × book_avg_cost_snapshot)`；盘盈 `money(diff × valuation_rate)` |
| `reason_code` | ENUM，§4.1 | 差异归因（必填，仅 diff≠0 行） |
| `remark` | String(255) | 行备注（DATA_CORRECTION 等场景必填说明） |
| `created_at` | DATETIME(3) | 明细时间 |

约束：`uk_ri_line(reconciliation_id, line_no)`；`uk_ri_mat(reconciliation_id, material_id)`；
`ck_rc_physical_nonneg`（physical ≥ 0）；`ck_rc_snapshot_nonneg`；
服务端保证 `difference_quantity = physical − book_snapshot`（可选 DB CHECK 同式兜底）。

**为什么 `difference` 不入库计算而是固化**：它只对"录入时点"成立；一旦审批前余额漂移，
旧的 difference 已不指向任何当前事实，必须被 POST 守卫拦截（§6.3），而不是悄悄沿用。

### 3.4 关键设计结论（回应任务书 §4 "字段可以调整，但必须解释为什么需要"）

- 每个字段都服务于四个目标之一：**审计链**（counted_by/submitted_at/approved_by/posted_at/version）、
  **语义固化**（book_quantity_snapshot/book_total_amount_snapshot/book_avg_cost_snapshot/counted_on）、
  **成本决策**（valuation_rate）、**合规**（override_reason/freeze_override_reason/reverse_reason）。
- 不建"盘点期间/盘点批"复杂结构；单头直接承载一次计数事件，明细支持 **Cycle Count / 部分盘点**（§4.3）。

### 3.5 审计事件设计（AuditAction 扩展草案，三十）

新增枚举（沿用 `operation_logs`，与业务同事务写入）：

| AuditAction | 触发点 |
|---|---|
| `STOCK_COUNT_CREATE` | 创建盘点单（DRAFT） |
| `STOCK_COUNT_UPDATE` | DRAFT 编辑（可选：合并进 CREATE 描述，避免过碎） |
| `STOCK_COUNT_SUBMIT` | 提交（DRAFT→PENDING） |
| `STOCK_COUNT_APPROVE` | 审批通过并过账（PENDING→POSTED，含 override 标志） |
| `STOCK_COUNT_REJECT` | 驳回（PENDING→REJECTED） |
| `STOCK_COUNT_REVERSE` | 冲销（POSTED→REVERSED） |
| `STOCK_FREEZE_CHANGE` | 修改冻结日（仅 ADMIN，§10.3） |
| `STOCK_FREEZE_OVERRIDE` | (future) effective-date 冻结门禁 override 实际发生（§10.4） |
| `INVENTORY_DIAGNOSTIC_RUN` | 诊断"手动执行"，记录分级结果摘要（§12.7 决策：**要审计**，理由见该节） |

不审计：普通 GET 列表/详情（对齐 Q15 只审计关键业务操作的现有原则）。

---

## 4. State Machine（状态机）

### 4.1 状态定义

```
DRAFT → PENDING → POSTED
           │  ↘ REJECTED → DRAFT（驳回可改）
POSTED → REVERSED（终态）
CANCELLED（DRAFT/PENDING 可撤，终态）
```

| 状态 | 含义 |
|---|---|
| DRAFT | 盘点人录入中（可增删行、改 physical/reason） |
| PENDING | 已提交待审批 |
| POSTED | 已审批并**过账**（库存已动，append-only 流水已写） |
| REJECTED | 审批驳回，退回 DRAFT 可改 |
| CANCELLED | 撤销（DRAFT 或 PENDING 期） |
| REVERSED | 已冲销（终态，对应反向流水已写） |

白名单转换（沿用 data-integrity-review §7 的 Service 层白名单风格）：

```
DRAFT:    {PENDING, CANCELLED}
PENDING:  {POSTED, REJECTED, CANCELLED}
POSTED:   {REVERSED}
REJECTED: {DRAFT}
CANCELLED / REVERSED: {}
```

### 4.2 关键问题：Approval 与 Posting 是否同一步？

| 方案 | 流程 | 优点 | 缺点 |
|---|---|---|---|
| 方案 1 | DRAFT→PENDING→APPROVED→POSTED | 审批与执行分离，可"先批后择机过账" | 多一个中间态；APPROVED 滞留窗口内余额继续漂移 → 过账时快照早已过期；需管理"已批未过账"清单；多一次操作 |
| 方案 2 | DRAFT→PENDING→**POSTED**（审批动作内直接过账） | 原子：状态翻转 + 流水 + 余额 + 审计在一个事务；无滞留窗口；与 Receipt"创建即过账"哲学一致；SoD 检查点收敛到单点 | 审批人同时是执行人（但 SoD 约束的是"≠ 盘点人"，依然成立） |

**结论：采用方案 2（审批即过账）**。理由：

1. 盘点校正的"批准"和"落账"之间**没有需要等待的中间动作**——不像 PR 批准后还要转 PO。
   拆开只会制造"已批准但账还没动"的不一致窗口（§6 的漂移问题被窗口放大）。
2. 本系统 Receipt 已确立"实物操作创建即过账"的文化；盘点过账同属实物校正。
3. 一个动作 = 一个事务 = 一次 CAS 幂等，天然规避"批了没过 / 过了没批"两类半程状态。
4. SoD 最小实现：审批人 ≠ 盘点人即可（§5.3），无需在两段分别校验。

未来若出现"仓管组长审批、仓管员执行过账"的组织结构，再拆 APPROVED/POSTED（见 §23 OQ-1）。

### 4.3 需求补全（三十八～四十三 在状态机内的落点）

| 需求 | 结论 | 依据 |
|---|---|---|
| 三十八 部分盘点 / Cycle Count | **支持**：明细由用户勾选物料录入，不要求全仓全盘；提交时逐行校验即可 | 单头只记录 warehouse 与"本次盘了哪些行"，不隐含全盘语义 |
| 三十九 账面 0 / 实盘 5（盘盈从零） | **支持**：`lock_balances` 的 upsert 语义本就"无行则建行"（`INSERT...ON DUPLICATE`），过账时余额行自动创建 | 复用 `lock_balance()`，无需新逻辑；成本按 §7.3 |
| 四十 diff = 0 | **允许提交/过账**；diff=0 的行**不产生流水**；整单全为 0 仍 POSTED（作盘点留痕/循环盘点凭证） | 记录盘点结果与产生库存变动是两件事；无变动即无流水（对齐恒等式，不写 0 流水） |
| 四十一 physical < 0 | **DB CHECK + 服务端校验双重禁止** | 负实盘无业务语义 |
| 四十二 material 盘点中途被停用 | 参照 Receipt 冲销原则：**创建时**物料必须 ACTIVE；**提交/审批/冲销**不因当前 INACTIVE 阻断 | "历史纠错不能被主数据停用阻断"（与 `reverse_receipt` 刻意不校验物料状态的既有设计一致） |
| 四十三 warehouse 盘点中途被停用 | 同上：创建时 ACTIVE；创建后停用**不阻断**已存在盘点单的提交/审批/冲销 | 仓停用是行政动作，不能使已发生的实盘作废 |

---

## 5. Permission / SoD（权限与职责分离）

### 5.1 现状核查：是否存在 WAREHOUSE_MANAGER

**不存在。** 现有 5 角色：ADMIN / APPLICANT / DEPT_MANAGER / BUYER / WAREHOUSE。
`WAREHOUSE`（"仓库管理员"，demo 用户 zhaoliu）当前拥有：`warehouse:view, po:view, receipt:view,
receipt:create, receipt:reverse, inventory:view, inventory_txn:view, inventory_policy:view, dashboard:view`。
审批能力只存在于 ADMIN（`pr:approve`/`po:confirm` 等）；`department_managers` 目前只挂了 RD 部门。

### 5.2 三种方案比较

| 方案 | 内容 | 优点 | 缺点 |
|---|---|---|---|
| A | WAREHOUSE 建单/录数，**ADMIN 审批**（纯角色二分） | 最省事 | 服务层到处硬编码 role_code（与现有"权限点 + 对象级规则"风格不符）；未来给"仓库主管"授权要改代码 |
| B | 新增权限点：`inventory:reconcile_create/submit`（给 WAREHOUSE）、`inventory:reconcile_approve`（给 ADMIN）；服务层只查权限 | 与 `pr:approve`/`receipt:reverse` 现有 RBAC 粒度一致；审批权可后续平滑授给新角色；可测（权限即矩阵数据） | 多几个 seed 权限行（成本极低） |
| C | 新增 `WAREHOUSE_MANAGER` 角色 | 组织语义最"像真 ERP" | 新增角色 = 改 RoleCode ENUM（DB migration）+ init_data + 全套 UI 角色映射；**为一个审批动作造角色，过度设计** |

**推荐：方案 B（最小合理）**。理由：当前系统权限模型是"权限点挂角色"，方案 A 违反该模型、
C 引入结构成本；B 只增加权限点数据 + 角色授权矩阵两行，行为上等价于"WAREHOUSE 建、ADMIN 批"，
但把"谁能审"变成数据而非代码。另：**不复用 `inventory:view` 当审批权限**——查看与审批职责必须分开（SoD）。

盘点单**读权限**：`inventory:reconcile:view` 授给 ADMIN + WAREHOUSE；WAREHOUSE 全仓可见
（与 Receipt 的 `_FULL_SCOPE_ROLES = {ADMIN, WAREHOUSE}` 一致——仓库职能天然是全公司仓）。

### 5.3 Self-Approval / SoD（七）

- **默认禁止 `approved_by == counted_by`**（审批/过账人 ≠ 盘点人）。
  因审批即过账，该单一检查同时覆盖"自批"与"自过账"，不需要两段检查。
- **ADMIN override**：允许，但必须同时满足：
  1. 调用者角色 = ADMIN 且持 `inventory:reconcile_approve`；
  2. 请求带 `override_self_approval=true` + **必填** `override_reason`（如"盘点人请假，唯一操作员"）；
  3. 落库两字段 + `STOCK_COUNT_APPROVE` 审计描述自动附加 `override_reason`。
- **最小 SoD 实现** = 服务层一行比较 + 三个字段/审计，不引入审批流框架。
- 兜底提示：仓库"自盘自审"是典型舞弊路径，UI 在提交前即提示"本人不能审批自己创建的盘点单"。

---

## 6. Snapshot / Cutoff Strategy（快照与盘点截断，DA-001）

### 6.1 问题重述（八）

盘点开始时账面 100；提交/审批前又来一张 +20 Receipt，账面变 120。
`difference` 到底按 97−100=−3 还是 97−120=−23？

**物理盘点针对的是"盘点进行时点"的库存**。实盘 97 是与"当时账面 100"对比得出的结论，
与后来的 +20 收货（无论货物是盘后才到、还是盘时已到但晚录）**在盘点语义上无关**。
若按 −23 过账，等于拿旧事实去改新状态，会把 +20 的业务影响一并吞掉——这是静默错账。

### 6.2 两个候选方案

| 方案 | 做法 | 风险 |
|---|---|---|
| A. Snapshot-based | 创建盘点行时固化**三快照**（book_quantity_snapshot / book_total_amount_snapshot / book_avg_cost_snapshot）；`difference = physical − snapshot`；过账时按 difference 调整**当前**余额 | 若创建后、过账前有 movement，快照即 stale → 判定（→ 守卫，§6.3） |
| B. Posting-time recalculation | 过账时才读当前余额算 difference | ① 实盘语义对不上（对的是"过账时"账面而非"盘点时"账面）；② 盘点人与审批人看到/批的 difference 会变，单据内容与审批所见不一致，审计失真；③ 中间任何一笔业务都会静默改写校正金额 |

**结论：采用 A（Snapshot-based）**，并配套**过账守卫**（非静默重算）。

**v1 方案命名：Short Count Window + Snapshot Guard（DA-001）**——"短计数窗口"指从快照固化到 POST
之间业务不被冻结但窗口很短，"快照守卫"指 stale 判定在 POST 时强制执行。

### 6.3 过账守卫（Posting Guard）与 Staleness 语义（DA-001）

- **Staleness 定义**：从盘点创建（快照固化）到 POST 之前，目标 (warehouse, material) 若发生
  **任何影响库存的 movement**（Receipt / 冲销 / 其他盘点过账等），则该 reconciliation item 视为 **stale**。
- POST 事务内、**取得余额 X 锁之后**做守卫判定：

```
lock_balances 后当前余额 quantity == book_quantity_snapshot ？
  相等  → 按冻结的 difference 过账（movement 净影响为 0，快照仍有效）
  不等  → 该行 stale → 抛 RECONCILIATION_BALANCE_CHANGED(7005)，整单回滚，提示：
          "盘点后该仓该料又发生业务，盘点基准已漂移（stale）；
           请刷新库存、确认实物后新建盘点单。"
          （v1 不提供 ignore / 静默 rebase 开关，见 §21 RD-004）
```

- **禁止**：stale 时**静默按最新 Balance 重算 difference** 后过账——那等于拿旧盘点去改新状态（静默错账）。
- **定位声明**：这是当前系统**没有 As-Of Inventory Engine** 前提下的**保守正确性策略**；
  守卫是 v1 对 §九"盘点期间能否继续收货"的轻量替代（§6.4）。
- 配套测试：**Reconciliation Staleness Test**（T-46 / T-47，§19，DA-006）。

### 6.4 Count Cutoff / 是否需要真正的 Warehouse Lock（九，DA-001）

| 方案 | 说明 |
|---|---|
| 真锁：盘点期间冻结整仓收货/发货/调拨 | 语义最干净，但要全局"计数锁"，要区分盘点仓/物料做阻挡，影响所有入库流程，UI/文案成本高 |
| 本方案（v1）：**Short Count Window + Snapshot Guard** | 不阻挡业务；创建时固化三快照 + 移动告警，POST 时守卫把 stale 行显式拒绝（§6.3） |

**结论（v1 不实现真锁）**：业务不中断（好）；代价是"创建盘点后又有 movement → 该盘点单基本作废，
需重盘"（坏，但**显式失败**而非静默错账，可接受）。

**Future Design（Count Cutoff T，本 Sprint 不实现）**：引入计数截断点 T，允许以
`Physical(T) + Movements after T` 推导当前库存，从而允许盘点单跨 movement 存活；
这需要 As-Of / 历史重放语义，见 §11 / §22。

---

## 7. Adjustment Transaction 与成本策略

### 7.1 流水类型（十）

**结论：复用已预留的 `TxnType.ADJUST_IN` / `ADJUST_OUT`，绝不借用 PURCHASE 类型。**

| 方向 | TxnType | quantity | unit_cost | amount |
|---|---|---|---|---|
| 盘盈（100→103） | `ADJUST_IN` | +3 | valuation_rate（**显式必填且 > 0，缺失拒绝，不静默取均价，DA-002**） | +money(3×rate) |
| 盘亏（100→97） | `ADJUST_OUT` | −3 | book_avg_cost_snapshot（= 守卫通过时点的当前库存均价） | −money(3×avg) |

- `PURCHASE_IN_REVERSAL` 语义是"撤销某笔采购入库"（回滚**原始单笔金额**），与盘点校正（按**余额层面均价**）
  的成本来源完全不同，混用会让报表/审计无法区分"撤销采购"与"实物损耗"。
- `it_sign` CHECK 已允许这两类（DB ENUM 无需改列定义，只扩 `TxnSourceType`）。
- **新增 `TxnSourceType.STOCK_RECONCILIATION`**（来源单据类型）＋ 可选 `TxnSourceType.STOCK_RECONCILIATION_REVERSAL`
  用于冲销反向行；`source_id = reconciliation.id`、`source_item_id = reconciliation_item.id`（沿用非 FK 多态引用惯例）。
- `write_transaction()` 的"amount 与 quantity 同号"校验天然兼容（ADJUST_IN 正、ADJUST_OUT 负）。
- 反向行（§8）通过既有 `reversed_transaction_id` 指回原始 ADJUST 行，形成纠错链。

### 7.2 盘亏成本（十二）

按快照移动平均价扣减，**均价不变**：

```
qty = 100, total = 1000, avg = 10
盘亏 −3：amount = −money(3 × 10) = −30.00
qty = 97, total = 970.00, avg = 970/97 = 10.0000（不变，推导见 apply_outbound）
```

- 语义：库存损耗分摊到整体平均成本（无批次可指认，符合无批次 ERP 的移动平均口径）。
- 与 PURCHASE_IN_REVERSAL 的区别在此显式化：**冲销采购**回滚"原单金额"；**盘亏**按
  **快照均价**（= 守卫通过时点的当前库存均价，两者相等，DA-001/DA-002）扣减——两者都维持
  `SUM(amount)==total_amount`，因为 amount 都是对余额的直接增减。
- 边界：`apply_outbound` 已拒绝 `new_total<0`（金额不足 → INVENTORY_BALANCE_MISMATCH 类冲突），天然兜底。

### 7.3 盘盈成本（十一：valuation rate 比较）与十三的推演

| 候选 | 做法 | 评价 |
|---|---|---|
| A. 当前移动均价 | +3×10 → total 1030, avg 10 | 简单；但盘盈来源不明的"价值"被系统假设为现均价 |
| B. 用户输入 valuation rate | rate=12 → total 1036, avg = 1036/103 ≈ 10.0583 | **业务数据驱动**，能正确展示"rate 会改写移动平均"（§13） |
| C. 最近采购价 | 扫历史 Receipt 取最近单价 | 需"最近采购"查询口径，无 GL 时仍只是近似；可作 UI "建议值" |
| D. 0 | +3×0 → 数量增金额不增 | 会拉低均价（1030→1000 分给 103），扭曲后续出库成本，**不可取** |
| E. 财务确认 | 等财务核价再入账 | 当前无财务模块，凭空引入"待核价"状态，**超范围** |

**结论（DA-002 修订）：ADJUST_IN 的 valuation_rate 必须显式确认；后端不得缺省。**

- **后端规则**：凡盘盈行（diff > 0，**含 Book Qty = 0 而 Physical > 0 的行**），`valuation_rate`
  **必填且 > 0**；缺失或 ≤ 0 → 拒绝（`RECONCILIATION_VALUATION_RATE_REQUIRED`，§18）。后端
  **绝不**在缺失时静默采用当前 `average_unit_cost`（消除"系统替业务定价"的歧义）。
- **前端规则**：当余额存在当前 avg_cost 时，允许预填 **Suggested Valuation Rate**（标注"建议值"，
  可修改、可清空）；不存在 avg_cost（零库存盘盈）时留空并提示必填。
- 为什么这样改：这是**库存成本 Demo，不是完整财务处理**——但"盘盈入账价是业务数据、必须由人确认"
  本身就是要展示的正确性认知；把均价当静默默认值会让用户无意识接受系统假设。
- **范围声明**：v1 只更新库存余额与流水；**不生成 GL / Accounting Entry / Financial Posting**。
- 精度：`total_amount` 权威 2 位 ROUND_HALF_UP；`average_unit_cost` 派生 4 位；与 §5.3 完全一致。

---

## 8. Reversal Strategy（盘点冲销 / 录错纠错，十四）

**场景**：POSTED 后发现 physical 录错（97 录成 79）。

| 方案 | 流程 | 现实语义 |
|---|---|---|
| A. Reverse original（冲销原盘点单） | 原单 POSTED→REVERSED（写反向 ADJUST 流水链回原行）；再开一张新盘点单 | "上次盘点作废，重盘一次"。审计链完整：79 那笔的错被显式撤销，读者看到原单+冲销+新单三段历史 |
| B. New reconciliation（直接再盘一次） | 不动原单，直接对当前账面 79 盘出 97 → diff +18 | 表面上结果一致（97），但审计上像是"一天盘了两次（79 然后 97）"，原录错被**静默覆盖**；avg 链上残留 79 那次的 -21 校正痕迹，解释成本高 |

**结论：推荐 A（Reverse original）**，复用 Receipt 冲销的成熟三件套：
CAS 状态翻转 `POSTED→REVERSED` + `reversed_by/reversed_at/reverse_reason`（整单，禁止编辑 POSTED 行）+
对每条原 ADJUST 流水写反向行（`reversed_transaction_id` 指回原行、金额取反、按原 unit_cost）+
审计 `STOCK_COUNT_REVERSE`。然后由用户新建一张正确盘点单（可复制原单 physical 修正）。
**为什么不是 B**：B 把"纠错"伪装成"新盘点"，破坏审计叙事，且可能掩盖系统性录入错误。
v1 禁止任何对 POSTED 单的直接编辑（对齐 Receipt"无 DRAFT、冲销纠错"原则）。

---

## 9. Backdate Strategy（历史补录 = Late Entry / Backdated Business Date）

### 9.1 时间语义三分离与能力命名（DA-003）

| 字段/概念 | 语义 | v1 取值 |
|---|---|---|
| `business_date`（单据业务日，Receipt = `receipt_date`） | 业务"名义发生日"（**标签**，可早于过账日） | 用户可填过去日期 |
| `created_at` | 单据/流水的物理录入时间 | DB 自动 |
| `posted_at`（库存影响时点） | **库存实际发生影响的时间** | 过账时刻（= 当前） |

现状：Receipt 允许 `business_date < posted_at`（`receipt_date` 补录），但**库存实际影响发生于
posted_at**：余额在当前值上直接追加，不重放后续流水，也不改写历史 Ledger。

**能力命名（必须遵守）**：本能力叫 **Late Entry / Backdated Business Date**（补录 + 业务日回填），
**禁止**描述为 **True Backdated Inventory Posting**（= 历史生效插入 + 后续 ledger/cost 重放，
当前版本 **NOT IMPLEMENTED**）。

### 9.2 哪些业务允许 backdate（十五）

| 单据 | 允许补录？ | v1 规则 |
|---|---|---|
| Receipt（采购入库） | **允许（Late Entry）** | 允许 `business_date < posted_at`；库存影响在 posted_at（当前期）发生；business_date 落入冻结历史期 → **标记 LATE_ENTRY**，不拒绝（DA-004，§10.2） |
| Reconciliation（盘点） | **禁止** | `counted_on` 强制 = 今天（RD-001）；backdated reconciliation 需要"历史时点账面快照"，v1 无重放引擎，禁止 |
| 手工 Adjustment | （v1 不存在独立入口，只随盘点产生） | — |

不默认全部允许的理由：每种单据的"历史化代价"不同——Receipt 有 PO 链可追溯、金额快照自 PO；
盘点/调整校正的是**时点状态**，一旦允许历史盘点就要回答"那之后所有流水怎么重算"，代价不成比例。

### 9.3 最大难点推演：True Backdate 会打破移动平均的时间序（十六）

（以下讨论的是 **True Backdated Inventory Posting**——把补录当作"历史生效插入"并重放后续 Ledger；
v1 不实现，但必须把后果讲清楚。）

现状：8/30 库存 100×10（avg 10）；9/01 入库 100×20 → 200×3000 avg 15；9/04 当前 200 total 3000 avg 15。
如果"简单在 9/04 执行 `balance += 50×12`（金额 +600）"且宣称其"生效于 8/31"：

- 新余额 = 250 × 3600，avg = 14.4。数字"自洽"，但：
  1. **9/01 的 avg 历史失真**：若按业务发生序（8/30→8/31→9/01），9/01 入库后的均价应是
     (1000+600+2000)/250 = 14.4；但 9/01 那笔流水的 `balance_after` 不是按该顺序算出的，
     历史中间态不可复现。
  2. 若补录发生时点之后有**出库**，出库时用错的 avg，追加永远无法修正历史出库行（append-only）。
  3. 要修正必须引入 `effective_inventory_date` + stable `posting_sequence` + ledger replay（§11），
     否则任何"补录生效到历史"的说法都是假的。

**结论**：v1 的 Late Entry **不**把补录"生效到历史"：`business_date` 只是标签，成本/余额按
`posted_at` 当前期追加；不重放、不改写历史 Ledger 序。True Backdated Inventory Posting
（repost 引擎）**NOT IMPLEMENTED**、超出本 Sprint（§22）。

### 9.4 四个方案比较（十七）

| 方案 | 正确性 | 复杂度 | 审计 | 用户理解 | 实现成本 | v1 判定 |
|---|---|---|---|---|---|---|
| A. 完全历史插入 + 重放后续 Ledger | 最高 | 高：需 posting_sequence + repost 引擎 + 期间冻结 | 好 | 难（"为什么我改 8/31 会影响 9 月均价"） | 高 | ✗ 超出 Portfolio 边界 |
| B. 禁止一切 backdate | 高（无历史） | 低 | 好 | 易 | 低 | 部分采纳：**盘点禁止** |
| C. 有限 backdate + 未冻结期 + inventory repost | 中高 | 中高（仍需 repost） | 好 | 中 | 中高 | ✗ 需要 A 的地基 |
| D. 只记 business_date，成本按 posting time | 中（历史成本链不精确，SUM 恒等式仍成立） | 低 | 中（occurred_at 保留真实业务日） | 易 | 低 | **采纳（Receipt 现状即 D）** |

**推荐：B（盘点）+ D（Receipt 保留业务日、成本按过账时）的组合，能力命名为 Late Entry（DA-003）**。
理由：Portfolio ERP 的价值在"把一件事做扎实 + 把边界讲清楚"，而不在模拟 SAP 的历史重算；
`SUM(流水)==余额` 恒等式在 Late Entry 下依然成立——代价是"历史中间态不可按 business_date 复现"，
而诊断 L2 按 physical posting order 重放（DA-005），Late Entry 不产生误报（§12.4）。

### 9.5 二十一：Backdate + Reconciliation（最危险组合）→ 第一版禁止

9/04 账面 100，用户要建"8/30 实盘 90"。若允许：9/01 的 +50 收货之后"当前应是"什么？必须重放
8/30→9/01 才能知道 8/30 的差该落到哪——**第一版没有重放引擎**，任何"当前余额→90"式实现都是错的。

**结论：RD-001，v1 盘点 `counted_on` 强制 = 服务器今天**。未来放开 = §11 的 posting_sequence/repost
地基落地之后（§22/§23）。若未来引入 `effective_inventory_date`，backdated reconciliation
须满足 `effective_inventory_date > frozen_upto`，否则需 `inventory:backdate_override` + reason + audit
（DA-004，§10.4）。

---

## 10. Stock Period Freeze（库存期间冻结，DA-004 重定义）

### 10.1 存储方案（十八）

| 方案 | 说明 | 评价 |
|---|---|---|
| A. 全局 `stock_frozen_upto` | 一行设置（单值日期） | **最小且合理**：v1 只有一个冻结维度；语义 = "库存生效（effective）日期 ≤ 该日即冻结"（DA-004），v1 只记录阈值 + LATE_ENTRY 标记 |
| B. 每仓库 frozen_upto | warehouses 表加列或独立表 | 灵活但 v1 无跨仓差异化业务诉求，纯增维护面 |
| C. Accounting Period 表 | 会计期间 + 开启/关闭状态 | 面向 GL/月结，超范围（§22） |

**结论：A**，落在一张极小的 `inventory_settings`（或复用单行 key-value）：v1 仅一个键
`stock_frozen_upto`（Date，NULL = 从未冻结，兼容现有 seed/历史数据语义——**存量数据不受影响**）。

### 10.2 冻结语义（DA-004 重定义）

**重要**：当前系统**没有 True Historical Posting**，因此 `stock_frozen_upto` **不是**"阻止用户填写
旧 business_date"的输入闸门。冻结针对的是**库存生效时点（effective inventory date）**，而不是单据上的
业务日标签。

```
stock_frozen_upto = 2026-08-31
v1 判例（9/04 创建 Receipt、business_date = 8/30）：
  posted_at（库存影响）= 9/04（当前开放期）→ 允许
  单据标记：LATE_ENTRY
  说明文案："Business occurred in frozen historical period,
            but inventory impact is posted in current period."
  8 月历史 Ledger：不得修改 / 重写

Future（引入 effective_inventory_date 后）：
  effective_inventory_date <= frozen_upto  → 拒绝（STOCK_PERIOD_FROZEN）
  除非：inventory:backdate_override + reason + audit
```

- **用 Date 而非 datetime**：冻结粒度为"日"，避免 datetime 边界含混；与既有
  `receipt_date / order_date / apply_date` 的 Date 口径对齐。
- 时区：业务"今天"取服务器本地日（现状 `date.today()`），§23 OQ-6 挂账。
- **v1 对 Receipt 的门禁点**：**不拒绝**旧 business_date；仅当 `business_date <= frozen_upto`
  时落 **LATE_ENTRY 标记**（单据/流水 remark 或独立标记列，落库方式见 §23 OQ-10）并在审计描述注明。
- **v1 对 Reconciliation**：counted_on = 今天，天然不在冻结语义内（RD-001）。

### 10.3 Freeze Override（二十，面向 Future effective date）

完全禁止 vs Admin override：

**结论：允许 Admin override（未来生效），做成最小权限模型而非 `if role == ADMIN`**：

1. 新权限点 `inventory:backdate_override`，仅授 ADMIN（seed 一行）；
2. **v1**：冻结不拦旧 business_date（§10.2），override 在 v1 **不触发**；
3. **Future**（引入 `effective_inventory_date` 后）：请求带 `freeze_override_reason`（必填）→ 落库 +
   审计 `STOCK_FREEZE_OVERRIDE`（记录单号 + 理由）；
4. v1 的等价物是 **LATE_ENTRY 标记**：自动标注 + 审计说明，无需人工 override。

### 10.4 Freeze × Late Entry 场景串起来（DA-004）

补录 Receipt：`business_date=8/30`、frozen=8/31、posted_at=9/04 → **允许** + LATE_ENTRY 标记
（库存影响发生在当前开放期 9/04；8 月历史 Ledger 不动）。`business_date=9/02`（开放期）→ 普通 Late Entry。
改冻结日：仅 ADMIN + `STOCK_FREEZE_CHANGE` 审计；与过账路径经 `inventory_settings` 行 `FOR UPDATE`
串行化（§13 Case D）。

---

## 11. Ledger Ordering / Identity（账本排序与身份，二十四/二十五）

### 11.1 Physical insertion order vs Business effective order（DA-005）

- **append-only（物理不可变）** 约束的是 `inventory_transactions` 的行本身：永不 UPDATE/DELETE，
  新行永远物理追加（id 单调）。
- **v1 的库存生效顺序 == physical posting order（物理过账序，= 追加/id 序）**：因为 current
  version 的 business_date **不决定库存估值顺序**（估值只发生在 posted_at，§9.3），重放/诊断一律
  按物理过账序，**不要用 business_date 排序**。
- True Backdate（Future）才引入 **effective_inventory_date + stable posting_sequence** 用于
  historical replay；在那之前"按 id 重放"与"按业务生效重放"是同一件事，不存在矛盾。

### 11.2 时间语义（v1 + 未来规范）

| 字段 | 语义 | v1 用途 / 说明 |
|---|---|---|
| `business_date`（=transaction_at / receipt_date） | 业务**标签日**（可早于过账日 = Late Entry） | 报表/显示用；**不驱动**库存估值顺序 |
| `created_at` | 物理录入/追加时间 | 审计"何时录入"；v1 append 序 = id 序 |
| `posted_at` | 库存**实际生效**时间 | v1 估值/余额变动的唯一依据 |
| `posting_sequence`（未来，可空列） | 每个 (warehouse, material) 上实际应用顺序的单调计数 | True Backdate 重放引擎的稳定主序 |

v1 不建 `posting_sequence`（无 repost 引擎）；诊断 L2 重放按 **physical posting order（id 升序）**
执行（§12.4，DA-005）。现有 `list_transactions` 用 `transaction_at DESC, id DESC` 仅作展示倒序，
不代表重放顺序。

---

## 12. Inventory Consistency Diagnostic（库存一致性诊断）

### 12.1 定位

只读、只检测、**不自动修复**（二十三/二十八）。产出按 (warehouse, material) 分组的差异报告。

### 12.2 检查项（二十二/二十四）

**L1 — SUM 恒等式**（对每个有余额行或无余额但有流水的键）：

```
diff_qty  = SUM(流水.quantity)          − 余额.quantity
diff_amt  = SUM(流水.amount)            − 余额.total_amount
```

**L2 — 重放校验**（每个 (warehouse, material)）：按 **physical posting order（id 升序）** 重放，检查
① 重放过程数量不出现负值（中间态合理性）；② 每条流水的 `balance_after` == 重放序下的 running 值；
③ 重放终值 == 余额。（DA-005：**不用 business_date 排序**——当前 business_date 不决定库存估值顺序；
True Backdate 落地后才切到 effective_inventory_date + posting_sequence 重放。）

**L3 — 孤立余额/孤儿流水**：有流水无余额行（正常应为 0 后归零清理？余额行不删——qty=0 行允许存在）
等结构检查（列为可选增强）。

### 12.3 输出列（二十三）

| Warehouse | Material | Ledger Qty | Balance Qty | Qty Diff | Ledger Amt | Balance Amt | Amt Diff | Status |
|---|---|---|---|---|---|---|---|---|
| … | … | SUM(qty) | balance.quantity | diff | SUM(amount) | balance.total_amount | diff | OK/WARNING/ERROR |

### 12.4 Severity（二十六）——Decimal 与 tolerance

| 状态 | 判定 | 说明 |
|---|---|---|
| OK | L1 两个 diff = 0 且 L2 重放逐行 `balance_after` / 终值吻合 | 完全一致 |
| WARNING | L1 diff = 0、L2 终值吻合，但重放中间态为负等**结构可疑但不破坏恒等式**的提示性情形 | 提示性；**v1 正常业务不应出现**，出现即需人工核查（不再是"backdate 已声明特性"——DA-005 下 Late Entry 不产生该偏差） |
| ERROR | L1 qty/amt diff ≠ 0，或 L2 任一 `balance_after` / 终值与重放不符 | 恒等式被打破或账本链断裂 = 真实数据损坏（同事务写入被绕过 / 手工改库 / 迁移缺陷） |

**不引入 tolerance**：金额与数量全链路 Decimal + ROUND_HALF_UP；L1 SUM 与 L2 重放都走**同一算术
路径**（余额按物理过账序逐一累加，流水 `balance_after` 也是同一路径的产物），因此必须**精确**相等；
任何 diff 都意味着"有一条路没走统一记账"，不是浮点噪声——tolerance 会掩盖它。

### 12.5 Scope 与权限（二十七）

- 接口要求 `inventory:view`（与库存页一致）。现有系统**无按物料/仓库的对象级行权限**
  （WAREHOUSE/ADMIN 全量可见、Receipt 的对象级 scope 只作用于单据链），
  诊断读取的是库存快照本身，**沿用同一可见性**：ADMIN/WAREHOUSE 全量，其余角色按其 `inventory:view`
  决定能否进入诊断页。诊断接口**不创建第二套绕过规则**。
- 参数：`warehouse_id? / material_id?` 过滤；不传 = 全部（权限内）。

### 12.6 Repair（二十八）——本 Sprint 只设计 Future Direction

- Future：`Repair Balance`（对 ERROR 行按流水 SUM 回写 balance 并 bump version，需 ADMIN +
  二次确认 + `INVENTORY_DIAGNOSTIC_REPAIR` 审计）；`Repost Ledger`（需 §11 posting_sequence 引擎）。
- 为什么不在本 Sprint：任何"自动改余额"都可能在根因未明时掩盖系统缺陷（迁移 bug/触发器被绕过），
  修复动作本身是高危操作，应由 Review 单独开 Sprint 决策。

### 12.7 审计（三十）：DIAGNOSTIC_RUN 要审计吗

**结论：审计"显式执行（run）"、不审计普通 GET。** 诊断是控制活动（control activity），
审计痕迹要回答"何时谁跑过、当时看到了什么"；但带筛选的页面 GET 高频且只读，不产生控制价值。
实现：`POST /inventory/diagnostics/run` 返回结果并写一条 `INVENTORY_DIAGNOSTIC_RUN`
（摘要：scope + OK/WARNING/ERROR 计数）；`GET /inventory/diagnostics` 只读不审计。
（轻量折中，见 §23 OQ-7。）

### 12.8 Dashboard 影响（二十九）——第一版不加 KPI

| 选项 | 分析 |
|---|---|
| Dashboard 显示"库存账异常: 2" | 有告警价值，但 v1 无定时任务，数字只能来自"每次加载全量扫描"或"上次手动 run 的缓存"，前者随库存量线性变贵且与过账并发（REPEATABLE READ 下是合法快照但语义弱），后者需要新增"诊断结果缓存表"与失效管理 |
| 本 Sprint 不加 | 诊断是运营动作不是执行 KPI；把"异常数"强塞首页 = 为展示而加 |

**结论：v1 不加 Dashboard KPI**；仅在两处露出：库存菜单入口红点（读取最近一次 run 结果概要，
无缓存则隐藏）+ 库存诊断页自身。未来有定时任务后再把 KPI 上 Dashboard（§23 OQ-8）。

---

## 13. Concurrency（并发场景设计，三十一）

| Case | 场景 | 是否需要锁 | 设计 |
|---|---|---|---|
| A | 两人同时 approve 同一 reconciliation | **必须串行** | POST 前 CAS：`UPDATE ... SET status='POSTED' WHERE id=? AND status='PENDING' AND version=?`；rowcount=0 → 7006 RECONCILIATION_ALREADY_PROCESSED（复用 PR 4012 模式）。后到者失败，不产生第二组流水 |
| B | reconciliation POST vs Receipt（同仓同料） | **必须串行（行锁）** | 两条路径都经 `lock_balances()`（§14），余额行 X 锁互斥；若 Receipt 恰在快照后落账 → POST 守卫（§6.3）抛 7005，显式失败 |
| C | reconciliation reversal vs Receipt | **必须串行（行锁）** | 冲销先 CAS 翻转本单状态再锁余额（同 reverse_receipt 顺序），与 Receipt 锁序一致，无死锁（§14） |
| D | freeze 日期修改 vs Late Entry POST（未来含 effective date 门禁） | **必须串行（设置行锁）** | 涉及冻结判定的过账事务先对 `inventory_settings` 行 `SELECT ... FOR UPDATE`；改冻结日同样锁该行 → 二者互斥，杜绝"边改冻结边放行"。v1 的 Late Entry 不拒绝旧 business_date，Case D 风险极低，串行保留以面向 future |
| E | diagnostic vs 正在 posting | **允许读到合法快照** | 诊断只读聚合，InnoDB REPEATABLE READ 快照下看到的是过账事务前或后的完整状态（同事务内多表一致），不会读到半程（流水写了余额没写）。不加锁；结果以"run 时点快照"标注 |
| F | 两盘点单同料（叠盘） | 行锁串行 | 各自按快照+守卫判定；第二个若快照已漂移则失败重盘，天然防叠盘错账 |

补充：**盘点过账不支持"锁余额前先读快照再算"**——守卫判定必须在取得 X 锁后做（否则 TOCTOU）。

---

## 14. Lock Ordering（锁顺序，三十二）

**结论：Reconciliation 的所有余额锁必须复用 `inventory_service.lock_balances()` 统一入口，
禁止另建一套 reconciliation 专用锁序。**

三条写库存路径的锁序对比：

| 路径 | 第一步 | 随后 |
|---|---|---|
| Receipt create | （校验后）`lock_balances()` 全量有序取锁 | 插单头(FK S 锁在后)、逐 PO 行 CAS、写流水、apply |
| Receipt reverse | 先 CAS 翻转本 receipt 状态 | 再 `lock_balances()` 有序取锁 → 回滚 |
| **Reconciliation POST（新）** | **先 CAS 翻转本单状态（POSTED）** | **再 `lock_balances()` 有序取锁** → 守卫 → 写 ADJUST 流水 → apply |
| Reconciliation reverse（新） | 先 CAS 翻转本单（REVERSED） | 再 `lock_balances()` 有序取锁 → 反向流水 → apply |

- 三种路径中**余额锁永远经同一入口、同一 (warehouse_id, material_id) 升序**；任何两路径并发都不会
  出现 A 持 1 等 2 / B 持 2 等 1 的交叉死锁。
- Reconciliation 先"认领自己的单据行"再取余额锁，与 `reverse_receipt` 同构；没有其他路径会以反序
  锁 reconciliation 行，故无环。
- 守卫/冻结校验都放在**取到余额锁或设置锁之后**的事务内执行（避免读-改竞态）。

---

## 15. Transaction Boundary（事务边界，三十三）

Reconciliation POST 一个事务内依次完成（失败全回滚）：

```
1. CAS 状态认领 PENDING→POSTED（幂等闸门，§13-A）
2. （涉及冻结判定的未来场景）读取并锁 inventory_settings 行（v1 盘点 counted_on = 今天、无 freeze/backdate 判定，本步为 future 预留）
3. lock_balances(全部 diff≠0 行)                 ← 统一锁序（diff=0 行不锁不写）
4. 逐行（diff≠0）守卫：balance.quantity == book_quantity_snapshot（否则 7005 回滚）
5. 逐行计算并 write_transaction(ADJUST_IN/OUT × N)
6. 逐行 apply_inbound / apply_outbound（同锁序写回）
7. reconciliation 头/明细状态与 posted_at/approved_by/version 更新
8. audit_service.write_audit(STOCK_COUNT_APPROVE)      ← 同事务
9. 调用方统一 COMMIT / 异常 ROLLBACK
```

- "第二个 material 更新失败 → 全部回滚"由"单一 session + 单次 commit"保证（与 Receipt §十六同款）。
- 明细差异为 0 的行跳过 5/6（不产生流水，§4.3 四十）。
- DRAFT 编辑（PUT）与 SUBMIT 用 `version` CAS（对齐 PR 4011 模式）；重复点击/网络重试不会产生双份
  （SUBMIT 幂等 + POST CAS，§34）。

---

## 16. API Draft（三十六）

| API | v1 需要？ | 说明 |
|---|---|---|
| `GET /stock-reconciliations` | ✅ | 列表（状态/仓库/日期过滤 + 分页），读权限 `inventory:reconcile:view` |
| `POST /stock-reconciliations` | ✅ | 建 DRAFT 单；服务端写 counted_by/counted_on=today、按行锁读快照 |
| `GET /stock-reconciliations/{id}` | ✅ | 详情（头+明细+审计摘要） |
| `PUT /stock-reconciliations/{id}` | ✅ | 仅 DRAFT 可编辑；version CAS；重新锁读刷新快照？——**不刷新**：快照在**创建行时**固化，编辑只允许改 physical/reason/remark/增删行（新增行才取新快照） |
| `POST /{id}/submit` | ✅ | DRAFT→PENDING；提交前校验（明细非空、diff 行均有 reason_code、负库存校验先行预览） |
| `POST /{id}/approve` | ✅ | **审批即过账**（§4.2）：PENDING→POSTED；含 SoD/override/守卫（staleness）全链路（§13/15） |
| `POST /{id}/reject` | ✅ | PENDING→REJECTED（comment 必填）；REJECTED→DRAFT 走 PUT |
| `POST /{id}/cancel` | ✅ | DRAFT/PENDING→CANCELLED |
| `POST /{id}/reverse` | ✅ | POSTED→REVERSED（§8；reason 必填） |
| `GET /inventory/diagnostics` | ✅ | 只读查询（带过滤），权限 `inventory:view`，不审计 |
| `POST /inventory/diagnostics/run` | ✅ | 显式执行全量/范围扫描 + 结果 + 审计（§12.7） |
| `GET/PUT /inventory/settings` | ✅ | 仅 ADMIN（`inventory:settings:manage`）：读写 `stock_frozen_upto`；PUT 审计 `STOCK_FREEZE_CHANGE` |
| 独立"approve-only / post-only"拆分 | ❌ | 方案 2 已合并，不提供 |

**被剔除的**：`/submit` 与 `/approve` 之外的任何"状态直接跳变"接口；批量过账接口（v1 单仓单处理）。
错误全部走现有 `ApiResponse` 信封 + 7xxx 业务码。

---

## 17. Frontend UX Draft（三十七）

页面树（库存管理模块内新增）：

```
库存管理
├ 当前库存          (BalanceListView 已有)
├ 库存流水          (TransactionListView 已有)
├ 库存盘点          ← ReconciliationList / Create / Detail
└ 库存诊断          ← DiagnosticView
```

**盘点列表**：单号/仓库/状态/盘点人/日期/差异行数；状态徽标（DRAFT/PENDING/POSTED/REJECTED/REVERSED）；
操作按钮按状态与权限渲染（提交/审批/驳回/冲销）。

**创建（核心交互）**：
1. 选仓库 → 加载该仓余额（Balance + 安全库存）为候选行；
2. **用户只输入**：勾选要盘的物料（**部分盘点**，默认全选可取消）+ `physical_quantity` + `reason_code`(+remark)；
   `book_quantity`/`book_avg_cost` 只读（来自服务端快照）；
3. `difference` 前端**实时预览**（只读展示 = physical − book），**后端权威计算**（提交/过账时重算比对）；
4. 盘盈行展开 `valuation_rate`（**必填**；有当前均价时预填 **Suggested Valuation Rate** 建议值，可改/可清空；Book=0 盘盈留空并提示必填，DA-002）；diff=0 行灰色标注"无差异，过账不产生流水"；
5. 底部提示：盘点创建后若该仓该料发生业务，过账可能被守卫拦截（§6.3）。

**详情/审批**：明细表 + 差异汇总；PENDING 时对 ADMIN 显示【通过（过账）】【驳回】；
SoD 触发（本人盘点）时显示 override 对话框（勾选 + 必填理由）；POSTED 后显示【冲销】。

**诊断页**：过滤条件（仓库/物料）→ 手动"运行诊断"按钮 → 分级结果表（§12.3 列），ERROR 红、WARNING 黄、
OK 绿；附"只读检测、不自动修复"声明与 run 时间戳（快照语义）。按中国股市配色习惯的延伸不适用——
库存诊断用常规红黄绿状态语义即可（非涨跌场景）。

**Receipt（入库）页**：当 `business_date <= frozen_upto` 时显示 **LATE_ENTRY** 徽标与说明文案
"业务发生于冻结历史期，库存影响过账于当前期"（DA-004，§10.2）。

---

## 18. Error Code Draft（三十五，规划 7xxx 段）

```
# 7xxx stock reconciliation & inventory reality
RECONCILIATION_NOT_FOUND         = 7001
RECONCILIATION_INVALID_STATUS    = 7002
RECONCILIATION_VERSION_CONFLICT  = 7003
STOCK_PERIOD_FROZEN              = 7004   # (future) effective_inventory_date ≤ frozen_upto 拒绝（v1 Late Entry 不拒绝）
RECONCILIATION_BALANCE_CHANGED   = 7005   # 过账守卫：item stale（快照漂移，DA-001）
RECONCILIATION_ALREADY_PROCESSED = 7006   # CAS 认领失败（并发/重复审批）
RECONCILIATION_SELF_APPROVAL     = 7007   # SoD：审批人==盘点人（未 override）
RECONCILIATION_OVERRIDE_REASON_REQUIRED = 7008
RECONCILIATION_EMPTY_ITEMS       = 7009
RECONCILIATION_REASON_CODE_REQUIRED     = 7010
RECONCILIATION_PHYSICAL_NEGATIVE = 7011
RECONCILIATION_ALREADY_REVERSED  = 7012
RECONCILIATION_NOT_POSTED        = 7013
RECONCILIATION_ITEM_NOT_FOUND    = 7014
RECONCILIATION_NOT_PENDING       = 7015   # submit/approve 前置状态不符
RECONCILIATION_ITEM_ADDED_AFTER_SUBMIT  = 7016（预留，若未来允许审批中编辑）
RECONCILIATION_VALUATION_RATE_REQUIRED = 7017   # 盘盈行 valuation_rate 缺失或 ≤ 0（DA-002）
BACKDATE_NOT_ALLOWED             = 7020   # (future) backdated reconciliation / effective date 门禁
BACKDATE_OVERRIDE_REASON_REQUIRED = 7021
INVENTORY_SETTINGS_FORBIDDEN     = 7030
INVENTORY_SETTINGS_INVALID_DATE  = 7031
```

**`INVENTORY_DIAGNOSTIC_MISMATCH` 是否应为业务错误码？——不是。** 理由：错误码表达"请求无法按预期完成"；
诊断结果表达"数据当前状态与恒等式不符"，是**返回值（payload）**而非请求失败。mismatch 行应出现在
诊断响应里（每行一个 status），HTTP 仍 200；只有"执行诊断本身失败"（超时/参数错）才用 1xxx/校验码。
任务书 §35 的判断与之呼应：不把数据状态塞进异常体系。

---

## 19. Test Matrix（30+ 测试设计，四十六）

> 仅设计，不实现。编号 T-01…；分类覆盖任务书全部类别。

| # | 分类 | 用例 | 预期 |
|---|---|---|---|
| T-01 | StateMachine | DRAFT→PENDING→POSTED 合法链 | 每步成功 |
| T-02 | StateMachine | PENDING→PENDING（重复 submit） | 7003/7015，不产生双流水 |
| T-03 | StateMachine | POSTED 后 PUT 编辑 | 拒绝（仅 DRAFT 可编辑） |
| T-04 | StateMachine | POSTED→REVERSED→再 reverse | 7012 |
| T-05 | RBAC | WAREHOUSE 调 approve | 403（无 inventory:reconcile_approve） |
| T-06 | RBAC | APPLICANT 查盘点列表 | 403（无 reconcile:view） |
| T-07 | RBAC | ADMIN 全流程通过 | 200 全链成功 |
| T-08 | SoD | 盘点人 = 审批人（同人 approve） | 7007 |
| T-09 | SoD | 同人 + override 无理由 | 7008 |
| T-10 | SoD | 同人 + override + 理由（ADMIN） | 成功，审计含 override_reason |
| T-11 | Decimal | 盘亏金额 ROUND_HALF_UP（3×10.3333=31.00? 边界） | amount == money(Δ×avg) |
| T-12 | Decimal | avg 尾差：多次盘盈后 avg 4 位、total 2 位一致 | SUM(amount)==total_amount |
| T-13 | AdjOut | 100→97，avg=10 | qty 97 / total 970.00 / avg 10.0000 / 流水 −3 |
| T-14 | AdjOut | 盘亏量 > 当前余额 | 6009 负库存拒绝，全回滚 |
| T-15 | AdjOut | 盘亏金额 > total_amount | 6010 金额不足拒绝 |
| T-16 | AdjIn | 100→103，显式 rate=12 | qty 103 / total 1036.00 / avg 1036/103（4 位） |
| T-17 | AdjIn | rate=0 | 拒绝（估值率必须 >0，盘盈不可 0 入账） |
| T-18 | AdjIn | 多行同料不同 rate | 按行分别入账、余额一次聚合正确 |
| T-19 | ZeroDiff | 全行 diff=0 过账 | POSTED，**0 条流水**，余额不变 |
| T-20 | ZeroBalance | book=0、physical=5 盘盈 | lock_balance 自动建行 → 余额 5 |
| T-21 | ZeroBalance | 无余额行且 diff=0 | 快照照常记录，但不过账写行 → 余额行数不变（断言） |
| T-22 | Concurrency | 两线程同时 approve 同单（Case A） | 恰 1 成功 1 ×7006，流水仅 1 组 |
| T-23 | Concurrency | POST vs Receipt 同料（Case B） | 串行；若 Receipt 先落账 → 7005 守卫 |
| T-24 | Concurrency | Reverse vs Receipt（Case C） | 无死锁，先后串行，终值 = 数学期望 |
| T-25 | Concurrency | freeze 修改 vs Late Entry POST（Case D） | 设置行锁串行；互斥无漏放 |
| T-26 | Concurrency | Diagnostic run vs POST（Case E） | 读到一致快照，不报错不阻塞 |
| T-27 | Rollback | 第 2 行 material 失败 | 第 1 行流水/余额/状态全回滚 |
| T-28 | Rollback | 守卫 7005 触发 | 状态仍 PENDING，可撤回/作废 |
| T-29 | InactiveMaster | 盘点创建后物料 DISABLED 再 submit/approve | **允许**完成（历史纠错不被阻断） |
| T-30 | InactiveMaster | 建单时物料已 DISABLED | 拒绝（MASTER_DATA_DISABLED） |
| T-31 | Freeze | business_date(8/30) ≤ frozen_upto(8/31)、posted_at=9/04 | **允许** + LATE_ENTRY 标记（Late Entry，DA-004） |
| T-32 | Freeze | counted_on 过去日期 | 拒绝（RD-001） |
| T-33 | Freeze | future：effective_inventory_date ≤ frozen_upto + override | 默认拒绝；override(ADMIN + 理由) 成功 + STOCK_FREEZE_OVERRIDE 审计（v1 不触发，DA-004） |
| T-34 | Backdate | Late Entry：Receipt business_date < posted_at（回归） | 成功（库存影响在 posted_at），SUM 恒等式成立，不重写历史 Ledger |
| T-35 | Backdate | Late Entry 后诊断 L2 | **OK**（DA-005：L2 按 physical posting order 重放，Late Entry 不产生偏差）；L1 OK |
| T-36 | Diagnostic | 手工 UPDATE 余额行（模拟损坏） | L1 ERROR，qty diff ≠ 0 |
| T-37 | Diagnostic | 手工 DELETE 一条流水（触发器应拦截） | ERROR/无法执行 → 断言触发器生效 |
| T-38 | Diagnostic | 权限：无 inventory:view 用户 run | 403 |
| T-39 | Diagnostic | L1 OK 且 L2 逐行吻合（含 Late Entry 行） | OK（全绿，DA-005） |
| T-40 | Ledger | ADJUST 行 quantity 符号/类型绑定 | it_sign CHECK 生效（INSERT 正数到 ADJUST_OUT 拒绝） |
| T-41 | Ledger | ADJUST 行 append-only | 触发器禁 UPDATE/DELETE（同 6011 语义） |
| T-42 | Balance | 过账后 SUM(qty)==balance 且 SUM(amount)==total | 恒等式成立 |
| T-43 | Balance | 盘盈后 avg 变化符合移动平均公式 | 1036/103 断言 |
| T-44 | Audit | POST 成功写 STOCK_COUNT_APPROVE | operation_logs 1 条含单号 |
| T-45 | Audit | DIAGNOSTIC_RUN（显式 run）写审计、GET 不写 | run 1 条 / GET 0 条 |
| T-46 | Staleness | 盘点创建 qty=100 → 同仓同料 Receipt +20 → approve | stale → 7005 拒绝（DA-001，Reconciliation Staleness Test） |
| T-47 | Staleness | stale 拒绝后的副作用检查 | 无 ADJUST 流水、余额不变、无 STOCK_COUNT_APPROVE 审计（DA-001） |
| T-48 | AdjIn | Book=0、Physical=5、缺 valuation_rate | 拒绝（7017，DA-002） |
| T-49 | AdjIn | Book=0、Physical=5、valuation_rate=12 | ADJUST_IN +5 / amount +60.00，余额 qty5/total60（DA-002） |
| T-50 | Freeze | business_date 在冻结历史期内、posted_at 当前 | 允许 + LATE_ENTRY 标记（DA-004） |
| T-51 | Backdate | Late Entry 不重写历史 Ledger 序 | 冻结期无新增/改写流水；id/追加序不变（DA-004/DA-005） |
| T-52 | Diagnostic | 含 Late Entry 的 ledger 跑 L2 | 按 physical posting order（非 business_date）重放 → 通过（DA-005） |

（52 个 ≥ 30 达标）

---

## 20. UAT Matrix（10+ 业务场景，四十七）

> UAT 不用 pytest 表达；给业务角色可执行剧本。

| UAT ID | 业务角色 | Precondition | Action | Expected Result | Business Reason |
|---|---|---|---|---|---|
| UAT-01 | 仓管 zhaoliu | 原材料仓 ESP32 账面 100 | 开盘点单：physical=97, reason=COUNT_VARIANCE → 提交 | PENDING；快照=100、diff=−3 固化 | 记录实盘差异，进入审批 |
| UAT-02 | 仓管 zhaoliu | UAT-01 后 | 对自己建的单点【审批过账】 | 7007 拒绝并提示 SoD | 防止自盘自审舞弊 |
| UAT-03 | 管理员 admin | UAT-01 PENDING | 点【审批过账】 | 库存 100→97；流水 −3 ADJUST_OUT；余额 total 970；审计 1 条 | 审批即过账，账实一致且留痕 |
| UAT-04 | 仓管 | 账面 100、实盘 103（盘盈） | 建单 physical=103；rate 显式填 10（前端建议值 10） | 预览 +3；审批后 103 / total 1030 / avg 10 | 盘盈按显式确认的估值率入账 |
| UAT-05 | 仓管 | UAT-04 后 | rate 改 12 再过账 | 103 / total 1036 / avg≈10.0583 | 估值率是业务数据，会改写移动平均 |
| UAT-06 | 仓管 | 账面 0、实盘 5 | 建单（此前无余额行）；rate 必填 = 12 | 审批过账自动建余额行 → qty 5 / total 60.00 | 零库存盘盈必须显式估值（DA-002） |
| UAT-07 | 仓管+admin | 盘到一半，另一仓管做了一笔 +20 Receipt | 提交后 admin 审批 | 7005：快照漂移，提示重盘 | 防止用过期盘点改当前账 |
| UAT-08 | 仓管+admin | UAT-03 已过账 | 发现 physical 应为 97 但录成 79 | 点【冲销】→ 新建正确单 | 冲销原单保留审计链，禁止编辑 POSTED |
| UAT-09 | 仓管 | 实际收货 50 忘录（frozen=8/31，今天 9/04） | 补一张 business_date=8/30 的入库 | **允许**（库存影响发生在 9/04 当前期）；单据标 LATE_ENTRY；8 月 Ledger 不动 | 冻结历史期业务走 Late Entry：账务落当前开放期，不伪造历史过账（DA-004） |
| UAT-10 | 仓管 | business_date=9/02（开放期） | 补录 | 成功，单据显示业务日 9/02，库存影响 = 9/04 过账时 | 开放期内 Late Entry，成本按 posted_at |
| UAT-11 | admin | future：引入 effective_inventory_date 后想补 8/30 | override + 理由 | 默认拒绝；override(ADMIN + 理由) 成功 + 审计（v1 不触发） | 例外放行必须留痕可追（DA-004） |
| UAT-12 | admin | 怀疑账有问题 | 库存诊断 run（全部） | 输出分级表；ERROR/WARNING 行给出数量差异 | 只读诊断暴露账实问题，不自动改账 |

（12 个 ≥ 10 达标）

---

## 21. Decision Log（四十八）

| ID | 决策 | Alternatives | Reason | Future Extension |
|---|---|---|---|---|
| RD-001 | **盘点不允许 backdate**（counted_on = 今天） | 允许历史盘点 + 重放 | 第一版无重放引擎；历史盘点需要"历史时点账面"，否则任何实现都是错的 | §11 posting_sequence + repost 引擎落地后再放开 |
| RD-002 | **盘盈（ADJUST_IN）valuation_rate 必须显式确认**：后端必填且 > 0、缺失拒绝，**不静默取当前均价**；前端仅可预填 Suggested Valuation Rate | A 均价静默兜底 / C 最近采购价 / D 0 / E 财务确认 | 盘盈入账价是业务数据，不能由系统静默定价（DA-002）；Book=0 盘盈同样必填 | 财务模块落地后接"待核价/损益科目" |
| RD-003 | **盘亏按快照移动平均**（amount=|Δ|×avg_snapshot） | 原单金额式回滚（不适用，无原单） | 损耗无法指认批次，均摊口径 + SUM 恒等式成立 | 批次/序列化后按批扣减 |
| RD-004 | **Snapshot Guard：盘点创建后目标 (wh, mat) 有 movement → item stale → POST 7005 拒绝；无 ignore、无静默按最新余额 rebase** | 警告放行 / 自动 rebase | **当前版本限制而非完整 Count Cutoff 方案**——无 As-Of Inventory Engine 下的保守正确性策略（DA-001） | Count Cutoff T（Physical(T) + Movements after T）落地后可放宽 |
| RD-005 | **审批与过账同一步（PENDING→POSTED）** | 拆 APPROVED/POSTED | 无中间等待动作；避免滞留窗口 + 半程状态；与 Receipt 文化一致 | 出现"组长批、组员过账"组织时拆分 |
| RD-006 | **Self-approval 默认禁止；ADMIN override 需理由 + 审计** | 完全禁止 | 小团队有合法单人场景；override 留痕满足 SoD | 多级审批流 |
| RD-007 | **冻结 = 全局 `stock_frozen_upto`(Date)，语义 = "库存生效（effective）日期 ≤ 该日即冻结"** | 每仓 / Accounting Period 表 | 无 True Historical Posting 时不得把冻结当"业务日输入闸门"（DA-004）；v1 只记录阈值 + LATE_ENTRY 标记 | 每仓冻结、会计期间、effective_inventory_date 门禁 |
| RD-008 | **用 Date 不用 datetime 冻结** | datetime | 冻结粒度为"日"，日期边界无时区含混 | 业务时区配置落地后细化 |
| RD-009 | **错误纠错 = 冲销原盘点单再开新单** | 直接再盘（B） | 保留审计链，避免"错被静默覆盖" | — |
| RD-010 | **ADJUST_IN/OUT 复用预留枚举 + 新增 TxnSourceType.STOCK_RECONCILIATION** | 新建 STOCK_ADJUST_* 枚举 | 枚举已在 DB/CHECK 预留；来源类型区分单据语义 | 手工 Adjustment 独立入口 |
| RD-011 | **Diagnostic mismatch 不是业务错误码** | 7000+ 码表达 | mismatch 是数据状态（返回值）不是请求失败 | — |
| RD-012 | **DIAGNOSTIC_RUN 显式执行要审计** | 全不审计 / 全审计 | 控制活动需要"何时谁跑过、看到什么"；GET 高频只读不审 | 定时任务化后审计任务触发 |
| RD-013 | **Diagnostic 不自动修复，Repair/Repost 只留 Future** | 发现即修 | 自动修可能掩盖根因，属高危操作 | 单独 Sprint |
| RD-014 | **权限 = 新增 permission 点（方案 B），不新增角色** | A 角色二分 / C WAREHOUSE_MANAGER | 与现有 RBAC 粒度一致；不造角色 | 未来可挂 WAREHOUSE_MANAGER |
| RD-015 | **冻结 override 用权限点（`inventory:backdate_override`）+ 必填理由 + 审计，非 `if ADMIN`** | 纯角色判断 | v1 不触发（冻结不拦旧 business_date，DA-004）；为 future effective_inventory_date 门禁预留 | effective date 门禁上线时启用 |
| RD-016 | **盘点单只认实物校正语义；漏录业务引导补录真实单据** | 让 Adjustment 万能化 | Adjustment 不是漏录业务的替代品（任务书 §45） | 生产领料/调拨落地后闭环 |
| RD-017 | **Dashboard 不加诊断 KPI** | 加异常数卡片 | v1 无定时任务与缓存，强塞 = 为展示而加 | 定时诊断 + 缓存后上 KPI |
| RD-018 | **能力命名 = Late Entry / Backdated Business Date；禁止描述为 True Backdated Inventory Posting** | 允许统称"backdate" | business_date < posted_at 是"补录 + 业务日回填"，库存影响在 posted_at（DA-003） | True Backdate（repost 引擎）另立 Sprint |
| RD-019 | **business_date ≠ 库存生效时间；v1 生效 = posted_at；`stock_frozen_upto` 面向未来 effective_inventory_date** | 把冻结当业务日输入闸门 | Late Entry 下旧 business_date 不改变库存生效期（DA-004） | effective_inventory_date + override 门禁 |
| RD-020 | **诊断 L2 按 physical posting order（id 升序）重放，不用 business_date** | 按 occurred_at/business_date 排序 | business_date 不决定库存估值顺序（DA-005） | True Backdate 时切 effective_inventory_date + stable posting_sequence |

---

## 22. Known Limitations（四十九）

本 Sprint 不解决（也不借盘点扩张）：

- Production Issue（生产领料）、Sales Delivery（销售出库）、Warehouse Transfer（调拨）
- Batch / Serial Number（批次/序列号）
- Multi-UOM Conversion（多单位换算）
- Full Accounting / GL / FIFO / Landed Cost（总账、先进先出、到岸成本）
- **True Backdated Inventory Posting / 历史移动平均重算引擎**（effective_inventory_date +
  posting_sequence + ledger replay）——v1 仅支持 Late Entry / Backdated Business Date（DA-003）
- **As-Of Inventory Engine 与 Count Cutoff T**（Physical(T) + Movements after T）；v1 用
  Short Count Window + Snapshot Guard 保守替代（§6.4，DA-001）
- 真正的 Warehouse Count Lock / 盘点期间物理冻结（同由 §6.4 方案覆盖）
- 按物料/仓库的对象级数据权限（现状只有单据链 scope + inventory:view）
- 多仓同时盘点、盘点单跨仓

已声明为"特性而非 bug"：**Late Entry（business_date < posted_at）**——L2 按 physical posting order
重放，不产生诊断误报（DA-005，§12.4）。

---

## 23. Open Questions（待决策，Review 时讨论）

| # | 问题 | 选项 | 倾向 |
|---|---|---|---|
| OQ-1 | 未来是否拆分 APPROVED / POSTED 两步审批？ | 拆 / 不拆 | 出现"组长批、组员过账"再拆（RD-005） |
| OQ-2 | `inventory_settings` 单行 key-value vs 单列单行表？ | key-value / 单行表 | 单行 key-value（可扩展 freeze 多键） |
| OQ-3 | DATA_CORRECTION 是否需要比 COUNT_VARIANCE 更严的审批提示？ | 高亮+审计 vs 同权 | 高亮+必填 remark（RD-016） |
| OQ-4 | 盘点差异是否要限额分层（如 |diff|>N 需二次确认）？ | 要/不要 | v1 不要（Demo 数据小），未来可加 |
| OQ-5 | future：Receipt override / effective-date 字段落库位置 | 加列 / 审计 only | 加可空列（语义显式） |
| OQ-6 | "今天/业务日期"的时区定义 | 服务器本地（现状）/ 业务时区配置 | v1 沿用服务器本地并文档化，后续加 BUSINESS_TZ |
| OQ-7 | DIAGNOSTIC_RUN 审计是否过碎？ | 保持 / 仅记录非 OK 结果 | 保持（轻量） |
| OQ-8 | 诊断 KPI 何时上 Dashboard？ | 有定时任务后 / 永不 | 有定时任务后（RD-017） |
| OQ-9 | 盘点过账后是否联动 Dashboard 库存金额 KPI 变化提示？ | 不联动（现有 KPI 自动反映） | 不新增联动（余额变了 KPI 自然变） |
| OQ-10 | LATE_ENTRY 标记落库方式：Receipt/流水 remark 前缀 vs 专用列 vs 仅审计/UI 推导（business_date < posted_at 日期）？ | remark / 专用列 / 推导 | v1 倾向 remark 前缀 + 审计，避免加列（§10.2） |
| OQ-11 | Suggested Valuation Rate 预填口径：仅当 avg_cost > 0 时预填？预填值是否随余额变动实时刷新？ | 固定 / 实时 | 创建行时取快照 avg 预填一次（与三快照一致），不实时刷新 |
| OQ-12 | Staleness 守卫比较范围：仅 quantity 还是 quantity + total_amount？ | 仅 qty / qty+amount | 仅 qty（amount 由 qty 与 avg 派生，qty 相等即等价）——待确认 |

---

## 24. Recommended Implementation Order（若获批的实现顺序）

> 仅实施路线建议，本报告不实施。

```
Phase A（地基，先做不影响存量）：
  A1. AuditAction / TxnSourceType / SequenceKey 枚举扩展（仅加值，向后兼容）
  A2. 新增 inventory_settings + init_data 权限点与授权矩阵
  A3. 新增 7xxx 错误码（枚举 + 异常类，纯新增）

Phase B（盘点主链）：
  B1. stock_reconciliations / items 表 + Alembic migration（含索引/CHECK）
  B2. stock_reconciliation_service：DRAFT 建单/编辑/快照 + submit/approve(POST)/reject/cancel
  B3. POST 链路：CAS → lock_balances → staleness 守卫 → ADJUST 流水 → apply → 审计（§15）
  B4. reverse（冲销链）
  B5. API 路由 + Schema（§16 打勾项）

Phase C（冻结阈值 + Late Entry 标记）：
  C1. Receipt 创建：business_date ≤ frozen_upto → LATE_ENTRY 标记 + 审计说明（不拒绝，DA-004）
  C2. settings GET/PUT（ADMIN）+ STOCK_FREEZE_CHANGE 审计

Phase D（诊断）：
  D1. 诊断服务（L1/L2/L3 + 分级；L2 按 physical posting order 重放，DA-005）
  D2. GET /run + 审计

Phase E（前端）：
  E1. 盘点列表/创建/详情/审批 页面 + 路由/菜单
  E2. 诊断页 + 库存菜单入口红点
  E3. 权限按钮渲染 / SoD override 对话框

Phase F（测试 + 文档）：
  F1. §19 测试矩阵（按 A→D 依赖分批落地）
  F2. §20 UAT 手工脚本 + 演示数据脚本扩展
  F3. 更新 database-design.md / inventory_design.md / 本报告状态
```

每 Phase 独立可验收；A 全程向后兼容（存量 seed/测试不受影响）。

---

## 25. Files that would be changed IF approved（获批后预计改动文件）

| 层 | 文件 |
|---|---|
| 枚举/模型 | `backend/app/utils/enums.py`（AuditAction/TxnSourceType/ReconcileStatus/ReasonCode/SequenceKey）、`backend/app/models/inventory.py`（+2 表 +settings 可选）、`backend/app/models/__init__.py` |
| 错误码 | `backend/app/core/exceptions.py`（7xxx + 异常类） |
| 服务 | 新增 `backend/app/services/stock_reconciliation_service.py`；`backend/app/services/inventory_service.py`（暴露守卫/诊断辅助，lock_balances 不变）；`backend/app/services/purchase_receipt_service.py`（Late Entry / LATE_ENTRY 标记 + 冻结阈值读取）；`backend/app/services/audit_service.py` 无需改 |
| 数据 | `backend/app/db/init_data.py`（权限点 + 角色矩阵）、新 Alembic migration（+2~3 表/列/权限数据） |
| Schema/API | `backend/app/schemas/`（reconciliation/inventory_settings/diagnostic）、`backend/app/api/v1/`（reconciliations.py、inventory 扩展、router 注册） |
| 前端 | `frontend/src/views/inventory/`（ReconciliationList/Create/Detail、DiagnosticView）、`router/index.ts`、菜单/权限、API client |
| Dashboard | 无（RD-017）；仅诊断入口红点（E2） |
| 文档 | `docs/database-design.md`、`docs/inventory_design.md`、本报告状态更新、README 能力清单 |
| 测试 | `backend/tests/`（test_stock_reconciliation*.py 等，按 §19 分批） |

---

## 26. 合规声明

- 本轮（含 v2 Design Amendment DA-001~DA-007）仅修改本设计文档；
- 未修改任何 Python / Vue / 数据库结构 / Alembic 迁移 / API / 测试代码；
- 未执行 git commit；
- 唯一产出为本报告（`docs/sprint1-inventory-reality-design.md`）。

**STOP — 等待 Review。**
