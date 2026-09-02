// ---- 权限 helper 单测（hasPerm / hasAnyPerm / filterMenus）----
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// mock 掉 request 模块（store 只用到 token helpers；保持纯逻辑测试）
vi.mock('@/api/request', () => ({
  http: { post: vi.fn(), get: vi.fn() },
  getToken: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
}))

import { useAuthStore } from '@/stores/auth'
import { filterMenus, hasAnyPerm, hasPerm, type MenuEntry } from '@/utils/permission'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

function loginAs(permissions: string[]) {
  const auth = useAuthStore()
  ;(auth as unknown as { token: string }).token = 't'
  ;(auth as unknown as { user: { permissions: string[] } }).user = {
    id: 1,
    username: 'u1',
    real_name: '测试',
    role_id: 1,
    role_code: 'ADMIN',
    role_name: '系统管理员',
    department_id: null,
    department_name: null,
    permissions,
  }
}

describe('hasPerm', () => {
  it('未登录一律 false', () => {
    expect(hasPerm('material:view')).toBe(false)
  })
  it('未声明权限点（undefined）视为放行', () => {
    expect(hasPerm(undefined)).toBe(true)
  })
  it('单权限点命中', () => {
    loginAs(['material:view', 'pr:view'])
    expect(hasPerm('material:view')).toBe(true)
    expect(hasPerm('pr:create')).toBe(false)
  })
  it('多权限点需全部命中', () => {
    loginAs(['pr:view', 'pr:create'])
    expect(hasPerm(['pr:view', 'pr:create'])).toBe(true)
    expect(hasPerm(['pr:view', 'pr:approve'])).toBe(false)
  })
})

describe('hasAnyPerm', () => {
  it('任一命中即 true', () => {
    loginAs(['pr:approve'])
    expect(hasAnyPerm(['pr:view', 'pr:approve'])).toBe(true)
    expect(hasAnyPerm(['pr:create', 'pr:update'])).toBe(false)
  })
})

describe('filterMenus', () => {
  const menus: MenuEntry[] = [
    { path: '/dashboard', title: '首页' },
    { path: '/materials', title: '物料', perms: ['material:view'] },
    {
      path: '/system',
      title: '系统管理',
      children: [
        { path: '/users', title: '用户', perms: ['user:view'] },
        { path: '/roles', title: '角色', perms: ['role:view'] },
      ],
    },
    { path: '/hidden-root', title: '隐藏父级', perms: ['a:b'], children: [{ path: '/x', title: '子项' }] },
  ]

  it('无权限时只保留无 perms 菜单', () => {
    loginAs([])
    const out = filterMenus(menus)
    expect(out.map((m) => m.path)).toEqual(['/dashboard'])
  })

  it('按权限过滤叶子并保留命中的父级', () => {
    loginAs(['user:view'])
    const out = filterMenus(menus)
    const paths = out.map((m) => m.path)
    expect(paths).toContain('/dashboard')
    expect(paths).toContain('/system')
    const sys = out.find((m) => m.path === '/system')
    expect(sys?.children?.map((c) => c.path)).toEqual(['/users'])
  })

  it('父级自身无权限时整棵折叠', () => {
    loginAs(['user:view'])
    const out = filterMenus(menus)
    expect(out.find((m) => m.path === '/hidden-root')).toBeUndefined()
  })
})
