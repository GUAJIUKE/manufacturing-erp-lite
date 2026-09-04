# 业务流程与状态机（Business Flow & State Machines）

> 完整说明核心业务链与三套单据状态机：**为什么存在这些状态、哪些操作在哪些状态合法**。
> 代码事实来源：`backend/app/utils/enums.py` + 各 Service 的 `_TRANSITIONS` 与
> `recompute_po_status`；所有转换均由 Service 层白名单强制，API/Schema 无法直接改状态。

---

## 1. 核心业务链总览

```
申请人           主管              采购员              仓库管理员
┌─────────┐   ┌──────────┐   ┌─────────────┐   ┌──────────────────┐
│ 创建 PR  │──▶│ 提交审批  │──▶│ 审批通过     │──▶│ 转采购订单 PO     │
│ DRAFT   │   │ PENDING  │   │ APPROVED    │   │ DRAFT            │
└─────────┘   └──────────┘   └─────────────┘   └────────┬─────────┘
       ▲                                ▲              │ 确认
       │ revise（驳回后修订）           │ 取消           ▼
       ▼                                │         CONFIRMED
   REJECTED ◀──── 驳回 ──── PENDING ────┘              │
                                                        ▼ 收货（可分批）
                                            PARTIALLY_RECEIVED ──▶ RECEIVED
                                                        │
                                                        ▼
                                          Inventory Transaction（流水）
                                                        │
                                                        ▼
                                          Inventory Balance（余额）
```

典型故事：采购 100 件 → 收 40 → `PARTIALLY_RECEIVED` → 收 60 → `RECEIVED`；
入库单可整单冲销（`POSTED → REVERSED`），PO 状态由明细数量**重新推导**回退。

## 2. 采购申请 PR（Purchase Requisition）

### 2.1 状态

| 状态 | 含义 | 谁到达 | 说明 |
|---|---|---|---|
| `DRAFT` | 草稿 | 创建时 | 唯一可自由编辑的状态；提交后不可再改 |
| `PENDING` | 待审批 | 申请人提交 | 已进入审批流，内容冻结 |
| `APPROVED` | 已批准 | 主管/ADMIN 审批通过 | 可被转成采购订单（唯一可转状态） |
| `REJECTED` | 已驳回 | 主管/ADMIN 驳回 | 只能走 `revise` 回到 DRAFT 修改后重新提交，**不能直接改回 PENDING** |
| `CONVERTED` | 已全部转单 | PO 创建流程原子判定 | 所有明细 `converted_quantity == requested_quantity` 时由系统置位 |
| `CANCELLED` | 已取消 | DRAFT 或 APPROVED 时取消 | 终态 |

### 2.2 合法流转（`_TRANSITIONS`，真实代码）

```
DRAFT    → {PENDING, CANCELLED}
PENDING  → {APPROVED, REJECTED}
REJECTED → {DRAFT}                    # revise：驳回后回到草稿重新编辑
APPROVED → {CANCELLED}                # Q2：批准后若需求取消仍可取消（未转单前）
```

不在表中的流转一律拒绝（`4002 PR_INVALID_STATUS_TRANSITION`），例如：
`PENDING → DRAFT`（提交后内容冻结）、`PENDING → CANCELLED`（审批中不允许撤回）、
`REJECTED → PENDING`（必须经 DRAFT 修订再提）、`CONVERTED/CANCELLED → 任何状态`。

### 2.3 关键操作约束

| 操作 | 允许者 | 状态前提 | 要点 |
|---|---|---|---|
| create | 申请人本人 | — | 部门必须 ACTIVE；物料 ACTIVE；金额服务端重算 |
| update | 申请人本人/ADMIN | DRAFT | 乐观锁 `version` 必须匹配 |
| submit | 申请人本人/ADMIN | DRAFT | 提交后冻结内容 |
| cancel | 申请人本人/ADMIN | DRAFT、APPROVED | APPROVED 取消是为了「需求取消」场景（Q2） |
| approve | 申请部门主管/ADMIN | PENDING | 对象级：必须是 `department_managers` 中该部门主管 |
| reject | 同上 | PENDING | 驳回意见必填 |
| revise | 申请人本人/ADMIN | REJECTED | 回到 DRAFT，`version` 续用 |

> 状态为什么存在：`PENDING` 冻结内容，保证审批人与申请人看到同一版本；
> `REJECTED` 单独成态而不是直接回 DRAFT，是为了在审批记录里留下「驳回 → 修订 →
> 重提」的完整轨迹（`approval_records` 允许同一单据多轮，每轮都是合法历史）。

## 3. 审批（Approval）

- 审批人认定：查 `department_managers`（dept_id ↔ user_id），**不写死** user_id，
  支持一部门多主管、一主管多部门；ADMIN 可越权审批，审计中显式标注
  `is_admin_override`（`step_name`/描述里体现）。
- 申请部门停用（INACTIVE/DISABLED）→ 拒绝审批；账号禁用 → 拒绝。
- 审批记录表 `approval_records`：document_type + document_id + 动作 +
  from_status/to_status + 意见 + 审批人。step_no 恒为 1（v1 单级），字段为多级预留。
- 并发保护：approve/reject 均带 `version` 条件更新；两个主管同时操作同一 PR，
  只有一人成功（另一个收到 `4012 PR_ALREADY_PROCESSED`）。

## 4. 采购订单 PO（Purchase Order）

### 4.1 状态

| 状态 | 含义 | 谁到达 |
|---|---|---|
| `DRAFT` | 草稿（已从 PR 转出但未向供应商下单） | PO 创建时；此时单价可为 0 暂存 |
| `CONFIRMED` | 已确认（已向供应商下单） | 采购员确认；确认时强制每行 `unit_price > 0` |
| `PARTIALLY_RECEIVED` | 部分到货 | 收货流程推导 |
| `RECEIVED` | 全部到货 | 收货流程推导 |
| `CANCELLED` | 已取消 | DRAFT/CONFIRMED 取消；终态 |

### 4.2 合法流转

```
DRAFT    → {CONFIRMED, CANCELLED}
CONFIRMED → {CANCELLED}
# PARTIALLY_RECEIVED / RECEIVED 不在此表——它们由收货/冲销后
# recompute_po_status 依据明细 received_quantity 推导（见下），
# 人工无法直接把 PO 置为这两个状态。
```

`recompute_po_status` 推导逻辑（收货与冲销后都执行，从不硬编码）：

```
全部明细 received == 0                → CONFIRMED
全部明细 received == ordered          → RECEIVED
否则（部分收、或冲销后回到部分）      → PARTIALLY_RECEIVED
```

因此冲销最后一笔收货时，PO 会从 `RECEIVED → PARTIALLY_RECEIVED → CONFIRMED`
正确回退——这是「状态由数据推导」而非「记住上一个状态」的价值。

### 4.3 关键操作约束

| 操作 | 允许者 | 状态前提 | 要点 |
|---|---|---|---|
| create（转单） | BUYER | 来源 PR 必须 APPROVED | 来源数量合计必须**严格等于**订购数量（`PO_SOURCE_QUANTITY_MISMATCH`）；CAS 更新 PR 明细 `converted_quantity` 防超转 |
| confirm | 创建该 PO 的 BUYER/ADMIN | DRAFT | 乐观锁 + 每行单价 > 0 |
| cancel | 同上 | DRAFT/CONFIRMED | **整单未收货**才能取消（R14）；取消后回退 sources 的 `converted_quantity`，PR 不再全转则回退 APPROVED |
| receive | WAREHOUSE | CONFIRMED/PARTIALLY_RECEIVED | 见入库节 |

## 5. 采购入库 Receipt

| 状态 | 含义 | 说明 |
|---|---|---|
| `POSTED` | 已过账 | **创建即过账，无 DRAFT**：实物收货不可逆，阶段一不做暂存 |
| `REVERSED` | 已冲销 | 整单冲销，终态 |

操作约束：

- 收货（receive）：只能对 `CONFIRMED / PARTIALLY_RECEIVED` 的 PO；仓库与物料必须
  ACTIVE；同一入库单内不允许重复引用同一 PO 明细；`received_quantity` CAS
  （`received_quantity + qty <= ordered_quantity`），超收即拒绝（`6002`）。
- 冲销（reverse）：只能对 `POSTED` 的入库单；**整单**冲销（不支持部分行）；
  原因必填；按**原始流水金额**回滚；防止并发双冲（状态翻转先原子 claim +
  `reversed_transaction_id` 存在性检查）。已冲销的入库单再冲 → `6005/6006` 域错误。

> 冲销为什么不做部分行：阶段一业务语义「错了就整单撤销重录」，部分行冲销需要
> 拆行重算 PO 状态，复杂度和出错率不成比例（见 docs/transaction.md 的取舍说明）。

## 6. 为什么状态机值得单独设计（面试要点）

1. **把「非法操作」变成数据库/服务层事实**，而不是前端按钮隐藏——任何人绕过前端
   直接调 API，同样被 Service 拒绝。
2. **状态 = 授权前提的一部分**：`APPROVED` 才能转单、`PENDING` 才能批、
   `CONFIRMED/PARTIALLY_RECEIVED` 才能收——状态机与 RBAC、对象级权限三者叠加，
   才是完整的「这步能不能做」判定（见 docs/rbac.md）。
3. **可审计**：每步流转都写 `approval_records`/`audit_logs`，含 from/to 状态，
   历史可回放。
4. **推导优于记忆**：PO 状态由明细数量推导（recompute），冲销场景自动回退，
   不存在「状态与数据不一致」的陈旧状态问题。
