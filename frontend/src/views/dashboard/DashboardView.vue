<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { filterMenus } from '@/utils/permission'

const auth = useAuthStore()
const router = useRouter()

interface ModuleEntry {
  path: string
  title: string
  desc: string
  perms?: string[]
}

const MODULES: ModuleEntry[] = [
  { path: '/materials', title: '物料管理', desc: '物料主数据维护', perms: ['material:view'] },
  { path: '/suppliers', title: '供应商', desc: '供应商主数据', perms: ['supplier:view'] },
  { path: '/warehouses', title: '仓库', desc: '仓库主数据', perms: ['warehouse:view'] },
  { path: '/inventory-policies', title: '库存策略', desc: '安全库存配置', perms: ['inventory_policy:view'] },
  { path: '/purchase-requisitions', title: '采购申请', desc: 'PR 全生命周期', perms: ['pr:view'] },
  { path: '/approvals', title: '审批中心', desc: '待审批单据', perms: ['pr:approve'] },
  { path: '/purchase-orders', title: '采购订单', desc: 'PO 与来源追溯', perms: ['po:view'] },
  { path: '/purchase-receipts', title: '采购入库', desc: '收货过账与冲销', perms: ['receipt:view'] },
  { path: '/inventory', title: '当前库存', desc: '余额与安全库存', perms: ['inventory:view'] },
  { path: '/inventory/transactions', title: '库存流水', desc: '带符号流水账', perms: ['inventory_txn:view'] },
  { path: '/users', title: '用户', desc: '账号与角色', perms: ['user:view'] },
  { path: '/roles', title: '角色权限', desc: 'RBAC 权限点', perms: ['role:view'] },
  { path: '/departments', title: '部门', desc: '组织架构', perms: ['department:view'] },
]

const visibleModules = computed(() => filterMenus(MODULES))
</script>

<template>
  <div>
    <div class="welcome-card">
      <div class="welcome-text">
        <h2>你好，{{ auth.user?.real_name || auth.user?.username }}</h2>
        <p>
          <el-tag size="small" effect="plain">{{ auth.user?.role_name }}</el-tag>
          <span v-if="auth.user?.department_name" class="dept-tag">{{ auth.user.department_name }}</span>
        </p>
      </div>
      <div class="welcome-tip">
        <p>Phase 10 后台 · 基于真实 FastAPI 业务 API</p>
        <p class="sub">统计图表将在 Phase 11 Dashboard 中呈现</p>
      </div>
    </div>

    <el-card shadow="never" class="module-card">
      <template #header><span class="card-title">系统模块入口</span></template>
      <div class="module-grid">
        <div v-for="m in visibleModules" :key="m.path" class="module-item" @click="router.push(m.path)">
          <div class="module-name">{{ m.title }}</div>
          <div class="module-desc">{{ m.desc }}</div>
        </div>
        <el-empty v-if="visibleModules.length === 0" description="当前账号没有可访问的模块" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.welcome-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  background: linear-gradient(120deg, #2f6fed 0%, #4a86f7 100%);
  color: #fff;
  border-radius: 8px;
  padding: 24px 28px;
  margin-bottom: 16px;
}
.welcome-text h2 {
  margin: 0 0 10px;
  font-size: 22px;
}
.dept-tag {
  margin-left: 8px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
}
.welcome-tip {
  text-align: right;
}
.welcome-tip p {
  margin: 0;
  font-size: 13px;
  opacity: 0.9;
}
.welcome-tip .sub {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.7;
}
.module-card {
  border-radius: 8px;
}
.card-title {
  font-weight: 600;
  color: #1f2329;
}
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.module-item {
  border: 1px solid #e6e8eb;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.15s;
}
.module-item:hover {
  border-color: #2f6fed;
  box-shadow: 0 2px 10px rgba(47, 111, 237, 0.12);
  transform: translateY(-1px);
}
.module-name {
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 6px;
}
.module-desc {
  font-size: 12px;
  color: #8a919f;
}
</style>
