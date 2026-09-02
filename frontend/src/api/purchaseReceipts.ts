import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { PurchaseReceipt } from '@/types/models'
import type { ReceiptStatus } from '@/types/enums'

export interface ReceiptQuery extends PageQuery {
  receipt_no?: string
  po_no?: string
  po_id?: number
  warehouse_id?: number
  status?: ReceiptStatus | ''
  receipt_date_from?: string
  receipt_date_to?: string
}

export interface ReceiptItemPayload {
  po_item_id: number
  received_quantity: string
  remark?: string | null
}

export interface ReceiptCreatePayload {
  po_id: number
  warehouse_id: number
  receipt_date?: string | null
  remark?: string | null
  items: ReceiptItemPayload[]
}

export function apiReceipts(params: ReceiptQuery) {
  return http.get<PageResult<PurchaseReceipt>>('/purchase-receipts', params as Record<string, unknown>)
}

export function apiReceipt(id: number) {
  return http.get<PurchaseReceipt>(`/purchase-receipts/${id}`)
}

export function apiCreateReceipt(data: ReceiptCreatePayload) {
  return http.post<PurchaseReceipt>('/purchase-receipts', data)
}

export function apiReverseReceipt(id: number, data: { reason: string }) {
  return http.post<PurchaseReceipt>(`/purchase-receipts/${id}/reverse`, data)
}
