// ---- Dashboard 纯映射工具（可单测；视图只消费这些映射，不自行判断）----

import type { LocationQueryRaw } from 'vue-router'

export const TODO_TYPES = ['PR_APPROVAL', 'PR_TO_PO', 'PO_CONFIRM', 'PO_RECEIVE'] as const
export type TodoType = (typeof TODO_TYPES)[number]

/** 待办 → 展示文案（type 与后端 dashboard_service 输出一一对应） */
export const TODO_LABEL: Record<TodoType, string> = {
  PR_APPROVAL: '待审批采购申请',
  PR_TO_PO: '待转采购订单',
  PO_CONFIRM: '待确认采购订单',
  PO_RECEIVE: '待收货入库',
}

export function todoLabel(type: string): string {
  return TODO_LABEL[type as TodoType] ?? type
}

export interface DrillTarget {
  path: string
  query?: LocationQueryRaw
}

/**
 * 待办 → 下钻目标。
 * - PR_TO_PO：转 PO 动作发生在 PR 列表页（已批准行上）→ PR 列表
 * - PO_RECEIVE：能建入库单（WAREHOUSE/ADMIN）→ 入库登记页；否则 → PO 列表
 */
export function todoRoute(type: string, opts: { canCreateReceipt: boolean }): DrillTarget {
  switch (type as TodoType) {
    case 'PR_APPROVAL':
      return { path: '/approvals' }
    case 'PR_TO_PO':
      return { path: '/purchase-requisitions' }
    case 'PO_CONFIRM':
      return { path: '/purchase-orders', query: { status: 'DRAFT' } }
    case 'PO_RECEIVE':
      return opts.canCreateReceipt
        ? { path: '/purchase-receipts/create' }
        : { path: '/purchase-orders' }
    default:
      return { path: '/dashboard' }
  }
}

/** 最近动态 action → 中文动作文案（后端 _RECENT_ACTIONS 全量覆盖） */
export const ACTION_LABEL: Record<string, string> = {
  PR_CREATE: '新建采购申请',
  PR_SUBMIT: '提交审批',
  PR_APPROVE: '审批通过',
  PR_REJECT: '驳回申请',
  PR_REVISE: '重新编辑',
  PR_CANCEL: '取消申请',
  PO_CREATE: '创建采购订单',
  PO_CONFIRM: '确认采购订单',
  PO_CANCEL: '取消采购订单',
  RECEIPT_POST: '入库过账',
  RECEIPT_REVERSE: '入库冲销',
}

export function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action
}
