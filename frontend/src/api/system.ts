import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { Department, Permission, Role, User, UserCreate } from '@/types/models'

// ---------- users ----------
export interface UserQuery extends PageQuery {
  keyword?: string
  status?: string
}

export function apiUsers(params: UserQuery) {
  return http.get<PageResult<User>>('/users', params as Record<string, unknown>)
}

export function apiCreateUser(data: UserCreate) {
  return http.post<User>('/users', data)
}

/** UserUpdate 为全可选（status 启停、password 留空不修改），与后端 UserUpdate schema 对齐 */
export interface UserUpdatePayload {
  real_name?: string
  email?: string | null
  phone?: string | null
  department_id?: number | null
  role_id?: number
  status?: string
  password?: string
}

export function apiUpdateUser(id: number, data: UserUpdatePayload) {
  return http.put<User>(`/users/${id}`, data)
}

export function apiDisableUser(id: number) {
  return http.del<User>(`/users/${id}`)
}

// ---------- roles ----------
export function apiRoles() {
  return http.get<Role[]>('/roles')
}

export function apiRole(id: number) {
  return http.get<Role>(`/roles/${id}`)
}

export function apiCreateRole(data: { role_code: string; role_name: string; description?: string | null }) {
  return http.post<Role>('/roles', data)
}

export function apiUpdateRole(id: number, data: { role_name?: string; description?: string | null; status?: string }) {
  return http.put<Role>(`/roles/${id}`, data)
}

export function apiDeleteRole(id: number) {
  return http.del<Role>(`/roles/${id}`)
}

export function apiAssignRolePermissions(id: number, permission_ids: number[]) {
  return http.post<Role>(`/roles/${id}/permissions`, { permission_ids })
}

// ---------- permissions ----------
export function apiPermissions() {
  return http.get<Permission[]>('/permissions')
}

// ---------- departments ----------
export function apiDepartments() {
  return http.get<Department[]>('/departments')
}

export function apiCreateDepartment(data: { dept_code: string; dept_name: string; parent_id?: number | null; sort_order?: number; remark?: string | null }) {
  return http.post<Department>('/departments', data)
}

export function apiUpdateDepartment(id: number, data: { dept_name?: string; parent_id?: number | null; sort_order?: number; remark?: string | null; status?: string }) {
  return http.put<Department>(`/departments/${id}`, data)
}

export function apiDisableDepartment(id: number) {
  return http.del<Department>(`/departments/${id}`)
}
