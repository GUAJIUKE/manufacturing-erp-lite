// ---- 状态 → 标签/颜色 集中映射（全站唯一权威，禁止页面各自判断）----

import type {
  ActiveStatus,
  PoStatus,
  PrStatus,
  ReceiptStatus,
  RoleCode,
  TxnType,
  UserStatus,
} from '@/types/enums'

export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

export interface StatusMeta {
  label: string
  type: TagType
}

// PR
const PR_STATUS: Record<PrStatus, StatusMeta> = {
  DRAFT: { label: '草稿', type: 'info' },
  PENDING: { label: '待审批', type: 'warning' },
  APPROVED: { label: '已批准', type: 'success' },
  REJECTED: { label: '已驳回', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' },
  CONVERTED: { label: '已转PO', type: 'primary' },
}

// PO
const PO_STATUS: Record<PoStatus, StatusMeta> = {
  DRAFT: { label: '草稿', type: 'info' },
  CONFIRMED: { label: '已确认', type: 'primary' },
  PARTIALLY_RECEIVED: { label: '部分收货', type: 'warning' },
  RECEIVED: { label: '已收完', type: 'success' },
  CANCELLED: { label: '已取消', type: 'info' },
}

// Receipt
const RECEIPT_STATUS: Record<ReceiptStatus, StatusMeta> = {
  POSTED: { label: '已过账', type: 'success' },
  REVERSED: { label: '已冲销', type: 'danger' },
}

// 主数据 / 用户
const ACTIVE_STATUS: Record<ActiveStatus, StatusMeta> = {
  ACTIVE: { label: '启用', type: 'success' },
  DISABLED: { label: '停用', type: 'info' },
}

const USER_STATUS: Record<UserStatus, StatusMeta> = {
  ACTIVE: { label: '启用', type: 'success' },
  DISABLED: { label: '停用', type: 'danger' },
}

// 流水类型（库存流水颜色）
const TXN_TYPE: Record<TxnType, StatusMeta> = {
  PURCHASE_IN: { label: '采购入库', type: 'success' },
  PURCHASE_IN_REVERSAL: { label: '入库冲销', type: 'danger' },
  ADJUST_IN: { label: '调整入库', type: 'primary' },
  ADJUST_OUT: { label: '调整出库', type: 'warning' },
  PRODUCTION_OUT: { label: '生产领料', type: 'warning' },
  PRODUCTION_IN: { label: '生产入库', type: 'success' },
}

const ROLE_CODE: Record<RoleCode, string> = {
  ADMIN: '系统管理员',
  APPLICANT: '采购申请人',
  DEPT_MANAGER: '部门主管',
  BUYER: '采购员',
  WAREHOUSE: '仓库管理员',
}

export function prStatusMeta(s: PrStatus | string): StatusMeta {
  return PR_STATUS[s as PrStatus] ?? { label: s, type: 'info' }
}
export function poStatusMeta(s: PoStatus | string): StatusMeta {
  return PO_STATUS[s as PoStatus] ?? { label: s, type: 'info' }
}
export function receiptStatusMeta(s: ReceiptStatus | string): StatusMeta {
  return RECEIPT_STATUS[s as ReceiptStatus] ?? { label: s, type: 'info' }
}
export function activeStatusMeta(s: ActiveStatus | string): StatusMeta {
  return ACTIVE_STATUS[s as ActiveStatus] ?? { label: s, type: 'info' }
}
export function userStatusMeta(s: UserStatus | string): StatusMeta {
  return USER_STATUS[s as UserStatus] ?? { label: s, type: 'info' }
}
export function txnTypeMeta(s: TxnType | string): StatusMeta {
  return TXN_TYPE[s as TxnType] ?? { label: s, type: 'info' }
}
export function roleCodeLabel(code: RoleCode | string): string {
  return ROLE_CODE[code as RoleCode] ?? code
}
