import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { PurchaseOrder } from '@/types/models'
import type { PoStatus } from '@/types/enums'

export interface PoQuery extends PageQuery {
  po_no?: string
  supplier_id?: number
  status?: PoStatus | ''
  order_date_from?: string
  order_date_to?: string
}

export interface PoItemPayload {
  material_id: number
  ordered_quantity: string
  unit_price: string
  remark?: string | null
  sources: { pr_item_id: number; quantity: string }[]
}

export interface PoCreatePayload {
  supplier_id: number
  order_date?: string | null
  expected_date?: string | null
  remark?: string | null
  items: PoItemPayload[]
}

export function apiPos(params: PoQuery) {
  return http.get<PageResult<PurchaseOrder>>('/purchase-orders', params as Record<string, unknown>)
}

export function apiPo(id: number) {
  return http.get<PurchaseOrder>(`/purchase-orders/${id}`)
}

export function apiCreatePo(data: PoCreatePayload) {
  return http.post<PurchaseOrder>('/purchase-orders', data)
}

export function apiConfirmPo(id: number, data: { version: number; comment?: string | null }) {
  return http.post<PurchaseOrder>(`/purchase-orders/${id}/confirm`, data)
}

export function apiCancelPo(id: number, data: { version: number; reason?: string | null }) {
  return http.post<PurchaseOrder>(`/purchase-orders/${id}/cancel`, data)
}
