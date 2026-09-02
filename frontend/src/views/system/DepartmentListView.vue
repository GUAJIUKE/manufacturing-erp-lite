<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { apiCreateDepartment, apiDepartments, apiDisableDepartment, apiUpdateDepartment } from '@/api/system'
import type { Department } from '@/types/models'
import type { ActiveStatus } from '@/types/enums'
import { activeStatusMeta } from '@/utils/status'
import { formatDateTime } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const rows = ref<Department[]>([])

async function load() {
  loading.value = true
  try {
    rows.value = await apiDepartments()
  } finally {
    loading.value = false
  }
}

function deptName(id: number | null): string {
  if (id == null) return '-'
  return rows.value.find((d) => d.id === id)?.dept_name ?? `#${id}`
}

// ---------- 新建/编辑 ----------
const formRef = ref<FormInstance>()
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  dept_code: '',
  dept_name: '',
  parent_id: null as number | null,
  sort_order: 0,
  remark: '',
  status: 'ACTIVE' as ActiveStatus,
})
const rules: FormRules = {
  dept_code: [{ required: true, message: '请输入部门编码', trigger: 'blur' }],
  dept_name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { dept_code: '', dept_name: '', parent_id: null, sort_order: rows.value.length + 1, remark: '', status: 'ACTIVE' })
  dialogVisible.value = true
}

function openEdit(d: Department) {
  editingId.value = d.id
  Object.assign(form, {
    dept_code: d.dept_code,
    dept_name: d.dept_name,
    parent_id: d.parent_id,
    sort_order: d.sort_order,
    remark: d.remark ?? '',
    status: d.status,
  })
  dialogVisible.value = true
}

async function onSave() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    if (editingId.value == null) {
      await apiCreateDepartment({
        dept_code: form.dept_code.trim(),
        dept_name: form.dept_name.trim(),
        parent_id: form.parent_id,
        sort_order: form.sort_order,
        remark: form.remark.trim() || null,
      })
      ElMessage.success('部门已创建')
    } else {
      await apiUpdateDepartment(editingId.value, {
        dept_name: form.dept_name.trim(),
        parent_id: form.parent_id,
        sort_order: form.sort_order,
        remark: form.remark.trim() || null,
        status: form.status,
      })
      ElMessage.success('部门已更新')
    }
    dialogVisible.value = false
    load()
  } catch {
    /* toast */
  } finally {
    saving.value = false
  }
}

// ---------- 启停 ----------
async function onToggle(d: Department) {
  if (d.status === 'ACTIVE') {
    try {
      await ElMessageBox.confirm(`停用部门 ${d.dept_name}？停用后该部门用户审批范围将受影响。`, '停用部门', {
        type: 'warning',
        confirmButtonText: '停用',
      })
    } catch {
      return
    }
    try {
      await apiDisableDepartment(d.id)
      ElMessage.success('已停用')
      load()
    } catch {
      /* toast */
    }
  } else {
    try {
      await apiUpdateDepartment(d.id, { status: 'ACTIVE' })
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
      <span class="text-muted" style="font-size: 13px">共 {{ rows.length }} 个部门</span>
      <div class="spacer" />
      <el-button v-if="hasPerm('department:create')" type="primary" :icon="Plus" @click="openCreate">新建部门</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="dept_code" label="部门编码" width="140">
        <template #default="{ row }"><span class="mono">{{ (row as Department).dept_code }}</span></template>
      </el-table-column>
      <el-table-column prop="dept_name" label="部门名称" min-width="160">
        <template #default="{ row }">
          <span style="font-weight: 600">{{ (row as Department).dept_name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="上级部门" width="160">
        <template #default="{ row }">{{ deptName((row as Department).parent_id) }}</template>
      </el-table-column>
      <el-table-column prop="sort_order" label="排序" width="70" align="center" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="activeStatusMeta((row as Department).status)" /></template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="180">
        <template #default="{ row }">{{ (row as Department).remark || '-' }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="165">
        <template #default="{ row }">{{ formatDateTime((row as Department).created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('department:update')" link type="primary" class="link-btn" @click="openEdit(row as Department)">编辑</el-button>
          <el-button
            v-if="hasPerm('department:delete') || hasPerm('department:update')"
            link
            :type="(row as Department).status === 'ACTIVE' ? 'danger' : 'success'"
            class="link-btn"
            @click="onToggle(row as Department)"
          >
            {{ (row as Department).status === 'ACTIVE' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无部门" /></template>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId == null ? '新建部门' : `编辑部门 ${form.dept_name}`" width="480px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="部门编码" prop="dept_code">
          <el-input v-model="form.dept_code" :disabled="editingId != null" placeholder="如：DEPT-001" />
        </el-form-item>
        <el-form-item label="部门名称" prop="dept_name">
          <el-input v-model="form.dept_name" placeholder="如：生产部" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="form.parent_id" clearable filterable placeholder="无（顶级部门）" style="width: 100%">
            <el-option
              v-for="d in rows.filter((x) => x.id !== editingId)"
              :key="d.id"
              :value="d.id"
              :label="d.dept_name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="可空" />
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
.mono {
  font-family: 'Consolas', 'Sarosa Mono SC', 'Sarasa Mono SC', monospace;
  font-size: 12px;
}
</style>
