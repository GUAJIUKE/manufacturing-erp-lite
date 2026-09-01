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
| 4 | 登录与 RBAC | JWT 认证、权限守卫、用户/角色/部门 CRUD | 3 | 中 | ⬜ |
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

### Phase 4 — 登录与 RBAC

- `POST /api/v1/auth/login` → JWT
- `get_current_user` 依赖、`require_perm("po:confirm")` 权限守卫
- 用户 CRUD（密码 bcrypt 哈希）、角色 CRUD（权限分配）、部门 CRUD
- 审计日志记录登录

**验收**：登录、无 token 401、无权限 403、密码哈希不可逆 → `feat: implement auth and RBAC`

### Phase 5 — 主数据

- 物料 CRUD（编码自动生成、唯一校验、软删除）
- 供应商 CRUD
- 仓库 CRUD（初始化 1 个主仓库）
- 分页 + 关键字/状态筛选

**验收**：编码唯一冲突 409、被引用数据不可物理删除 → `feat: add material and supplier master data`

### Phase 6 — 采购申请

- PR 单头 + 明细 CRUD（同事务）
- 状态机：`DRAFT → PENDING`，仅 DRAFT 可改
- 编号生成（序列表 + 行锁）
- 金额服务端重算

**验收**：PENDING 不可修改、明细为空被拒、并发编号不重复 → `feat: implement purchase requisition`

### Phase 7 — 审批流程

- `submit` / `approve` / `reject` / `cancel` 接口
- 审批记录落库
- 审批中心列表（待我审批）
- 业务级校验：同部门主管

**验收**：非主管审批被拒、驳回必填意见、跨部门不可审批 → `feat: implement approval workflow`

### Phase 8 — 采购订单

- PR → PO 转换（按 Q3/Q4 结果：拆单 / 合并）
- PO 确认、取消（已收货不可取消）
- PO 明细记录来源 PR

**验收**：非 APPROVED 的 PR 不可转单、无供应商被拒 → `feat: implement purchase order`

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
