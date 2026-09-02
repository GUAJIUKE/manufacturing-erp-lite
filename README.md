# Manufacturing ERP Lite

**制造企业采购库存协同系统** — 面向小型研发制造企业的轻量级 ERP 系统。

> 当前阶段：**Phase 10 前端已完成**（Vue 3 + TS + Element Plus 单页应用，真实 API 全业务链，无 mock；typecheck ✅ / build ✅ / vitest 32 项 ✅ / 真实 API E2E 37 项 ✅ / 后端回归保持全绿）。**等待 Review，未进入 Phase 11**。

---

## 项目目标

一个真实可用的采购 + 仓储业务闭环系统，而非静态页面 Demo。核心体现 ERP 的十个设计维度：

主数据管理 · 单据管理 · 状态流转 · 审批流程 · 数据一致性 · 权限控制 · 库存流水 · 操作审计 · 业务关联 · 报表统计

## 业务闭环

```
采购申请 PR → 主管审批 → 采购订单 PO → 供应商到货 → 采购入库 → 库存流水 → 库存余额
```

支持**部分到货**：采购 100 → 到货 40（`部分到货`）→ 到货 60（`已完成`），超量入库被拒绝。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.x · Pydantic v2 · MySQL 8 · Alembic · JWT · Pytest |
| 前端 | Vue 3 · TypeScript · Vite · Element Plus · Pinia · Vue Router · Axios · Vitest（ECharts 留待 Phase 11 Dashboard） |
| 部署 | Docker · Docker Compose |

## 目录结构

```
backend/                后端服务（分层：api / core / models / schemas / services / repositories / db / utils）
frontend/               前端应用（Vue 3：api / components / layouts / router / stores / types / utils / views）
docs/                   项目文档
docker-compose.yml      容器编排
```

## 文档

| 文档 | 说明 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 需求规格：模块划分、业务流程、状态机、业务规则 R1–R15 |
| [docs/roadmap.md](docs/roadmap.md) | Phase 0–14 路线图、验收标准、Q1–Q16 决策落地 |
| [docs/database-design.md](docs/database-design.md) | 数据库设计：22 张表、字段、约束、索引、枚举、Q1–Q16 落地对照 |
| [docs/ERD.md](docs/ERD.md) | ER 图：全局 / 采购库存链路 / RBAC，附单据状态机 |
| [docs/data-integrity-review.md](docs/data-integrity-review.md) | 数据一致性评审：11 维度 75 项检查点 |
| [docs/architecture.md](docs/architecture.md) | 系统架构：分层职责、事务边界、并发控制、编号方案 |
| docs/business-flow.md | 业务流程图（Phase 10） |
| docs/api-design.md | 接口设计（Phase 6） |
| docs/deployment.md | 部署文档（Phase 13） |

## 快速开始

### 1. 启动后端（依赖本地 MySQL 8，库名 `erp_lite`）

```bash
cd backend
./.venv/Scripts/python.exe -m alembic upgrade head   # 首次：建表（已执行可跳过）
./.venv/Scripts/python.exe -m app.db.init_data       # 首次：RBAC + 演示账号（幂等）
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173（/api 代理到 127.0.0.1:8000）
```

后端地址通过 `frontend/.env.development` 的 `VITE_API_BASE_URL` 配置（默认 `http://localhost:8000/api/v1`）。

### 3. 演示账号

| 账号 | 密码 | 角色 | 典型操作 |
|---|---|---|---|
| admin | admin123 | 系统管理员 | 主数据 / 系统管理 |
| zhangsan | demo123 | 采购申请人 | 创建并提交 PR |
| lisi | demo123 | 部门主管 | 审批中心（通过/驳回） |
| wangwu | demo123 | 采购员 | 由 PR 创建 PO 并确认 |
| zhaoliu | demo123 | 仓库管理员 | 收货入库 / 冲销 / 库存查询 |

### 4. 完整演示流程（全程浏览器，不碰 Swagger/DB/脚本）

```
zhangsan 登录 → 新建采购申请(PR) → 提交
lisi 登录 → 审批中心 → 通过
wangwu 登录 → 创建采购订单(PO，带 PR 来源) → 确认
zhaoliu 登录 → 采购入库：第一次收 40 → 库存 40 → 第二次收 60 → PO 已收完
             → 库存余额 100（安全库存红/低库存标记）→ 库存流水 +40/+60
             → 入库单详情 → 冲销第二批（填写原因）→ 库存回退 40 → 流水 +40/+60/-60
admin 登录 → 系统管理（用户/角色权限分配/部门）
```

每次切换账号请先退出登录（右上角用户菜单），登录页可点击演示账号卡片快速填充。

## 开发进度

| Phase | 名称 | 状态 |
|---|---|---|
| 0–1 | 项目规划与需求文档 | ✅ 完成 |
| 2 | 数据库设计 + Data Integrity Review | ✅ 完成 |
| 3 | 后端基础架构（骨架 + 迁移 + 测试） | ✅ 完成 |
| 4 | 登录与 RBAC（JWT + 权限守卫 + 用户/角色/部门） | ✅ 完成 |
| 5 | 主数据（物料/供应商/仓库/库存策略 + 编号服务） | ✅ 完成 |
| 6 | 采购申请（PR 单据 + 状态机 + 乐观锁） | ✅ 完成 |
| 7 | 审批工作流（部门主管审批 + 审批记录 + 并发保护） | ✅ 完成 |
| 8 | 采购订单（PR→PO 转换 + 确认/取消 + 数量一致性） | ✅ 完成 |
| 9 | 采购入库 + 库存（Receipt/Transaction/Balance/冲销） | ✅ 完成 |
| 10 | 前端（Vue 3 + TS + Element Plus，真实 API 全业务链 10.1–10.10） | ✅ 完成 |
| 11 | Dashboard 与图表（待 Review 通过后） | ⬜ 未开始 |
| 12–14 | 测试、部署、文档 | ⬜ 未开始 |

## 设计要点

| 维度 | 决策 |
|---|---|
| 表数量 | 22 张（主数据 10 / 采购 5 / 仓储 4 / 支撑 3） |
| 安全库存 | 独立 `inventory_policies`，维度为 **warehouse + material** |
| 审批人认定 | 独立 `department_managers` 表，不写死 user_id，避免循环外键 |
| PR→PO 映射 | `purchase_order_item_sources` 明细级映射表，支持拆单与合单 |
| 库存流水 | 带符号 `quantity`，`SUM(quantity)` 可一键对账；append-only 由触发器强制 |
| 冲销 | 独立 `PURCHASE_IN_REVERSAL` 类型，不用 `ADJUST_OUT` 代替 |
| 并发防超收 | 条件更新 + `rowcount` 校验，禁止「先 SELECT 再 UPDATE」 |
| 编号生成 | `ON DUPLICATE KEY UPDATE + LAST_INSERT_ID()`，独立短事务，允许跳号 |
