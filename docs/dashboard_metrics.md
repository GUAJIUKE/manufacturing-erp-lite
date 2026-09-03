# Dashboard 数据口径文档（Phase 11）

> 本文档是管理驾驶舱**唯一权威口径说明**。所有 KPI 的定义、权限范围、空值语义
> 都以本文件 + `backend/app/services/dashboard_service.py` 为准；前端只做展示
> 格式化（`formatMoney` / `formatQuantity`），**绝不自行聚合/求和**。
>
> 对应实现：`backend/app/services/dashboard_service.py`、`backend/app/api/v1/dashboard.py`、
> `backend/app/schemas/dashboard.py`、`backend/tests/test_dashboard.py`（21 项验收）。

---

## 0. 总原则

| # | 原则 | 说明 |
|---|------|------|
| P1 | 聚合在数据库 | 全部 KPI 由后端 `COUNT / SUM / GROUP BY` 完成；禁止 `SELECT 全表再 Python 求和` |
| P2 | 范围复用 | PR/PO 可见范围一律复用业务域函数：`purchase_requisition_service.visible_pr_condition` / `purchase_order_service.visible_po_id_stmt`（与列表页同一套逻辑，禁止在统计层复制第二套规则） |
| P3 | 金额 Decimal | 金额端到端 `Decimal`，wire 上为字符串；前端不重算 |
| P4 | 权限门 | 每类 KPI 先做权限门（无权限返回 0 / 空列表，**不 403**），卡片显隐由前端按 `/auth/me` permissions 控制 |
| P5 | 空数据语义 | 空库/无可见数据返回 0 与空列表；趋势缺日由后端补 0，图表轴完整 |
| P6 | 颜色对齐 | 图表颜色 = StatusTag 颜色，同源常量 `frontend/src/utils/status.ts` 的 `TAG_COLOR` |

---

## 1. KPI 口径表（`GET /dashboard/summary`）

| 字段 | 名称 | 口径（SQL 语义） | 权限门 | 可见范围 |
|------|------|------------------|--------|----------|
| `pending_pr_count` | 待审批采购申请 | `status = PENDING` 计数 | `pr:view` | `visible_pr_condition`（APPLICANT=自己；DEPT_MANAGER=自己+所管部门；其余全量） |
| `pending_purchase_count` | 待转采购需求 | `status = APPROVED` **且** `EXISTS(明细 converted_quantity < requested_quantity)`，`COUNT(DISTINCT PR)` | `pr:view` 且 `po:view` | 同 PR 范围（支持拆单：PR 状态原子翻转为 CONVERTED 后自然不计） |
| `draft_po_count` | 待确认采购订单 | `status = DRAFT` 计数 | `po:confirm` | BUYER 仅 `buyer_id = 自己`（与 confirm 对象级规则一致）；ADMIN 全量；其余角色 0 |
| `pending_po_count` | 待收货采购订单 | `status IN (CONFIRMED, PARTIALLY_RECEIVED)` 计数 | `po:view` | `visible_po_id_stmt`（与 PO 列表页一致） |
| `low_stock_count` | 低库存预警 | JOIN `inventory_policies` 后 `quantity < safety_stock` 计数 | `inventory:view` | 无仓库/物料维度差异（余额为全局表） |
| `inventory_total_amount` | 库存账面金额 | `SUM(inventory_balances.total_amount)`（权威值，不按最新单价重算） | `inventory:view` | 同上 |

### 1.1 易错点对照（Phase 11 §口径红线）

| 易错点 | 处理 |
|--------|------|
| 统计接口 SELECT 全库绕过权限 | 每个 KPI 先权限门，再叠加对象级 scope（P2） |
| 待转 = status==APPROVED 简单计数 | 必须存在未转完明细（`converted < requested`），`COUNT(DISTINCT id)` 防拆单重复 |
| 跨单位 SUM 待收数量 | 待收/待转只计 PR/PO **单数**，不做数量求和 |
| 低库存边界 | `strict <`；**无策略行不算**、`quantity == safety_stock` 不算 |
| 金额重算 | 直接 SUM `total_amount` 字段，Decimal-as-string |
| 趋势 7/30/90 前端拼 | 后端按区间聚合，缺日补 0，CANCELLED 排除 |
| 图表拉明细再统计 | 后端 SQL 聚合，前端零求和 |

---

## 2. PR 趋势（`GET /dashboard/pr-trend?days=7|30|90`）

- 口径：`apply_date` 落在 `[today - days + 1, today]`，`status != CANCELLED`；
  按 `apply_date` `GROUP BY`，返回 **count**（单数）与 **amount**（`SUM(total_estimated_amount)`）。
- 缺日：后端用日历补齐，`count=0, amount="0.00"`，保证折线/柱状轴连续。
- 范围：`visible_pr_condition`；无 `pr:view` 返回 `[]`。
- 测试锚点：当日 7 条活跃 PR（PR1..PR6+PR9，PR7 取消不计），金额 `1910.00`。

## 3. PO 状态分布（`GET /dashboard/po-status-distribution`）

- 返回**全部定义状态**（DRAFT/CONFIRMED/PARTIALLY_RECEIVED/RECEIVED/CANCELLED），
  `count=0` 也返回 —— 前端图表结构稳定、可直接着色。
- 范围：`visible_po_id_stmt`；无 `po:view` 返回全 0 列表。
- 颜色：前端按 `poStatusMeta(status).type → TAG_COLOR` 上色，与列表 StatusTag 同色。

## 4. 低库存 Top（`GET /dashboard/low-stock?limit=10`）

- 行语义与库存页 `below_safety_stock=true` **完全一致**：有策略行且 `quantity < safety_stock`。
- 排序：按绝对缺口 `safety_stock - quantity` 倒序；字段含仓库/物料编码名称、现存量、
  安全库存、缺口量（Decimal-as-string）。
- `low_stock_count` 与 `low-stock` 列表口径一致性有专门测试锚定（§4 测试）。

## 5. 待办（`GET /dashboard/todos`）—— 按执行角色收敛

后端只返回 `{type, count}`；label/跳转在前端 `frontend/src/utils/dashboard.ts`。

| type | 含义 | 角色（后端收敛） | 前端跳转 |
|------|------|------------------|----------|
| `PR_APPROVAL` | 待审批申请 | ADMIN / DEPT_MANAGER（`_PR_APPROVE_ROLES`） | `/approvals` |
| `PR_TO_PO` | 待转采购订单 | ADMIN / BUYER（`_PO_EXEC_ROLES`） | `/purchase-requisitions` |
| `PO_CONFIRM` | 待确认采购订单 | ADMIN / BUYER | `/purchase-orders?status=DRAFT` |
| `PO_RECEIVE` | 待收货入库 | ADMIN / BUYER / WAREHOUSE（`_PO_RECEIVE_TODO_ROLES`） | 能建入库单 → `/purchase-receipts/create`；否则 `/purchase-orders` |

> ⚠️ APPLICANT / DEPT_MANAGER 虽持 `po:view`（用于跟踪自己链路上的 PO），但**无收货执行职责**，
> 后端不向其输出 `PO_RECEIVE` 待办 —— 这是「待办 = 我可执行的动作」的语义，与 KPI 卡片
> 「我能看到多少待收货 PO」不同。

## 6. 动态区

- `GET /dashboard/recent-activities?limit=10`：`operation_logs` 中 `_RECENT_ACTIONS`
  关键业务动作（PR_CREATE/SUBMIT/APPROVE/REJECT/REVISE/CANCEL、PO_CREATE/CONFIRM/CANCEL、
  RECEIPT_POST/REVERSE），**不含 LOGIN/LOGIN_FAILED/主数据 CRUD/权限变更**；operator 取日志快照。
- `GET /dashboard/inventory-activities?limit=6`：`inventory_transactions` 最近 N 条，
  带符号 quantity（入库正、冲销负）；一次性批量解析 `source_id → receipt_no`（防 N+1）。
  权限门 `inventory_txn:view`。

## 7. 五角色可见性矩阵（summary 卡片 & 面板）

| 卡片/面板 | 权限 | ADMIN | APPLICANT | DEPT_MANAGER | BUYER | WAREHOUSE |
|-----------|------|:----:|:---------:|:------------:|:-----:|:---------:|
| 待审批 PR 卡 | `pr:view`+`pr:approve` | ✅ | – | ✅ | – | – |
| 待转 PO 卡 | `po:create` | ✅ | – | – | ✅ | – |
| 待确认 PO 卡 | `po:confirm` | ✅ | – | – | ✅ | – |
| 待收货 PO 卡 | `receipt:create` / BUYER | ✅ | – | – | ✅ | ✅ |
| 低库存 / 库存金额卡 | `inventory:view` | ✅ | ✅ | ✅ | ✅ | ✅ |
| PR 趋势面板 | `pr:view` | ✅ | ✅ | ✅ | ✅ | – |
| PO 状态面板 | `po:view` | ✅ | ✅ | ✅ | ✅ | ✅ |
| 待办面板 | 后端按角色收敛 | ✅ | 空 | ✅ | ✅ | ✅ |
| 最近库存动态 | `inventory_txn:view` | ✅ | ✅ | ✅ | ✅ | ✅ |

> 后端计数与卡片显隐是两件事：后端按权限门返回（无权限计 0），前端按上表权限显隐；
> APPLICANT 的 summary 中 `pending_pr_count=1`（自己那条 PENDING）但审批卡因无 `pr:approve` 不显示 ——
> 待办数为 0 且无卡片，符合「APPLICANT 无动作待办」。

## 8. 索引与迁移

`alembic check` 结果：**No new upgrade operations detected** —— Phase 11 不新增迁移。
Dashboard 查询全部命中既有索引：

| 查询 | 索引 |
|------|------|
| PR 按状态/范围 | `ix_pr_dept_status`、`ix_pr_applicant`、`ix_pr_status` |
| PR 趋势按日期 | `ix_pr_date` |
| PO 按状态/范围 | `ix_po_status`、`ix_po_buyer`、`ix_po_date` |
| 低库存 JOIN 策略 | `ix_ib_mat` + `(warehouse_id, material_id)` 策略唯一键 |
| 库存动态时间序 | `ix_it_time`、`ix_it_source`、`ix_it_wh_mat` |

## 9. 演示数据与一致性验证

```bash
# 1) 复位+重建业务故事（幂等，会清空业务链路/主数据后重放真实 API 链）
./.venv/Scripts/python.exe -m app.db.seed_demo

# 2) 后端口径验收（21 项）
./.venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q

# 3) 真实 uvicorn + curl 全量 E2E（五角色、口径一致性，见 smoke_ph11.sh）
bash smoke_ph11.sh

# 4) 前端单测 / 类型 / 构建
npm test && npm run typecheck && npm run build
```

seed 故事预期（admin）：待审批 PR=2、待转=2、待确认 PO=1、待收货 PO=1、
低库存=2、库存账面金额 `1190.00`；当日 PR 趋势 count=7、amount=`1910.00`。
