// ---- 权限 helper：以服务端 /auth/me 返回的 permissions 为准 ----

import { useAuthStore } from '@/stores/auth'

/** 当前用户是否拥有某权限点（严格模式：admin 角色也需真实包含，seed 中 ADMIN 拥有全部） */
export function hasPerm(perm: string | string[] | undefined): boolean {
  if (!perm) return true
  const auth = useAuthStore()
  if (!auth.token) return false
  const need = Array.isArray(perm) ? perm : [perm]
  return need.every((p) => auth.permissions.includes(p))
}

/** 是否拥有任一权限点 */
export function hasAnyPerm(perms: string[]): boolean {
  const auth = useAuthStore()
  if (!auth.token) return false
  return perms.some((p) => auth.permissions.includes(p))
}

export interface MenuEntry {
  path: string
  title: string
  icon?: string
  /** 全部满足才显示；为空表示登录即可见 */
  perms?: string[]
  children?: MenuEntry[]
}

/**
 * 按当前用户权限过滤菜单树（泛型：任何带 perms/children 的结构均可过滤）。
 * 规范：不要显示用户没有权限访问的菜单。
 */
export function filterMenus<T extends { perms?: string[]; children?: T[] }>(menus: T[]): T[] {
  const auth = useAuthStore()
  const result: T[] = []
  for (const m of menus) {
    if (m.perms && m.perms.length && !m.perms.every((p) => auth.permissions.includes(p))) {
      continue
    }
    const children = m.children ? filterMenus(m.children) : undefined
    if (children !== undefined && children.length === 0 && m.children?.length) {
      continue // 子菜单全部无权限 → 折叠父级
    }
    result.push(children ? { ...m, children } : m)
  }
  return result
}
