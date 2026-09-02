// ---- 业务模型（与 backend schemas 对齐；Decimal 字段一律 string）----

import type {
  ActiveStatus,
  ApprovalAction,
  DocumentType,
  PoStatus,
  PrStatus,
  ReceiptStatus,
  RoleCode,
  TxnSourceType,
  TxnType,
  UserStatus,
} from './enums'

// ---------- auth ----------
export interface CurrentUser {
  id: number
  username: string
  real_name: string
  role_id: number
  role_code: string
  role_name: string
  department_id: number | null
  department_name: string | null
  permissions: string[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

// ---------- 主数据 ----------
export interface Material {
  id: number
  material_code: string
  material_name: string
  category: string | null
  specification: string | null
  unit: string
  status: ActiveStatus
  remark: string | null
  created_at: string
  updated_at: string
}

export interface MaterialCreate {
  material_name: string
  category?: string | null
  specification?: string | null
  unit: string
  remark?: string | null
}

export interface Supplier {
  id: number
  supplier_code: string
  supplier_name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  address: string | null
  status: ActiveStatus
  remark: string | null
  created_at: string
  updated_at: string
}

export interface SupplierCreate {
  supplier_name: string
  contact_person?: string | null
  phone?: string | null
  email?: string | null
  address?: string | null
  remark?: string | null
}

export interface Warehouse {
  id: number
  warehouse_code: string
  warehouse_name: string
  status: ActiveStatus
  remark: string | null
  created_at: string
  updated_at: string
}

export interface WarehouseCreate {
  warehouse_name: string
  remark?: string | null
}

export interface InventoryPolicy {
  id: number
  warehouse_id: number
  material_id: number
  safety_stock: string
  min_stock: string | null
  reorder_point: string | null
  max_stock: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface InventoryPolicyCreate {
  warehouse_id: number
  material_id: number
  safety_stock: string | number
  reorder_point?: string | number | null
  max_stock?: string | number | null
  remark?: string | null
}

// ---------- PR ----------
export interface PrItem {
  id: number
  line_no: number
  material_id: number
  material_code: string | null
  material_name: string | null
  requested_quantity: string
  converted_quantity: string
  estimated_unit_price: string
  estimated_amount: string
  required_date: string | null
  remark: string | null
}

export interface PurchaseRequisition {
  id: number
  pr_no: string
  applicant_id: number
  applicant_name: string | null
  department_id: number
  department_name: string | null
  apply_date: string
  reason: string | null
  status: PrStatus
  total_estimated_amount: string
  submitted_at: string | null
  version: number
  remark: string | null
  created_at: string
  updated_at: string
  items?: PrItem[]
}

export interface PrItemDraft {
  id?: number | null
  material_id: number | null
  requested_quantity: string
  estimated_unit_price: string
  required_date: string | null
  remark: string | null
  // 展示用（服务端金额不可信，仅前端实时计算展示）
  material_code?: string | null
  material_name?: string | null
  unit?: string | null
}

export interface PrCreatePayload {
  apply_date?: string | null
  reason?: string | null
  items: { material_id: number; requested_quantity: string; estimated_unit_price: string; required_date?: string | null; remark?: string | null }[]
}

export interface PrUpdatePayload {
  version: number
  apply_date?: string | null
  reason?: string | null
  items: { id?: number | null; material_id: number; requested_quantity: string; estimated_unit_price: string; required_date?: string | null; remark?: string | null }[]
}

export interface ApprovalRecord {
  id: number
  document_type: DocumentType
  document_no: string | null
  step_name: string | null
  approver_id: number
  approver_name: string | null
  action: ApprovalAction
  from_status: string | null
  to_status: string | null
  comment: string | null
  created_at: string
}

// ---------- PO ----------
export interface PoSource {
  id: number
  pr_item_id: number
  quantity: string
  pr_no: string | null
  pr_item_line_no: number | null
  material_code: string | null
  material_name: string | null
}

export interface PoItem {
  id: number
  line_no: number
  material_id: number
  material_code: string | null
  material_name: string | null
  ordered_quantity: string
  received_quantity: string
  unit_price: string
  amount: string
  remark: string | null
  sources?: PoSource[]
}

export interface PurchaseOrder {
  id: number
  po_no: string
  supplier_id: number
  supplier_name: string | null
  buyer_id: number
  buyer_name: string | null
  order_date: string
  expected_date: string | null
  status: PoStatus
  total_amount: string
  version: number
  remark: string | null
  created_at: string
  updated_at: string
  items?: PoItem[]
}

/** 创建 PO 用的来源行：PR item 携带剩余可转数量 */
export interface PrSourceLine {
  pr_id: number
  pr_no: string
  pr_item_id: number
  pr_item_line_no: number
  material_id: number
  material_code: string
  material_name: string
  /** PR 明细总申请量 */
  requested_quantity: string
  /** 已转出量 */
  converted_quantity: string
  /** 剩余可转 = requested - converted */
  remaining: string
}

// ---------- Receipt ----------
export interface ReceiptItem {
  id: number
  line_no: number
  po_item_id: number
  material_id: number
  material_code: string | null
  material_name: string | null
  unit: string | null
  ordered_quantity: string | null
  received_quantity: string
  unit_price: string
  amount: string
  remark: string | null
}

export interface PurchaseReceipt {
  id: number
  receipt_no: string
  po_id: number
  po_no: string | null
  supplier_name: string | null
  warehouse_id: number
  warehouse_code: string | null
  warehouse_name: string | null
  received_by: number
  received_by_name: string | null
  received_at: string
  status: ReceiptStatus
  remark: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  reverse_reason: string | null
  created_at: string
  updated_at: string
  items?: ReceiptItem[]
}

/** 可收货 PO（CONFIRMED/PARTIALLY_RECEIVED）及其明细剩余量 */
export interface ReceivablePoItem {
  po_item_id: number
  material_id: number
  material_code: string
  material_name: string
  unit: string | null
  ordered_quantity: string
  received_quantity: string
  remaining: string
  unit_price: string
}

// ---------- Inventory ----------
export interface BalanceRow {
  warehouse_id: number
  warehouse_code: string
  warehouse_name: string
  material_id: number
  material_code: string
  material_name: string
  unit: string
  quantity: string
  average_unit_cost: string
  total_amount: string
  safety_stock: string | null
  is_below_safety_stock: boolean
  last_transaction_at: string | null
}

export interface Transaction {
  id: number
  txn_no: string
  transaction_type: TxnType
  warehouse_id: number
  warehouse_code: string | null
  warehouse_name: string | null
  material_id: number
  material_code: string | null
  material_name: string | null
  unit: string | null
  quantity: string
  unit_cost: string
  amount: string
  balance_after: string
  source_type: TxnSourceType | null
  source_id: number | null
  source_item_id: number | null
  reference_no: string | null
  reversed_transaction_id: number | null
  operator_id: number | null
  operator_name: string | null
  transaction_at: string
  remark: string | null
  created_at: string
}

// ---------- System ----------
export interface User {
  id: number
  username: string
  real_name: string
  email: string | null
  phone: string | null
  department_id: number | null
  department_name: string | null
  role_id: number
  role_code: string | null
  role_name: string | null
  status: UserStatus
  last_login_at: string | null
  created_at: string
}

export interface UserCreate {
  username: string
  password: string
  real_name: string
  email?: string | null
  phone?: string | null
  department_id?: number | null
  role_id: number
}

export interface Role {
  id: number
  role_code: RoleCode | string
  role_name: string
  description: string | null
  is_system: boolean
  status: ActiveStatus
  created_at: string
  permission_ids?: number[]
}

export interface Permission {
  id: number
  perm_code: string
  perm_name: string
  module: string
}

export interface Department {
  id: number
  dept_code: string
  dept_name: string
  parent_id: number | null
  sort_order: number
  status: ActiveStatus
  remark: string | null
  created_at: string
}
