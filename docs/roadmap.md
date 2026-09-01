# Manufacturing ERP Lite — 项目路线图

> 版本：v1.0 ｜ 日期：2026-09-01
> 推进原则：**一个 Phase 不通过测试，不进入下一 Phase**

---

## 一、Phase 全景

| Phase | 名称 | 核心交付物 | 依赖 | 预估工作量 | 状态 |
|---|---|---|---|---|---|
| 0 | 项目规划 | 仓库初始化、目录骨架、技术选型确认 | — | — | ✅ 完成 |
| 1 | 需求文档 | `docs/requirements.md`、roadmap、模块划分、业务流程、待确认清单 | 0 | — | ✅ 完成 |
| 2 | 数据库设计 | `docs/database-design.md`、`docs/ERD.md`、`docs/data-integrity-review.md` | 1 | 中 | ✅ 完成（待 Review） |
| 3 | 后端基础架构 | FastAPI 分层骨架、配置、统一响应、异常处理、Alembic、22 表迁移 | 2 | 中 | ✅ 完成 |
| 4 | 登录与 RBAC | JWT 认证、权限守卫、用户/角色/部门 CRUD | 3 | 中 | ✅ 完成 |
| 5 | 主数据 | 物料、供应商、仓库 CRUD + 编码生成 | 4 | 小 | ⬜ |
| 6 | 采购申请 | PR 单头明细 CRUD、状态机、编号生成 | 5 | 中 | ⬜ |
| 7 | 审批流程 | 提交/批准/驳回、审批中心、审批记录 | 6 | 中 | ⬜ |
| 8 | 采购订单 | PR→PO 转换、确认、取消 | 7 | 中 | ⬜ |
| 9 | 采购入库与库存 | 入库单、库存流水、余额更新、部分到货、冲销 | 8 | 大 | ⬜ |
| 10 | 前端 | Vue3 骨架、登录、主数据、采购、仓库、系统管理页面 | 3–9 | 大 | ⬜ |
| 11 | Dashboard | 统计卡片、采购金额趋势、库存排行 | 10 | 小 | ⬜ |
| 12 | 自动测试 | 13 类测试场景，覆盖率 > 70% | 9 | 中 | ⬜ |
| 13 | Docker 部署 | 多阶段构建、`docker compose up` 一键启动、部署文档 | 12 | 中 | ⬜ |
| 14 | 文档与作品集 | README、架构/API/业务流文档、演示脚本、简历描述 | 13 | 小 | ⬜ |

---

## 二、Phase 详细拆解

### Phase 0 — 项目规划 ✅

- [x] 检查仓库状态（空目录，无既有代码冲突）
- [x] `git init`，建立 `backend/ frontend/ docs/` 骨架
- [x] 确认技术栈与分层规范
- [x] 确认业务边界（采购 + 仓储闭环，BOM/生产推迟）

### Phase 1 — 需求文档 ✅

- [x] `docs/requirements.md`
- [x] `docs/roadmap.md`
- [x] 系统模块划分（5 大模块 → 后端分层映射）
- [x] 第一版采购业务流程（主流程 / 部分到货 / 状态机 / 数据追溯）
- [x] 15 条强制业务规则（R1–R15）
- [x] 16 项待确认业务问题（Q1–Q16）

### Phase 2 — 数据库设计 ✅

**输入**：Q1–Q16 最终决策
**产出**：
- `docs/database-design.md` — 22 张表的完整字段定义、MySQL 类型、PK/FK/UNIQUE/INDEX/CHECK、枚举、Q1–Q16 决策落地对照
- `docs/ERD.md` — Mermaid 图：全局 ERD / PR→PO→Receipt→Inventory 局部 ERD / 用户部门 RBAC ERD / 附录状态机
- `docs/data-integrity-review.md` — 11 个维度 75 项检查点的数据一致性评审

**最终表清单（22 张，较计划增加 3 张）**：

```
主数据域（10）
  departments              部门
  department_managers      部门主管关系   ★ 新增（Q12，避免循环外键）
  roles / permissions / role_permissions  RBAC
  users                    用户
  materials                物料（不含 safety_stock）
  suppliers                供应商
  warehouses               仓库
  inventory_policies       库存策略       ★ 新增（Q10，安全库存按 warehouse+material）

采购域（5）
  purchase_requisitions / purchase_requisition_items
  purchase_orders / purchase_order_items
  purchase_order_item_sources            ★ 新增（Q4，PO-PR 明细映射）

仓储域（4）
  purchase_receipts / purchase_receipt_items
  inventory_balances / inventory_transactions

支撑域（3）
  approval_records / number_sequences / operation_logs
```

**关键设计决策**：
- 安全库存独立成 `inventory_policies`，不放 `materials`（Q10）
- 部门主管独立成 `department_managers`，不放 `departments.manager_user_id`（Q12）
- PO-PR 用映射表 `purchase_order_item_sources` 而非 `po_item.source_pr_id`（Q4）
- 库存流水 `quantity` 带符号，`SUM(quantity)` 可一键对账
- 流水 append-only 用数据库触发器强制；`reversal_transaction_id` 因无法回填而移除
- 编号用 `ON DUPLICATE KEY UPDATE + LAST_INSERT_ID()`，取号独立短事务，允许跳号

**验收**：Data Integrity Review 通过 → 提交 `docs: add database design, ERD and integrity review`

### Phase 3 — 后端基础架构 ✅ 已完成（2026-09-01）

- FastAPI 应用工厂、`/api/v1/` 路由聚合（health check）
- `core/config.py`（Pydantic Settings，环境变量驱动，Q14 防误连测试库）
- 统一响应封装 `ApiResponse[T]` / `PageResult[T]`
- 全局异常处理器（业务异常 / 校验异常 / 认证异常 / IntegrityError / 未捕获）
- SQLAlchemy 2.0 Session 工厂、`Base`（命名约定）、事务上下文管理器
- 22 张表 ORM 模型 + Alembic 初始迁移（含 append-only 触发器）
- `pytest` 骨架 + conftest（独立测试库 `erp_lite_test`，fixture 隔离）

**验收记录**：
- ✅ `pytest` 3/3 通过（health / 统一 404 / OpenAPI schema）
- ✅ `/api/v1/health` 返回统一信封，数据库连通
- ✅ 开发库与测试库迁移均为 23 表（22 业务表 + alembic_version）
- ✅ 触发器 `trg_it_no_update` / `trg_it_no_delete` 生效
- ⏳ `docker-compose.yml` 延后至 Phase 13（Docker daemon 不可用，开发用本机 MySQL）

### Phase 4 — 登录与 RBAC ✅ 已完成（2026-09-01）

- `POST /api/v1/auth/login` → JWT（HS256，`sub`=username，`uid`/`role` 入 payload）
- `get_current_user` 依赖、`require_perm("po:confirm")` 权限守卫（401 / 403 统一信封）
- 用户 CRUD（密码 bcrypt 哈希、用户名唯一、软删除停用）
- 角色 CRUD（替换式权限分配 `POST /roles/{id}/permissions` → `PERMISSION_CHANGE` 审计）
- 部门 CRUD（软删除停用，有用户引用时拒绝）
- 审计日志：登录成功 `LOGIN`、失败 `LOGIN_FAILED`（独立事务，无会话也能落库）
- 初始化脚本 `python -m app.db.init_data`：6 部门 / 5 角色 / 44 权限点 / 角色-权限矩阵 / 5 个演示账号 / 部门主管关系（幂等，dev + test 双库可跑）

**验收**：登录、无 token 401、无权限 403、密码哈希不可逆、停用账号 403 → `pytest` 23/23 通过 → `feat: implement auth and RBAC`

### Phase 5 — 主数据 ✅ 已完成（2026-09-01）

- 物料：`MAT-000001` 自动编码（numbering_service 单语句 upsert + `LAST_INSERT_ID`，并发安全/不连续/不回收）；name 不要求全局唯一；被 PR/PO/库存引用禁删（停用优先）；停用后禁止新建 PR 明细/PO 明细/库存策略；列表分页 + code 精确 + name 模糊 + category/status 筛选
- 供应商：`SUP-000001` 自动编码；name 不强制唯一（历史变更/分公司）；停用后禁止新建 PO；被 PO 引用禁删
- 仓库：`WH-000001` 自动编码；被 balance/transaction/receipt 引用禁删；**停用时若非零库存 → `WAREHOUSE_HAS_STOCK(3010)` 拒绝**；停用后禁止新入库/新策略
- 库存策略：`UNIQUE(warehouse_id, material_id)`（安全库存不绑定 material 表）；`safety_stock>=0`、`reorder_point>=0`、`max_stock>0`；同时配置强制 `safety<=reorder<=max`；material/warehouse 停用后禁止新建/修改；`safety_stock` 不复制到 inventory_balance（Dashboard 低安全库存后续 policy+balance 联查）
- 编号服务 `numbering_service.py`：MAT/SUP/WH 共用 `number_sequences`，全局键 1970-01-01；INSERT 分支显式 `LAST_INSERT_ID(1)`（否则返回表自增主键导致首次取号错误大号）
- 删除策略：**统一不开放 DELETE API**，只提供 disable/enable（引用关系复杂，物理删除风险高）；从未被引用数据也不提供物理删除入口
- 权限：复用 `material:*` / `supplier:*` / `warehouse:*`（view/create/update/delete→disable 语义），新增 `inventory_policy:view/create/update`（44→47 权限点）
- 审计：MATERIAL/SUPPLIER/WAREHOUSE 的 CREATE/UPDATE/DISABLE/ENABLE + `INVENTORY_POLICY_CHANGE`（AuditAction 11→24）
- 迁移：`2026_09_01_1345-9f2e7c1a4b8d`（operation_logs.action ENUM 扩展至 26 值 + `max_stock` CHECK 改 `> 0`），模型同步

**验收**：编码唯一且并发无重复（8 线程×5=40 全唯一）、被引用不可物理删除（停用制）、非零库存仓库禁停、策略唯一对/数值/范围校验、403 权限拦截、审计落库 → `pytest` 40/40 + 冒烟 18/18 → `feat: implement master data (materials/suppliers/warehouses/inventory policies)`

### Phase 6 — 采购申请 ✅ 已完成（2026-09-01）

- 数据模型：PR 单头（新增 `version` 乐观锁 + `submitted_at`；`total_estimated_amount` 收窄为 DECIMAL(18,2)）+ 明细（`estimated_amount` 由生成列改为服务端计算列 DECIMAL(18,2)；新增 `estimated_unit_price >= 0` CHECK）；`UNIQUE(pr_no)` / `UNIQUE(pr_id, line_no)`，允许同物料多行（不同需求日期/用途）
- 编号：`PR-YYYYMMDD-0001` 按申请日分组取号（numbering_service `next_daily_code`），唯一/可读/并发安全/允许跳号/不回收，DB UNIQUE 兜底
- 状态机集中定义：Phase 6 仅 `DRAFT→PENDING`（submit）、`DRAFT→CANCELLED`（cancel），其余转换一律 409；API 层禁止直接写 status
- 创建：至少 1 条明细；`applicant_id`/`department_id` 为创建时快照（调岗不改历史单据）；客户端不可伪造 pr_no/状态/金额；Header+Items+审计同事务
- 金额：`money.py` 统一 ROUND_HALF_UP（2 位）；`estimated_amount = ROUND_HALF_UP(qty×price,2)`，`total = Σ行金额`；提交时重算，杜绝 float
- 编辑：仅 DRAFT 且本人（ADMIN 有管理能力）；Header+Items 单事务（任一明细非法整体回滚）；乐观锁 `WHERE version=?` 条件更新，冲突 409「单据已被其他操作修改，请刷新后重试」
- submit/cancel：原子状态条件更新（`WHERE status=DRAFT`），并发提交恰好 1 个成功；submit 后业务内容冻结
- 对象级权限：RBAC 权限点（复用 pr:view/create/update/submit/cancel）是第一层；第二层——APPLICANT 只能查看/操作自己的 PR，ADMIN 可管理全部，部门主管范围规则留给 Phase 7
- 审计：`PR_CREATE/PR_UPDATE/PR_SUBMIT/PR_CANCEL`（AuditAction 24→26）；`operation_logs` 新增 `document_no` 列记录单据编号；GET 不审计
- 迁移：`2026_09_01_1410-f2a7d3b5c9e1`（version/submitted_at/精度/CHECK/ENUM/document_no），模型与 schema 一致（`alembic check` 无 drift）
- 期间修复：ORM-enabled UPDATE 默认 `synchronize_session='auto'`（MySQL 8.0.19+ RETURNING）导致 version 双加 → 显式 `synchronize_session=False`；新增明细必须 `pr.items.append()` 而非 `db.add()`（否则金额汇总漏行）；删除明细用 `pr.items.remove()` 同步集合

**验收**：编号格式与并发唯一（8 线程×5=40 无重复）、停用物料拦截、金额 HALF_UP 精度、乐观锁 409、并发 submit 单成功、对象级 403、审计四类落库 → `pytest` 67/67 + 冒烟 21/21 → `feat: implement purchase requisition (PR business document)`

### Phase 7 — 审批流程 ✅ 已完成（2026-09-01）

- 状态机扩展（集中映射 `_TRANSITIONS`，API 层不直接写 status）：Phase 6 已有 `DRAFT→PENDING` / `DRAFT→CANCELLED`；Phase 7 新增 `PENDING→APPROVED`（approve）、`PENDING→REJECTED`（reject）、`REJECTED→DRAFT`（revise）。禁止 `DRAFT→APPROVED/REJECTED`、`PENDING→DRAFT`、`APPROVED→*`、`CANCELLED→*`、`REJECTED→PENDING`（必须经 revise 回 DRAFT 再 submit）
- 审批记录 `approval_records`（Phase 2 已建表，Phase 7 补列）：新增 `document_no`（单据编号冗余）、`from_status` / `to_status`（动作前后状态），`result_status` 保留并同步 `to_status`；`action=APPROVE/REJECT`；`comment` 通过时可选、驳回时必填（trim 非空，≤1000）；append-only，无 update/delete API
- 审批权限两层：第一层 RBAC（复用 `pr:approve`，新增 `pr:reject` 权限点，DEPT_MANAGER/ADMIN 持有）；第二层对象级——仅 `department_managers` 当前有效关系中该部门主管可审批（用户 ACTIVE、部门 ACTIVE 复查），跨部门主管 403 `PR_NOT_APPROVER`；ADMIN 允许越权兜底，但 `approval_record.step_name="管理员越权审批"` + 审计 description 显式记录（is_admin_override）
- approve 校验链（13 项）：PR 存在 → status=PENDING → 用户 ACTIVE → 有 pr:approve → 是申请部门主管（或 ADMIN override）→ version 匹配 → 至少 1 条明细 → 物料存在且 ACTIVE（提交与审批间可能被停用，必须重校验）→ 数量>0 → 单价≥0 → 金额服务端重算一致 → 并发原子更新 → 单事务写 approval_record + `PR_APPROVE` 审计
- reject 校验链：不强制校验物料/金额（业务数据有问题也应允许驳回），comment 必填；写 approval_record + `PR_REJECT` 审计
- revise：仅原申请人（或 ADMIN）；`REJECTED→DRAFT`、清空 `submitted_at`（历史提交时间仍可从审计追溯）、version+1；只写 `PR_REVISE` 审计，不写 approval_record
- 重新提交：不新增 resubmit 端点，submit 天然支持 `REJECTED→DRAFT→PENDING` 链路；每次提交更新 `submitted_at`、version+1、写新 `PR_SUBMIT` 审计
- 审批历史 `GET /{id}/approvals`：按 created_at 升序返回 approver/action/comment/from_status/to_status/created_at；仅「能查看该 PR 的用户」可看（复用 get_pr 对象级规则，无 pr:view 或非申请人看他人 PR 均 403）
- 查询范围扩展：APPLICANT 只看自己；DEPT_MANAGER 看自己创建 + 自己负责部门的 PR（审批中心数据源，`status=PENDING` 筛选）；ADMIN/BUYER 看全部（采购执行跨部门）；不因拥有 pr:view 就全量放行
- 乐观锁 + 并发审批：approve/reject/revise 均原子条件更新 `WHERE id=? AND version=? AND status=?` + `synchronize_session=False`；rowcount==0 时锁定读（`with_for_update`）穿透 REPEATABLE READ 快照，区分 `PR_VERSION_CONFLICT`(4011) 与 `PR_ALREADY_PROCESSED`(4012)；并发 approve-vs-approve、approve-vs-reject 均恰好 1 个成功（8 线程实测）
- 索引：新增 `ix_pr_dept_status (department_id, status)` 联合索引支撑审批中心高频查询；保留单列 `ix_pr_status`（"我的 PENDING"）、`ix_pr_dept`（独立部门筛选），组合索引左前缀不可替代单列场景
- 审计：AuditAction 26→27（新增 `PR_REVISE`）；审批动作审计含 document_no / old-new status / version / ADMIN override 标记；approval_records 存业务审批意见，operation_logs 存系统操作审计，两概念分离
- 迁移：`2026_09_01_1445-b7c4d9e1a3f6`（approval_records 三列 + `ix_pr_dept_status` + action ENUM 扩 27），dev+test `alembic check` 无 drift
- 期间修复：冒烟脚本断言 submitted_at 清空值为 Python `None`（非 JSON `null`）；SUBMIT 动作只写审计不写 approval_record（历史长度断言修正）；被停用物料阻断后续场景需新建物料
- 安全 Review（9 项）：无 role 名称直判授权（权限点+对象级双层）；无前端隐藏授权依赖（API 强制校验）；跨部门审批被 department_managers 拦截；applicant/department 为服务端字段不可伪造；审批历史无侧漏；ADMIN override 双处审计；inactive 用户/部门均被复查拦截；主管关系实时查询（历史审批人经 approver_id 保留）

**验收**：部门主管 approve 成功、403 矩阵（跨部门主管/普通申请人/无权限）、提交后停用物料 approve 拦截（reject 放行）、金额重算、reject comment 必填、revise 清空 submitted_at + 可编辑可重提、审批历史顺序与权限、部门主管列表范围、乐观锁 4011、并发 approve/approve-vs-reject 单成功、approval_records 无写 API → `pytest` 103/103 + 冒烟 22/22 → `feat: implement purchase requisition approval workflow`

### Phase 8 — 采购订单 ✅ 已完成（2026-09-01）

- PR → PO 转换（按 Q3/Q4：拆单 / 合并）：一个 PO 可合并多张 PR 的明细（Q4，sources 映射表 `purchase_order_item_sources`），一个 PR 明细可拆给多张 PO（Q3，`converted_quantity` 累积）；无来源采购允许（差额为 MOQ 等超采，须在 item.remark 说明）
- 数量一致性（§9.2，架构规则 6）：逐 source CAS 更新 `converted_quantity + qty <= requested_quantity`，rowcount==0 → `PR_ITEM_CONVERT_EXCEEDED`(4009)，并发转单恰一成功；`SUM(sources.quantity) <= ordered_quantity` 预校验（`PO_SOURCE_EXCEEDS_ORDERED` 5010，uk_pois 唯一键防同一来源重复累加）
- PR 头状态：仅当**全部明细** `converted_quantity = requested_quantity` 时置 `CONVERTED`（单条原子 UPDATE + NOT EXISTS 子查询判定，避免 REPEATABLE READ 快照漏判）；部分转出保持 `APPROVED` 可继续转单
- 校验链：PR 存在且 `APPROVED`（R4，非 APPROVED → 4002）→ 供应商存在且 ACTIVE（R5，停用 → 5006）→ 物料存在且 ACTIVE（3009）→ 明细非空（R12，schema min_length=1）→ 数量/单价合法 → 来源合计 ≤ 采购数量 → 金额服务端重算（ROUND_HALF_UP 2 位）
- PO 确认（Q9）：DRAFT 允许单价为 0 暂存；confirm 时逐行强制 `unit_price > 0`（`PO_UNIT_PRICE_REQUIRED` 5007）→ `DRAFT→CONFIRMED`
- PO 取消（R14 + §9.2 回退）：仅当 `SUM(received_quantity) == 0`（有收货 → `PO_CANCEL_HAS_RECEIPT` 5008）；`DRAFT/CONFIRMED→CANCELLED` 后逐 source CAS 回退 `converted_quantity`，PR 不再全部转完时原子回退 `APPROVED`
- Q2 扩展：`APPROVED` 的 PR 允许取消，但存在非 CANCELLED 关联 PO 时禁止（`PR_CANCEL_HAS_ACTIVE_PO` 4008，实时 join 查询）；关联 PO 全部取消后可取消
- 乐观锁 + 并发：PO 新增 `version` 列；confirm/cancel 原子条件更新 `WHERE id=? AND version=? AND status=?`，rowcount==0 时锁定读穿透快照区分 `PO_VERSION_CONFLICT`(5012) 与 `PO_ALREADY_PROCESSED`(5013)；并发 confirm 8 线程恰一成功
- 对象级权限：BUYER 只能操作自己创建的 PO（ADMIN override）；APPLICANT 仅见自己 PR 转出的 PO、DEPT_MANAGER 仅见本部门 PR 转出的 PO（sources→pr_item→PR 链路 EXISTS 子查询），BUYER/ADMIN/WAREHOUSE 全量（收货选单需要）
- 审计：AuditAction 27→28（新增 `PO_CANCEL`）；`PO_CREATE`/`PO_CONFIRM`/`PO_CANCEL` 均含 document_no、version 变化、备注/原因
- 迁移：`2026_09_01_1450-a1b2c3d4e5f6`（purchase_orders.version + total_amount 18,4→18,2 + purchase_order_items.amount 生成列→普通列（ROUND_HALF_UP 2 位，MySQL 需 drop+add）+ action ENUM 扩 28），dev+test `alembic check` 无 drift，downgrade/upgrade 往返验证通过
- 期间修复：`_visible_source_stmt` 子查询去掉 LIMIT（MySQL 不允许 `IN (SELECT ... LIMIT 1)`）；Q2 测试场景改为部分转出（全转完是 CONVERTED，取消走 4002）；DECIMAL(18,4) 数量 JSON 序列化为 4 位小数（断言修正）；PR/approval 测试清理函数纳入 PO 表（sources FK RESTRICT 阻塞旧清理）

**验收**：非 APPROVED 的 PR 不可转单（4002）、无供应商/停用供应商被拒（404/5006）、拆单两 PO 后 PR 全转完 CONVERTED、合单两 PR 进一 PO、超转 4009、并发转单单成功、confirm 单价 0 被拒（5007）、取消回退 converted_quantity + PR 回退 APPROVED、已收货不可取消（5008）、Q2 有 active PO 4008、乐观锁 5012、并发 confirm 单成功、403 矩阵、列表可见范围 → `pytest` 135/135 + 冒烟 23/23 → `feat: implement purchase order`

### Phase 9 — 采购入库与库存 ⭐ 核心

- 入库单创建（明细级数量校验）
- 事务内：写流水 → 更余额 → 更 PO 累计收货 → 重算 PO 状态
- 条件更新（CAS）防并发超收
- 部分到货 / 完全到货
- 入库冲销（按 Q6 结果）
- 库存余额、库存流水查询（支持按单据反查）

**验收**：并发入库不重复增加、超量入库被拒、流水可反查 → `feat: add purchase receipt and inventory transaction`

### Phase 10 — 前端

- Vite + Vue3 + TS + Element Plus 骨架
- Axios 拦截器（token、统一错误处理）
- Pinia（user / permission）、Vue Router（动态路由）
- 页面：登录、主数据 3 页、采购 5 页、仓库 3 页、系统 2 页

**验收**：主流程页面手工走通 → `feat: build frontend application`

### Phase 11 — Dashboard

- 6 个统计卡片
- ECharts：采购金额趋势（按月）、库存数量排行 Top10
- 安全库存预警列表

**验收**：数字与数据库一致 → `feat: add dashboard statistics`

### Phase 12 — 自动测试

13 类必测场景（见 `requirements.md` §11 对应章节）：

| # | 场景 | 类型 |
|---|---|---|
| 1 | 登录成功 / 失败 / 密码错误 | 集成 |
| 2 | 创建物料（含编码生成、唯一冲突） | 集成 |
| 3 | 创建采购申请 | 集成 |
| 4 | 提交采购申请（DRAFT → PENDING） | 集成 |
| 5 | 审批采购申请（通过 / 驳回） | 集成 |
| 6 | 生成采购订单 | 集成 |
| 7 | 确认采购订单 | 集成 |
| 8 | 采购入库（一次性收齐） | 集成 |
| 9 | 部分入库 | 集成 |
| 10 | 完全入库（PO → RECEIVED） | 集成 |
| 11 | 库存变化（余额 + 流水条数 + 金额） | 集成 |
| 12 | 非法状态转换（PENDING 修改、未审批转 PO 等） | 单元 + 集成 |
| 13 | 超量入库 | 集成 |
| 14 | 并发入库幂等 | 集成 |
| 15 | 权限测试（越权审批、越权入库） | 集成 |

**验收**：全部通过，覆盖率 > 70% → `test: add purchase workflow integration tests`

### Phase 13 — Docker 部署

- 后端多阶段构建 Dockerfile（非 root 用户）
- 前端 Nginx 镜像
- `docker-compose.yml`（mysql / backend / frontend）
- 数据库初始化 + Demo 数据种子脚本
- `docs/deployment.md`

**验收**：`docker compose up -d` 后 `localhost` 可登录演示 → `chore: add docker deployment`

### Phase 14 — 文档与作品集

- `README.md`（项目亮点、架构图、快速开始、演示截图位）
- `docs/architecture.md` `docs/business-flow.md` `docs/api-design.md`
- 演示剧本（requirements §9 的 10 步）
- 简历项目描述要点

**验收**：文档齐全、README 可独立阅读 → `docs: complete project documentation`

---

## 三、Git 提交规范

```
feat:     新功能
fix:      缺陷修复
docs:     文档
test:     测试
refactor: 重构（不改变外部行为）
chore:    构建/配置/依赖
```

格式：`<type>: <小写英文动宾短语>`，正文可选。
每完成一个 Phase 单独 commit（Phase 内部可按子功能拆分多个 commit）。

---

## 四、当前阻塞项

**Phase 3 前置条件**：Phase 2 输出需通过 Review。

### 4.1 Q1–Q16 决策已全部落地 ✅

| 决策 | 落地位置 |
|---|---|
| Q1 `REJECTED → DRAFT → PENDING` | PR 状态机白名单 |
| Q2 APPROVED PR 无有效 PO 时可取消 | Service 校验（非 DB 约束） |
| Q3 一 PR 拆多 PO | `pr_items.requested_quantity` + `converted_quantity` + CHECK |
| Q4 一 PO 合并多 PR | `purchase_order_item_sources` 映射表 |
| Q5 禁止超收 | CHECK + CAS 条件更新 |
| Q6 冲销 | `PURCHASE_IN_REVERSAL` 枚举 + `reversed_transaction_id` + append-only 触发器 |
| Q7 移动加权平均 | `inventory_balances(quantity, total_amount, average_unit_cost)` |
| Q8 禁止负库存 | CHECK `quantity >= 0` |
| Q9 PR 价可 0 / PO 价 > 0 | DB CHECK `>= 0` + Service confirm 时校验 `> 0` |
| Q10 安全库存按 warehouse+material | `inventory_policies` 独立表 |
| Q11 单级审批，预留多级 | `approval_records.step_no` |
| Q12 审批人由部门+主管关系决定 | `department_managers` 表 |
| Q13 Python 3.12 + MySQL 8 | 已确认 Python 3.12.9；Docker daemon 待启动 |
| Q14 独立测试数据库 | `erp_lite` / `erp_lite_test` 双库 |
| Q15 9 类关键业务审计 | `operation_logs` + `AuditAction` 枚举 |
| Q16 不实现附件 | 不建表，扩展方案写入文档 §11 |

### 4.2 待 Review 确认的 6 个开放点

记录在 [`database-design.md` §13](./database-design.md#13-待确认--需-review-关注点)：

| # | 关注点 | 我的处理 |
|---|---|---|
| A-1 | `reversal_transaction_id` 移除，仅保留单向指针 | 反向查询用 `WHERE reversed_transaction_id = :id` |
| A-2 | `po_item.ordered_quantity` 允许 > 来源数量之和（MOQ 超采） | Service 校验 `<=`，差额需填 `remark` |
| A-3 | 冲销不回退 PR `converted_quantity` | 冲销是仓库端纠错，采购关系仍成立 |
| A-4 | `unit_price` DB CHECK `>= 0`，confirm 时校验 `> 0` | 允许 DRAFT 暂存 0 |
| A-5 | Docker daemon 未启动 | 已给出本地 MySQL 备选方案 |
| A-6 | 冲销为整单冲销，不支持部分冲销 | 第一阶段简化 |

### 4.3 环境待办

- [ ] 启动 Docker Desktop，验证 `docker info` 可用
- [ ] 若 Docker 不可用，按 `database-design.md` §0 方案 B 部署本地 MySQL 8
- [ ] 确认 Python 3.12.9（`E:\Python312\python.exe`）作为虚拟环境基线
