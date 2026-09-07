import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type {
  ReconciliationCreatePayload,
  ReconciliationItemLine,
  StockReconciliation,
  ReconciliationUpdatePayload,
} from '@/types/models'
import type { ReconciliationStatus } from '@/types/enums'

export interface ReconciliationQuery extends PageQuery {
  reconciliation_no?: string
  warehouse_id?: number
  status?: ReconciliationStatus | ''
  counted_on_from?: string
  counted_on_to?: string
}

export function apiReconciliations(params: ReconciliationQuery) {
  return http.get<PageResult<StockReconciliation>>('/stock-reconciliations', params as Record<string, unknown>)
}

export function apiReconciliation(id: number) {
  return http.get<StockReconciliation>(`/stock-reconciliations/${id}`)
}

export function apiCreateReconciliation(data: ReconciliationCreatePayload) {
  return http.post<StockReconciliation>('/stock-reconciliations', data)
}

export function apiUpdateReconciliation(id: number, data: ReconciliationUpdatePayload) {
  return http.put<StockReconciliation>(`/stock-reconciliations/${id}`, data)
}

export function apiSubmitReconciliation(id: number, version: number) {
  return http.post<StockReconciliation>(`/stock-reconciliations/${id}/submit`, { version })
}

export interface ApprovePayload {
  approve_comment?: string | null
  override_self_approval?: boolean
  override_reason?: string | null
}

export function apiApproveReconciliation(id: number, data: ApprovePayload = {}) {
  return http.post<StockReconciliation>(`/stock-reconciliations/${id}/approve`, data)
}

export function apiRejectReconciliation(id: number, comment: string) {
  return http.post<StockReconciliation>(`/stock-reconciliations/${id}/reject`, { comment })
}

export type { ReconciliationItemLine }
