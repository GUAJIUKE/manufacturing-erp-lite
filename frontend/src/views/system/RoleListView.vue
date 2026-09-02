<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import {
  apiAssignRolePermissions,
  apiCreateRole,
  apiDeleteRole,
  apiPermissions,
  apiRole,
  apiRoles,
  apiUpdateRole,
} from '@/api/system'
import type { Permission, Role } from '@/types/models'
import type { RoleCode } from '@/types/enums'
import { activeStatusMeta, roleCodeLabel } from '@/utils/status'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const rows = ref<Role[]>([])
const perms = ref<Permission[]>([])

const ROLE_CODE_OPTIONS: { value: RoleCode; label: string }[] = [
  { value: 'ADMIN', label: 'ADMIN - 系统管理员' },
  { value: 'APPLICANT', label: 'APPLICANT - 采购申请人' },
  { value: 'DEPT_MANAGER', label: 'DEPT_MANAGER - 部门主管' },
  { value: 'BUYER', label: 'BUYER - 采购员' },
  { value: 'WAREHOUSE', label: 'WAREHOUSE - 仓库管理员' },
]

async function load() {
  loading.value = true
  try {
    rows.value = await apiRoles()
  } finally {
    loading.value = false
  }
}

function permCount(r: Role): number {
  return r.permission_ids?.length ?? 0
}

// ---------- 新建/编辑 ----------
const formRef = ref<FormInstance>()
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const isSystemEditing = ref(false)
const form = reactive({
  role_code: '' as string,
  role_name: '',
  description: '',
  status: 'ACTIVE' as string,
})
const rules: FormRules = {
  role_code: [{ required: true, message: '请选择角色编码', trigger: 'change' }],
  role_name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  isSystemEditing.value = false
  Object.assign(form, { role_code: '', role_name: '', description: '', status: 'ACTIVE' })
  dialogVisible.value = true
}

function openEdit(r: Role) {
  editingId.value = r.id
  isSystemEditing.value = !!r.is_system
  Object.assign(form, {
    role_code: String(r.role_code),
    role_name: r.role_name,
    description: r.description ?? '',
    status: r.status,
  })
  dialogVisible.value = true
}

async function onSave() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    if (editingId.value == null) {
      await apiCreateRole({
        role_code: form.role_code as RoleCode,
        role_name: form.role_name.trim(),
        description: form.description.trim() || null,
      })
      ElMessage.success('角色已创建')
    } else {
      await apiUpdateRole(editingId.value, {
        role_name: form.role_name.trim(),
        description: form.description.trim() || null,
        status: form.status,
      })
      ElMessage.success('角色已更新')
    }
    dialogVisible.value = false
    load()
  } catch {
    /* toast */
  } finally {
    saving.value = false
  }
}

// ---------- 权限分配 ----------
const permVisible = ref(false)
const permSaving = ref(false)
const permTarget = ref<Role | null>(null)
const checkedPerms = ref<number[]>([])
const permModules = ref<{ module: string; items: Permission[] }[]>([])

async function openPerms(r: Role) {
  permTarget.value = r
  checkedPerms.value = [...(r.permission_ids ?? [])]
  permVisible.value = true
  try {
    const [all, detail] = await Promise.all([apiPermissions(), apiRole(r.id)])
    perms.value = all
    checkedPerms.value = [...(detail.permission_ids ?? [])]
    const map = new Map<string, Permission[]>()
    for (const p of all) {
      const list = map.get(p.module) ?? []
      list.push(p)
      map.set(p.module, list)
    }
    permModules.value = [...map.entries()].map(([module, items]) => ({ module, items }))
  } catch {
    /* toast */
  }
}

async function onSavePerms() {
  if (!permTarget.value) return
  permSaving.value = true
  try {
    await apiAssignRolePermissions(permTarget.value.id, checkedPerms.value)
    ElMessage.success('权限已更新')
    permVisible.value = false
    load()
  } catch {
    /* toast */
  } finally {
    permSaving.value = false
  }
}

// ---------- 删除 ----------
async function onDelete(r: Role) {
  try {
    await ElMessageBox.confirm(`删除角色 ${r.role_name}？删除后其用户将受影响。`, '删除角色', {
      type: 'warning',
      confirmButtonText: '删除',
    })
  } catch {
    return
  }
  try {
    await apiDeleteRole(r.id)
    ElMessage.success('已删除')
    load()
  } catch {
    /* toast */
  }
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <span class="text-muted" style="font-size: 13px">共 {{ rows.length }} 个角色 · 权限分配为替换式保存</span>
      <div class="spacer" />
      <el-button v-if="hasPerm('role:create')" type="primary" :icon="Plus" @click="openCreate">新建角色</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column label="角色编码" width="170">
        <template #default="{ row }">
          <span class="mono">{{ (row as Role).role_code }}</span>
          <el-tag v-if="(row as Role).is_system" size="small" type="warning" effect="plain" style="margin-left: 6px">系统</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="角色名称" width="160">
        <template #default="{ row }">
          <div style="font-weight: 600">{{ (row as Role).role_name }}</div>
          <div class="text-muted" style="font-size: 12px">{{ roleCodeLabel((row as Role).role_code) }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="200">
        <template #default="{ row }">{{ (row as Role).description || '-' }}</template>
      </el-table-column>
      <el-table-column label="权限点" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" type="info">{{ permCount(row as Role) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="activeStatusMeta((row as Role).status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('role:assign')" link type="primary" class="link-btn" @click="openPerms(row as Role)">权限配置</el-button>
          <el-button v-if="hasPerm('role:update')" link type="primary" class="link-btn" @click="openEdit(row as Role)">编辑</el-button>
          <el-button
            v-if="hasPerm('role:delete') && !(row as Role).is_system"
            link
            type="danger"
            class="link-btn"
            @click="onDelete(row as Role)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无角色" /></template>
    </el-table>

    <!-- 新建/编辑 -->
    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建角色' : `编辑角色 ${form.role_name}`" width="480px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="角色编码" prop="role_code">
          <el-select v-model="form.role_code" :disabled="editingId != null" style="width: 100%">
            <el-option v-for="o in ROLE_CODE_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色名称" prop="role_name">
          <el-input v-model="form.role_name" placeholder="如：质量主管" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可空" />
        </el-form-item>
        <el-form-item v-if="editingId != null && !isSystemEditing" label="状态">
          <el-radio-group v-model="form.status">
            <el-radio value="ACTIVE">启用</el-radio>
            <el-radio value="DISABLED">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 权限配置 -->
    <el-dialog v-model="permVisible" :title="`权限配置 - ${permTarget?.role_name ?? ''}`" width="680px">
      <p class="text-muted perm-hint">勾选后保存将【整体替换】该角色权限（替换式赋值）</p>
      <el-scrollbar height="440px">
        <div v-for="g in permModules" :key="g.module" class="perm-group">
          <div class="perm-module">{{ g.module }}</div>
          <el-checkbox-group v-model="checkedPerms" class="perm-checkbox-group">
            <el-checkbox v-for="p in g.items" :key="p.id" :value="p.id" class="perm-item">
              {{ p.perm_name }}
              <span class="mono perm-code">{{ p.perm_code }}</span>
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <el-empty v-if="permModules.length === 0" description="暂无权限点数据" :image-size="60" />
      </el-scrollbar>
      <template #footer>
        <el-button @click="permVisible = false">取消</el-button>
        <el-button type="primary" :loading="permSaving" @click="onSavePerms">保存权限</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.spacer {
  flex: 1;
}
.mono {
  font-family: 'Consolas', 'Sarasa Mono SC', monospace;
  font-size: 12px;
}
.perm-hint {
  margin: 0 0 10px;
  font-size: 12px;
}
.perm-group {
  margin-bottom: 14px;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  padding: 10px 12px;
}
.perm-module {
  font-weight: 600;
  color: #2f6fed;
  font-size: 13px;
  margin-bottom: 8px;
}
.perm-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.perm-item {
  width: 240px;
  margin-right: 0;
}
.perm-code {
  color: #8a919f;
  margin-left: 6px;
}
</style>
