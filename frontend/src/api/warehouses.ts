import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { Warehouse, WarehouseCreate } from '@/types/models'

export interface WarehouseQuery extends PageQuery {
  code?: string
  name?: string
  status?: string
}

export function apiWarehouses(params: WarehouseQuery) {
  return http.get<PageResult<Warehouse>>('/warehouses', params as Record<string, unknown>)
}

export function apiWarehouse(id: number) {
  return http.get<Warehouse>(`/warehouses/${id}`)
}

export function apiCreateWarehouse(data: WarehouseCreate) {
  return http.post<Warehouse>('/warehouses', data)
}

export function apiUpdateWarehouse(id: number, data: Partial<WarehouseCreate>) {
  return http.put<Warehouse>(`/warehouses/${id}`, data)
}

export function apiDisableWarehouse(id: number) {
  return http.post<Warehouse>(`/warehouses/${id}/disable`)
}

export function apiEnableWarehouse(id: number) {
  return http.post<Warehouse>(`/warehouses/${id}/enable`)
}
