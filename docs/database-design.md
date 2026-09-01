# Manufacturing ERP Lite — 数据库设计说明书

> 版本：v1.0 ｜ 日期：2026-09-01 ｜ 阶段：Phase 2
> 状态：待 Review（Review 通过前不进入 Phase 3）
> 目标数据库：MySQL 8.0 ｜ 引擎：InnoDB ｜ 字符集：`utf8mb4` / `utf8mb4_0900_ai_ci`

---

## 0. 运行环境确认（Q13 结论）

| 检查项 | 实测结果 | 结论 |
|---|---|---|
| Python 3.12 | ✅ `E:\Python312\python.exe` → Python 3.12.9，pip 24.3.1 | **采用系统 Python 3.12.9 作为目标运行时**，不使用 3.13 |
| Docker CLI | ⚠️ Docker 29.5.3 + Compose v5.1.4 已安装 | CLI 就绪 |
| Docker daemon | ❌ `npipe:////./pipe/dockerDesktopLinuxEngine` 连接失败 | **Docker Desktop 未启动**，需手动启动后验证 |
| WSL | ❌ `wsl.exe` 被安全策略列入黑名单，无法调用 | Docker Desktop 的 WSL2 后端可能受影响，需确认是否切换为 Hyper-V 后端 |
| 本地 MySQL | ❌ 无 `mysql` / `mysqld`，无 MySQL 服务 | 本机未安装 MySQL Server |

**方案 A（首选）：Docker Compose**

```bash
# 1. 手动启动 Docker Desktop（需用户操作，GUI 启动约 30-60 秒）
# 2. 验证
docker info --format '{{.ServerVersion}}'
docker compose up -d mysql
```

`docker-compose.yml` 在 Phase 3 提供，包含 `mysql:8.0`（开发库 `erp_lite` + 测试库 `erp_lite_test` 双库初始化）。

**方案 B（Docker 不可用时的本地开发方案）**

1. 下载 MySQL 8.0 Windows ZIP Archive（免安装版，无需管理员权限）
2. 初始化数据目录：
   ```bash
   mysqld --initialize-insecure --datadir=D:\dev\mysql-data
   mysqld --console --datadir=D:\dev\mysql-data --port=3306
   ```
3. 建库（开发与测试严格分离，满足 Q14）：
   ```sql
   CREATE DATABASE erp_lite      CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   CREATE DATABASE erp_lite_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   ```
4. 后端通过环境变量 `DATABASE_URL` / `TEST_DATABASE_URL` 区分，测试环境强制校验库名后缀 `_test`。

> **风险提示**：若 WSL 被禁用导致 Docker Desktop 无法启动，Phase 3 起将走方案 B。数据库设计两种方案完全一致（均为 MySQL 8），无需调整表结构。

---

## 1. 设计约定

### 1.1 通用字段

所有业务表均包含以下审计字段（`number_sequences`、`role_permissions` 等纯关联/技术表除外）：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | 代理主键 |
| `created_at` | DATETIME(3) | NOT NULL DEFAULT CURRENT_TIMESTAMP(3) | 创建时间 |
| `updated_at` | DATETIME(3) | NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) | 更新时间 |
| `created_by` | BIGINT UNSIGNED | NULL, FK → `users.id` | 创建人 |
| `updated_by` | BIGINT UNSIGNED | NULL, FK → `users.id` | 更新人 |

### 1.2 精度约定（金额与数量）

| 类别 | 类型 | 小数位 | 舍入规则 | 说明 |
|---|---|---|---|---|
| 数量 | `DECIMAL(18,4)` | 4 | ROUND_HALF_UP | 支持 kg / m / 个 等计量单位 |
| 单价 | `DECIMAL(18,4)` | 4 | ROUND_HALF_UP | 支持精密器件计价（如 0.0125 元/个） |
| 金额 | `DECIMAL(18,4)` | 4 | ROUND_HALF_UP | 元 |

- 应用层统一使用 Python `decimal.Decimal`，**禁止 float 参与金额计算**
- 全局 `getcontext().prec = 28`，`rounding = ROUND_HALF_UP`
- 明细金额一律由**服务端重算**，不接受前端传入（需求 R13）

### 1.3 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 表 | 小写复数，蛇形 | `purchase_order_items` |
| 主键索引 | `PRIMARY` | — |
| 唯一索引 | `uk_{表缩写}_{字段}` | `uk_pr_no` |
| 普通索引 | `ix_{表缩写}_{字段}` | `ix_pr_status` |
| 外键 | `fk_{表缩写}_{字段}` | `fk_pr_applicant` |
| 检查约束 | `ck_{表缩写}_{语义}` | `ck_pri_converted_not_exceed` |
| 触发器 | `trg_{表缩写}_{动作}` | `trg_invtxn_no_update` |

### 1.4 删除策略总表（架构规则 2）

| 对象 | 物理删除 | 替代动作 |
|---|---|---|
| 物料 / 供应商 / 仓库 | ❌ 禁止 | `status = DISABLED` |
| 部门 | ❌ 禁止 | `status = INACTIVE` |
| 用户 | ❌ 禁止 | `status = DISABLED` |
| PR（`DRAFT` / `REJECTED`→`DRAFT`） | ✅ 允许 | 仅创建人 |
| PR（`PENDING` 及以后） | ❌ 禁止 | `CANCEL` |
| PO（`DRAFT`，无来源引用） | ✅ 允许 | — |
| PO（`CONFIRMED` 及以后） | ❌ 禁止 | `CANCEL`（需累计收货 = 0） |
| Receipt（任意状态） | ❌ 禁止 | `REVERSE` |
| Inventory Transaction | ❌ 禁止（触发器强制） | 反向流水 |
| Approval Record | ❌ 禁止 | 追加新记录 |
| Operation Log | ❌ 禁止 | 只追加 |

---

## 2. 全局枚举定义

### 2.1 数据库层 ENUM

| 枚举名（逻辑） | 应用字段 | 取值 | 业务含义 |
|---|---|---|---|
| `StatusCommon` | 多处 `status` | `ACTIVE` / `DISABLED` / `INACTIVE` | 启用 / 停用 / 失效 |
| `UserStatus` | `users.status` | `ACTIVE` / `DISABLED` | 在职 / 禁用 |
| `PrStatus` | `purchase_requisitions.status` | `DRAFT` `PENDING` `APPROVED` `REJECTED` `CANCELLED` `CONVERTED` | 草稿 / 待审批 / 已批准 / 已驳回 / 已取消 / 已转订单 |
| `PoStatus` | `purchase_orders.status` | `DRAFT` `CONFIRMED` `PARTIALLY_RECEIVED` `RECEIVED` `CANCELLED` | 草稿 / 已确认 / 部分到货 / 已完成 / 已取消 |
| `ReceiptStatus` | `purchase_receipts.status` | `POSTED` / `REVERSED` | 已过账 / 已冲销 |
| `TxnType` | `inventory_transactions.transaction_type` | `PURCHASE_IN` `PURCHASE_IN_REVERSAL` `ADJUST_IN` `ADJUST_OUT` `PRODUCTION_OUT` `PRODUCTION_IN` | 采购入库 / 采购入库冲销 / 调整入库 / 调整出库 / 生产领料 / 生产完工 |
| `SourceType` | `inventory_transactions.source_type` | `PURCHASE_RECEIPT` `PURCHASE_RECEIPT_REVERSAL` `MANUAL_ADJUST` `PRODUCTION_ISSUE` `PRODUCTION_RECEIPT` | 流水来源单据类型 |
| `DocumentType` | `approval_records.document_type` | `PURCHASE_REQUISITION` / `PURCHASE_ORDER` | 单据类型（未来扩展） |
| `ApprovalAction` | `approval_records.action` | `SUBMIT` `APPROVE` `REJECT` `CANCEL` | 提交 / 批准 / 驳回 / 取消 |
| `AuditAction` | `operation_logs.action` | `LOGIN` `LOGIN_FAILED` `PR_SUBMIT` `PR_APPROVE` `PR_REJECT` `PR_CANCEL` `PO_CREATE` `PO_CONFIRM` `RECEIPT_POST` `RECEIPT_REVERSE` `PERMISSION_CHANGE` | 见 §12 |

### 2.2 应用层 Python Enum（Phase 3 实现于 `app/utils/enums.py`）

```python
class PrStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CONVERTED = "CONVERTED"

class PoStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

class ReceiptStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"

class TxnType(str, Enum):
    PURCHASE_IN = "PURCHASE_IN"
    PURCHASE_IN_REVERSAL = "PURCHASE_IN_REVERSAL"
    ADJUST_IN = "ADJUST_IN"
    ADJUST_OUT = "ADJUST_OUT"
    PRODUCTION_OUT = "PRODUCTION_OUT"
    PRODUCTION_IN = "PRODUCTION_IN"

class RoleCode(str, Enum):
    ADMIN = "ADMIN"
    APPLICANT = "APPLICANT"
    DEPT_MANAGER = "DEPT_MANAGER"
    BUYER = "BUYER"
    WAREHOUSE = "WAREHOUSE"
```

### 2.3 权限点清单（Phase 4 初始化脚本数据）

| 模块 | 权限点编码 | 说明 |
|---|---|---|
| 物料 | `material:view` `material:create` `material:update` `material:delete` | delete 实际为 DISABLE |
| 供应商 | `supplier:view` `supplier:create` `supplier:update` `supplier:delete` | |
| 仓库 | `warehouse:view` `warehouse:create` `warehouse:update` `warehouse:delete` | |
| 部门 | `department:view` `department:create` `department:update` `department:delete` | |
| 用户 | `user:view` `user:create` `user:update` `user:delete` | |
| 角色 | `role:view` `role:create` `role:update` `role:delete` `role:assign` | `role:assign` 触发 `PERMISSION_CHANGE` 审计 |
| 采购申请 | `pr:view` `pr:create` `pr:update` `pr:delete` `pr:submit` `pr:approve` `pr:cancel` | |
| 采购订单 | `po:view` `po:create` `po:update` `po:delete` `po:confirm` `po:cancel` | |
| 采购入库 | `receipt:view` `receipt:create` `receipt:reverse` | **无 `receipt:delete`** |
| 库存 | `inventory:view` `inventory_txn:view` | |
| 首页 | `dashboard:view` | |

---

## 3. 主数据域

### 3.1 `departments` — 部门

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `dept_code` | VARCHAR(32) | NO | — | UNIQUE `uk_dept_code` | 部门编码，如 `RD` / `PUR` |
| `dept_name` | VARCHAR(64) | NO | — | | 部门名称 |
| `parent_id` | BIGINT UNSIGNED | YES | NULL | FK → `departments.id` `fk_dept_parent` | 上级部门，自引用 |
| `sort_order` | INT | NO | 0 | | 排序 |
| `status` | ENUM('ACTIVE','INACTIVE') | NO | 'ACTIVE' | | 状态 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_dept_code(dept_code)`、`ix_dept_parent(parent_id)`、`ix_dept_status(status)`

> **设计说明（Q12）**：部门主管**不**放在 `departments.manager_user_id`。原因见 §3.6 —— 采用独立的 `department_managers` 关联表，避免 `departments ↔ users` 循环外键。

### 3.2 `roles` — 角色

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `role_code` | VARCHAR(32) | NO | — | UNIQUE `uk_role_code` | `ADMIN`/`APPLICANT`/`DEPT_MANAGER`/`BUYER`/`WAREHOUSE` |
| `role_name` | VARCHAR(64) | NO | — | | 角色名称 |
| `description` | VARCHAR(255) | YES | NULL | | |
| `is_system` | TINYINT(1) | NO | 0 | | 1 = 系统内置，不可删除 |
| `status` | ENUM('ACTIVE','INACTIVE') | NO | 'ACTIVE' | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

### 3.3 `permissions` — 权限点

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `perm_code` | VARCHAR(64) | NO | — | UNIQUE `uk_perm_code` | 如 `pr:approve` |
| `perm_name` | VARCHAR(64) | NO | — | | 权限名称 |
| `module` | VARCHAR(32) | NO | — | | 模块分组，前端菜单渲染用 |
| `created_at` | DATETIME(3) | NO | | | |

### 3.4 `role_permissions` — 角色权限关联

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `role_id` | BIGINT UNSIGNED | NO | — | FK → `roles.id` ON DELETE CASCADE | |
| `permission_id` | BIGINT UNSIGNED | NO | — | FK → `permissions.id` ON DELETE CASCADE | |

索引：`uk_role_perm(role_id, permission_id)` 唯一，防止重复授权
索引：`ix_roleperm_perm(permission_id)`

### 3.5 `users` — 用户

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `username` | VARCHAR(64) | NO | — | UNIQUE `uk_user_username` | 登录账号 |
| `password_hash` | VARCHAR(255) | NO | — | | bcrypt 哈希，明文永不落库 |
| `real_name` | VARCHAR(64) | NO | — | | 姓名 |
| `email` | VARCHAR(128) | YES | NULL | | |
| `phone` | VARCHAR(32) | YES | NULL | | |
| `department_id` | BIGINT UNSIGNED | YES | NULL | FK → `departments.id` ON DELETE RESTRICT `fk_user_dept` | 所属部门 |
| `role_id` | BIGINT UNSIGNED | NO | — | FK → `roles.id` ON DELETE RESTRICT `fk_user_role` | 角色（v1 单角色） |
| `status` | ENUM('ACTIVE','DISABLED') | NO | 'ACTIVE' | | |
| `last_login_at` | DATETIME(3) | YES | NULL | | 最后登录时间 |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_user_username(username)`、`ix_user_dept(department_id)`、`ix_user_role(role_id)`、`ix_user_status(status)`

### 3.6 `department_managers` — 部门主管关系 ★ Q12

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `dept_id` | BIGINT UNSIGNED | NO | — | FK → `departments.id` ON DELETE CASCADE `fk_deptmgr_dept` | 部门 |
| `user_id` | BIGINT UNSIGNED | NO | — | FK → `users.id` ON DELETE CASCADE `fk_deptmgr_user` | 主管用户 |
| `is_primary` | TINYINT(1) | NO | 0 | | 是否主主管 |
| `created_at` | DATETIME(3) | NO | | | |

索引：`uk_deptmgr(dept_id, user_id)` 唯一

**为什么用独立表而不是 `departments.manager_user_id`？**

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. `departments.manager_user_id` | 直观，少一张表 | ① 与 `users.department_id` 形成**循环外键**，插入需先插部门再插用户再回写，删除受双边约束；② 一个部门只能有一个主管，无法表达正副主管；③ 多级审批时无处安放层级信息 |
| **B. `department_managers` 关联表** ✅ | ① 无循环外键（`departments ← users ← department_managers` 单向）；② 支持一部门多主管；③ 未来多级审批只需在该表加 `approval_level` 字段，无需新建表 | 多一张表，多一次 JOIN |

**审批人判定逻辑（不写死 user_id）**：

```sql
SELECT 1
FROM department_managers dm
JOIN users u ON u.id = :applicant_id
WHERE dm.dept_id = u.department_id
  AND dm.user_id = :current_user_id
LIMIT 1;
```

`role.code = 'DEPT_MANAGER'` 仅用于**菜单/按钮级权限**（`pr:approve`），**具体审批资格由本表决定**。两者职责分离，符合 Q12。

### 3.7 `materials` — 物料主数据

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `material_code` | VARCHAR(32) | NO | — | UNIQUE `uk_mat_code` | `MAT-000001` |
| `material_name` | VARCHAR(128) | NO | — | | 物料名称 |
| `category` | VARCHAR(64) | YES | NULL | | 分类（电子件/结构件/紧固件） |
| `specification` | VARCHAR(128) | YES | NULL | | 规格型号 |
| `unit` | VARCHAR(16) | NO | — | | 计量单位（个/kg/m/套） |
| `status` | ENUM('ACTIVE','DISABLED') | NO | 'ACTIVE' | | |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_mat_code(material_code)`、`ix_mat_name(material_name)`、`ix_mat_status(status)`

> **⚠️ 明确不含 `safety_stock`**。原因见 §3.10 `inventory_policies`（Q10 决策）。

### 3.8 `suppliers` — 供应商

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `supplier_code` | VARCHAR(32) | NO | — | UNIQUE `uk_sup_code` | `SUP-000001` |
| `supplier_name` | VARCHAR(128) | NO | — | | |
| `contact_person` | VARCHAR(64) | YES | NULL | | 联系人 |
| `phone` | VARCHAR(32) | YES | NULL | | |
| `email` | VARCHAR(128) | YES | NULL | | |
| `address` | VARCHAR(255) | YES | NULL | | |
| `status` | ENUM('ACTIVE','DISABLED') | NO | 'ACTIVE' | | |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_sup_code(supplier_code)`、`ix_sup_name(supplier_name)`、`ix_sup_status(status)`

### 3.9 `warehouses` — 仓库

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `warehouse_code` | VARCHAR(32) | NO | — | UNIQUE `uk_wh_code` | `WH-000001` |
| `warehouse_name` | VARCHAR(64) | NO | — | | |
| `status` | ENUM('ACTIVE','DISABLED') | NO | 'ACTIVE' | | |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

初始化数据：1 条主仓库（主仓库 / `WH-000001` / ACTIVE）。

### 3.10 `inventory_policies` — 库存策略（安全库存）★ Q10

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `warehouse_id` | BIGINT UNSIGNED | NO | — | FK → `warehouses.id` ON DELETE CASCADE `fk_invpol_wh` | 仓库 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE CASCADE `fk_invpol_mat` | 物料 |
| `safety_stock` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 安全库存 |
| `min_stock` | DECIMAL(18,4) | YES | NULL | CHECK `IS NULL OR >= 0` | 最低库存 |
| `max_stock` | DECIMAL(18,4) | YES | NULL | CHECK `IS NULL OR >= 0` | 最高库存 |
| `reorder_point` | DECIMAL(18,4) | YES | NULL | CHECK `IS NULL OR >= 0` | 补货点 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

索引：**`uk_invpol(warehouse_id, material_id)` 唯一** —— 一个仓库一个物料只有一条策略
索引：`ix_invpol_mat(material_id)`

**为什么安全库存必须独立成表（Q10）？**

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. `materials.safety_stock` | 查询简单，少一次 JOIN | ① 语义错误：安全库存是**仓库+物料**维度，同一物料在 A 仓安全库存 100、B 仓 20 无法表达；② 多仓库扩展时需新增列或数据迁移；③ 违反主数据与配置数据分离 | ❌ 不采用 |
| **B. `inventory_policies` 独立表** ✅ | ① 正确的业务维度；② 多仓库开箱即用；③ 未配置策略的物料通过 `LEFT JOIN + COALESCE(safety_stock, 0)` 取默认值 0；④ 后续可扩展 min/max/补货点而无需改物料表 | 多一次 JOIN | ✅ **采用** |
| C. 放在 `inventory_balances` 表 | 少一次 JOIN | 余额是**业务结果数据**（会被库存流水驱动更新），策略是**配置数据**，混在一起导致无法区分"库存数量"与"库存策略"，且余额行可能不存在 | ❌ 不采用 |

预警查询：

```sql
SELECT m.material_code, m.material_name, w.warehouse_name,
       b.quantity, p.safety_stock
FROM inventory_balances b
JOIN materials m   ON m.id = b.material_id
JOIN warehouses w  ON w.id = b.warehouse_id
LEFT JOIN inventory_policies p
       ON p.warehouse_id = b.warehouse_id AND p.material_id = b.material_id
WHERE b.quantity < COALESCE(p.safety_stock, 0);
```

> 口径：`quantity < safety_stock` 才预警（Q10 决策，等于时仍在安全线）。

---

## 4. 采购域

### 4.1 `purchase_requisitions` — 采购申请单头

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `pr_no` | VARCHAR(32) | NO | — | UNIQUE `uk_pr_no` | `PR-20260901-0001` |
| `applicant_id` | BIGINT UNSIGNED | NO | — | FK → `users.id` ON DELETE RESTRICT `fk_pr_applicant` | 申请人 |
| `department_id` | BIGINT UNSIGNED | NO | — | FK → `departments.id` ON DELETE RESTRICT `fk_pr_dept` | 申请部门（**单据快照**） |
| `apply_date` | DATE | NO | — | | 申请日期 |
| `reason` | VARCHAR(500) | YES | NULL | | 申请事由 |
| `status` | ENUM(...) | NO | 'DRAFT' | 见 §2.1 `PrStatus` | 单据状态 |
| `total_estimated_amount` | DECIMAL(18,4) | NO | 0 | | 明细预估金额合计（服务端汇总） |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_pr_no(pr_no)`、`ix_pr_status(status)`、`ix_pr_applicant(applicant_id)`、`ix_pr_dept(department_id)`、`ix_pr_date(apply_date)`

> `department_id` 是**冗余快照**而非仅依赖 `applicant.department_id`。理由：申请人可能调岗，历史单据必须保留申请时的部门归属，否则审批记录与统计口径会漂移。

### 4.2 `purchase_requisition_items` — 采购申请明细 ★ Q3

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `pr_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_requisitions.id` ON DELETE CASCADE `fk_pri_pr` | 所属申请单 |
| `line_no` | INT | NO | — | | 行号，单内唯一 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE RESTRICT `fk_pri_mat` | 物料 |
| `requested_quantity` | DECIMAL(18,4) | NO | — | CHECK `> 0` | **申请数量** |
| `converted_quantity` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | **已转 PO 数量**（Q3 核心） |
| `estimated_unit_price` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 预估单价，**允许为 0**（Q9） |
| `estimated_amount` | DECIMAL(18,4) | — | 生成列 | `GENERATED ALWAYS AS (ROUND(requested_quantity * estimated_unit_price, 4)) STORED` | 预估金额 |
| `required_date` | DATE | YES | NULL | | 需求日期 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

索引：`uk_pri_line(pr_id, line_no)` 唯一、`ix_pri_mat(material_id)`、`ix_pri_pr(pr_id)`

**关键约束（Q3）**：

```sql
CONSTRAINT ck_pri_qty_positive CHECK (requested_quantity > 0)
CONSTRAINT ck_pri_converted_not_exceed CHECK (converted_quantity >= 0 AND converted_quantity <= requested_quantity)
```

`converted_quantity <= requested_quantity` 是**数据库层硬约束**，即使 Service 有 Bug 也无法写入超转数据。

> **为什么不用 `status` 表达"部分转换"？**
> PR 明细转出部分数量后，单据头保持 `APPROVED`（仍可继续转单）；仅当**全部明细** `converted_quantity = requested_quantity` 时，单据头才置 `CONVERTED`。这样不引入新状态，语义清晰。

### 4.3 `purchase_orders` — 采购订单单头

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `po_no` | VARCHAR(32) | NO | — | UNIQUE `uk_po_no` | `PO-20260901-0001` |
| `supplier_id` | BIGINT UNSIGNED | NO | — | FK → `suppliers.id` ON DELETE RESTRICT `fk_po_supplier` | 供应商（**必填**，需求 R5） |
| `buyer_id` | BIGINT UNSIGNED | NO | — | FK → `users.id` ON DELETE RESTRICT `fk_po_buyer` | 采购员 |
| `order_date` | DATE | NO | — | | 订单日期 |
| `expected_date` | DATE | YES | NULL | | 期望到货日期 |
| `status` | ENUM(...) | NO | 'DRAFT' | 见 §2.1 `PoStatus` | |
| `total_amount` | DECIMAL(18,4) | NO | 0 | | 明细金额合计 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |
| `created_by` / `updated_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |

索引：`uk_po_no(po_no)`、`ix_po_supplier(supplier_id)`、`ix_po_buyer(buyer_id)`、`ix_po_status(status)`、`ix_po_date(order_date)`

### 4.4 `purchase_order_items` — 采购订单明细 ★ Q5

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `po_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_orders.id` ON DELETE CASCADE `fk_poi_po` | 所属订单 |
| `line_no` | INT | NO | — | | 行号 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE RESTRICT `fk_poi_mat` | 物料 |
| `ordered_quantity` | DECIMAL(18,4) | NO | — | CHECK `> 0` | 采购数量 |
| `received_quantity` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 累计已收数量 |
| `unit_price` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 采购单价 |
| `amount` | DECIMAL(18,4) | — | 生成列 | `GENERATED ALWAYS AS (ROUND(ordered_quantity * unit_price, 4)) STORED` | 金额 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

索引：`uk_poi_line(po_id, line_no)` 唯一、`ix_poi_mat(material_id)`、`ix_poi_po(po_id)`

**关键约束（Q5 + 架构规则 5）**：

```sql
CONSTRAINT ck_poi_ordered_positive CHECK (ordered_quantity > 0)
CONSTRAINT ck_poi_received_not_exceed CHECK (received_quantity >= 0 AND received_quantity <= ordered_quantity)
CONSTRAINT ck_poi_price_nonneg CHECK (unit_price >= 0)
```

**关于 `unit_price > 0`（Q9）的取舍**：

| 做法 | 说明 |
|---|---|
| DB 层 `CHECK (unit_price > 0)` | 最严格，但 DRAFT 阶段无法暂存"价格待定"的订单 |
| **DB 层 `CHECK (unit_price >= 0)` + Service 在 `confirm` 时校验 `> 0`** ✅ | 允许草稿期暂存 0，确认下单时强制有价。符合 Q9「**正式采购** unit_price 原则上必须 > 0」 |

采用后者。Service 抛 `PO_UNIT_PRICE_REQUIRED` 业务异常。

### 4.5 `purchase_order_item_sources` — PO 明细 ↔ PR 明细来源映射 ★ Q4

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `po_item_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_order_items.id` ON DELETE CASCADE `fk_pois_poi` | PO 明细 |
| `pr_item_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_requisition_items.id` ON DELETE RESTRICT `fk_pois_pri` | PR 明细 |
| `quantity` | DECIMAL(18,4) | NO | — | CHECK `> 0` | 从该 PR 明细转出的数量 |
| `created_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) | | |

索引：**`uk_pois(po_item_id, pr_item_id)` 唯一**、`ix_pois_pri(pr_item_id)`

**为什么建映射表而不是在 `po_item` 加 `source_pr_id`？**

| 场景 | `po_item.source_pr_id`（单字段） | `purchase_order_item_sources`（映射表） |
|---|---|---|
| 一张 PO 明细合并 3 个 PR 明细（Q4） | ❌ 只能存 1 个来源 | ✅ 3 行记录 |
| 一个 PR 明细拆给 2 张 PO（Q3） | ❌ 无法表达 | ✅ 2 行指向同一 `pr_item_id` |
| 来源数量追溯 | ❌ 只能整单关联，无数量维度 | ✅ 每行带 `quantity`，明细级精确追踪 |

**约束清单**：

```sql
CONSTRAINT ck_pois_qty_positive CHECK (quantity > 0)
-- 同一 PO 明细不能重复引用同一 PR 明细（防止重复行累加绕过校验）
UNIQUE KEY uk_pois (po_item_id, pr_item_id)
```

**业务约束（数据库无法表达，由 Service 层 CAS 保证）**：

1. `SUM(sources.quantity WHERE pr_item_id = X)` 增加后，不得超过 `pr_item.requested_quantity`
   —— 通过 `pr_item.converted_quantity` 的 CAS 更新保证（见 §9.2）
2. `SUM(sources.quantity WHERE po_item_id = Y) <= po_item.ordered_quantity`
   —— 差额为"无 PR 来源采购"（如最小起订量 MOQ 导致的超采），需在 `po_item.remark` 说明，对账脚本可识别

> **设计取舍说明**：允许 `ordered_quantity > SUM(sources.quantity)`。真实采购中因最小起订量、包装倍数导致的超采极常见，强制相等会让系统无法录入真实业务。第一阶段 Service 校验 `<=` 关系，差额部分要求填写 `remark`。

---

## 5. 仓储域

### 5.1 `purchase_receipts` — 采购入库单头 ★ Q6

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `receipt_no` | VARCHAR(32) | NO | — | UNIQUE `uk_receipt_no` | `REC-20260901-0001` |
| `po_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_orders.id` ON DELETE RESTRICT `fk_receipt_po` | 来源采购订单 |
| `warehouse_id` | BIGINT UNSIGNED | NO | — | FK → `warehouses.id` ON DELETE RESTRICT `fk_receipt_wh` | 收货仓库 |
| `received_by` | BIGINT UNSIGNED | NO | — | FK → `users.id` ON DELETE RESTRICT `fk_receipt_user` | 收货人 |
| `received_at` | DATETIME(3) | NO | — | | 收货时间 |
| `status` | ENUM('POSTED','REVERSED') | NO | 'POSTED' | | 已过账 / 已冲销 |
| `reversed_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | 冲销人 |
| `reversed_at` | DATETIME(3) | YES | NULL | | 冲销时间 |
| `reverse_reason` | VARCHAR(500) | YES | NULL | | 冲销原因（**必填**，Service 校验） |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

索引：`uk_receipt_no(receipt_no)`、`ix_receipt_po(po_id)`、`ix_receipt_wh(warehouse_id)`、`ix_receipt_status(status)`

> **状态说明**：第一阶段不使用 `DRAFT`。入库单在事务内创建即 `POSTED`（实物操作不可逆，架构规则 4）。若未来需要"暂存入库单"场景，加枚举值即可，无需改结构。

### 5.2 `purchase_receipt_items` — 采购入库明细

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `receipt_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_receipts.id` ON DELETE CASCADE `fk_ri_receipt` | 所属入库单 |
| `po_item_id` | BIGINT UNSIGNED | NO | — | FK → `purchase_order_items.id` ON DELETE RESTRICT `fk_ri_poi` | 对应 PO 明细 |
| `line_no` | INT | NO | — | | 行号 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE RESTRICT `fk_ri_mat` | 物料（冗余自 PO 明细，便于库存记账） |
| `received_quantity` | DECIMAL(18,4) | NO | — | CHECK `> 0` | **本次入库数量** |
| `unit_price` | DECIMAL(18,4) | NO | — | CHECK `>= 0` | **成本单价快照**（取自 `po_item.unit_price`） |
| `amount` | DECIMAL(18,4) | — | 生成列 | `GENERATED ALWAYS AS (ROUND(received_quantity * unit_price, 4)) STORED` | 入库金额 |
| `remark` | VARCHAR(255) | YES | NULL | | |
| `created_at` | DATETIME(3) | NO | | | |

索引：**`uk_ri_line(receipt_id, line_no)` 唯一**
索引：**`uk_ri_poi(receipt_id, po_item_id)` 唯一** —— 一张入库单对同一 PO 明细只能有一行，防止同单内多行累加绕过超收校验
索引：`ix_ri_poi(po_item_id)`、`ix_ri_mat(material_id)`

> `unit_price` 必须**快照**而非实时查 PO。理由：库存成本金额应固化在入库时点，PO 单价后续被修改不应追溯篡改历史成本。

### 5.3 `inventory_balances` — 库存余额 ★ Q7 / Q8

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `warehouse_id` | BIGINT UNSIGNED | NO | — | FK → `warehouses.id` ON DELETE RESTRICT `fk_ib_wh` | 仓库 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE RESTRICT `fk_ib_mat` | 物料 |
| `quantity` | DECIMAL(18,4) | NO | 0 | **CHECK `>= 0`**（Q8 禁止负库存） | 账面数量 |
| `total_amount` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 账面总金额 |
| `average_unit_cost` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 移动加权平均单价 |
| `version` | INT UNSIGNED | NO | 0 | | 乐观锁版本号 |
| `last_transaction_at` | DATETIME(3) | YES | NULL | | 最近变动时间 |
| `created_at` / `updated_at` | DATETIME(3) | NO | | | |

索引：**`uk_ib(warehouse_id, material_id)` 唯一**、`ix_ib_mat(material_id)`

**移动加权平均成本计算（Q7）**：

入库时：
```
new_quantity     = old_quantity + receipt_quantity
new_total_amount = old_total_amount + receipt_amount          -- receipt_amount = received_quantity * unit_price(快照)
new_avg_cost     = ROUND(new_total_amount / new_quantity, 4)  -- new_quantity > 0
```

冲销时：
```
new_quantity     = old_quantity - reversal_quantity
new_total_amount = old_total_amount - original_amount
new_avg_cost     = new_quantity > 0 ? ROUND(new_total_amount / new_quantity, 4) : 0
```

**已知精度问题与处理策略**：

`average_unit_cost * quantity` 因 4 位小数舍入，可能不等于 `total_amount`。这是移动加权平均的固有特性。处理约定：

1. **`total_amount` 为权威值**，`average_unit_cost` 是派生展示值
2. 出库成本按 `average_unit_cost` 计算；当余额归零时，强制 `total_amount = 0`、`average_unit_cost = 0`，避免残留分位误差
3. 第一阶段只涉及采购入库（只增不减），该问题影响有限；生产领料（二阶段）实现时需补充"尾差处理"规则

**余额行的存在性**：首次入库时通过 `INSERT ... ON DUPLICATE KEY UPDATE` 创建，不预建空行。

### 5.4 `inventory_transactions` — 库存流水（append-only ledger）★ Q6 / 架构规则 3

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `txn_no` | VARCHAR(32) | NO | — | UNIQUE `uk_txn_no` | `TXN-20260901-000001` |
| `transaction_type` | ENUM(见 §2.1 `TxnType`) | NO | — | | 流水类型 |
| `warehouse_id` | BIGINT UNSIGNED | NO | — | FK → `warehouses.id` ON DELETE RESTRICT `fk_it_wh` | 仓库 |
| `material_id` | BIGINT UNSIGNED | NO | — | FK → `materials.id` ON DELETE RESTRICT `fk_it_mat` | 物料 |
| `quantity` | DECIMAL(18,4) | NO | — | **带符号**，见下方约束 | 入库为正，出库为负 |
| `unit_cost` | DECIMAL(18,4) | NO | 0 | CHECK `>= 0` | 计价单价 |
| `amount` | DECIMAL(18,4) | NO | 0 | | 计价金额（`quantity * unit_cost`，带符号） |
| `balance_after` | DECIMAL(18,4) | NO | — | | **流水后余额快照**，审计用 |
| `source_type` | ENUM(见 §2.1 `SourceType`) | YES | NULL | | 来源单据类型 |
| `source_id` | BIGINT UNSIGNED | YES | NULL | | 来源单据 ID（**非 FK**，见 [data-integrity-review.md §2 孤儿记录风险](./data-integrity-review.md#2-孤儿记录风险)） |
| `source_item_id` | BIGINT UNSIGNED | YES | NULL | | 来源单据明细 ID |
| `reversed_transaction_id` | BIGINT UNSIGNED | YES | NULL | FK → `inventory_transactions.id` `fk_it_reversed` | **Q6**：指向被冲销的原始流水 |
| ~~`reversal_transaction_id`~~ | — | — | — | **已从 v1 移除**，原因见本节末尾说明 | 原设计为反向指针（指向冲销自己的流水），因 append-only 无法回填而废弃 |
| `transaction_at` | DATETIME(3) | NO | — | | 业务发生时间 |
| `remark` | VARCHAR(500) | YES | NULL | | |
| `created_by` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` | |
| `created_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) | | |

索引：`uk_txn_no(txn_no)`、`ix_it_wh_mat(warehouse_id, material_id)`、`ix_it_mat(material_id)`、`ix_it_source(source_type, source_id)`、`ix_it_type(transaction_type)`、`ix_it_time(transaction_at)`、`ix_it_reversed(reversed_transaction_id)`

**约束（符号与类型一致性）**：

```sql
CONSTRAINT ck_it_sign CHECK (
    (transaction_type IN ('PURCHASE_IN', 'ADJUST_IN', 'PRODUCTION_IN')      AND quantity > 0)
 OR (transaction_type IN ('PURCHASE_IN_REVERSAL', 'ADJUST_OUT', 'PRODUCTION_OUT') AND quantity < 0)
)
```

**为什么 `quantity` 采用带符号设计？**

| | 方案 A：恒正 + 类型隐含方向 | 方案 B：带符号 ✅ |
|---|---|---|
| 余额重算校验 | 需 `SUM(CASE WHEN type IN (...) THEN qty ELSE -qty END)` | `SUM(quantity)` 直接等于余额 |
| 防错能力 | 类型写错不会报错 | CHECK 强制类型与符号一致 |
| 冲销表达 | 需 CASE 转换 | 天然为负 |

采用 **B**。最大收益：`SUM(quantity)` 可一键校验账实一致，这是最强的对账手段。

**append-only 强制（架构规则 3）**：

```sql
DELIMITER //
CREATE TRIGGER trg_it_no_update BEFORE UPDATE ON inventory_transactions
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'inventory_transactions is append-only: UPDATE forbidden, use reversal transaction';
END//
CREATE TRIGGER trg_it_no_delete BEFORE DELETE ON inventory_transactions
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'inventory_transactions is append-only: DELETE forbidden, use reversal transaction';
END//
DELIMITER ;
```

> 例外：`reversal_transaction_id` 需要回填（原始流水指向冲销流水）。这违反 append-only。
> **解决方案**：**不回填原始流水的 `reversal_transaction_id`**，仅保留 `reversed_transaction_id`（冲销流水指向原始流水，创建时即可确定）。若需反向查询，用 `WHERE reversed_transaction_id = :original_id`。
> → 因此 `reversal_transaction_id` 字段**从 v1 表结构中移除**，避免 UPDATE 需求。

**修正后**：

| 字段 | 处理 |
|---|---|
| `reversed_transaction_id` | ✅ 保留（冲销流水创建时写入，指向原始） |
| `reversal_transaction_id` | ❌ **移除**（回填需要 UPDATE，破坏 append-only） |

---

## 6. 支撑域

### 6.1 `approval_records` — 审批记录 ★ Q11

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `document_type` | ENUM('PURCHASE_REQUISITION','PURCHASE_ORDER') | NO | — | | 单据类型 |
| `document_id` | BIGINT UNSIGNED | NO | — | | 单据 ID（**非 FK**，见 [data-integrity-review.md §2 孤儿记录风险](./data-integrity-review.md#2-孤儿记录风险)） |
| `step_no` | SMALLINT UNSIGNED | NO | 1 | | **审批级别**，第一阶段恒为 1（Q11） |
| `step_name` | VARCHAR(64) | YES | NULL | | 步骤名，如 `部门主管审批` |
| `approver_id` | BIGINT UNSIGNED | NO | — | FK → `users.id` ON DELETE RESTRICT `fk_ar_approver` | 审批人 |
| `action` | ENUM('SUBMIT','APPROVE','REJECT','CANCEL') | NO | — | | 动作 |
| `result_status` | VARCHAR(32) | NO | — | | 动作执行后单据状态快照 |
| `comment` | VARCHAR(1000) | YES | NULL | | 审批意见，**驳回时必填**（Service 校验） |
| `created_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) | | |

索引：`ix_ar_doc(document_type, document_id)`、`ix_ar_approver(approver_id)`、`ix_ar_time(created_at)`

**不加唯一约束的原因**：`REJECTED → DRAFT → 重新提交 → 再次审批`（Q1）会产生同一 `step_no` 同一 `action` 的多条记录，这是**正确的历史轨迹**，不应被唯一约束阻断。

**Q11 多级审批扩展路径**（不过度设计，不建 BPM 引擎）：

1. 新增配置表 `approval_flows(document_type, is_active)` + `approval_flow_steps(flow_id, step_no, step_name, approver_type)`
2. `approval_records.step_no` 已存在，直接承载多级序号，**无需改表**
3. Service 从"固定 1 步"改为"按 flow 配置循环"

第一阶段只有 1 步，不建立上述配置表。

### 6.2 `number_sequences` — 单据编号序列 ★ 架构规则 1

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `sequence_key` | VARCHAR(32) | NO | — | | `PR` / `PO` / `REC` / `TXN` / `MAT` / `SUP` / `WH` |
| `sequence_date` | DATE | NO | — | | 按日重置的用业务日期；全局递增的固定 `'1970-01-01'` |
| `current_value` | BIGINT UNSIGNED | NO | 0 | | 当前值 |
| `updated_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) | | |

索引：**`uk_seq(sequence_key, sequence_date)` 唯一**

**取号方案（推荐：`ON DUPLICATE KEY UPDATE` + `LAST_INSERT_ID()`）**

```sql
-- 单语句原子取号，独立事务
INSERT INTO number_sequences (sequence_key, sequence_date, current_value, updated_at)
VALUES (?, ?, 1, NOW(3))
ON DUPLICATE KEY UPDATE
    current_value = LAST_INSERT_ID(current_value + 1),
    updated_at = NOW(3);
SELECT LAST_INSERT_ID() AS new_value;
```

**并发行为与事务边界说明**：

| 维度 | 说明 |
|---|---|
| **原子性** | `ON DUPLICATE KEY UPDATE` 在唯一索引 `uk_seq` 上加行锁，单语句完成「读 + 增 + 写」，不存在读后写竞态。并发请求被 InnoDB 串行化，但锁持有时间仅为**单语句执行时长**（微秒级） |
| **事务边界** | 取号在**独立短事务**中执行并立即提交，**不嵌套在业务事务内**。这是避免长事务持锁的关键设计 |
| **跳号行为** | 取号已提交，若后续业务事务失败回滚，该编号被废弃 → **产生跳号**。这符合「不要求绝对连续、不允许跳号（重复）」的要求 |
| **唯一性兜底** | 所有编号列（`pr_no` / `po_no` / `receipt_no` / `txn_no` / `material_code`）均有 UNIQUE 索引。极端情况下（如手工导入数据导致序列被重置）发生冲突时，Service 捕获 `IntegrityError` 重试最多 3 次 |
| **为什么不用 `SELECT ... FOR UPDATE`** | 需要 2 次交互（SELECT 加锁 → UPDATE），且若嵌在业务事务中，锁会持有到业务事务结束（可能数百毫秒），造成串行瓶颈 |

| 方案 | 交互次数 | 锁持有 | 结论 |
|---|---|---|---|
| **ON DUPLICATE KEY + LAST_INSERT_ID** ✅ | 1 | 单语句 | **采用** |
| SELECT FOR UPDATE + UPDATE（独立事务） | 2 | 短事务 | 可用，但多一次往返 |
| SELECT FOR UPDATE + UPDATE（嵌套业务事务） | 2 | 整个业务事务 ❌ | **禁止**，会造成严重锁竞争 |
| 号段预分配（hi/lo） | 极少 | 极短 | 性能最优，但应用重启丢号段、实现复杂，本项目量级无需 |

**编号格式**：

| 单据 | `sequence_key` | `sequence_date` | 格式 |
|---|---|---|---|
| 物料 | `MAT` | `'1970-01-01'` | `MAT-{value:06d}` → `MAT-000001` |
| 供应商 | `SUP` | `'1970-01-01'` | `SUP-000001` |
| 仓库 | `WH` | `'1970-01-01'` | `WH-000001` |
| 采购申请 | `PR` | 申请日期 | `PR-{yyyymmdd}-{value:04d}` → `PR-20260901-0001` |
| 采购订单 | `PO` | 订单日期 | `PO-20260901-0001` |
| 入库单 | `REC` | 收货日期 | `REC-20260901-0001` |
| 库存流水 | `TXN` | 业务日期 | `TXN-20260901-000001` |

### 6.3 `operation_logs` — 操作审计日志 ★ Q15

| 字段 | 类型 | NULL | 默认值 | 约束 | 业务含义 |
|---|---|---|---|---|---|
| `id` | BIGINT UNSIGNED | NO | AUTO | PK | |
| `operator_id` | BIGINT UNSIGNED | YES | NULL | FK → `users.id` ON DELETE SET NULL `fk_ol_operator` | 操作人（登录失败时可能为 NULL） |
| `username_snapshot` | VARCHAR(64) | YES | NULL | | 账号快照（用户被删后仍可追溯） |
| `action` | ENUM(见 §2.1 `AuditAction`) | NO | — | | 操作类型 |
| `module` | VARCHAR(32) | NO | — | | 所属模块 |
| `document_type` | VARCHAR(32) | YES | NULL | | 关联单据类型 |
| `document_id` | BIGINT UNSIGNED | YES | NULL | | 关联单据 ID |
| `description` | VARCHAR(500) | YES | NULL | | 操作描述 |
| `ip_address` | VARCHAR(45) | YES | NULL | | 支持 IPv6 |
| `user_agent` | VARCHAR(255) | YES | NULL | | |
| `request_id` | VARCHAR(64) | YES | NULL | | 链路追踪 ID |
| `created_at` | DATETIME(3) | NO | CURRENT_TIMESTAMP(3) | | |

索引：`ix_ol_operator(operator_id)`、`ix_ol_action(action)`、`ix_ol_doc(document_type, document_id)`、`ix_ol_time(created_at)`

**Q15 审计范围**：

| 审计动作 | 说明 |
|---|---|
| `LOGIN` / `LOGIN_FAILED` | 登录成功与失败 |
| `PR_SUBMIT` / `PR_APPROVE` / `PR_REJECT` / `PR_CANCEL` | PR 关键状态变更 |
| `PO_CREATE` / `PO_CONFIRM` | PO 创建与确认 |
| `RECEIPT_POST` / `RECEIPT_REVERSE` | 入库过账与冲销 |
| `PERMISSION_CHANGE` | 角色权限分配变更 |

**不审计**：普通 CRUD 字段级 diff（Q15 明确暂不要求）。

**写入时机**：
- 业务操作类日志（`PR_*` / `PO_*` / `RECEIPT_*`）：**与业务操作同一事务**，业务回滚则日志一并回滚（操作未真实发生）
- 登录类日志（`LOGIN` / `LOGIN_FAILED`）：独立事务
- 权限变更（`PERMISSION_CHANGE`）：与授权操作同一事务

---

## 7. 表清单汇总

| # | 表名 | 中文名 | 域 | 预估数据量 |
|---|---|---|---|---|
| 1 | `departments` | 部门 | 主数据 | 10 |
| 2 | `roles` | 角色 | 主数据 | 5 |
| 3 | `permissions` | 权限点 | 主数据 | 40 |
| 4 | `role_permissions` | 角色权限关联 | 主数据 | 100 |
| 5 | `users` | 用户 | 主数据 | 100 |
| 6 | `department_managers` | 部门主管关系 | 主数据 | 20 |
| 7 | `materials` | 物料 | 主数据 | 10k |
| 8 | `suppliers` | 供应商 | 主数据 | 500 |
| 9 | `warehouses` | 仓库 | 主数据 | 10 |
| 10 | `inventory_policies` | 库存策略 | 主数据 | 50k |
| 11 | `purchase_requisitions` | 采购申请头 | 采购 | 100k |
| 12 | `purchase_requisition_items` | 采购申请明细 | 采购 | 300k |
| 13 | `purchase_orders` | 采购订单头 | 采购 | 100k |
| 14 | `purchase_order_items` | 采购订单明细 | 采购 | 300k |
| 15 | `purchase_order_item_sources` | PO-PR 来源映射 | 采购 | 400k |
| 16 | `purchase_receipts` | 采购入库头 | 仓储 | 150k |
| 17 | `purchase_receipt_items` | 采购入库明细 | 仓储 | 400k |
| 18 | `inventory_balances` | 库存余额 | 仓储 | 50k |
| 19 | `inventory_transactions` | 库存流水 | 仓储 | 1M+ |
| 20 | `approval_records` | 审批记录 | 支撑 | 200k |
| 21 | `number_sequences` | 编号序列 | 支撑 | 1k |
| 22 | `operation_logs` | 操作审计日志 | 支撑 | 1M+ |

> 注：原计划 18 张，因 Q10（库存策略独立）、Q12（部门主管独立）增加 3 张，共 **22 张**。Q16 附件表**不创建**。

---

## 8. Q1–Q16 决策落地对照表

| 决策 | 落地位置 |
|---|---|
| **Q1** REJECTED → DRAFT → PENDING，必须重新提交 | `PrStatus` 枚举含 `REJECTED`；Service 状态机加边 `REJECTED → DRAFT`；`approval_records` 累积历史 |
| **Q2** APPROVED PR 无有效 PO 时可 CANCEL | Service 校验：不存在 `status != 'CANCELLED'` 的 PO 通过 `purchase_order_item_sources` 关联到本 PR 才允许取消 |
| **Q3** 一 PR 拆多 PO | `purchase_requisition_items.requested_quantity` + `converted_quantity`；CHECK `converted_quantity <= requested_quantity` |
| **Q4** 一 PO 合并多 PR，映射表 | `purchase_order_item_sources(po_item_id, pr_item_id, quantity)`；UNIQUE(po_item_id, pr_item_id) |
| **Q5** 禁止超收 + CAS | CHECK `received_quantity <= ordered_quantity`；Service 用条件更新 `WHERE received_quantity + :qty <= ordered_quantity` + rowcount 校验 |
| **Q6** 冲销，禁改禁删 | `TxnType` 增加 `PURCHASE_IN_REVERSAL`（**不用 ADJUST_OUT 代替**）；`reversed_transaction_id`；`ReceiptStatus.REVERSED`；append-only 触发器 |
| **Q7** 移动加权平均 | `inventory_balances(quantity, total_amount, average_unit_cost)`；不实现 FIFO / 总账 / 应付 / 成本核算 |
| **Q8** 禁止负库存 | `inventory_balances` CHECK `quantity >= 0`；扣减用条件更新 `WHERE quantity >= :qty` |
| **Q9** PR 价可 0，PO 价 > 0 | `pr_items` CHECK `estimated_unit_price >= 0`；`po_items` CHECK `unit_price >= 0` + Service 在 `confirm` 时校验 `> 0` |
| **Q10** 安全库存按 warehouse+material | `inventory_policies` 独立表，UNIQUE(warehouse_id, material_id)；`materials` **不含** safety_stock |
| **Q11** 单级审批，结构支持多级 | `approval_records.step_no` 预留；不建 BPM 引擎 |
| **Q12** 审批人由部门+主管关系决定 | `department_managers` 表；查询见 §3.6；不写死 user_id |
| **Q13** Python 3.12 + MySQL 8，优先 Docker | 见 §0；环境已确认 Python 3.12.9 可用，Docker daemon 待启动 |
| **Q14** 独立测试数据库 | `erp_lite` / `erp_lite_test` 双库；测试环境强制校验库名后缀 |
| **Q15** 9 类关键业务审计 | `operation_logs` + `AuditAction` 枚举；不做字段 diff |
| **Q16** 不实现附件 | 不建表；扩展方式见 §11 |

---

## 9. 核心业务一致性保证

### 9.1 采购入库事务（架构规则 4）

单数据库事务内的完整步骤序列：

```
BEGIN
 1. 校验 PO 状态 ∈ {CONFIRMED, PARTIALLY_RECEIVED}
 2. 校验 PO Item 存在且属于该 PO
 3. 逐行校验 received_quantity + 本次数量 <= ordered_quantity
 4. INSERT purchase_receipts (status=POSTED)
 5. INSERT purchase_receipt_items (逐行，含 unit_price 快照)
 6. UPDATE purchase_order_items SET received_quantity = received_quantity + :qty
    WHERE id = :id AND received_quantity + :qty <= ordered_quantity     ← CAS
    检查 rowcount == 1，否则 ROLLBACK + 抛 RECEIPT_EXCEEDS_REMAINING
 7. INSERT inventory_transactions (type=PURCHASE_IN, quantity=+qty,
    source_type=PURCHASE_RECEIPT, source_id=receipt.id, balance_after=...)
 8. UPSERT inventory_balances (quantity += qty, total_amount += amount,
    重算 average_unit_cost)  WHERE 满足 quantity + :qty >= :qty           ← 防负数
 9. 重算 PO 状态（见 §9.3）
10. INSERT operation_logs (action=RECEIPT_POST)
COMMIT   ← 任一失败 ROLLBACK
```

### 9.2 PR → PO 转换的数量一致性（架构规则 6）

```
BEGIN
 1. 校验 PR 状态 = APPROVED
 2. 逐条 source：
    a. 校验 pr_item 存在且所属 PR = APPROVED
    b. CAS 更新：UPDATE purchase_requisition_items
         SET converted_quantity = converted_quantity + :qty
       WHERE id = :pr_item_id
         AND converted_quantity + :qty <= requested_quantity
       检查 rowcount == 1，否则 ROLLBACK + 抛 PR_ITEM_CONVERT_EXCEEDED
    c. INSERT purchase_order_item_sources
 3. INSERT purchase_order_items
 4. 校验 SUM(sources.quantity) <= ordered_quantity
 5. INSERT purchase_orders
 6. 若 PR 所有明细 converted_quantity = requested_quantity → PR 状态 = CONVERTED
 7. INSERT approval_records / operation_logs
COMMIT
```

**PO 取消时的回退**：

```
仅当 SUM(po_item.received_quantity) = 0 时允许取消
逐条 source：UPDATE purchase_requisition_items
   SET converted_quantity = converted_quantity - :qty
 WHERE id = :pr_item_id AND converted_quantity >= :qty
若 PR 因此不再全部转完 → PR 状态回退为 APPROVED
```

### 9.3 PO 状态重算规则（架构规则 5）

```python
def recompute_po_status(items: list[PoItem]) -> PoStatus:
    total_ordered = sum(i.ordered_quantity for i in items)
    total_received = sum(i.received_quantity for i in items)
    if total_received == 0:
        return PoStatus.CONFIRMED          # 已确认，未到货
    if total_received >= total_ordered:    # 全部收齐
        return PoStatus.RECEIVED
    return PoStatus.PARTIALLY_RECEIVED    # 部分到货
```

| 条件 | 状态 |
|---|---|
| 所有 Item `received_quantity = 0` 且已确认 | `CONFIRMED` |
| 至少一行 `received_quantity > 0` 且存在未完全到货 | `PARTIALLY_RECEIVED` |
| 所有 Item 全部收齐 | `RECEIVED` |

### 9.4 冲销逻辑（Q6）

```
BEGIN
 1. 校验 Receipt 状态 = POSTED
 2. 校验该 Receipt 未被冲销过（查询是否存在 source_id = receipt.id 且 type = PURCHASE_IN_REVERSAL 的流水）
 3. 逐行：
    a. 校验 po_item.received_quantity >= 本次冲销数量
    b. UPDATE purchase_order_items
         SET received_quantity = received_quantity - :qty
       WHERE id = :id AND received_quantity >= :qty                      ← CAS
    c. INSERT inventory_transactions(
         type = PURCHASE_IN_REVERSAL,                    ← 不使用 ADJUST_OUT
         quantity = -qty,
         reversed_transaction_id = 原 PURCHASE_IN 流水.id,
         source_type = PURCHASE_RECEIPT_REVERSAL,
         source_id = receipt.id)
    d. UPDATE inventory_balances
         SET quantity = quantity - :qty, total_amount = total_amount - :amount
       WHERE warehouse_id = :wh AND material_id = :mat AND quantity >= :qty   ← 防负数
 4. UPDATE purchase_receipts SET status='REVERSED', reversed_by=..., reversed_at=..., reverse_reason=...
 5. 重算 PO 状态（§9.3）
 6. INSERT operation_logs (action=RECEIPT_REVERSE)
COMMIT
```

**冲销的边界规则**：

| 规则 | 说明 |
|---|---|
| 原始记录保留 | `purchase_receipts` 只改状态为 `REVERSED`，**不删除**；原始 `PURCHASE_IN` 流水**不被修改或删除** |
| 禁用 ADJUST_OUT 代替 | `PURCHASE_IN_REVERSAL` 是独立枚举值，语义上明确"这是对采购入库的冲销"，可追溯、可统计。用 `ADJUST_OUT` 会丢失业务语义 |
| 一次冲销完整性 | 冲销针对整张入库单，不做部分冲销（第一阶段）。部分冲销需拆单处理，留待需求明确后实现 |
| 重复冲销防护 | 步骤 2 先查是否已存在冲销流水，防止重复冲销导致库存变负 |

---

## 10. Data Integrity Review

完整的数据一致性审查独立输出至 **[`docs/data-integrity-review.md`](./data-integrity-review.md)**，覆盖 11 个维度、75 项检查点。

核心结论摘要：

| 维度 | 主要风险 | 缓解手段 |
|---|---|---|
| 重复数据 | 同一 PO 明细重复引用同一 PR 明细 | `uk_pois(po_item_id, pr_item_id)` 唯一约束 |
| 孤儿记录 | 流水 `source_id` 指向的入库单被删 | 入库单禁止物理删除；主数据 FK 均 `RESTRICT` |
| 并发 | 并发入库超收 / 余额重复增加 | 条件更新 + `rowcount` 校验 + DB CHECK 兜底 |
| 金额精度 | float 参与金额计算 | 全链路 `DECIMAL(18,4)` + STORED 生成列 |
| 状态一致性 | 前端直接改 `status` | Pydantic Schema 不含 `status`；Service 状态机白名单 |
| 库存账实 | 余额与流水不符 | `SUM(inventory_transactions.quantity)` 一键对账 |
| 冲销 | 重复冲销导致负库存 | 冲销前置校验 + `quantity >= 0` CHECK |

Phase 3 / Phase 9 实现时必须落实的 3 项高危控制：

1. **C-01/C-02**：入库必须用条件更新 + `rowcount == 1` 校验，禁止「先 SELECT 判断再 UPDATE」
2. **R-01**：冲销前先查是否已存在 `PURCHASE_IN_REVERSAL` 流水
3. **S-01**：Create / Update Schema 中严禁出现 `status` 字段

---

## 11. 未来扩展说明（不在 Phase 1 实现）

### 11.1 附件（Q16 —— 本阶段不建表）

未来扩展方式：

```
设计：独立的 polymorphic attachment 表，避免污染业务表

attachments
  id
  biz_type        VARCHAR(32)   -- 'SUPPLIER_QUALIFICATION' / 'PURCHASE_CONTRACT' / 'RECEIPT_VOUCHER'
  biz_id          BIGINT UNSIGNED
  file_name       VARCHAR(255)
  storage_path    VARCHAR(500)  -- 本地路径或对象存储 key
  file_size       BIGINT
  content_type    VARCHAR(64)
  uploaded_by     BIGINT UNSIGNED FK users
  created_at

索引：ix_att_biz(biz_type, biz_id)
```

- 采用 `biz_type + biz_id` 多态关联，新增业务类型的附件无需改表
- 存储层抽象为 `StorageProvider` 接口（本地磁盘 / S3 / MinIO / 腾讯云 COS），Phase 1 只定义接口
- 安全：上传时校验扩展名白名单 + 重命名存储（防路径穿越），下载走后端鉴权代理，**不直接暴露静态目录**

### 11.2 生产模块（第二阶段）

`TxnType` 已预留 `PRODUCTION_OUT` / `PRODUCTION_IN`，届时需新增：

```
boms / bom_items             物料清单
production_orders            生产任务
production_issues            生产领料单
production_receipts          生产完工单
```

`inventory_transactions.source_type` 已预留 `PRODUCTION_ISSUE` / `PRODUCTION_RECEIPT`。

### 11.3 多级审批（Q11 扩展）

见 §6.1 扩展路径，只需新增 `approval_flows` + `approval_flow_steps` 两张配置表，`approval_records.step_no` 已就位。

### 11.4 多仓库调拨

`inventory_transactions` 需新增 `TRANSFER_OUT` / `TRANSFER_IN` 类型，新增 `stock_transfers` 表。`inventory_balances` 按 (warehouse, material) 设计已天然支持多仓。

---

## 12. 审计动作与触发点对照

| `AuditAction` | 触发接口 | 记录内容 |
|---|---|---|
| `LOGIN` | `POST /api/v1/auth/login` 成功 | 用户、IP、UA |
| `LOGIN_FAILED` | 登录失败（密码错误 / 用户禁用） | 账号快照、IP、UA |
| `PR_SUBMIT` | `POST /api/v1/purchase-requisitions/{id}/submit` | PR 编号、金额 |
| `PR_APPROVE` | `.../approve` | PR 编号、审批意见 |
| `PR_REJECT` | `.../reject` | PR 编号、驳回原因（必填） |
| `PR_CANCEL` | `.../cancel` | PR 编号、取消原因 |
| `PO_CREATE` | `POST /api/v1/purchase-orders` | PO 编号、供应商、金额 |
| `PO_CONFIRM` | `POST /api/v1/purchase-orders/{id}/confirm` | PO 编号 |
| `RECEIPT_POST` | `POST /api/v1/purchase-receipts` | 入库单号、PO 编号、物料与数量摘要 |
| `RECEIPT_REVERSE` | `POST /api/v1/purchase-receipts/{id}/reverse` | 入库单号、冲销原因 |
| `PERMISSION_CHANGE` | 角色权限分配变更 | 角色、变更的权限项 |

---

## 13. Review 结论（已确认，2026-09-01）

Phase 2 Review 通过，6 个开放点**全部采纳推荐方案**，据此进入 Phase 3。

| # | 关注点 | 最终决策 | 影响 |
|---|---|---|---|
| A-1 | 冲销指针方向 | ✅ **采纳单向指针**。仅保留 `reversed_transaction_id`，反向查询用 `WHERE reversed_transaction_id = :id` | 保持 append-only 纯粹性，反向查询多一次索引扫描，可接受 |
| A-2 | PO 超采差额 | ✅ **采纳允许差额**。`ordered_quantity >= SUM(sources.quantity)`，差额需在 `po_item.remark` 说明 | 支持 MOQ / 包装倍数场景；对账脚本需能识别差额 |
| A-3 | 冲销是否回退 PR | ✅ **采纳不回退**。冲销是仓库端纠错，PR→PO 的采购关系依然成立 | 需重新采购时新建 PO，而非回退 PR。UI 需明确提示 |
| A-4 | `unit_price` 严格度 | ✅ **采纳 DB `>= 0` + confirm 时校验 `> 0`** | 允许草稿暂存 0，确认下单强制有价 |
| A-5 | 运行环境 | ✅ **采纳本地 MySQL 方案**（Docker daemon 不可用）。Python 3.12.9 + MySQL 8 ZIP 免安装版 | `docker-compose.yml` 仍按方案 A 交付，Docker 恢复后可直接切换 |
| A-6 | 部分冲销 | ✅ **采纳整单冲销**。第一阶段不支持部分冲销 | 部分冲销需拆单处理，留待需求明确 |

**同时确认的实现约束**（来自 Data Integrity Review，Phase 3/9 强制落实）：

| 编号 | 约束 |
|---|---|
| C-01/C-02 | 入库必须用条件更新 + `rowcount == 1` 校验，禁止「先 SELECT 判断再 UPDATE」 |
| R-01 | 冲销前先查是否已存在 `PURCHASE_IN_REVERSAL` 流水 |
| S-01 | Pydantic Create / Update Schema 中严禁出现 `status` 字段 |
| O-01 | 入库单、已提交 PR、库存流水禁止物理删除 |
| M-01 | 全链路 `DECIMAL(18,4)`，Python 侧 `Decimal`，禁止 float |

---

*Phase 2 结束。Phase 3：后端基础架构（FastAPI 分层 + Alembic + 首个迁移 + pytest 骨架）。*
