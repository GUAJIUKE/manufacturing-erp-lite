# 系统架构（Manufacturing ERP Lite）

> Portfolio 技术架构说明。适用读者：评审简历项目、准备面试讲解、接手代码的工程师。
> 所有描述与 `backend/` 真实代码一一对应；标注为「本 Demo 未实现」的均不做。

---

## 1. 一句话架构

前后端分离的单体应用：**Vue 3 前端通过 REST API 访问 FastAPI 后端，后端按
api → service → repository/model 单向分层，业务规则全部收敛在 Service 层，
MySQL 8 提供事务与行锁，Alembic 管理迁移。**

```
Browser
   │  HTTPS/HTTP（JWT Bearer）
   ▼
Vue 3 (TypeScript + Element Plus + Pinia)
   │  axios 封装，统一错误处理与分页信封
   ▼
REST API  /api/v1  （FastAPI 路由 + Pydantic v2 校验 + 鉴权依赖）
   │  仅做：HTTP 语义、参数校验、权限点校验、调用 Service
   ▼
Service 层  app/services/   ← 全部业务逻辑在这里
   │  状态机转换 / 事务边界 / CAS 并发控制 / 编号生成 / 审计写入
   ▼
SQLAlchemy 2.x ORM  app/models/（22 张表，1:1 对应 docs/database-design.md）
   │
   ▼
MySQL 8（InnoDB 事务 + 行锁 + 触发器强制 append-only）
```

依赖方向**单向**，禁止反向：

```
api → services → repositories → models
              ↘ core / utils（配置、安全、异常、枚举、金额工具，可被任意层引用）
```

## 2. 各层职责与「不做的事」

| 层 | 目录 | 职责 | 明确不做 |
|---|---|---|---|
| API | `app/api/v1/` | 路由、Pydantic 请求/响应、`require_perm` 鉴权、调 Service | ❌ 不写业务判断、❌ 不直接改 `status` 字段、❌ 不手写复杂 SQL |
| Service | `app/services/` | **全部业务规则**：状态机、事务、CAS、对象级权限、编号、审计 | ❌ 不接触 HTTP 对象 |
| Repository | `app/repositories/` | 数据访问封装 | ❌ 无业务规则 |
| Models | `app/models/` | ORM 映射 + DB 约束表达 | ❌ 无业务方法 |
| Core / Utils | `app/core/` `app/utils/` | 配置（纯 env 驱动）、JWT/bcrypt、统一异常与响应、枚举、金额 | — |

统一响应信封：`{code, message, data, request_id}`。`code == 0` 成功；`code != 0`
为业务错误码（按域分段：1xxx 通用 / 2xxx 认证 / 3xxx 主数据 / 4xxx 采购申请 /
5xxx 采购订单 / 6xxx 入库库存）。HTTP 状态码表达语义类别，`code` 表达精确原因。

## 3. 为什么业务规则放在 Service 层，而不是 API 层？

这是本项目最重要的分层决策，理由都来自踩过的真实问题：

1. **可测试性（首要动机）**：Service 层以「db session + 当前用户 + 入参」为边界，
   不依赖 HTTP。测试用 `TestClient` 走 API，也能直接调 Service 复现边界场景
   （如并发）。如果规则散在路由函数里，任何一条都要靠发 HTTP 才能验证。
2. **事务边界只能由代码调用链表达**：一次入库涉及「单头 + 明细 + PO 数量 +
   流水 + 余额 + PO 状态 + 审计」7 类写入，必须在一个 `session_scope()` 上下文里
   同生共死（见 docs/transaction.md）。这个边界天然属于 Service 层的函数体，
   API 层无法表达「这段逻辑必须整体回滚」。
3. **规则需要跨接口复用**：`recompute_po_status`（由收货/冲销后的明细数量推导
   PO 状态）被收货、冲销两处调用；`visible_po_id_stmt`（PO 可见范围子查询）被
   PO 列表、入库单可见性复用。规则进 Service 才谈得上复用，复制到多个路由必然
   漂移。
4. **状态机必须单点收口**：PR/PO/Receipt 的状态变更集中在各自 Service 的
   `_TRANSITIONS` 白名单表里。若 API 层可以直接 `UPDATE status`，就没有「合法
   流转」可言——这是为什么 Pydantic 的 Create/Update Schema 里**刻意不暴露
   `status` 字段**（S-01），前端根本提交不了状态。
5. **审计与编号的调用点一致性**：编号（`numbering_service`）与审计
   （`audit_service`）在 Service 内部与业务写在同事务。放 API 层则要么漏写、
   要么多一次不一致的提交点。
6. **入参信任边界**：`buyer_id`、`received_by`、`status`、金额等一律由服务端从
   `CurrentUser` 与数据库推导，客户端传入的金额被忽略（`money` 工具服务端重算）。

一句话：**API 层回答「谁能调」，Service 层回答「这件事怎么才算对」**。

## 4. 一次请求的生命周期（以「确认采购订单」为例）

```
PUT /api/v1/purchase-orders/{id}/confirm   {version: 3}
  │
  ├─ deps.get_current_user       → 解析 JWT、加载用户、禁用检查 → CurrentUser
  ├─ require_perm("po:confirm")  → 角色权限点校验（403 缺权限）
  ├─ FastAPI Pydantic 校验 body  → 422 非法入参
  │
  ▼
purchase_order_service.confirm_po(...)
  ├─ _load(po)                        → 404
  ├─ _assert_transition(DRAFT→CONFIRMED)  → 状态机白名单（5002 非法流转）
  ├─ _assert_version(version)              → 乐观锁（5012 版本冲突）
  ├─ _assert_buyer_or_admin(...)           → 对象级权限（403 非本人创建）
  ├─ 校验每行 unit_price > 0               → 确认前置条件（Q9）
  ├─ UPDATE ... WHERE id=? AND version=? AND status='DRAFT'
  │      rowcount==0 → with_for_update 锁定读，区分「已被处理」/「版本过期」
  ├─ write_audit(PO_CONFIRM)               → 审计（同一事务）
  └─ 返回 PO（version 已 +1）
```

注意第 4 步「对象级权限」**不在**第 2 步的权限点里——两层校验分离是刻意的，
详见 docs/rbac.md。

## 5. 关键机制一览（各有专文）

| 机制 | 落点 | 详见 |
|---|---|---|
| 单据状态机 | 各 Service `_TRANSITIONS` 白名单 + 状态由服务端推导 | docs/business_flow.md |
| 事务边界 | `session_scope()` 包裹整段业务 | docs/transaction.md |
| 乐观锁 / CAS | PR/PO `version` 条件更新；`converted_quantity`、`received_quantity` CAS | docs/concurrency.md |
| 余额行锁 | `INSERT..ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` + `SELECT..FOR UPDATE`，全量预排序取锁 | docs/concurrency.md |
| append-only 流水 | MySQL 触发器 `trg_it_no_update` / `trg_it_no_delete` | docs/inventory_design.md |
| 编号 | `ON DUPLICATE KEY UPDATE + LAST_INSERT_ID()` 单语句原子取号，独立短事务 | database-design.md §7 |
| 金额 | `Decimal(18,2)` ROUND_HALF_UP，服务端 `money` 工具计算 | docs/inventory_design.md |
| 审计 | `audit_logs` 关键操作（登录/单据流转/主数据变更/权限变更） | database-design.md §6 |
| 认证 | JWT（HS256, 8h）+ bcrypt(12) 密码哈希 | — |

## 6. 配置与安全（纯 env 驱动）

- `backend/app/core/config.py`：**所有设置走环境变量**，本地默认值可直接启动
  （无 `.env` 也能跑）；生产必须覆盖 `SECRET_KEY` / `DB_PASSWORD`。
- 默认 `SECRET_KEY` 是显式占位 `dev-only-secret-key-change-me-in-production`，
  仅用于本地开发；仓库不提交任何真实密钥（见 .env.example 占位约定）。
- 测试库防护：`ENV != test` 时若 `DB_NAME` 以 `_test` 结尾，`model_validator`
  直接拒绝启动，防止误连测试库（测试库可被 suite 随意 drop/recreate）。
- bcrypt 哈希落库，明文密码永不存储；Demo 账号仅限本地演示。

## 7. 前端结构

```
frontend/src/
├── api/        axios 实例 + 各域接口封装（request.ts 统一 baseURL/错误/分页信封）
├── stores/     Pinia（auth：登录态 + 权限点缓存 + 菜单渲染）
├── router/     路由 + 元信息权限码，403/404 页
├── views/      按域组织：login / dashboard / pr / approval / po / receipt /
│               inventory / master / system
├── components/ KpiCard / StatusTag / MoneyText / QuantityText / 选择器组件
├── utils/      permission.ts（前端按钮/菜单级显隐）、status.ts、format.ts
└── types/      与后端 schema 对齐的 TS 类型
```

前端不保存任何业务判断：按钮显隐由「权限点 + 单据状态」双条件驱动（与后端一致），
最终合法性由后端裁决——前端只是体验层。

## 8. 测试策略

- 后端 pytest：独立测试库（`erp_lite_test`），函数级回滚；覆盖 15 类场景映射 +
  端到端业务故事（tests/test_workflow_e2e.py）+ 并发/事务/RBAC 边界。
- 覆盖率门禁：`.coveragerc`（`source=app` + `branch=True`）> 70%，实测 91%。
- 前端：Vitest 组件/工具单测 + `vue-tsc` 类型 + `vite build`。
- 演示数据：`app/db/seed_demo.py` 走真实 HTTP 链重放确定性业务故事并做 KPI 自检。

## 9. 演进边界（本项目明确不做的）

- 不引入 Redis / 消息队列 / BPM 引擎（单级审批用 `approval_records.step_no`
  预留扩展）。
- 不做 FIFO / 凭证 / 总账 / 应收应付（移动加权平均仅覆盖采购入库域）。
- 不做生产 / 销售 / 财务模块与 AI——边界外功能以「预留枚举/字段」表达，不实现。
