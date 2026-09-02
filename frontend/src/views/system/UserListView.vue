<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { apiCreateUser, apiDisableUser, apiUpdateUser, apiUsers } from '@/api/system'
import { apiRoles } from '@/api/system'
import { apiDepartments } from '@/api/system'
import type { Department, Role, User } from '@/types/models'
import type { UserStatus } from '@/types/enums'
import { userStatusMeta, roleCodeLabel } from '@/utils/status'
import { formatDateTime } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'

const auth = useAuthStore()
const loading = ref(false)
const rows = ref<User[]>([])
const total = ref(0)
const roles = ref<Role[]>([])
const departments = ref<Department[]>([])
const query = reactive({
  page: 1,
  page_size: 20,
  keyword: '',
  status: '' as '' | UserStatus,
})

// ---------- 列表 ----------
async function load() {
  loading.value = true
  try {
    const page = await apiUsers({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
    })
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}
function onSearch() {
  query.page = 1
  load()
}
function onReset() {
  Object.assign(query, { keyword: '', status: '' })
  onSearch()
}

// ---------- 新建/编辑 ----------
const formRef = ref<FormInstance>()
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  username: '',
  password: '',
  real_name: '',
  email: '',
  phone: '',
  department_id: null as number | null,
  role_id: null as number | null,
  status: 'ACTIVE' as UserStatus,
})
const rules: FormRules = {
  username: [
    { required: true, message: '请输入登录账号', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: '2-64 位字母/数字/._-' },
  ],
  password: [
    { required: true, message: '请输入初始密码（至少 6 位）', trigger: 'blur' },
    { min: 6, max: 128, message: '至少 6 位', trigger: 'blur' },
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  role_id: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

async function ensureOptions() {
  try {
    const [r, d] = await Promise.all([apiRoles(), apiDepartments()])
    roles.value = r
    departments.value = d
  } catch {
    /* 403/网络错误已由 client toast */
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    username: '',
    password: '',
    real_name: '',
    email: '',
    phone: '',
    department_id: null,
    role_id: null,
    status: 'ACTIVE' as UserStatus,
  })
  dialogVisible.value = true
  ensureOptions()
}

function openEdit(row: User) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username,
    password: '', // 留空 = 不修改
    real_name: row.real_name,
    email: row.email ?? '',
    phone: row.phone ?? '',
    department_id: row.department_id,
    role_id: row.role_id,
    status: row.status,
  })
  dialogVisible.value = true
  ensureOptions()
}

async function onSave() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    if (editingId.value == null) {
      await apiCreateUser({
        username: form.username.trim(),
        password: form.password,
        real_name: form.real_name.trim(),
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        department_id: form.department_id,
        role_id: form.role_id!,
      })
      ElMessage.success('用户已创建')
    } else {
      await apiUpdateUser(editingId.value, {
        real_name: form.real_name.trim(),
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        department_id: form.department_id,
        role_id: form.role_id ?? undefined,
        status: form.status,
        ...(form.password ? { password: form.password } : {}),
      })
      ElMessage.success('用户已更新')
    }
    dialogVisible.value = false
    load()
  } catch {
    /* 业务错误由 client toast */
  } finally {
    saving.value = false
  }
}

// ---------- 启停 ----------
async function onToggle(row: User) {
  if (row.username === auth.user?.username) {
    ElMessage.warning('不能停用自己的账号')
    return
  }
  if (row.status === 'ACTIVE') {
    try {
      await ElMessageBox.confirm(`停用用户 ${row.real_name}（${row.username}）？停用后无法登录。`, '停用用户', {
        type: 'warning',
        confirmButtonText: '停用',
      })
    } catch {
      return
    }
    try {
      await apiDisableUser(row.id)
      ElMessage.success('已停用')
      load()
    } catch {
      /* toast */
    }
  } else {
    try {
      await apiUpdateUser(row.id, { status: 'ACTIVE' })
      ElMessage.success('已启用')
      load()
    } catch {
      /* toast */
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="账号/姓名搜索" clearable style="width: 200px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px" @change="onSearch">
        <el-option value="ACTIVE" label="启用" />
        <el-option value="DISABLED" label="停用" />
      </el-select>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('user:create')" type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="username" label="账号" width="140">
        <template #default="{ row }">
          <span style="font-weight: 600">{{ (row as User).username }}</span>
          <el-tag v-if="(row as User).username === auth.user?.username" size="small" type="info" effect="plain" style="margin-left: 6px">我</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="real_name" label="姓名" width="110" />
      <el-table-column label="角色" width="150">
        <template #default="{ row }">
          <div>{{ (row as User).role_name || '-' }}</div>
          <div class="text-muted" style="font-size: 12px">{{ roleCodeLabel((row as User).role_code ?? '') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="部门" width="140">
        <template #default="{ row }">{{ (row as User).department_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" min-width="170">
        <template #default="{ row }">{{ (row as User).email || '-' }}</template>
      </el-table-column>
      <el-table-column prop="phone" label="电话" width="130">
        <template #default="{ row }">{{ (row as User).phone || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="userStatusMeta((row as User).status)" /></template>
      </el-table-column>
      <el-table-column label="最后登录" width="165">
        <template #default="{ row }">{{ formatDateTime((row as User).last_login_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('user:update')" link type="primary" class="link-btn" @click="openEdit(row as User)">编辑</el-button>
          <el-button
            v-if="hasPerm('user:delete') || hasPerm('user:update')"
            link
            :type="(row as User).status === 'ACTIVE' ? 'danger' : 'success'"
            class="link-btn"
            :disabled="(row as User).username === auth.user?.username"
            @click="onToggle(row as User)"
          >
            {{ (row as User).status === 'ACTIVE' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无用户" /></template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[10, 20, 50, 100]"
        @change="load"
      />
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建用户' : `编辑用户 ${form.username}`" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="登录账号" prop="username">
          <el-input v-model="form.username" :disabled="editingId != null" placeholder="字母/数字/._-，2-64 位" />
        </el-form-item>
        <el-form-item :label="editingId == null ? '初始密码' : '重置密码'" :prop="editingId == null ? 'password' : ''">
          <el-input v-model="form.password" type="password" show-password :placeholder="editingId == null ? '至少 6 位' : '留空则不修改密码'" />
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="form.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="可空" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" placeholder="可空" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="form.department_id" clearable filterable placeholder="选择部门（可空）" style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :value="d.id" :label="d.dept_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色" prop="role_id">
          <el-select v-model="form.role_id" filterable placeholder="选择角色" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :value="r.id" :label="`${r.role_name}（${roleCodeLabel(r.role_code)}）`" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingId != null" label="状态">
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
  </div>
</template>

<style scoped>
.spacer {
  flex: 1;
}
</style>
