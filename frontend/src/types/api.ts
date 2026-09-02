// ---- 后端响应 envelope + 分页（app/core/response.py）----

/** 统一响应：code===0 成功；否则 data 为错误 detail（422 时为 {field,message}[]） */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T | null
  request_id?: string | null
}

/** 分页结果 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/** 分页查询参数 */
export interface PageQuery {
  page?: number
  page_size?: number
}
