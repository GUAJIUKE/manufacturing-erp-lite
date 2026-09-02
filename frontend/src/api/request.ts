// ---- 统一 API client ----
// * baseURL: VITE_API_BASE_URL（默认 http://localhost:8000/api/v1）
// * 请求自动附加 Authorization: Bearer <token>
// * 响应解包统一 envelope {code,message,data,request_id}
// * 错误策略：401 清 token 跳登录；403 统一提示；业务 code!=0 展示后端 message

import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

export const TOKEN_KEY = 'erp_access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

const service = axios.create({
  baseURL: BASE_URL,
  timeout: 20000,
})

service.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** 业务错误（envelope code != 0）——页面可 catch 后做定制 UX */
export class ApiBusinessError extends Error {
  code: number
  httpStatus: number
  detail: unknown

  constructor(code: number, message: string, httpStatus: number, detail: unknown) {
    super(message)
    this.name = 'ApiBusinessError'
    this.code = code
    this.httpStatus = httpStatus
    this.detail = detail
  }
}

function redirectToLogin(): void {
  clearToken()
  if (!location.pathname.startsWith('/login')) {
    const from = encodeURIComponent(location.pathname + location.search)
    location.href = `/login?redirect=${from}`
  }
}

export interface RequestOptions {
  /** 业务错误/HTTP 错误是否自动 toast（默认 true，页面需定制时传 false 自行 catch） */
  showError?: boolean
}

/**
 * 发请求并解包 envelope.data。
 * - HTTP 401 → 清 token 跳登录
 * - HTTP 403 → 统一提示「无权限执行此操作」
 * - envelope.code != 0 → toast 后端 message（可抑制），reject ApiBusinessError
 */
export async function request<T>(config: AxiosRequestConfig, options: RequestOptions = {}): Promise<T> {
  const { showError = true } = options
  let resp
  try {
    resp = await service.request<ApiResponse<T>>(config)
  } catch (err) {
    const axErr = err as AxiosError<ApiResponse<unknown>>
    const httpStatus = axErr.response?.status
    const body = axErr.response?.data

    if (httpStatus === 401) {
      if (showError) ElMessage.error('登录已过期，请重新登录')
      redirectToLogin()
      throw new ApiBusinessError(2001, '未认证或登录已过期', 401, null)
    }
    if (httpStatus === 403) {
      const msg = body?.message || '无权限执行此操作'
      if (showError) ElMessage.error(msg)
      throw new ApiBusinessError(body?.code ?? 2002, msg, 403, body?.data)
    }
    // 业务错误（409 / 422 / 500 等，envelope.code != 0）
    if (body && typeof body.code === 'number' && body.code !== 0) {
      const message = body.message || '操作失败'
      if (showError) ElMessage.error(message)
      throw new ApiBusinessError(body.code, message, httpStatus ?? 0, body.data)
    }
    // 网络错误或非 envelope 响应
    if (showError) ElMessage.error('网络异常，请检查后端服务是否可用')
    throw new ApiBusinessError(1000, '网络异常', httpStatus ?? 0, null)
  }

  const body = resp.data
  if (body && typeof body.code === 'number' && body.code !== 0) {
    const message = body.message || '操作失败'
    if (showError) ElMessage.error(message)
    throw new ApiBusinessError(body.code, message, resp.status, body.data)
  }
  return body?.data as T
}

export const http = {
  get<T>(url: string, params?: Record<string, unknown>, options?: RequestOptions): Promise<T> {
    return request<T>({ url, method: 'GET', params }, options)
  },
  post<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>({ url, method: 'POST', data }, options)
  },
  put<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>({ url, method: 'PUT', data }, options)
  },
  del<T>(url: string, params?: Record<string, unknown>, options?: RequestOptions): Promise<T> {
    return request<T>({ url, method: 'DELETE', params }, options)
  },
}
