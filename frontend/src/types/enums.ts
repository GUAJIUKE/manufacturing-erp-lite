// ---- 后端状态枚举（与 backend/app/utils/enums.py 一致）----

export type ActiveStatus = 'ACTIVE' | 'DISABLED'
export type DeptStatus = 'ACTIVE' | 'INACTIVE'
export type UserStatus = 'ACTIVE' | 'DISABLED'

export type PrStatus =
  | 'DRAFT'
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'CANCELLED'
  | 'CONVERTED'

export type PoStatus =
  | 'DRAFT'
  | 'CONFIRMED'
  | 'PARTIALLY_RECEIVED'
  | 'RECEIVED'
  | 'CANCELLED'

export type ReceiptStatus = 'POSTED' | 'REVERSED'

export type TxnType =
  | 'PURCHASE_IN'
  | 'PURCHASE_IN_REVERSAL'
  | 'ADJUST_IN'
  | 'ADJUST_OUT'
  | 'PRODUCTION_OUT'
  | 'PRODUCTION_IN'

export type TxnSourceType =
  | 'PURCHASE_RECEIPT'
  | 'PURCHASE_RECEIPT_REVERSAL'
  | 'MANUAL_ADJUST'
  | 'PRODUCTION_ISSUE'
  | 'PRODUCTION_RECEIPT'

export type ApprovalAction =
  | 'SUBMIT'
  | 'APPROVE'
  | 'REJECT'
  | 'CANCEL'

export type DocumentType = 'PURCHASE_REQUISITION' | 'PURCHASE_ORDER'

export type RoleCode =
  | 'ADMIN'
  | 'APPLICANT'
  | 'DEPT_MANAGER'
  | 'BUYER'
  | 'WAREHOUSE'

/** 主数据启停（ACTIVE/DISABLED 通用表） */
export type EntityActive = 'ACTIVE' | 'DISABLED'
