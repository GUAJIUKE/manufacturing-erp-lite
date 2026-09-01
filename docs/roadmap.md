# Manufacturing ERP Lite — 项目路线图

> 版本：v1.0 ｜ 日期：2026-09-01
> 推进原则：**一个 Phase 不通过测试，不进入下一 Phase**

---

## 一、Phase 全景

| Phase | 名称 | 核心交付物 | 依赖 | 预估工作量 | 状态 |
|---|---|---|---|---|---|
| 0 | 项目规划 | 仓库初始化、目录骨架、技术选型确认 | — | — | ✅ 完成 |
| 1 | 需求文档 | `docs/requirements.md`、roadmap、模块划分、业务流程、待确认清单 | 0 | — | ✅ 完成 |
| 2 | 数据库设计 | `docs/database-design.md`、`docs/ERD.md`（Mermaid） | 1 | 中 | ⏸ 待确认 Q1–Q16 |
| 3 | 后端基础架构 | FastAPI 分层骨架、配置、统一响应、异常处理、Alembic、Docker Compose | 2 | 中 | ⬜ |
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

### Phase 2 — 数据库设计（下一步）

**输入**：Q1–Q16 的确认结果
**产出**：
- `docs/database-design.md` — 全部表、字段、类型、主键、外键、唯一约束、索引、状态枚举、表关系说明
- `docs/ERD.md` — Mermaid ER Diagram（全图 + 采购域局部图）

**计划表清单（15 张）**：

```
主数据域
  departments       部门
  roles             角色
  permissions       权限点
  role_permissions  角色-权限关联
  users             用户
  materials         物料
  suppliers         供应商
  warehouses        仓库

采购域
  purchase_requisitions      采购申请单头
  purchase_requisition_items 采购申请明细
  purchase_orders            采购订单单头
  purchase_order_items       采购订单明细

仓储域
  purchase_receipts          采购入库单头
  purchase_receipt_items     采购入库明细
  inventory_balances         库存余额
  inventory_transactions     库存流水

支撑域
  approval_records           审批记录
  doc_sequences              单据编号序列
  operation_logs             操作审计日志
```

**验收**：表结构评审通过 → 提交 `docs: add database design and ERD`

### Phase 3 — 后端基础架构

- FastAPI 应用工厂、`/api/v1/` 路由聚合
- `core/config.py`（Pydantic Settings，环境变量驱动）
- 统一响应封装 `ApiResponse[T]`
- 全局异常处理器（业务异常 / 校验异常 / 认证异常 / 未捕获）
- SQLAlchemy 2.0 Session 工厂、`Base`、事务上下文管理器
- Alembic 初始化 + 首个迁移
- `docker-compose.yml`（MySQL 8 + backend）
- `pytest` 骨架 + conftest（测试库、fixture 隔离）

**验收**：`pytest` 通过冒烟测试（health check + 建表/回滚）→ `chore: setup backend architecture`

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

**Phase 2 前置条件**：`docs/requirements.md` §7 的 Q1–Q16 需确认。

其中**影响表结构、必须确认**的关键 6 项：

| 关键项 | 影响的表 |
|---|---|
| Q3 一 PR 多 PO（拆单） | `purchase_requisition_items.converted_quantity` |
| Q4 一 PO 多 PR（合并） | `purchase_order_items.source_pr_id / source_pr_item_id` |
| Q6 入库冲销 | `inventory_transactions` 反向流水、`purchase_receipts.status` |
| Q7 移动加权平均计价 | `inventory_balances.total_amount / avg_price` |
| Q11/Q15 多级审批 + 审计日志 | `approval_records`、`operation_logs` |
| Q13 Docker / Python 3.12 环境 | 部署方式、依赖版本锁定 |

其余为非阻塞项，可沿用推荐方案。
