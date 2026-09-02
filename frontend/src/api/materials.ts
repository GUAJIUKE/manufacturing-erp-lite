import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { Material, MaterialCreate } from '@/types/models'

export interface MaterialQuery extends PageQuery {
  code?: string
  name?: string
  category?: string
  status?: string
}

export function apiMaterials(params: MaterialQuery) {
  return http.get<PageResult<Material>>('/materials', params as Record<string, unknown>)
}

export function apiMaterial(id: number) {
  return http.get<Material>(`/materials/${id}`)
}

export function apiCreateMaterial(data: MaterialCreate) {
  return http.post<Material>('/materials', data)
}

export function apiUpdateMaterial(id: number, data: Partial<MaterialCreate>) {
  return http.put<Material>(`/materials/${id}`, data)
}

export function apiDisableMaterial(id: number) {
  return http.post<Material>(`/materials/${id}/disable`)
}

export function apiEnableMaterial(id: number) {
  return http.post<Material>(`/materials/${id}/enable`)
}
