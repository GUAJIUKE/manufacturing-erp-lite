import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { Supplier, SupplierCreate } from '@/types/models'

export interface SupplierQuery extends PageQuery {
  code?: string
  name?: string
  status?: string
}

export function apiSuppliers(params: SupplierQuery) {
  return http.get<PageResult<Supplier>>('/suppliers', params as Record<string, unknown>)
}

export function apiSupplier(id: number) {
  return http.get<Supplier>(`/suppliers/${id}`)
}

export function apiCreateSupplier(data: SupplierCreate) {
  return http.post<Supplier>('/suppliers', data)
}

export function apiUpdateSupplier(id: number, data: Partial<SupplierCreate>) {
  return http.put<Supplier>(`/suppliers/${id}`, data)
}

export function apiDisableSupplier(id: number) {
  return http.post<Supplier>(`/suppliers/${id}/disable`)
}

export function apiEnableSupplier(id: number) {
  return http.post<Supplier>(`/suppliers/${id}/enable`)
}
