// ---- Auth store 单测：login → token → fetchMe；失败/登出清理 ----
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { CurrentUser, TokenResponse } from '@/types/models'

const h = vi.hoisted(() => {
  const kv = new Map<string, string>()
  return {
    httpPost: vi.fn(),
    httpGet: vi.fn(),
    getToken: vi.fn(() => kv.get('erp_access_token') ?? null),
    setToken: vi.fn((t: string) => kv.set('erp_access_token', t)),
    clearToken: vi.fn(() => kv.delete('erp_access_token')),
  }
})

vi.mock('@/api/request', () => ({
  http: { post: h.httpPost, get: h.httpGet },
  getToken: h.getToken,
  setToken: h.setToken,
  clearToken: h.clearToken,
}))

import { useAuthStore } from '@/stores/auth'

const ME: CurrentUser = {
  id: 2,
  username: 'zhangsan',
  real_name: '张三',
  role_id: 3,
  role_code: 'APPLICANT',
  role_name: '采购申请人',
  department_id: 1,
  department_name: '生产部',
  permissions: ['pr:view', 'pr:create', 'material:view'],
}

beforeEach(() => {
  h.httpPost.mockReset()
  h.httpGet.mockReset()
  h.clearToken()
  setActivePinia(createPinia())
})

describe('auth store', () => {
  it('login 成功：保存 token 并拉取 /auth/me', async () => {
    h.httpPost.mockResolvedValue({ access_token: 'tk-1', token_type: 'bearer', expires_in: 7200 } as TokenResponse)
    h.httpGet.mockResolvedValue(ME)

    const store = useAuthStore()
    expect(store.isLoggedIn).toBe(false)

    await store.login('zhangsan', 'demo123')

    expect(h.httpPost).toHaveBeenCalledWith('/auth/login', { username: 'zhangsan', password: 'demo123' })
    expect(store.token).toBe('tk-1')
    expect(h.getToken()).toBe('tk-1') // 已写入 localStorage
    expect(h.httpGet).toHaveBeenCalledWith('/auth/me', undefined, { showError: false })
    expect(store.user?.username).toBe('zhangsan')
    expect(store.permissions).toContain('pr:create')
    expect(store.roleCode).toBe('APPLICANT')
    expect(store.isLoggedIn).toBe(true)
  })

  it('fetchMe 失败（token 失效被清）→ reset 置空', async () => {
    h.getToken.mockReturnValueOnce('expired')
    h.httpGet.mockImplementation(async () => {
      h.clearToken() // 模拟 401 分支清 token
      throw new Error('401')
    })

    const store = useAuthStore()
    const me = await store.fetchMe()

    expect(me).toBeNull()
    expect(store.user).toBeNull()
    expect(store.token).toBeNull()
    expect(store.isLoggedIn).toBe(false)
  })

  it('logout 清除 token 与用户', async () => {
    h.httpGet.mockResolvedValue(ME)
    const store = useAuthStore()
    store.token = 'tk-x'
    store.user = ME
    expect(store.isLoggedIn).toBe(true)

    store.logout()

    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(h.getToken()).toBeNull()
  })

  it('restore：token 存在且无 user 时自动 fetchMe', async () => {
    h.getToken.mockReturnValue('tk-restore')
    h.httpGet.mockResolvedValue(ME)

    const store = useAuthStore()
    expect(store.token).toBe('tk-restore')
    expect(store.user).toBeNull()

    await store.restore()

    expect(h.httpGet).toHaveBeenCalled()
    expect(store.user?.username).toBe('zhangsan')
  })
})
