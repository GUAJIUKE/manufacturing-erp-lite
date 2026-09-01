# Manufacturing ERP Lite

**制造企业采购库存协同系统** — 面向小型研发制造企业的轻量级 ERP 系统。

> 当前阶段：**Phase 1 需求文档已完成**，等待数据库设计方向确认（Phase 2 未开始）。

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
| 前端 | Vue 3 · TypeScript · Vite · Element Plus · Pinia · Vue Router · Axios · ECharts |
| 部署 | Docker · Docker Compose |

## 目录结构

```
backend/                后端服务（分层：api / core / models / schemas / services / repositories / db / utils）
frontend/               前端应用
docs/                   项目文档
docker-compose.yml      容器编排
```

## 文档

| 文档 | 说明 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | 需求规格：模块划分、业务流程、状态机、业务规则、待确认问题 |
| [docs/roadmap.md](docs/roadmap.md) | Phase 0–14 路线图与验收标准 |
| docs/database-design.md | 数据库设计（Phase 2） |
| docs/ERD.md | ER 图（Phase 2） |
| docs/architecture.md | 系统架构（Phase 3） |
| docs/business-flow.md | 业务流程图（Phase 10） |
| docs/api-design.md | 接口设计（Phase 6） |
| docs/deployment.md | 部署文档（Phase 13） |

## 快速开始

> 待 Phase 13 完成后可用：`docker compose up -d`

## 开发进度

| Phase | 名称 | 状态 |
|---|---|---|
| 0–1 | 项目规划与需求文档 | ✅ 完成 |
| 2 | 数据库设计 | ⏸ 待确认需求问题 |
| 3–9 | 后端业务实现 | ⬜ 未开始 |
| 10–11 | 前端与 Dashboard | ⬜ 未开始 |
| 12–14 | 测试、部署、文档 | ⬜ 未开始 |
