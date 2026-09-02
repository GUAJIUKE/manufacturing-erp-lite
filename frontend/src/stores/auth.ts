import { defineStore } from 'pinia'
import { http } from '@/api/request'
import { clearToken, getToken, setToken } from '@/api/request'
import type { CurrentUser, TokenResponse } from '@/types/models'

interface AuthState {
  token: string | null
  user: CurrentUser | null
  /** 登录/刷新 me 的进行中状态，防止并发重复请求 */
  loading: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: getToken(),
    user: null,
    loading: false,
  }),

  getters: {
    currentUser(state): CurrentUser | null {
      return state.user
    },
    permissions(state): string[] {
      return state.user?.permissions ?? []
    },
    roleCode(state): string {
      return state.user?.role_code ?? ''
    },
    isLoggedIn(state): boolean {
      return Boolean(state.token)
    },
  },

  actions: {
    /** 登录：保存 token 后拉取 /auth/me */
    async login(username: string, password: string): Promise<void> {
      const token = await http.post<TokenResponse>('/auth/login', { username, password })
      this.token = token.access_token
      setToken(token.access_token)
      await this.fetchMe()
    },

    /** 拉取当前用户（角色/权限以服务器为准） */
    async fetchMe(): Promise<CurrentUser | null> {
      if (!this.token) return null
      this.loading = true
      try {
        const me = await http.get<CurrentUser>('/auth/me', undefined, { showError: false })
        this.user = me
        return me
      } catch {
        // 401 → token 已失效
        if (!getToken()) {
          this.reset()
        }
        return null
      } finally {
        this.loading = false
      }
    },

    /** 刷新页面后恢复会话 */
    async restore(): Promise<void> {
      if (this.token && !this.user) {
        await this.fetchMe()
      }
    },

    /** 退出登录 */
    logout(): void {
      this.reset()
    },

    reset(): void {
      this.token = null
      this.user = null
      clearToken()
    },
  },
})
