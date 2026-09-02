<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import {
  apiCreateSupplier,
  apiDisableSupplier,
  apiEnableSupplier,
  apiSuppliers,
  apiUpdateSupplier,
} from '@/api/suppliers'
import type { Supplier } from '@/types/models'
import { activeStatusMeta } from '@/utils/status'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const rows = ref<Supplier[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, code: '', name: '', status: '' as '' | 'ACTIVE' | 'DISABLED' })

async function load() {
  loading.value = true
  try {
    const page = await apiSuppliers({
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
const form = reactive({ supplier_name: '', contact_person: '', phone: '', email: '', address: '', remark: '' })
const rules: FormRules = {
  supplier_name: [{ required: true, message: '请输入供应商名称', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  editingCode.value = ''
  Object.assign(form, { supplier_name: '', contact_person: '', phone: '', email: '', address: '', remark: '' })
  dialogVisible.value = true
}
function openEdit(row: Supplier) {
  editingId.value = row.id
  editingCode.value = row.supplier_code
  Object.assign(form, {
    supplier_name: row.supplier_name,
    contact_person: row.contact_person ?? '',
    phone: row.phone ?? '',
    email: row.email ?? '',
    address: row.address ?? '',
    remark: row.remark ?? '',
  })
  dialogVisible.value = true
}

async function onSave() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    const payload = {
      supplier_name: form.supplier_name,
      contact_person: form.contact_person || null,
      phone: form.phone || null,
      email: form.email || null,
      address: form.address || null,
      remark: form.remark || null,
    }
    if (editingId.value) {
      await apiUpdateSupplier(editingId.value, payload)
      ElMessage.success('供应商已更新')
    } else {
      await apiCreateSupplier(payload)
      ElMessage.success('供应商已创建')
    }
    dialogVisible.value = false
    onSearch()
  } catch {
    /* request client 已 toast 后端 message */
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: Supplier) {
  if (row.status === 'ACTIVE') {
    try {
      await ElMessageBox.confirm(
        `停用供应商「${row.supplier_name}」？停用后不可用于新采购订单。`,
        '停用确认',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    await apiDisableSupplier(row.id)
    ElMessage.success('已停用')
  } else {
    await apiEnableSupplier(row.id)
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
      <el-button v-if="hasPerm('supplier:create')" type="primary" :icon="Plus" @click="openCreate">新增供应商</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column prop="supplier_code" label="供应商编码" width="130" />
      <el-table-column prop="supplier_name" label="供应商名称" min-width="180" />
      <el-table-column prop="contact_person" label="联系人" width="100">
        <template #default="{ row }">{{ row.contact_person || '-' }}</template>
      </el-table-column>
      <el-table-column prop="phone" label="电话" width="140">
        <template #default="{ row }">{{ row.phone || '-' }}</template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" min-width="160">
        <template #default="{ row }">{{ row.email || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="activeStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('supplier:update')" link type="primary" class="link-btn" @click="openEdit(row as Supplier)">编辑</el-button>
          <el-button
            v-if="hasPerm(row.status === 'ACTIVE' ? 'supplier:delete' : 'supplier:update')"
            link
            :type="row.status === 'ACTIVE' ? 'danger' : 'success'"
            class="link-btn"
            @click="toggleStatus(row as Supplier)"
          >
            {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无供应商数据" /></template>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑供应商' : '新增供应商'" width="540px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="编码" v-if="editingId">
          <el-input :model-value="editingCode" disabled />
        </el-form-item>
        <el-form-item label="供应商名称" prop="supplier_name">
          <el-input v-model="form.supplier_name" maxlength="64" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact_person" maxlength="32" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" maxlength="32" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" maxlength="128" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" maxlength="255" />
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
