import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { InventoryPolicy, InventoryPolicyCreate } from '@/types/models'

export interface PolicyQuery extends PageQuery {
  warehouse_id?: number
  material_id?: number
}

export function apiPolicies(params: PolicyQuery) {
  return http.get<PageResult<InventoryPolicy>>('/inventory-policies', params as Record<string, unknown>)
}

export function apiPolicy(id: number) {
  return http.get<InventoryPolicy>(`/inventory-policies/${id}`)
}

export function apiCreatePolicy(data: InventoryPolicyCreate) {
  return http.post<InventoryPolicy>('/inventory-policies', data)
}

export function apiUpdatePolicy(id: number, data: Partial<InventoryPolicyCreate>) {
  return http.put<InventoryPolicy>(`/inventory-policies/${id}`, data)
}
