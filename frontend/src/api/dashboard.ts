// ---- Dashboard API（与 backend/app/schemas/dashboard.py 对齐）----
// 约定：所有统计均由后端 SQL 聚合；金额/数量为 Decimal-as-string，
// 前端只负责展示格式化（formatMoney/formatQuantity），绝不参与业务求和。

import { http } from './request'
import type { PoStatus, TxnType } from '@/types/enums'

/** 首页 KPI（角色感知：无权限的指标后端返回 0，前端按权限隐藏卡片） */
export interface DashboardSummary {
  pending_pr_count: number
  pending_purchase_count: number
  draft_po_count: number
  pending_po_count: number
  low_stock_count: number
  inventory_total_amount: string
}

/** PR 趋势单日点（apply_date 口径，缺日后端补 0） */
export interface TrendPoint {
  date: string
  count: number
  amount: string
}

/** PO 状态分布（含 count=0 的全部定义状态） */
export interface StatusCount {
  status: PoStatus
  count: number
}

/** 低库存预警行（缺口 = safety_stock - quantity） */
export interface LowStockRow {
  warehouse_id: number
  warehouse_code: string
  warehouse_name: string
  material_id: number
  material_code: string
  material_name: string
  unit: string
  quantity: string
  safety_stock: string
  shortage_quantity: string
}

/** 待办项（后端只给 type + count，label/跳转由前端映射） */
export interface TodoItem {
  type: string
  count: number
}

/** 最近采购动态（operation_logs 关键业务动作） */
export interface ActivityItem {
  id: number
  action: string
  operator_name: string | null
  document_type: string | null
  document_no: string | null
  description: string | null
  created_at: string
}

/** 最近库存动态（带符号 quantity：入库正、冲销负） */
export interface InventoryActivityItem {
  id: number
  txn_no: string
  transaction_type: TxnType
  material_id: number
  material_code: string
  material_name: string
  unit: string | null
  warehouse_id: number
  warehouse_name: string
  quantity: string
  source_type: string | null
  source_id: number | null
  reference_no: string | null
  transaction_at: string
}

export function apiDashboardSummary() {
  return http.get<DashboardSummary>('/dashboard/summary')
}

export function apiPrTrend(days: number) {
  return http.get<TrendPoint[]>('/dashboard/pr-trend', { days })
}

export function apiPoStatusDistribution() {
  return http.get<StatusCount[]>('/dashboard/po-status-distribution')
}

export function apiLowStock(limit = 10) {
  return http.get<LowStockRow[]>('/dashboard/low-stock', { limit })
}

export function apiDashboardTodos() {
  return http.get<TodoItem[]>('/dashboard/todos')
}

export function apiRecentActivities(limit = 10) {
  return http.get<ActivityItem[]>('/dashboard/recent-activities', { limit })
}

export function apiInventoryActivities(limit = 6) {
  return http.get<InventoryActivityItem[]>('/dashboard/inventory-activities', { limit })
}
