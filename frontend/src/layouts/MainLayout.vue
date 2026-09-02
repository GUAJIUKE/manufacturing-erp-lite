<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Expand, Fold, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { filterMenus, type MenuEntry } from '@/utils/permission'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const MENUS: MenuEntry[] = [
  { path: '/dashboard', title: '首页', icon: 'Odometer', perms: ['dashboard:view'] },
  {
    path: '/master',
    title: '基础资料',
    icon: 'Collection',
    children: [
      { path: '/materials', title: '物料', perms: ['material:view'] },
      { path: '/suppliers', title: '供应商', perms: ['supplier:view'] },
      { path: '/warehouses', title: '仓库', perms: ['warehouse:view'] },
      { path: '/inventory-policies', title: '库存策略', perms: ['inventory_policy:view'] },
    ],
  },
  {
    path: '/procurement',
    title: '采购管理',
    icon: 'ShoppingCart',
    children: [
      { path: '/purchase-requisitions', title: '采购申请', perms: ['pr:view'] },
      { path: '/approvals', title: '审批中心', perms: ['pr:approve'] },
      { path: '/purchase-orders', title: '采购订单', perms: ['po:view'] },
    ],
  },
  {
    path: '/warehouse',
    title: '仓库管理',
    icon: 'Box',
    children: [
      { path: '/purchase-receipts', title: '采购入库', perms: ['receipt:view'] },
      { path: '/inventory', title: '当前库存', perms: ['inventory:view'] },
      { path: '/inventory/transactions', title: '库存流水', perms: ['inventory_txn:view'] },
    ],
  },
  {
    path: '/system',
    title: '系统管理',
    icon: 'Setting',
    children: [
      { path: '/users', title: '用户', perms: ['user:view'] },
      { path: '/roles', title: '角色', perms: ['role:view'] },
      { path: '/departments', title: '部门', perms: ['department:view'] },
    ],
  },
]

const visibleMenus = computed(() => filterMenus(MENUS))

/** 根据当前路径选中菜单 */
const activeMenu = computed(() => {
  const p = route.path
  if (p.startsWith('/purchase-requisitions')) return '/purchase-requisitions'
  if (p.startsWith('/approvals')) return '/approvals'
  if (p.startsWith('/purchase-orders')) return '/purchase-orders'
  if (p.startsWith('/purchase-receipts')) return '/purchase-receipts'
  if (p.startsWith('/inventory/transactions')) return '/inventory/transactions'
  if (p.startsWith('/inventory')) return '/inventory'
  if (p.startsWith('/materials')) return '/materials'
  if (p.startsWith('/suppliers')) return '/suppliers'
  if (p.startsWith('/warehouses')) return '/warehouses'
  if (p.startsWith('/inventory-policies')) return '/inventory-policies'
  if (p.startsWith('/users')) return '/users'
  if (p.startsWith('/roles')) return '/roles'
  if (p.startsWith('/departments')) return '/departments'
  return p
})

const pageTitle = computed(() => (route.meta.title as string) || '')

function onLogout() {
  auth.logout()
  router.replace('/login')
}
</script>

<template>
  <el-container class="app-shell">
    <el-aside :width="collapsed ? '64px' : '220px'" class="app-aside">
      <div class="brand" @click="router.push('/dashboard')">
        <span class="brand-logo">E</span>
        <span v-if="!collapsed" class="brand-text">ERP Lite</span>
      </div>
      <el-scrollbar>
        <el-menu
          :default-active="activeMenu"
          :collapse="collapsed"
          :collapse-transition="false"
          router
          background-color="#001529"
          text-color="rgba(255,255,255,0.68)"
          active-text-color="#fff"
          class="side-menu"
        >
          <template v-for="m in visibleMenus" :key="m.path">
            <el-sub-menu v-if="m.children && m.children.length" :index="m.path">
              <template #title>
                <el-icon><component :is="m.icon" /></el-icon>
                <span>{{ m.title }}</span>
              </template>
              <el-menu-item v-for="c in m.children" :key="c.path" :index="c.path">
                {{ c.title }}
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="m.path">
              <el-icon><component :is="m.icon" /></el-icon>
              <template #title>{{ m.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container class="app-body">
      <el-header class="app-header" height="56px">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapsed = !collapsed">
            <Expand v-if="collapsed" />
            <Fold v-else />
          </el-icon>
          <span class="page-title">{{ pageTitle }}</span>
        </div>
        <div class="header-right">
          <el-dropdown trigger="click">
            <span class="user-chip">
              <span class="user-avatar">{{ (auth.user?.real_name || auth.user?.username || '?').slice(0, 1) }}</span>
              <span class="user-info">
                <span class="user-name">{{ auth.user?.real_name || auth.user?.username }}</span>
                <span class="user-role">{{ auth.user?.role_name }}</span>
              </span>
              <el-icon class="arrow"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ auth.user?.department_name ? `${auth.user.department_name} · ` : '' }}{{ auth.user?.username }}
                </el-dropdown-item>
                <el-dropdown-item divided @click="onLogout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  height: 100vh;
}
.app-aside {
  background: #001529;
  transition: width 0.2s;
  overflow: hidden;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 56px;
  padding: 0 16px;
  cursor: pointer;
  color: #fff;
}
.brand-logo {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #2f6fed;
  color: #fff;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.brand-text {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}
.side-menu {
  border-right: none;
}
.side-menu:not(.el-menu--collapse) {
  width: 220px;
}
.app-body {
  min-width: 0;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e6e8eb;
  padding: 0 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.collapse-btn {
  font-size: 18px;
  cursor: pointer;
  color: #4b5563;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2329;
}
.header-right {
  display: flex;
  align-items: center;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}
.user-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #2f6fed;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
.user-info {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.user-name {
  font-size: 13px;
  color: #1f2329;
}
.user-role {
  font-size: 11px;
  color: #8a919f;
}
.arrow {
  font-size: 12px;
  color: #8a919f;
}
.app-main {
  background: #f3f5f8;
  padding: 16px;
  overflow: auto;
}
</style>
