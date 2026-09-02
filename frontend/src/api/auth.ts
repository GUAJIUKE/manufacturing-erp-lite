import { http } from './request'
import type { CurrentUser } from '@/types/models'

export interface LoginPayload {
  username: string
  password: string
}

/** POST /auth/login */
export function apiLogin(payload: LoginPayload) {
  return http.post<{ access_token: string; expires_in: number }>('/auth/login', payload)
}

/** GET /auth/me */
export function apiMe() {
  return http.get<CurrentUser>('/auth/me')
}
