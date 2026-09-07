<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  apiBalances,
} from '@/api/inventory'
import {
  apiCreateReconciliation,
  apiReconciliation,
  apiUpdateReconciliation,
} from '@/api/stockReconciliations'
import { useAuthStore } from '@/stores/auth'
import type { ReconciliationItemLine, StockReconciliation } from '@/types/models'
import { formatQuantity } from '@/utils/format'
import WarehouseSelect from '@/components/WarehouseSelect.vue'
import MaterialSelect from '@/components/MaterialSelect.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const editId = computed(() => {
  const id = route.params.id
  return id ? Number(id) : null
})
const isEdit = computed(() => editId.value !== null)

const saving = ref(false)
const loading = ref(false)
const warehouseId = ref<number | null>(null)
const reason = ref('')
const remark = ref('')
const version = ref(1)

interface LineRow {
  material_id: number | null
  physical: string
  valuation_rate: string
  remark: string
  // read-only preview（后端快照权威；新行按当前余额建议）
  bookQty: string
  bookAmount: string
  bookAvg: string
}

const lines = ref<LineRow[]>([])

// warehouse -> (material_id -> book suggestion) 来自当前库存
const bookMap = reactive<Record<number, Record<number, { q: string; a: string; v: string }>>>({})

async function refreshBookSuggestions() {
  if (!warehouseId.value) return
  const data = await apiBalances({ page: 1, page_size: 200, warehouse_id: warehouseId.value })
  const map: Record<number, { q: string; a: string; v: string }> = {}
  for (const b of data.items) {
    map[b.material_id] = { q: b.quantity, a: b.total_amount, v: b.average_unit_cost }
  }
  bookMap[warehouseId.value] = map
  // 刷新各行"新物料"预览（既有行来自服务端快照，不覆盖）
  for (const line of lines.value) {
    if (line.material_id && !(line.material_id in map)) {
      syncPreview(line, null)
    }
  }
}

function bookOf(wh: number | null, mat: number | null): { q: string; a: string; v: string } | null {
  if (!wh || !mat) return null
  return bookMap[wh]?.[mat] ?? null
}

function syncPreview(line: LineRow, book: { q: string; a: string; v: string } | null) {
  line.bookQty = book?.q ?? '0'
  line.bookAmount = book?.a ?? '0'
  line.bookAvg = book?.v ?? '0'
}

function addLine() {
  lines.value.push({
    material_id: null,
    physical: '',
    valuation_rate: '',
    remark: '',
    bookQty: '0',
    bookAmount: '0',
    bookAvg: '0',
  })
}

function removeLine(index: number) {
  lines.value.splice(index, 1)
}

watch(warehouseId, () => {
  if (!warehouseId.value) return
  if (!isEdit.value) lines.value = []
  refreshBookSuggestions().catch(() => undefined)
})

function onMaterialChange(line: any, val: number | null) {
  line.material_id = val
  const book = bookOf(warehouseId.value, val)
  syncPreview(line, book)
  if (book) line.valuation_rate = book.v // OQ-11：一次性"建议值"（非权威默认）
}

function diffOf(line: any): number {
  const p = Number(line.physical)
  const b = Number(line.bookQty || 0)
  if (!Number.isFinite(p)) return NaN
  return p - b
}

async function loadForEdit() {
  if (!editId.value) return
  loading.value = true
  try {
    const doc: StockReconciliation = await apiReconciliation(editId.value)
    if (!auth.permissions.includes('reconcile:update')) {
      ElMessage.warning('无编辑权限')
      router.replace(`/stock-reconciliations/${editId.value}`)
      return
    }
    warehouseId.value = doc.warehouse_id
    reason.value = doc.reason || ''
    remark.value = doc.remark || ''
    version.value = doc.version
    lines.value = (doc.items || []).map((it) => ({
      material_id: it.material_id,
      physical: it.physical_quantity,
      valuation_rate: it.valuation_rate || '',
      remark: it.remark || '',
      bookQty: it.book_quantity_snapshot,
      bookAmount: it.book_total_amount_snapshot,
      bookAvg: it.book_avg_cost_snapshot,
    }))
  } finally {
    loading.value = false
  }
}

function buildItems(): ReconciliationItemLine[] {
  return lines.value
    .filter((l) => l.material_id)
    .map((l) => ({
      material_id: l.material_id as number,
      physical_quantity: String(l.physical).trim(),
      valuation_rate: l.valuation_rate.trim() ? l.valuation_rate.trim() : null,
      remark: l.remark.trim() || null,
    }))
}

async function onSave() {
  if (!warehouseId.value) {
    ElMessage.warning('请选择仓库')
    return
  }
  if (lines.value.filter((l) => l.material_id).length === 0) {
    ElMessage.warning('请至少添加一条盘点明细')
    return
  }
  for (const l of lines.value) {
    if (!l.material_id) continue
    const q = Number(l.physical)
    if (!Number.isFinite(q) || q < 0) {
      ElMessage.warning('实盘数量必须为 >= 0 的数字')
      return
    }
    const diff = diffOf(l)
    if (diff > 0 && (!l.valuation_rate.trim() || Number(l.valuation_rate) <= 0)) {
      ElMessage.warning(`物料 ${l.material_id} 为盘盈（+${formatQuantity(diff)}），需填写大于 0 的入账单价`)
      return
    }
  }
  const payload = {
    reason: reason.value.trim() || null,
    remark: remark.value.trim() || null,
    items: buildItems(),
  }
  saving.value = true
  try {
    if (isEdit.value) {
      const doc = await apiUpdateReconciliation(editId.value!, { ...payload, version: version.value })
      ElMessage.success('盘点草稿已更新')
      router.replace(`/stock-reconciliations/${doc.id}`)
    } else {
      const doc = await apiCreateReconciliation({ warehouse_id: warehouseId.value, ...payload })
      ElMessage.success('盘点单已创建（草稿）')
      router.replace(`/stock-reconciliations/${doc.id}`)
    }
  } catch {
    /* 错误 toast 已由 request 层处理 */
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (isEdit.value) {
    await loadForEdit()
  } else {
    addLine()
  }
})
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <span>{{ isEdit ? '编辑库存盘点（草稿）' : '新建库存盘点' }}</span>
    </template>

    <el-form label-width="100px" style="max-width: 860px">
      <el-form-item label="仓库">
        <WarehouseSelect v-model="warehouseId" :disabled="isEdit" />
      </el-form-item>
      <el-form-item label="盘点原因">
        <el-input v-model="reason" type="textarea" :rows="2" maxlength="500" placeholder="可选：本次盘点的业务背景" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="remark" maxlength="255" />
      </el-form-item>
    </el-form>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="快照说明"
      description="账面快照在明细加入时由后端固化，不会随后续业务静默刷新；若提交到过账前该仓该料发生出入库，过账会被判为 stale 并拒绝（需重盘）。差异/金额由后端权威计算，此处仅为预览。"
      style="margin-bottom: 12px"
    />

    <el-table :data="lines" border>
      <el-table-column label="物料" min-width="190">
        <template #default="{ row }">
          <MaterialSelect :model-value="row.material_id" @update:model-value="(v: number | null) => onMaterialChange(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="账面快照（只读）" min-width="150">
        <template #default="{ row }">
          <div class="mono">数量 {{ formatQuantity(row.bookQty) }}</div>
          <div class="mono dim">金额 ¥{{ Number(row.bookAmount || 0).toFixed(2) }} · 均价 {{ formatQuantity(row.bookAvg) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="实盘数量" width="150">
        <template #default="{ row }">
          <el-input v-model="row.physical" placeholder=">= 0" />
        </template>
      </el-table-column>
      <el-table-column label="差异（预览）" width="120">
        <template #default="{ row }">
          <span v-if="row.material_id && row.physical !== ''" :class="{ gain: diffOf(row) > 0, loss: diffOf(row) < 0 }">
            {{ diffOf(row) > 0 ? '+' : '' }}{{ formatQuantity(diffOf(row)) }}
          </span>
          <span v-else class="dim">-</span>
        </template>
      </el-table-column>
      <el-table-column label="入账单价(盘盈必填)" width="170">
        <template #default="{ row }">
          <el-input v-model="row.valuation_rate" placeholder="建议值=快照均价" />
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="140">
        <template #default="{ row }">
          <el-input v-model="row.remark" maxlength="255" />
        </template>
      </el-table-column>
      <el-table-column width="60" align="center">
        <template #default="{ $index }">
          <el-button link type="danger" @click="removeLine($index)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-button type="primary" plain @click="addLine">+ 添加明细</el-button>
      </template>
    </el-table>

    <div style="margin-top: 12px; display: flex; gap: 8px">
      <el-button type="primary" plain @click="addLine">+ 添加明细</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">
        {{ isEdit ? '保存草稿' : '创建盘点单' }}
      </el-button>
      <el-button @click="router.back()">返回</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.dim {
  color: #8a919f;
}
.gain {
  color: #e65100;
  font-weight: 600;
}
.loss {
  color: #089981;
  font-weight: 600;
}
</style>
