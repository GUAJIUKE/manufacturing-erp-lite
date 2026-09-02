<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  apiCreateMaterial,
  apiDisableMaterial,
  apiEnableMaterial,
  apiMaterials,
  apiUpdateMaterial,
} from '@/api/materials'
import type { Material } from '@/types/models'
import { activeStatusMeta } from '@/utils/status'
import { formatDateTime } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const rows = ref<Material[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 20,
  code: '',
  name: '',
  category: '',
  status: '' as '' | 'ACTIVE' | 'DISABLED',
})

const CATEGORIES = ['电子件', '结构件', '紧固件', '包装材料', '其他']

async function load() {
  loading.value = true
  try {
    const page = await apiMaterials({
      page: query.page,
      page_size: query.page_size,
      code: query.code || undefined,
      name: query.name || undefined,
      category: query.category || undefined,
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
  query.category = ''
  query.status = ''
  onSearch()
}

// ---- 新增 / 编辑 ----
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const editingCode = ref('')
const formRef = ref<FormInstance>()
const form = reactive({
  material_name: '',
  unit: '',
  category: '',
  specification: '',
  remark: '',
})
const rules: FormRules = {
  material_name: [{ required: true, message: '请输入物料名称', trigger: 'blur' }],
  unit: [{ required: true, message: '请输入计量单位', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  editingCode.value = ''
  Object.assign(form, { material_name: '', unit: '', category: '', specification: '', remark: '' })
  dialogVisible.value = true
}
function openEdit(row: Material) {
  editingId.value = row.id
  editingCode.value = row.material_code
  Object.assign(form, {
    material_name: row.material_name,
    unit: row.unit,
    category: row.category ?? '',
    specification: row.specification ?? '',
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
      material_name: form.material_name,
      unit: form.unit,
      category: form.category || null,
      specification: form.specification || null,
      remark: form.remark || null,
    }
    if (editingId.value) {
      await apiUpdateMaterial(editingId.value, payload)
      ElMessage.success('物料已更新')
    } else {
      await apiCreateMaterial(payload)
      ElMessage.success('物料已创建')
    }
    dialogVisible.value = false
    onSearch()
  } catch {
    // 业务错误已由 request client toast
  } finally {
    saving.value = false
  }
}

// ---- 停用 / 启用 ----
async function toggleStatus(row: Material) {
  if (row.status === 'ACTIVE') {
    try {
      await ElMessageBox.confirm(
        `停用物料「${row.material_name}」？停用后不可用于新单据。`,
        '停用确认',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    await apiDisableMaterial(row.id)
    ElMessage.success('已停用')
  } else {
    await apiEnableMaterial(row.id)
    ElMessage.success('已启用')
  }
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input v-model="query.code" placeholder="编码搜索" clearable style="width: 170px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.name" placeholder="名称搜索" clearable style="width: 190px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.category" placeholder="全部分类" clearable style="width: 140px" @change="onSearch">
        <el-option v-for="c in CATEGORIES" :key="c" :value="c" :label="c" />
      </el-select>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px" @change="onSearch">
        <el-option value="ACTIVE" label="启用" />
        <el-option value="DISABLED" label="停用" />
      </el-select>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('material:create')" type="primary" :icon="Plus" @click="openCreate">新增物料</el-button>
    </div>

    <!-- 表格 -->
    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column prop="material_code" label="物料编码" width="130" />
      <el-table-column prop="material_name" label="物料名称" min-width="160" />
      <el-table-column prop="category" label="分类" width="110">
        <template #default="{ row }">{{ row.category || '-' }}</template>
      </el-table-column>
      <el-table-column prop="specification" label="规格型号" min-width="140">
        <template #default="{ row }">{{ row.specification || '-' }}</template>
      </el-table-column>
      <el-table-column prop="unit" label="单位" width="80" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :meta="activeStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('material:update')" link type="primary" class="link-btn" @click="openEdit(row as Material)">编辑</el-button>
          <el-button
            v-if="hasPerm(row.status === 'ACTIVE' ? 'material:delete' : 'material:update')"
            link
            :type="row.status === 'ACTIVE' ? 'danger' : 'success'"
            class="link-btn"
            @click="toggleStatus(row as Material)"
          >
            {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无物料数据" />
      </template>
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

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑物料' : '新增物料'" width="520px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="物料编码" v-if="editingId">
          <el-input :model-value="editingCode" disabled />
        </el-form-item>
        <el-form-item label="物料名称" prop="material_name">
          <el-input v-model="form.material_name" maxlength="64" placeholder="如：ESP32 开发板" />
        </el-form-item>
        <el-form-item label="计量单位" prop="unit">
          <el-input v-model="form.unit" maxlength="16" placeholder="如：pcs / set / kg" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" clearable placeholder="选择分类" style="width: 100%">
            <el-option v-for="c in CATEGORIES" :key="c" :value="c" :label="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格型号">
          <el-input v-model="form.specification" maxlength="128" placeholder="规格型号（可空）" />
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

