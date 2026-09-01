# Manufacturing ERP Lite — ER 图

> 版本：v1.0 ｜ 日期：2026-09-01 ｜ 阶段：Phase 2
> 配套：[`docs/database-design.md`](./database-design.md)（完整字段定义）｜ [`docs/data-integrity-review.md`](./data-integrity-review.md)

---

## 图例

| 符号 | 含义 |
|---|---|
| `||--|{` | 一对多，右侧至少 1 条 |
| `||--o{` | 一对多，右侧可 0 条 |
| `||--o|` | 一对一，右侧可 0 条 |
| `}o--o{` | 多对多（经关联表） |
| `PK` | 主键 |
| `FK` | 外键 |
| `UK` | 唯一约束 |
| `(logical)` | **逻辑关联，非数据库外键**（多态引用，靠业务规则保证完整性） |

> 数量与金额统一 `DECIMAL(18,4)`，图中简写为 `decimal`。

---

## 1. 全局 ERD

```mermaid
erDiagram
    DEPARTMENTS ||--o{ DEPARTMENTS : "parent_id 自引用"
    DEPARTMENTS ||--o{ USERS : "employs"
    DEPARTMENTS ||--o{ DEPARTMENT_MANAGERS : "has managers"
    USERS ||--o{ DEPARTMENT_MANAGERS : "is manager of"
    ROLES ||--o{ USERS : "assigned to"
    ROLES ||--o{ ROLE_PERMISSIONS : "grants"
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : "granted by"

    MATERIALS ||--o{ INVENTORY_POLICIES : "stock policy"
    WAREHOUSES ||--o{ INVENTORY_POLICIES : "stock policy"

    USERS ||--o{ PURCHASE_REQUISITIONS : "applies"
    DEPARTMENTS ||--o{ PURCHASE_REQUISITIONS : "owns"
    PURCHASE_REQUISITIONS ||--|{ PURCHASE_REQUISITION_ITEMS : "contains"
    MATERIALS ||--o{ PURCHASE_REQUISITION_ITEMS : "requested"

    SUPPLIERS ||--o{ PURCHASE_ORDERS : "supplies"
    USERS ||--o{ PURCHASE_ORDERS : "buys"
    PURCHASE_ORDERS ||--|{ PURCHASE_ORDER_ITEMS : "contains"
    MATERIALS ||--o{ PURCHASE_ORDER_ITEMS : "ordered"

    PURCHASE_REQUISITION_ITEMS ||--o{ PURCHASE_ORDER_ITEM_SOURCES : "sourced from"
    PURCHASE_ORDER_ITEMS ||--o{ PURCHASE_ORDER_ITEM_SOURCES : "sources"

    PURCHASE_ORDERS ||--o{ PURCHASE_RECEIPTS : "receives"
    WAREHOUSES ||--o{ PURCHASE_RECEIPTS : "receives into"
    USERS ||--o{ PURCHASE_RECEIPTS : "received by"
    PURCHASE_RECEIPTS ||--|{ PURCHASE_RECEIPT_ITEMS : "contains"
    PURCHASE_ORDER_ITEMS ||--o{ PURCHASE_RECEIPT_ITEMS : "received against"
    MATERIALS ||--o{ PURCHASE_RECEIPT_ITEMS : "received"

    MATERIALS ||--o{ INVENTORY_BALANCES : "stocked"
    WAREHOUSES ||--o{ INVENTORY_BALANCES : "holds"
    MATERIALS ||--o{ INVENTORY_TRANSACTIONS : "moves"
    WAREHOUSES ||--o{ INVENTORY_TRANSACTIONS : "moves in"
    INVENTORY_TRANSACTIONS ||--o| INVENTORY_TRANSACTIONS : "reversed_transaction_id"

    PURCHASE_RECEIPTS ||--o{ INVENTORY_TRANSACTIONS : "source_id (logical)"
    PURCHASE_REQUISITIONS ||--o{ APPROVAL_RECORDS : "document_id (logical)"
    PURCHASE_ORDERS ||--o{ APPROVAL_RECORDS : "document_id (logical)"
    USERS ||--o{ APPROVAL_RECORDS : "approves"
    USERS ||--o{ OPERATION_LOGS : "operates"

    DEPARTMENTS {
        bigint id PK
        varchar dept_code UK
        varchar dept_name
        bigint parent_id FK
        enum status
    }
    USERS {
        bigint id PK
        varchar username UK
        varchar password_hash
        varchar real_name
        bigint department_id FK
        bigint role_id FK
        enum status
    }
    ROLES {
        bigint id PK
        varchar role_code UK
        tinyint is_system
    }
    PERMISSIONS {
        bigint id PK
        varchar perm_code UK
        varchar module
    }
    ROLE_PERMISSIONS {
        bigint id PK
        bigint role_id FK
        bigint permission_id FK
    }
    DEPARTMENT_MANAGERS {
        bigint id PK
        bigint dept_id FK
        bigint user_id FK
        tinyint is_primary
    }
    MATERIALS {
        bigint id PK
        varchar material_code UK
        varchar material_name
        varchar unit
        enum status
    }
    SUPPLIERS {
        bigint id PK
        varchar supplier_code UK
        varchar supplier_name
        enum status
    }
    WAREHOUSES {
        bigint id PK
        varchar warehouse_code UK
        varchar warehouse_name
        enum status
    }
    INVENTORY_POLICIES {
        bigint id PK
        bigint warehouse_id FK
        bigint material_id FK
        decimal safety_stock
    }
    PURCHASE_REQUISITIONS {
        bigint id PK
        varchar pr_no UK
        bigint applicant_id FK
        bigint department_id FK
        enum status
        decimal total_estimated_amount
    }
    PURCHASE_REQUISITION_ITEMS {
        bigint id PK
        bigint pr_id FK
        int line_no UK
        bigint material_id FK
        decimal requested_quantity
        decimal converted_quantity
        decimal estimated_unit_price
    }
    PURCHASE_ORDERS {
        bigint id PK
        varchar po_no UK
        bigint supplier_id FK
        bigint buyer_id FK
        enum status
        decimal total_amount
    }
    PURCHASE_ORDER_ITEMS {
        bigint id PK
        bigint po_id FK
        int line_no UK
        bigint material_id FK
        decimal ordered_quantity
        decimal received_quantity
        decimal unit_price
    }
    PURCHASE_ORDER_ITEM_SOURCES {
        bigint id PK
        bigint po_item_id FK
        bigint pr_item_id FK
        decimal quantity
    }
    PURCHASE_RECEIPTS {
        bigint id PK
        varchar receipt_no UK
        bigint po_id FK
        bigint warehouse_id FK
        bigint received_by FK
        enum status
        bigint reversed_by FK
    }
    PURCHASE_RECEIPT_ITEMS {
        bigint id PK
        bigint receipt_id FK
        bigint po_item_id FK
        bigint material_id FK
        decimal received_quantity
        decimal unit_price
    }
    INVENTORY_BALANCES {
        bigint id PK
        bigint warehouse_id FK
        bigint material_id FK
        decimal quantity
        decimal total_amount
        decimal average_unit_cost
        int version
    }
    INVENTORY_TRANSACTIONS {
        bigint id PK
        varchar txn_no UK
        enum transaction_type
        bigint warehouse_id FK
        bigint material_id FK
        decimal quantity
        decimal unit_cost
        decimal balance_after
        enum source_type
        bigint source_id
        bigint reversed_transaction_id FK
    }
    APPROVAL_RECORDS {
        bigint id PK
        enum document_type
        bigint document_id
        smallint step_no
        bigint approver_id FK
        enum action
        varchar result_status
        varchar comment
    }
    NUMBER_SEQUENCES {
        bigint id PK
        varchar sequence_key UK
        date sequence_date UK
        bigint current_value
    }
    OPERATION_LOGS {
        bigint id PK
        bigint operator_id FK
        varchar username_snapshot
        enum action
        varchar module
        bigint document_id
        varchar ip_address
    }
```

---

## 2. 局部 ERD：PR → PO → Receipt → Inventory

业务主干全链路，重点标注数量字段的流转与约束。

```mermaid
erDiagram
    MATERIALS ||--o{ PURCHASE_REQUISITION_ITEMS : "requested"
    PURCHASE_REQUISITIONS ||--|{ PURCHASE_REQUISITION_ITEMS : "contains"

    PURCHASE_REQUISITION_ITEMS ||--o{ PURCHASE_ORDER_ITEM_SOURCES : "拆单 N:N"
    PURCHASE_ORDER_ITEM_SOURCES }o--|| PURCHASE_ORDER_ITEMS : "合单 N:1"

    PURCHASE_ORDERS ||--|{ PURCHASE_ORDER_ITEMS : "contains"
    PURCHASE_ORDERS ||--o{ PURCHASE_RECEIPTS : "receives"
    PURCHASE_RECEIPTS ||--|{ PURCHASE_RECEIPT_ITEMS : "contains"
    PURCHASE_ORDER_ITEMS ||--o{ PURCHASE_RECEIPT_ITEMS : "received against"

    PURCHASE_RECEIPT_ITEMS ||--|| INVENTORY_TRANSACTIONS : "1:1 生成流水"
    INVENTORY_TRANSACTIONS ||--o| INVENTORY_TRANSACTIONS : "reversed_transaction_id"
    INVENTORY_TRANSACTIONS ||--|| INVENTORY_BALANCES : "汇总更新"

    MATERIALS ||--o{ INVENTORY_BALANCES : "stocked"
    WAREHOUSES ||--o{ INVENTORY_BALANCES : "holds"
    MATERIALS ||--o{ INVENTORY_TRANSACTIONS : "moves"
    WAREHOUSES ||--o{ INVENTORY_TRANSACTIONS : "moves in"
    MATERIALS ||--o{ INVENTORY_POLICIES : "safety stock"

    PURCHASE_REQUISITIONS {
        bigint id PK
        varchar pr_no UK "PR-20260901-0001"
        bigint applicant_id FK
        bigint department_id FK "部门快照"
        date apply_date
        enum status "DRAFT PENDING APPROVED REJECTED CANCELLED CONVERTED"
        decimal total_estimated_amount
    }
    PURCHASE_REQUISITION_ITEMS {
        bigint id PK
        bigint pr_id FK
        int line_no UK
        bigint material_id FK
        decimal requested_quantity "CK > 0"
        decimal converted_quantity "CK 0 <= x <= requested"
        decimal estimated_unit_price "可为 0"
        decimal estimated_amount "生成列"
        date required_date
    }
    PURCHASE_ORDER_ITEM_SOURCES {
        bigint id PK
        bigint po_item_id FK "UK(po_item_id, pr_item_id)"
        bigint pr_item_id FK "RESTRICT 防孤儿"
        decimal quantity "CK > 0"
    }
    PURCHASE_ORDERS {
        bigint id PK
        varchar po_no UK "PO-20260901-0001"
        bigint supplier_id FK "必填"
        bigint buyer_id FK
        date order_date
        date expected_date
        enum status "DRAFT CONFIRMED PARTIALLY_RECEIVED RECEIVED CANCELLED"
        decimal total_amount
    }
    PURCHASE_ORDER_ITEMS {
        bigint id PK
        bigint po_id FK
        int line_no UK
        bigint material_id FK
        decimal ordered_quantity "CK > 0"
        decimal received_quantity "CK 0 <= x <= ordered  CAS 更新"
        decimal unit_price "CK >= 0，confirm 时校验 > 0"
        decimal amount "生成列"
    }
    PURCHASE_RECEIPTS {
        bigint id PK
        varchar receipt_no UK "REC-20260901-0001"
        bigint po_id FK
        bigint warehouse_id FK
        bigint received_by FK
        datetime received_at
        enum status "POSTED REVERSED"
        bigint reversed_by FK
        datetime reversed_at
        varchar reverse_reason "冲销必填"
    }
    PURCHASE_RECEIPT_ITEMS {
        bigint id PK
        bigint receipt_id FK
        bigint po_item_id FK "UK(receipt_id, po_item_id)"
        int line_no UK
        bigint material_id FK
        decimal received_quantity "CK > 0"
        decimal unit_price "成本快照"
        decimal amount "生成列"
    }
    INVENTORY_TRANSACTIONS {
        bigint id PK
        varchar txn_no UK "TXN-20260901-000001"
        enum transaction_type "带符号：IN为正 OUT为负"
        bigint warehouse_id FK
        bigint material_id FK
        decimal quantity "CK 符号与类型一致"
        decimal unit_cost
        decimal amount
        decimal balance_after "流水后余额快照"
        enum source_type "PURCHASE_RECEIPT 等"
        bigint source_id "logical FK"
        bigint reversed_transaction_id FK "指向被冲销流水"
        datetime transaction_at
    }
    INVENTORY_BALANCES {
        bigint id PK
        bigint warehouse_id FK "UK(warehouse_id, material_id)"
        bigint material_id FK
        decimal quantity "CK >= 0 禁止负库存"
        decimal total_amount "权威金额"
        decimal average_unit_cost "移动加权平均"
        int version "乐观锁"
    }
    INVENTORY_POLICIES {
        bigint id PK
        bigint warehouse_id FK "UK(warehouse_id, material_id)"
        bigint material_id FK
        decimal safety_stock
        decimal min_stock
        decimal max_stock
        decimal reorder_point
    }
    MATERIALS {
        bigint id PK
        varchar material_code UK "MAT-000001"
        varchar material_name
        varchar unit
    }
    WAREHOUSES {
        bigint id PK
        varchar warehouse_code UK "WH-000001"
        varchar warehouse_name
    }
```

### 数量流转不变量

```
pr_item.converted_quantity
    == SUM(po_item_sources.quantity)          按 pr_item_id，排除 CANCELLED PO
    <= pr_item.requested_quantity              DB CHECK

po_item.received_quantity
    == SUM(receipt_items.received_quantity)   按 po_item_id，排除 REVERSED receipt
    <= po_item.ordered_quantity                DB CHECK + CAS

inventory_balance.quantity
    == SUM(inventory_transactions.quantity)   按 (warehouse_id, material_id)
```

---

## 3. 局部 ERD：用户 / 部门 / RBAC

```mermaid
erDiagram
    DEPARTMENTS ||--o{ DEPARTMENTS : "parent_id 自引用"
    DEPARTMENTS ||--o{ USERS : "employs"
    DEPARTMENTS ||--o{ DEPARTMENT_MANAGERS : "has"
    USERS ||--o{ DEPARTMENT_MANAGERS : "manages"
    ROLES ||--o{ USERS : "assigned"
    ROLES ||--o{ ROLE_PERMISSIONS : "grants"
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : "belongs to"
    USERS ||--o{ OPERATION_LOGS : "operates"
    USERS ||--o{ APPROVAL_RECORDS : "approves"

    DEPARTMENTS {
        bigint id PK
        varchar dept_code UK "RD / PUR / WH"
        varchar dept_name "研发部 采购部 仓库"
        bigint parent_id FK
        int sort_order
        enum status "ACTIVE INACTIVE"
    }
    USERS {
        bigint id PK
        varchar username UK "admin rd001 buyer001"
        varchar password_hash "bcrypt"
        varchar real_name
        varchar email
        varchar phone
        bigint department_id FK "RESTRICT"
        bigint role_id FK "v1 单角色"
        enum status "ACTIVE DISABLED"
        datetime last_login_at
    }
    ROLES {
        bigint id PK
        varchar role_code UK "ADMIN APPLICANT DEPT_MANAGER BUYER WAREHOUSE"
        varchar role_name "系统管理员 申请人 部门主管 采购员 仓库管理员"
        varchar description
        tinyint is_system "1 内置不可删"
        enum status
    }
    PERMISSIONS {
        bigint id PK
        varchar perm_code UK "pr:approve po:confirm"
        varchar perm_name
        varchar module "material supplier pr po receipt"
    }
    ROLE_PERMISSIONS {
        bigint id PK
        bigint role_id FK "UK(role_id, permission_id)"
        bigint permission_id FK
    }
    DEPARTMENT_MANAGERS {
        bigint id PK
        bigint dept_id FK "UK(dept_id, user_id)"
        bigint user_id FK
        tinyint is_primary "主主管"
        datetime created_at
    }
    APPROVAL_RECORDS {
        bigint id PK
        enum document_type "PURCHASE_REQUISITION PURCHASE_ORDER"
        bigint document_id "logical，非 FK"
        smallint step_no "v1 恒为 1，预留多级"
        varchar step_name "部门主管审批"
        bigint approver_id FK
        enum action "SUBMIT APPROVE REJECT CANCEL"
        varchar result_status
        varchar comment "驳回必填"
        datetime created_at
    }
    OPERATION_LOGS {
        bigint id PK
        bigint operator_id FK "SET NULL 兜底"
        varchar username_snapshot
        enum action "LOGIN PR_APPROVE RECEIPT_POST 等 11 类"
        varchar module
        varchar document_type
        bigint document_id
        varchar description
        varchar ip_address
        varchar request_id
        datetime created_at
    }
```

### 权限校验两层模型

```mermaid
flowchart LR
    A["HTTP 请求"] --> B{"① 接口层<br/>require_perm<br/>pr:approve"}
    B -->|"无权限"| C["403 FORBIDDEN"]
    B -->|"有权限"| D{"② 业务层<br/>数据级校验"}
    D -->|"非本部门主管"| C
    D -->|"通过"| E["执行审批"]
```

**审批人判定 SQL（不写死 user_id）**：

```sql
SELECT 1
FROM department_managers dm
JOIN users u ON u.id = :applicant_id
WHERE dm.dept_id = u.department_id
  AND dm.user_id = :current_user_id
LIMIT 1;
```

| 层 | 校验内容 | 数据来源 |
|---|---|---|
| ① 接口层 | 是否拥有 `pr:approve` 权限 | `users.role_id → role_permissions → permissions` |
| ② 业务层 | 是否为申请人所在部门的主管 | `department_managers` 表 |

> 两层缺一不可：接口层拦不住"有权限但不是本部门主管"，业务层拦不住"完全无权限的用户"。

---

## 4. 附录：单据状态机

### 4.1 采购申请 PR

```mermaid
stateDiagram-v2
    [*] --> DRAFT : 创建
    DRAFT --> PENDING : submit 提交
    DRAFT --> CANCELLED : cancel 取消
    PENDING --> APPROVED : approve 主管批准
    PENDING --> REJECTED : reject 主管驳回
    PENDING --> CANCELLED : cancel 申请人撤回
    REJECTED --> DRAFT : 重新编辑 (Q1)
    APPROVED --> CONVERTED : 全部明细转完
    APPROVED --> CANCELLED : cancel 无有效 PO 时 (Q2)
    CONVERTED --> [*]
    CANCELLED --> [*]
```

> `REJECTED` **不能**直接到 `PENDING`，必须先回 `DRAFT` 再提交（Q1）。

### 4.2 采购订单 PO

```mermaid
stateDiagram-v2
    [*] --> DRAFT : 由 APPROVED PR 转换创建
    DRAFT --> CONFIRMED : confirm 确认下单
    DRAFT --> CANCELLED : cancel
    CONFIRMED --> PARTIALLY_RECEIVED : 部分入库
    CONFIRMED --> RECEIVED : 一次收齐
    CONFIRMED --> CANCELLED : cancel 累计收货=0
    PARTIALLY_RECEIVED --> PARTIALLY_RECEIVED : 继续部分入库
    PARTIALLY_RECEIVED --> RECEIVED : 收齐剩余
    RECEIVED --> [*]
    CANCELLED --> [*]
```

状态重算规则：

| 条件 | 状态 |
|---|---|
| 所有 Item `received_quantity = 0` 且已确认 | `CONFIRMED` |
| 至少一行 `> 0` 且存在未收齐 | `PARTIALLY_RECEIVED` |
| 所有 Item 全部收齐 | `RECEIVED` |

### 4.3 采购入库单 Receipt

```mermaid
stateDiagram-v2
    [*] --> POSTED : 事务内创建并过账
    POSTED --> REVERSED : reverse 冲销
    REVERSED --> [*]
```

> 无 `DRAFT` 状态：入库是实物操作，创建即生效。无删除路径，只能冲销。

### 4.4 冲销数据流

```mermaid
flowchart TD
    A["原始入库单 REC-001<br/>status = POSTED"] --> B["原始流水 TXN-001<br/>type = PURCHASE_IN<br/>quantity = +40"]
    B --> C["库存余额<br/>quantity = +40"]

    D["冲销操作"] --> E["冲销流水 TXN-002<br/>type = PURCHASE_IN_REVERSAL<br/>quantity = -40<br/>reversed_transaction_id = TXN-001"]
    E --> F["余额回退<br/>quantity = -40"]
    D --> G["入库单 REC-001<br/>status = REVERSED"]
    D --> H["PO received_quantity 回退<br/>重算 PO 状态"]

    style B fill:#E1F5EE,stroke:#0F6E56
    style E fill:#FCEBEB,stroke:#A32D2D
```

**三条铁律**：

1. ` PURCHASE_IN_REVERSAL` **不得**用 `ADJUST_OUT` 代替 —— 独立枚举保证业务语义可追溯
2. 原始流水 **禁止** UPDATE / DELETE（append-only 触发器强制）
3. 原始入库单只改状态为 `REVERSED`，**不删除**

---

## 5. 表关系速查

| 父表 | 子表 | 关系 | FK 删除策略 |
|---|---|---|---|
| `departments` | `departments` | 1:N 自引用 | RESTRICT |
| `departments` | `users` | 1:N | RESTRICT |
| `departments` | `department_managers` | 1:N | CASCADE |
| `users` | `department_managers` | 1:N | CASCADE |
| `roles` | `users` | 1:N | RESTRICT |
| `roles` | `role_permissions` | 1:N | CASCADE |
| `permissions` | `role_permissions` | 1:N | CASCADE |
| `materials` | `inventory_policies` | 1:N | CASCADE |
| `warehouses` | `inventory_policies` | 1:N | CASCADE |
| `materials` / `warehouses` | `inventory_balances` | 1:1（联合唯一） | RESTRICT |
| `materials` / `warehouses` | `inventory_transactions` | 1:N | RESTRICT |
| `purchase_requisitions` | `purchase_requisition_items` | 1:N | CASCADE |
| `purchase_orders` | `purchase_order_items` | 1:N | CASCADE |
| `purchase_order_items` | `purchase_order_item_sources` | 1:N | CASCADE |
| `purchase_requisition_items` | `purchase_order_item_sources` | 1:N | **RESTRICT**（防孤儿） |
| `purchase_receipts` | `purchase_receipt_items` | 1:N | CASCADE |
| `purchase_order_items` | `purchase_receipt_items` | 1:N | RESTRICT |
| `inventory_transactions` | `inventory_transactions` | 1:1 自引用（冲销） | RESTRICT |
| `users` | `operation_logs` | 1:N | SET NULL |
| `users` | `approval_records` | 1:N | RESTRICT |

**逻辑关联（非 FK）**：

| 来源表 | 字段 | 指向 | 完整性保证 |
|---|---|---|---|
| `inventory_transactions` | `source_type` + `source_id` | `purchase_receipts` 等 | 源单据禁止物理删除 |
| `approval_records` | `document_type` + `document_id` | PR / PO | 单据进入 PENDING 后禁止物理删除 |
| `operation_logs` | `document_type` + `document_id` | 各类单据 | 日志为历史快照，允许悬空 |

---

*文档结束。Review 通过后进入 Phase 3。*
