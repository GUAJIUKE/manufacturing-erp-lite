<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { apiPolicies, apiCreatePolicy, apiUpdatePolicy } from '@/api/inventoryPolicies'
import { apiMaterials } from '@/api/materials'
import { apiWarehouses } from '@/api/warehouses'
import type { InventoryPolicy, Material, Warehouse } from '@/types/models'
import { formatQuantity } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import MaterialSelect from '@/components/MaterialSelect.vue'
import WarehouseSelect from '@/components/WarehouseSelect.vue'

const loading = ref(false)
const rows = ref<InventoryPolicy[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, warehouse_id: null as number | null, material_id: null as number | null })

// 名称映射（列表行展示用）。demo/中小数据量一次拉全；大库可改远程搜索。
const warehouses = ref<Warehouse[]>([])
const materials = ref<Material[]>([])
const whName = computed(() => {
  const m = new Map<number, string>()
  warehouses.value.forEach((w) => m.set(w.id, w.warehouse_name))
  return m
})
const matName = computed(() => {
  const m = new Map<number, string>()
  materials.value.forEach((x) => m.set(x.id, x.material_name))
  return m
})

async function loadMaps() {
  const [w, m] = await Promise.all([
    apiWarehouses({ page: 1, page_size: 200 }),
    apiMaterials({ page: 1, page_size: 200 }),
  ])
  warehouses.value = w.items
  materials.value = m.items
}

async function load() {
  loading.value = true
  try {
    const page = await apiPolicies({
      page: query.page,
      page_size: query.page_size,
      warehouse_id: query.warehouse_id ?? undefined,
      material_id: query.material_id ?? undefined,
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

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({
  warehouse_id: null as number | null,
  material_id: null as number | null,
  safety_stock: '0',
  reorder_point: '',
  max_stock: '',
  remark: '',
})
const rules: FormRules = {
  warehouse_id: [{ required: true, message: '请选择仓库', trigger: 'change' }],
  material_id: [{ required: true, message: '请选择物料', trigger: 'change' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { warehouse_id: null, material_id: null, safety_stock: '0', reorder_point: '', max_stock: '', remark: '' })
  dialogVisible.value = true
}
function openEdit(row: InventoryPolicy) {
  editingId.value = row.id
  Object.assign(form, {
    warehouse_id: row.warehouse_id,
    material_id: row.material_id,
    safety_stock: row.safety_stock,
    reorder_point: row.reorder_point ?? '',
    max_stock: row.max_stock ?? '',
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
      warehouse_id: form.warehouse_id as number,
      material_id: form.material_id as number,
      safety_stock: form.safety_stock,
      reorder_point: form.reorder_point || null,
      max_stock: form.max_stock || null,
      remark: form.remark || null,
    }
    if (editingId.value) {
      await apiUpdatePolicy(editingId.value, payload)
      ElMessage.success('库存策略已更新')
    } else {
      await apiCreatePolicy(payload)
      ElMessage.success('库存策略已创建')
    }
    dialogVisible.value = false
    onSearch()
  } catch {
    /* 业务错误（如 3011 重复策略）由 request client toast */
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadMaps()
  load()
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <WarehouseSelect v-model="query.warehouse_id" placeholder="按仓库筛选" style="width: 200px" />
      <MaterialSelect v-model="query.material_id" placeholder="按物料筛选" style="width: 200px" />
      <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('inventory_policy:create')" type="primary" :icon="Plus" @click="openCreate">新增策略</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column label="仓库" min-width="150">
        <template #default="{ row }">
          {{ whName.get(row.warehouse_id) ?? `#${row.warehouse_id}` }}
        </template>
      </el-table-column>
      <el-table-column label="物料" min-width="200">
        <template #default="{ row }">
          {{ matName.get(row.material_id) ?? `#${row.material_id}` }}
          <span class="text-muted" style="font-size: 12px">({{ row.material_id }})</span>
        </template>
      </el-table-column>
      <el-table-column label="安全库存" width="110" align="right">
        <template #default="{ row }">{{ formatQuantity(row.safety_stock) }}</template>
      </el-table-column>
      <el-table-column label="补货点" width="110" align="right">
        <template #default="{ row }">{{ row.reorder_point === null ? '-' : formatQuantity(row.reorder_point) }}</template>
      </el-table-column>
      <el-table-column label="最高库存" width="110" align="right">
        <template #default="{ row }">{{ row.max_stock === null ? '-' : formatQuantity(row.max_stock) }}</template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="160">
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPerm('inventory_policy:update')" link type="primary" class="link-btn" @click="openEdit(row as InventoryPolicy)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无库存策略" /></template>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑库存策略' : '新增库存策略'" width="520px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="仓库" prop="warehouse_id">
          <WarehouseSelect v-model="form.warehouse_id" :disabled="Boolean(editingId)" />
        </el-form-item>
        <el-form-item label="物料" prop="material_id">
          <MaterialSelect v-model="form.material_id" :disabled="Boolean(editingId)" />
        </el-form-item>
        <el-form-item label="安全库存" prop="safety_stock">
          <el-input v-model="form.safety_stock" placeholder=">= 0">
            <template #append>单位</template>
          </el-input>
        </el-form-item>
        <el-form-item label="补货点">
          <el-input v-model="form.reorder_point" placeholder="可选，>= 0" />
        </el-form-item>
        <el-form-item label="最高库存">
          <el-input v-model="form.max_stock" placeholder="可选，> 0" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
        <el-form-item v-if="editingId">
          <span class="text-muted" style="font-size: 12px">仓库 + 物料 组合创建后不可变更</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
