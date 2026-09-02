<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import {
  apiCreateWarehouse,
  apiDisableWarehouse,
  apiEnableWarehouse,
  apiWarehouses,
  apiUpdateWarehouse,
} from '@/api/warehouses'
import type { Warehouse } from '@/types/models'
import { activeStatusMeta } from '@/utils/status'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const rows = ref<Warehouse[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, code: '', name: '', status: '' as '' | 'ACTIVE' | 'DISABLED' })

async function load() {
  loading.value = true
  try {
    const page = await apiWarehouses({
      page: query.page,
      page_size: query.page_size,
      code: query.code || undefined,
      name: query.name || undefined,
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
  query.code = ''
  query.name = ''
  query.status = ''
  onSearch()
}

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const editingCode = ref('')
const formRef = ref<FormInstance>()
const form = reactive({ warehouse_name: '', remark: '' })
const rules: FormRules = {
  warehouse_name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  editingCode.value = ''
  Object.assign(form, { warehouse_name: '', remark: '' })
  dialogVisible.value = true
}
function openEdit(row: Warehouse) {
  editingId.value = row.id
  editingCode.value = row.warehouse_code
  Object.assign(form, { warehouse_name: row.warehouse_name, remark: row.remark ?? '' })
  dialogVisible.value = true
}

async function onSave() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    const payload = { warehouse_name: form.warehouse_name, remark: form.remark || null }
    if (editingId.value) {
      await apiUpdateWarehouse(editingId.value, payload)
      ElMessage.success('仓库已更新')
    } else {
      await apiCreateWarehouse(payload)
      ElMessage.success('仓库已创建')
    }
    dialogVisible.value = false
    onSearch()
  } catch {
    /* request client 已 toast 后端 message */
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: Warehouse) {
  if (row.status === 'ACTIVE') {
    try {
      await ElMessageBox.confirm(
        `停用仓库「${row.warehouse_name}」？存在库存时后端将拒绝（WAREHOUSE_HAS_STOCK）。`,
        '停用确认',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    // 3010 等业务错误 message 由 request client 展示（如「仓库仍有库存，不能停用」）
    await apiDisableWarehouse(row.id)
    ElMessage.success('已停用')
  } else {
    await apiEnableWarehouse(row.id)
    ElMessage.success('已启用')
  }
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.code" placeholder="编码搜索" clearable style="width: 170px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.name" placeholder="名称搜索" clearable style="width: 190px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px" @change="onSearch">
        <el-option value="ACTIVE" label="启用" />
        <el-option value="DISABLED" label="停用" />
      </el-select>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('warehouse:create')" type="primary" :icon="Plus" @click="openCreate">新增仓库</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column prop="warehouse_code" label="仓库编码" width="140" />
      <el-table-column prop="warehouse_name" label="仓库名称" min-width="180" />
      <el-table-column prop="remark" label="备注" min-width="200">
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="activeStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('warehouse:update')" link type="primary" class="link-btn" @click="openEdit(row as Warehouse)">编辑</el-button>
          <el-button
            v-if="hasPerm(row.status === 'ACTIVE' ? 'warehouse:delete' : 'warehouse:update')"
            link
            :type="row.status === 'ACTIVE' ? 'danger' : 'success'"
            class="link-btn"
            @click="toggleStatus(row as Warehouse)"
          >
            {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无仓库数据" /></template>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑仓库' : '新增仓库'" width="480px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="编码" v-if="editingId">
          <el-input :model-value="editingCode" disabled />
        </el-form-item>
        <el-form-item label="仓库名称" prop="warehouse_name">
          <el-input v-model="form.warehouse_name" maxlength="64" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
