import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type {
  ApprovalRecord,
  PrCreatePayload,
  PrUpdatePayload,
  PurchaseRequisition,
} from '@/types/models'
import type { PrStatus } from '@/types/enums'

export interface PrQuery extends PageQuery {
  pr_no?: string
  applicant?: string
  department_id?: number
  status?: PrStatus | ''
  apply_date_from?: string
  apply_date_to?: string
}

export function apiPrs(params: PrQuery) {
  return http.get<PageResult<PurchaseRequisition>>('/purchase-requisitions', params as Record<string, unknown>)
}

export function apiPr(id: number) {
  return http.get<PurchaseRequisition>(`/purchase-requisitions/${id}`)
}

export function apiCreatePr(data: PrCreatePayload) {
  return http.post<PurchaseRequisition>('/purchase-requisitions', data)
}

export function apiUpdatePr(id: number, data: PrUpdatePayload) {
  return http.put<PurchaseRequisition>(`/purchase-requisitions/${id}`, data)
}

export function apiSubmitPr(id: number) {
  return http.post<PurchaseRequisition>(`/purchase-requisitions/${id}/submit`)
}

export function apiCancelPr(id: number) {
  return http.post<PurchaseRequisition>(`/purchase-requisitions/${id}/cancel`)
}

export function apiApprovePr(id: number, data: { version: number; comment?: string | null }) {
  return http.post<PurchaseRequisition>(`/purchase-requisitions/${id}/approve`, data)
}

export function apiRejectPr(id: number, data: { version: number; comment: string }) {
  return http.post<PurchaseRequisition>(`/purchase-requisitions/${id}/reject`, data)
}

export function apiRevisePr(id: number, data: { version: number }) {
  return http.post<PurchaseRequisition>(`/purchase-requisitions/${id}/revise`, data)
}

export function apiPrApprovals(id: number) {
  return http.get<ApprovalRecord[]>(`/purchase-requisitions/${id}/approvals`)
}
