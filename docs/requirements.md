# Manufacturing ERP Lite — 需求规格说明书

> 中文名：制造企业采购库存协同系统
> 文档版本：v1.0（Phase 1）
> 编写日期：2026-09-01
> 状态：待评审（数据库设计方向未确认，暂不进入 Phase 2 实现）

---

## 1. 项目定位与目标

### 1.1 项目性质

本项目是一个**面向小型研发制造企业的轻量级 ERP 系统**，同时承担两个用途：

| 用途 | 要求 | 权重 |
|---|---|---|
| 求职作品集 | 展示工程化能力：分层架构、领域建模、事务一致性、测试覆盖、文档完整度 | 高 |
| 真实业务演示 | 业务流程可走通、状态可追溯、数据可自洽、界面像真实管理后台 | 高 |

**明确不属于本项目的范畴：**

- 不是后台管理脚手架（CRUD generator）
- 不是静态页面 Demo（无真实状态机、无库存流水、无事务）
- 不是财务系统（不做总账、应收应付、成本核算）

### 1.2 业务边界

**第一阶段（Phase 1–13）纳入范围：**

```
主数据（物料 / 供应商 / 部门 / 仓库 / 用户 / 角色）
   ↓
采购申请 PR → 审批 → 采购订单 PO → 采购入库 → 库存余额 + 库存流水
   ↓
Dashboard 统计
```

**明确推迟到第二阶段（数据库预留扩展位，代码不实现）：**

- BOM（物料清单）
- 生产任务 / 生产领料 / 生产完工（`PRODUCTION_OUT` / `PRODUCTION_IN` 流水类型已在枚举中预留）
- 质量检验（IQC）
- 销售出库
- 多仓库调拨

### 1.3 ERP 核心思想的落地体现

本项目必须在代码中可验证地体现以下 10 条 ERP 设计原则，评审时可逐条对应到代码位置：

| # | ERP 思想 | 本项目的落地方式 |
|---|---|---|
| 1 | 主数据管理 | 物料 / 供应商 / 部门 / 仓库独立维护，业务单据只引用 `id`，不冗余名称快照（冗余字段仅保留编码便于列表展示） |
| 2 | 单据管理 | PR / PO / Receipt 均为「单头 + 明细」结构，明细不允为空，金额由明细汇总 |
| 3 | 单据状态流转 | 状态机集中在 Service 层，API 层禁止直接写 `status` |
| 4 | 审批流程 | 通用审批记录表 `approval_record`，按 `document_type + document_id` 关联，可追溯审批人与意见 |
| 5 | 数据一致性 | 入库 = 写流水 + 更余额 + 更 PO 累计收货量，单数据库事务；条件更新（CAS）防并发超收 |
| 6 | 权限控制 | RBAC：`user → role → permission`，接口级权限校验 + 业务级校验（如同部门主管才能审批） |
| 7 | 库存流水 | `inventory_transaction` 只追加不修改；余额表 `inventory_balance` 为流水汇总结果，可重算校验 |
| 8 | 操作审计 | 写操作记录操作人、时间；关键状态变更写入审批/操作日志 |
| 9 | 业务数据关联 | PR → PO → Receipt → Transaction 全链路可通过 `source_type / source_id` 双向追溯 |
| 10 | 报表统计 | Dashboard 聚合查询：待办数量、金额趋势、库存排行、安全库存预警 |

---

## 2. 用户与角色

### 2.1 角色定义

| 角色代码 | 角色名称 | 业务定位 |
|---|---|---|
| `ADMIN` | 系统管理员 | 全权限，负责主数据、用户、角色维护 |
| `APPLICANT` | 普通申请人 | 提出采购需求（研发/生产人员） |
| `DEPT_MANAGER` | 部门主管 | 审批本部门采购申请 |
| `BUYER` | 采购员 | 将已审批 PR 转为 PO，选择供应商与采购价 |
| `WAREHOUSE` | 仓库管理员 | 执行采购入库、查看库存与流水 |

> 说明：一个用户一个角色（v1 简化）。数据模型允许后续扩展为用户-角色多对多。

### 2.2 权限点定义

权限采用 `资源:操作` 编码，例如 `material:create`。

| 资源 | 权限点 | 说明 |
|---|---|---|
| `material` | `view` `create` `update` `delete` | 物料主数据 |
| `supplier` | `view` `create` `update` `delete` | 供应商主数据 |
| `department` | `view` `create` `update` `delete` | 部门 |
| `user` | `view` `create` `update` `delete` | 用户 |
| `role` | `view` `create` `update` `delete` | 角色权限 |
| `pr` | `view` `create` `update` `delete` `submit` `approve` `cancel` | 采购申请 |
| `po` | `view` `create` `update` `delete` `confirm` `cancel` | 采购订单 |
| `receipt` | `view` `create` | 采购入库（**不可删除**，只能冲销） |
| `inventory` | `view` | 库存余额 |
| `inventory_txn` | `view` | 库存流水 |
| `dashboard` | `view` | 首页统计 |

> **设计取舍**：权限校验分两层——
> 1. **接口层**（`Depends(require_perm("pr:approve"))`）拦截无权限访问；
> 2. **业务层**（Service 内）校验数据级规则，例如「只能审批本部门的申请」「只能修改自己创建的 DRAFT 单据」。
> 接口层权限不足不能替代业务层校验，两者都必须存在。

### 2.3 Demo 账号

| 账号 | 密码 | 角色 | 部门 |
|---|---|---|---|
| `admin` | `admin123` | 系统管理员 | 行政部 |
| `rd001` | `123456` | 普通申请人 | 研发部 |
| `rd_manager` | `123456` | 部门主管 | 研发部 |
| `buyer001` | `123456` | 采购员 | 采购部 |
| `wh001` | `123456` | 仓库管理员 | 仓库 |

> 密码使用 bcrypt 哈希存储，Demo 数据脚本中明文仅用于初始化。

---

## 3. 功能模块划分

```
Manufacturing ERP Lite
├── 001 系统管理
│   ├── 用户管理
│   ├── 角色权限管理（角色 - 权限分配）
│   └── 部门管理
├── 002 基础资料（主数据）
│   ├── 物料管理
│   ├── 供应商管理
│   └── 仓库管理
├── 003 采购管理
│   ├── 采购申请（PR）
│   ├── 审批中心
│   └── 采购订单（PO）
├── 004 仓库管理
│   ├── 采购入库
│   ├── 当前库存
│   └── 库存流水
└── 005 Dashboard
    ├── 业务概览卡片
    ├── 采购金额趋势（ECharts 折线）
    └── 库存数量排行（ECharts 柱状）
```

### 3.1 模块与后端分层映射

| 前端模块 | API 前缀 | Service 类 | 核心模型 |
|---|---|---|---|
| 认证 | `/api/v1/auth` | `AuthService` | `User` |
| 系统管理 | `/api/v1/users` `/api/v1/roles` `/api/v1/departments` | `UserService` `RoleService` `DepartmentService` | `User` `Role` `Permission` `Department` |
| 基础资料 | `/api/v1/materials` `/api/v1/suppliers` `/api/v1/warehouses` | `MaterialService` `SupplierService` | `Material` `Supplier` `Warehouse` |
| 采购管理 | `/api/v1/purchase-requisitions` `/api/v1/purchase-orders` | `PurchaseRequisitionService` `PurchaseOrderService` | `PurchaseRequisition` `PurchaseRequisitionItem` `PurchaseOrder` `PurchaseOrderItem` |
| 审批 | `/api/v1/approvals` | `ApprovalService` | `ApprovalRecord` |
| 仓库管理 | `/api/v1/purchase-receipts` `/api/v1/inventory` | `ReceiptService` `InventoryService` | `PurchaseReceipt` `PurchaseReceiptItem` `InventoryBalance` `InventoryTransaction` |
| Dashboard | `/api/v1/dashboard` | `DashboardService` | 聚合查询 |

---

## 4. 第一版采购业务流程

### 4.1 主流程（Happy Path）

```
① 需求提出      申请人（研发）在系统中新建采购申请 PR，状态 = DRAFT
      ↓
② 提交申请      确认明细后提交，状态 DRAFT → PENDING
      ↓
③ 主管审批      部门主管审批
                  通过：PENDING → APPROVED   （写审批记录 action=APPROVE）
                  驳回：PENDING → REJECTED   （写审批记录 action=REJECT，必填意见）
      ↓
④ 转采购订单    采购员基于 APPROVED 的 PR 创建 PO，指定供应商、单价、交期
                PO 状态 = DRAFT，PR 状态 → CONVERTED
      ↓
⑤ 订单确认      采购员确认订单（模拟已下单给供应商）
                PO 状态 DRAFT → CONFIRMED
      ↓
⑥ 供应商到货    实物到货，仓库收货
      ↓
⑦ 采购入库      仓库管理员选择 PO，填写本次到货数量，生成入库单 Receipt
                ├─ 校验：本次数量 ≤ 该明细剩余未到货数量
                ├─ 写 purchase_receipt + purchase_receipt_item
                ├─ 更新 po_item.received_quantity
                ├─ 写 inventory_transaction（type=PURCHASE_IN）
                └─ 更新 inventory_balance.quantity
                （以上 5 步在同一个数据库事务内）
      ↓
⑧ 订单状态更新  全部明细收齐 → PO = RECEIVED
                部分收货     → PO = PARTIALLY_RECEIVED
      ↓
⑨ 库存形成      库存余额可查，库存流水可追溯至入库单 → 采购订单 → 采购申请
```

### 4.2 部分到货示例

采购 100 个：

| 次数 | 本次入库 | 累计收货 | PO 状态 | 库存变化 |
|---|---|---|---|---|
| 第 1 次 | 40 | 40 | `PARTIALLY_RECEIVED` | +40 |
| 第 2 次 | 60 | 100 | `RECEIVED` | +60 |

第 3 次再尝试入库 → 拒绝，抛出 `RECEIPT_EXCEEDS_REMAINING` 业务异常。

### 4.3 状态机

**采购申请 PR**

| 当前状态 | 动作 | 目标状态 | 前置条件 | 执行角色 |
|---|---|---|---|---|
| — | 创建 | `DRAFT` | 明细 ≥ 1 条 | 申请人 |
| `DRAFT` | 修改 | `DRAFT` | 仅创建人本人 | 申请人 |
| `DRAFT` | 删除 | — | 仅创建人本人 | 申请人 |
| `DRAFT` | 提交 `submit` | `PENDING` | 明细 ≥ 1、必填字段完整 | 申请人 |
| `PENDING` | 批准 `approve` | `APPROVED` | 审批人为本部门主管 | 部门主管 |
| `PENDING` | 驳回 `reject` | `REJECTED` | 必须填写驳回意见 | 部门主管 |
| `PENDING` | 撤回 `cancel` | `CANCELLED` | 仅创建人本人 | 申请人 |
| `APPROVED` | 转订单 `convert` | `CONVERTED` | 生成 PO 成功 | 采购员 |
| `REJECTED` | 重新编辑 | `DRAFT` | 仅创建人本人（**待确认**，见 §7-Q1） | 申请人 |

> `CONVERTED`、`CANCELLED`、`REJECTED`（若不重新编辑）为终态。

**采购订单 PO**

| 当前状态 | 动作 | 目标状态 | 前置条件 |
|---|---|---|---|
| — | 创建 | `DRAFT` | 必须指定供应商；明细来源为已 `APPROVED` 的 PR |
| `DRAFT` | 修改 | `DRAFT` | 无 |
| `DRAFT` | 确认 `confirm` | `CONFIRMED` | 供应商有效、明细完整 |
| `DRAFT` / `CONFIRMED` | 取消 `cancel` | `CANCELLED` | 累计收货量 = 0 |
| `CONFIRMED` | 入库 | `PARTIALLY_RECEIVED` | 部分收货 |
| `CONFIRMED` / `PARTIALLY_RECEIVED` | 入库 | `RECEIVED` | 全部明细收齐 |

**采购入库单 Receipt**

| 当前状态 | 动作 | 目标状态 | 前置条件 |
|---|---|---|---|
| — | 创建 | `CONFIRMED` | 入库单创建即生效（实物操作不可逆），明细数量 > 0 |
| `CONFIRMED` | 冲销 `reverse` | `CANCELLED` | 生成反向流水 `ADJUST_OUT`（**待确认**，见 §7-Q6） |

### 4.4 全链路数据追溯

```
PurchaseRequisition (PR-20260901-0001)
   │  convert
   ▼
PurchaseOrder (PO-20260901-0001)  ← source_pr_id
   │  receive
   ▼
PurchaseReceipt (REC-20260901-0001)  ← po_id
   │  post
   ▼
InventoryTransaction (TXN-20260901-000001)  ← source_type='PURCHASE_RECEIPT', source_id
   │  aggregate
   ▼
InventoryBalance (warehouse_id + material_id, quantity)
```

追溯方向：
- **正向**：从 PR 查到最终形成了多少库存
- **反向**：从一条库存流水反查入库单 → 订单 → 申请 → 申请人

---

## 5. 业务规则清单（强制约束）

以下规则必须在 **Service 层**以代码断言形式实现，并全部有对应测试用例。

| # | 规则 | 违反时的行为 |
|---|---|---|
| R1 | 只有 `DRAFT` 状态的 PR 可修改内容 | 抛 `INVALID_STATUS_TRANSITION` |
| R2 | `PENDING` 状态禁止修改申请内容 | 抛 `INVALID_STATUS_TRANSITION` |
| R3 | 只有部门主管可审批，且只能审批**本部门**的申请 | 抛 `FORBIDDEN` / `PERMISSION_DENIED` |
| R4 | 只有 `APPROVED` 的 PR 才能生成 PO | 抛 `INVALID_STATUS_TRANSITION` |
| R5 | PO 必须指定供应商，且供应商状态为启用 | 抛 `VALIDATION_ERROR` |
| R6 | 只有 `CONFIRMED` / `PARTIALLY_RECEIVED` 的 PO 可入库 | 抛 `INVALID_STATUS_TRANSITION` |
| R7 | 入库数量 ≤ 该 PO 明细剩余未到货数量 | 抛 `RECEIPT_EXCEEDS_REMAINING` |
| R8 | 库存不得因重复请求重复增加 | 入库单号唯一索引 + 事务内条件更新（CAS）双保险 |
| R9 | 关键业务操作必须在数据库事务内完成 | 入库、转单、审批均为单事务 |
| R10 | 所有状态变更只能经由 Service 方法 | API 层不含 `status` 写入逻辑 |
| R11 | `material_code` 全局唯一 | 数据库唯一索引 + Service 预检 |
| R12 | PR / PO 明细不允许为空 | 抛 `VALIDATION_ERROR` |
| R13 | 金额由明细汇总，不接受前端传入的 `total_amount` | 服务端重算覆盖 |
| R14 | 已产生收货的 PO 不允许取消 | 抛 `INVALID_STATUS_TRANSITION` |
| R15 | 已被引用的主数据（物料/供应商）不允许物理删除 | 软删除（`status = DISABLED`） |

---

## 6. 技术需求

### 6.1 技术栈

| 层 | 选型 | 版本 | 说明 |
|---|---|---|---|
| 后端语言 | Python | 3.12 | 需确认本机运行时（见 §7-Q13） |
| Web 框架 | FastAPI | 0.11x | 自动生成 OpenAPI/Swagger |
| ORM | SQLAlchemy | 2.x | 使用 2.0 风格 `Mapped[]` / `select()` |
| 数据校验 | Pydantic | v2 | Schema 分层：Create / Update / Response |
| 数据库 | MySQL | 8.0 | Docker Compose 编排 |
| 迁移 | Alembic | 1.x | 禁止 `create_all()` 生产路径 |
| 认证 | JWT + Passlib(bcrypt) | — | Access Token，HS256 |
| 测试 | Pytest + HTTPX TestClient | — | 覆盖 13 类场景 |
| 前端 | Vue 3 + TypeScript + Vite | — | `<script setup lang="ts">` |
| UI | Element Plus | — | 企业管理后台风格 |
| 状态管理 | Pinia | — | |
| 路由 | Vue Router 4 | — | 动态路由按权限过滤 |
| HTTP | Axios | — | 统一拦截器 |
| 图表 | ECharts 5 | — | |
| 编排 | Docker / Docker Compose | — | |

### 6.2 架构分层（强制）

```
backend/
└── app/
    ├── api/           # 控制器层：路由、参数校验、权限注解、统一响应
    │   └── v1/
    ├── core/          # 配置、安全(JWT/bcrypt)、异常、依赖注入、权限守卫
    ├── models/        # SQLAlchemy ORM 模型（仅结构与关系，无业务）
    ├── schemas/       # Pydantic DTO（Create / Update / Out / Query）
    ├── repositories/  # 数据访问层：复杂查询、分页、可复用查询片段
    ├── services/      # 业务逻辑层：状态机、事务、规则校验（核心）
    ├── db/            # Session 工厂、Base、事务装饰器、初始化
    └── utils/         # 编号生成、枚举、时间、响应封装
```

**分层依赖规则（单向，不得反向调用）：**

```
api  →  services  →  repositories  →  models
                 ↘  db
```

- `api` 层不得直接 import `models` 做查询（可以 import 枚举）
- `services` 层不得感知 HTTP（不出现 `Request` / `Response`）
- 事务边界由 `services` 层控制

### 6.3 编码规范

- API 统一前缀 `/api/v1/`
- 统一响应结构 `{ code, message, data, trace_id }`，HTTP 200 承载业务错误码
- 全局异常处理器：区分 `BusinessException`（已知业务错误）/ `ValidationException` / `AuthException` / 未捕获异常
- 金额统一使用 `DECIMAL(18, 4)`，Python 侧 `Decimal`，**禁止 float 计算金额**
- 数量统一使用 `DECIMAL(18, 4)`（制造场景存在小数计量，如 kg/m）
- 时间统一 UTC 存储，展示层转换

### 6.4 编号生成规则

| 单据 | 格式 | 示例 |
|---|---|---|
| 物料 | `MAT-` + 6 位序号 | `MAT-000001` |
| 供应商 | `SUP-` + 6 位序号 | `SUP-000003` |
| 采购申请 | `PR-` + yyyyMMdd + `-` + 4 位当日流水 | `PR-20260901-0001` |
| 采购订单 | `PO-` + yyyyMMdd + `-` + 4 位当日流水 | `PO-20260901-0001` |
| 入库单 | `REC-` + yyyyMMdd + `-` + 4 位当日流水 | `REC-20260901-0001` |
| 库存流水 | `TXN-` + yyyyMMdd + `-` + 6 位当日流水 | `TXN-20260901-000001` |

**并发安全方案（推荐 A）：**

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 序列表 + 行锁 | `doc_sequence(key, date, current_value)`，`SELECT ... FOR UPDATE` 后 +1 | 无外部依赖、严格递增、事务内一致、可测试 | 高并发下有行锁竞争（本项目量级无影响） |
| B. 唯一索引 + 重试 | 先查 max+1，插入失败重试 | 实现简单 | 冲突频繁时性能差，可能不连续 |
| C. Redis INCR | Redis 原子自增 | 性能最好 | 引入额外组件，与 DB 事务不一致 |
| D. AUTO_INCREMENT | 用自增主键格式化 | 最简单 | 无法按日期重置流水，跨单据类型不统一 |

**推荐方案 A**。理由：本项目为单体内网/小型部署，不引入 Redis；序列表与业务表在同一事务内，回滚时编号一并回滚，保证严格连续无空洞，符合 ERP 单据编号「可审计、不跳号」的实务要求。

---

## 7. 待确认业务问题（阻塞 Phase 2）

以下问题会影响数据库表结构，**需确认后再进入 Phase 2**。每项已给出我的推荐方案与理由，如无异议可直接回复「按推荐」。

| # | 问题 | 选项 | 我的推荐 | 理由 |
|---|---|---|---|---|
| **Q1** | `REJECTED` 的 PR 是否允许修改后重新提交？ | A. 允许：驳回后回到 `DRAFT`，修改再提交，原审批记录保留<br>B. 不允许：驳回即终态，需重新建单 | **A** | 符合实际业务（驳回通常要求修改后重报）；保留审批记录可完整追溯；实现成本低（状态机加一条边） |
| **Q2** | `APPROVED` 的 PR 是否允许取消（作废）？ | A. 允许，状态 → `CANCELLED`<br>B. 不允许，只能转 PO 或自然过期 | **A，但限制在尚未转 PO 时** | 业务需求变化（项目取消、预算削减）时必须有出口；已转 PO 的 PR 禁止取消，避免数据不一致 |
| **Q3** | 一个 PR 能否拆给多个供应商 / 转多个 PO？ | A. 一 PR 一 PO（简单）<br>B. 一 PR 多 PO，明细级记录已转数量（复杂但真实） | **B** | 真实采购中拆单极为常见（不同物料找不同供应商）；数据模型上只需在 PR 明细加 `converted_quantity`，成本可控，但能显著提升作品集含金量。**若追求 Phase 1 交付速度可选 A** |
| **Q4** | 一个 PO 能否合并多个 PR 的明细？ | A. 可以，PO 明细记录 `source_pr_id` + `source_pr_item_id`<br>B. 不可以，一 PR 一 PO | **A** | 采购员合并同类需求下单是标准做法；`source_pr_id` 在明细行即可支持，几乎零额外成本 |
| **Q5** | 入库是否允许超收容差（如 +5%）？ | A. 严格禁止超收（`received + qty <= ordered`）<br>B. 允许百分比容差，可在系统参数配置 | **A** | 你的原始需求明确写「入库数量不能超过剩余未到货数量」，先严格实现；容差可作为配置项在 PO 明细预留 `over_receipt_rate` 字段（默认 0），后续开放 |
| **Q6** | 入库错误如何纠正？ | A. 不提供冲销（第一阶段）<br>B. 提供入库单冲销：生成反向流水 `ADJUST_OUT`，扣减余额与 PO 累计收货量 | **B** | 「库存不得因重复请求重复增加」只防并发，防不住人为录错；无冲销手段的真实 ERP 不可用。实现成本约 1 个 Service 方法 |
| **Q7** | 库存计价方式？ | A. 仅管数量，不管金额<br>B. 移动加权平均单价<br>C. 先进先出（FIFO 批次） | **B** | 制造企业需要看到库存金额；移动加权平均实现只需在余额表存 `total_amount` 与 `quantity`，入库时重算单价，是性价比最高的选择。FIFO 需要批次表，建议二阶段 |
| **Q8** | 库存余额是否允许为负？ | A. 不允许（扣减时校验 `quantity >= qty`）<br>B. 允许（先领料后补单） | **A** | 第一阶段只有采购入库（只增不减），规则 A 不影响现有流程，但为后续生产领料提前设防；条件更新 `WHERE quantity >= :qty` + `rowcount` 校验即可 |
| **Q9** | `unit_price` 是否允许为 0 或空？ | A. 必须 > 0<br>B. 允许 0（赠品/样品/待定价） | **B，但 PO 确认时校验 > 0** | 建单时价格未谈妥很常见；但订单确认（已向供应商下单）时必须有价，这是合理的卡点 |
| **Q10** | 安全库存预警口径？ | A. `quantity < safety_stock`<br>B. `quantity <= safety_stock` | **A** | 常规 ERP 惯例：低于安全库存才预警，等于时仍在安全线 |
| **Q11** | 审批是否需要金额分级（如 >5万 需总经理审批）？ | A. 单级审批（部门主管）<br>B. 多级/按金额分级 | **A 实现，表结构支持 B** | 你的需求明确「只有部门主管可以审批」；`approval_record` 表设计为多行记录，未来加多级只需增加审批流配置表，无需改现有结构 |
| **Q12** | 审批人认定规则？ | A. `role=DEPT_MANAGER` 且 `department_id` 与申请人一致<br>B. 仅校验角色，不限部门<br>C. 支持指定审批人字段 | **A** | 最贴近真实组织；管理员（`ADMIN`）作为兜底拥有全部审批权限 |
| **Q13** | 运行时环境确认 | Python 3.12 | 需确认 | 本机 managed Python 为 3.13.12，系统 Python 为 3.12.9。若严格按 3.12，需安装 managed 3.12 或使用系统解释器。**另需确认本机是否有可用 Docker**（MySQL 8 + 后端容器的编排方式） |
| **Q14** | 测试数据库策略 | A. 测试用独立 MySQL（Docker 起 `erp_test` 库）<br>B. 测试用 SQLite 内存库 | **A** | SQLite 与 MySQL 在 `DECIMAL`、行锁、`ON DUPLICATE KEY UPDATE` 上行为不同，会导致「测试通过但生产失败」。用同名 MySQL 测试库可真实验证事务与并发逻辑 |
| **Q15** | 审计日志粒度 | A. 仅记录关键单据状态变更（提交/审批/确认/入库）<br>B. 记录所有写操作（含主数据增删改）<br>C. B + 登录日志 | **C** | 审计是 ERP 的合规底线；统一在中间件/Service 基类实现成本可控，作品集展示效果好 |
| **Q16** | 是否需要附件（如供应商资质、采购合同扫描件）？ | A. 不需要<br>B. 需要，存本地 + 数据库记录路径 | **A** | 第一阶段聚焦业务闭环；预留 `attachment` 表结构不影响 Phase 1 交付 |

---

## 8. 非功能需求

| 类别 | 要求 |
|---|---|
| 接口响应 | 列表查询 P95 < 500ms（Demo 数据量 < 1 万行） |
| 并发安全 | 入库接口并发调用不产生重复库存（有测试用例验证） |
| 可维护性 | Service 方法单一职责，单个方法 < 80 行 |
| 可测试性 | 核心 Service 不依赖 FastAPI，可独立单测 |
| 文档 | Swagger 自动生成 + `docs/` 六份文档 |
| 部署 | `docker compose up -d` 一条命令启动完整环境 |
| 浏览器 | 支持 Chrome / Edge 最新两个大版本 |

---

## 9. 验收标准（Phase 13 完成时应可演示的完整剧本）

1. 用 `rd001` 登录 → 新建采购申请（明细：ESP32-WROOM × 100，STM32F407 × 50）→ 提交
2. 用 `rd_manager` 登录 → 审批中心看到待办 → 批准
3. 用 `buyer001` 登录 → 将 PR 转为 PO，选择供应商、填写单价 → 确认订单
4. 用 `wh001` 登录 → 采购入库，本次到货 40 → PO 状态变为「部分到货」，库存 +40
5. 再次入库 60 → PO 状态变为「已完成」，库存 +60
6. 第 4 次尝试入库 → 系统拒绝，提示超出剩余数量
7. 查看库存流水 → 2 条 `PURCHASE_IN`，可反查到入库单、订单、申请
8. 查看 Dashboard → 各统计数字与图表正确
9. 用 `rd001` 尝试审批自己的申请 → 403 权限拒绝
10. 用 `buyer001` 尝试对 `DRAFT` 状态的 PR 转 PO → 业务异常拒绝

---

## 10. 风险与权衡

| 风险 | 影响 | 应对 |
|---|---|---|
| Q3 拆单（一 PR 多 PO）显著增加复杂度 | Phase 8 工期拉长 | 若时间紧张，降级为「一 PR 一 PO」，但 PR 明细仍保留 `converted_quantity` 字段，日后启用无需改表 |
| 移动加权平均（Q7）与多仓库叠加 | 余额表设计变复杂 | 余额唯一键 `warehouse_id + material_id`，单价按每个仓库独立计算 |
| Docker 环境不可用 | 无法启动 MySQL | 备选：本机 MySQL 8 / 仅在 Docker 不可用时降级为 SQLite 开发库（生产仍为 MySQL） |
| 前端工作量集中在 Phase 10 | 后端完成后空窗 | 后端 Phase 9 完成后即启动前端，与 Phase 11/12 并行 |

---

*文档结束。下一阶段：确认 §7 待确认问题 → Phase 2 数据库设计（`docs/database-design.md` + `docs/ERD.md`）*
