import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layouts/MainLayout.vue'

declare module 'vue-router' {
  interface RouteMeta {
    /** 需要登录 */
    requiresAuth?: boolean
    /** 需要的权限点（全部满足） */
    permission?: string | string[]
    /** 页面标题 */
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { requiresAuth: true, permission: 'dashboard:view', title: '首页' },
      },
      // ---- 基础资料 ----
      {
        path: 'materials',
        name: 'materials',
        component: () => import('@/views/master/MaterialListView.vue'),
        meta: { requiresAuth: true, permission: 'material:view', title: '物料' },
      },
      {
        path: 'suppliers',
        name: 'suppliers',
        component: () => import('@/views/master/SupplierListView.vue'),
        meta: { requiresAuth: true, permission: 'supplier:view', title: '供应商' },
      },
      {
        path: 'warehouses',
        name: 'warehouses',
        component: () => import('@/views/master/WarehouseListView.vue'),
        meta: { requiresAuth: true, permission: 'warehouse:view', title: '仓库' },
      },
      {
        path: 'inventory-policies',
        name: 'inventory-policies',
        component: () => import('@/views/master/PolicyListView.vue'),
        meta: { requiresAuth: true, permission: 'inventory_policy:view', title: '库存策略' },
      },
      // ---- 采购管理 ----
      {
        path: 'purchase-requisitions',
        name: 'pr-list',
        component: () => import('@/views/pr/PrListView.vue'),
        meta: { requiresAuth: true, permission: 'pr:view', title: '采购申请' },
      },
      {
        path: 'purchase-requisitions/create',
        name: 'pr-create',
        component: () => import('@/views/pr/PrFormView.vue'),
        meta: { requiresAuth: true, permission: 'pr:create', title: '新建采购申请' },
      },
      {
        path: 'purchase-requisitions/:id',
        name: 'pr-detail',
        component: () => import('@/views/pr/PrDetailView.vue'),
        meta: { requiresAuth: true, permission: 'pr:view', title: '采购申请详情' },
      },
      {
        path: 'purchase-requisitions/:id/edit',
        name: 'pr-edit',
        component: () => import('@/views/pr/PrFormView.vue'),
        meta: { requiresAuth: true, permission: 'pr:update', title: '编辑采购申请' },
      },
      {
        path: 'approvals',
        name: 'approvals',
        component: () => import('@/views/approval/ApprovalListView.vue'),
        meta: { requiresAuth: true, permission: 'pr:approve', title: '审批中心' },
      },
      {
        path: 'purchase-orders',
        name: 'po-list',
        component: () => import('@/views/po/PoListView.vue'),
        meta: { requiresAuth: true, permission: 'po:view', title: '采购订单' },
      },
      {
        path: 'purchase-orders/create',
        name: 'po-create',
        component: () => import('@/views/po/PoCreateView.vue'),
        meta: { requiresAuth: true, permission: 'po:create', title: '创建采购订单' },
      },
      {
        path: 'purchase-orders/:id',
        name: 'po-detail',
        component: () => import('@/views/po/PoDetailView.vue'),
        meta: { requiresAuth: true, permission: 'po:view', title: '采购订单详情' },
      },
      // ---- 仓库管理 ----
      {
        path: 'purchase-receipts',
        name: 'receipt-list',
        component: () => import('@/views/receipt/ReceiptListView.vue'),
        meta: { requiresAuth: true, permission: 'receipt:view', title: '采购入库' },
      },
      {
        path: 'purchase-receipts/create',
        name: 'receipt-create',
        component: () => import('@/views/receipt/ReceiptCreateView.vue'),
        meta: { requiresAuth: true, permission: 'receipt:create', title: '新建入库单' },
      },
      {
        path: 'purchase-receipts/:id',
        name: 'receipt-detail',
        component: () => import('@/views/receipt/ReceiptDetailView.vue'),
        meta: { requiresAuth: true, permission: 'receipt:view', title: '入库单详情' },
      },
      {
        path: 'inventory',
        name: 'inventory',
        component: () => import('@/views/inventory/BalanceListView.vue'),
        meta: { requiresAuth: true, permission: 'inventory:view', title: '当前库存' },
      },
      {
        path: 'inventory/transactions',
        name: 'inventory-transactions',
        component: () => import('@/views/inventory/TransactionListView.vue'),
        meta: { requiresAuth: true, permission: 'inventory_txn:view', title: '库存流水' },
      },
      // ---- 系统管理 ----
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/system/UserListView.vue'),
        meta: { requiresAuth: true, permission: 'user:view', title: '用户' },
      },
      {
        path: 'roles',
        name: 'roles',
        component: () => import('@/views/system/RoleListView.vue'),
        meta: { requiresAuth: true, permission: 'role:view', title: '角色' },
      },
      {
        path: 'departments',
        name: 'departments',
        component: () => import('@/views/system/DepartmentListView.vue'),
        meta: { requiresAuth: true, permission: 'department:view', title: '部门' },
      },
      {
        path: '403',
        name: 'forbidden',
        component: () => import('@/views/error/ForbiddenView.vue'),
        meta: { requiresAuth: true, title: '无权限' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth) {
    if (!auth.token) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    // 页面刷新后：token 在但 user 未加载 → 拉 /auth/me（权限以服务器为准）
    if (!auth.user) {
      const me = await auth.fetchMe()
      if (!me) {
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
    const need = to.meta.permission
    if (need) {
      const needList = Array.isArray(need) ? need : [need]
      if (!needList.every((p) => auth.permissions.includes(p))) {
        return { name: 'forbidden' }
      }
    }
  }
  if (to.path === '/login' && auth.token) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  const base = import.meta.env.VITE_APP_TITLE || 'ERP Lite'
  document.title = to.meta.title ? `${to.meta.title} · ${base}` : base
})

export default router
