<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiCreateReceipt } from '@/api/purchaseReceipts'
import { apiPo, apiPos } from '@/api/purchaseOrders'
import { formatDateTime, formatQuantity } from '@/utils/format'
import type { PurchaseOrder, PoItem } from '@/types/models'
import WarehouseSelect from '@/components/WarehouseSelect.vue'

const route = useRoute()
const router = useRouter()

interface ReceiveLine {
  po_item_id: number
  material_code: string
  material_name: string
  ordered: number
  received: number
  remaining: number
  unit_price: string
  thisQty: string
}

const loading = ref(false)
const saving = ref(false)
const poOptions = ref<PurchaseOrder[]>([])
const selectedPoId = ref<number | null>(null)
const selectedPo = ref<PurchaseOrder | null>(null)
const lines = ref<ReceiveLine[]>([])
const warehouseId = ref<number | null>(null)
const remark = ref('')

function num(v: string | number | null | undefined): number {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}

/** 加载可收货 PO（CONFIRMED / PARTIALLY_RECEIVED） */
async function loadPoOptions() {
  try {
    const [a, b] = await Promise.all([
      apiPos({ page: 1, page_size: 200, status: 'CONFIRMED' }),
      apiPos({ page: 1, page_size: 200, status: 'PARTIALLY_RECEIVED' }),
    ])
    const seen = new Set<number>()
    poOptions.value = [...a.items, ...b.items].filter((p) => {
      if (seen.has(p.id)) return false
      seen.add(p.id)
      return true
    })
  } catch {
    /* toast */
  }
}

async function onPoChange(poId: number | null) {
  selectedPo.value = null
  lines.value = []
  if (!poId) return
  loading.value = true
  try {
    const po = await apiPo(poId)
    selectedPo.value = po
    lines.value = (po.items ?? [])
      .map((it: PoItem) => ({
        po_item_id: it.id,
        material_code: it.material_code || '',
        material_name: it.material_name || '',
        ordered: num(it.ordered_quantity),
        received: num(it.received_quantity),
        remaining: Math.max(0, num(it.ordered_quantity) - num(it.received_quantity)),
        unit_price: it.unit_price,
        thisQty: '',
      }))
      .filter((l) => l.remaining > 0)
  } finally {
    loading.value = false
  }
}

const receivableTotal = computed(() => lines.value.reduce((s, l) => s + num(l.thisQty), 0))

function lineInvalid(line: ReceiveLine): string | null {
  const q = num(line.thisQty)
  if (line.thisQty.trim() === '') return '请输入本次数量'
  if (q <= 0) return '数量必须大于 0'
  if (q > line.remaining) return `超过剩余可收 ${formatQuantity(line.remaining)}`
  return null
}

const canSubmit = computed(() => {
  if (!selectedPo.value || !warehouseId.value) return false
  if (lines.value.length === 0) return false
  return lines.value.every((l) => !lineInvalid(l))
})

async function onSubmit() {
  if (!selectedPo.value || !warehouseId.value) return
  const items = lines.value
    .filter((l) => num(l.thisQty) > 0)
    .map((l) => ({ po_item_id: l.po_item_id, received_quantity: l.thisQty.trim() }))
  if (items.length === 0) {
    ElMessage.warning('至少录入一条本次入库数量')
    return
  }
  saving.value = true
  try {
    const rc = await apiCreateReceipt({
      po_id: selectedPo.value.id,
      warehouse_id: warehouseId.value,
      receipt_date: null,
      remark: remark.value || null,
      items,
    })
    ElMessage.success(`入库单 ${rc.receipt_no} 已过账`)
    router.replace(`/purchase-receipts/${rc.id}`)
  } catch {
    // 6002 等业务错误 message 由 request client 展示
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadPoOptions()
  const preselect = Number(route.query.po)
  if (preselect && poOptions.value.some((p) => p.id === preselect)) {
    selectedPoId.value = preselect
    await onPoChange(preselect)
  }
})
</script>

<template>
  <div class="page-card">
    <el-page-header @back="router.back()">
      <template #content><span class="ph-title">新建入库单（创建即过账）</span></template>
    </el-page-header>

    <el-form label-width="100px" style="max-width: 860px; margin-top: 16px">
      <el-form-item label="采购订单" required>
        <el-select
          v-model="selectedPoId"
          filterable
          placeholder="选择 CONFIRMED / PARTIALLY_RECEIVED 的 PO"
          style="width: 100%"
          :disabled="loading"
          @change="onPoChange"
        >
          <el-option v-for="p in poOptions" :key="p.id" :value="p.id" :label="`${p.po_no} · ${p.supplier_name || ''} · ${p.status}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="收货仓库" required>
        <WarehouseSelect v-model="warehouseId" placeholder="选择仓库（仅启用）" style="width: 360px" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="remark" maxlength="255" placeholder="可空" style="width: 460px" />
      </el-form-item>
    </el-form>

    <template v-if="selectedPo">
      <el-descriptions :column="4" border size="small" class="po-meta">
        <el-descriptions-item label="PO">{{ selectedPo.po_no }}</el-descriptions-item>
        <el-descriptions-item label="供应商">{{ selectedPo.supplier_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ selectedPo.status }}</el-descriptions-item>
        <el-descriptions-item label="下单日期">{{ selectedPo.order_date }}</el-descriptions-item>
      </el-descriptions>

      <h3 class="block-title">收货明细（本次数量 ≤ 剩余可收）</h3>
      <el-table v-loading="loading" :data="lines" border stripe>
        <el-table-column label="物料" min-width="200">
          <template #default="{ row }">
            <div>{{ (row as ReceiveLine).material_name }}</div>
            <div class="text-muted" style="font-size: 12px">{{ (row as ReceiveLine).material_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Ordered（订购）" width="120" align="right">
          <template #default="{ row }">{{ formatQuantity((row as ReceiveLine).ordered) }}</template>
        </el-table-column>
        <el-table-column label="Received（已收）" width="120" align="right">
          <template #default="{ row }">
            <span class="text-muted">{{ formatQuantity((row as ReceiveLine).received) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Remaining（剩余可收）" width="150" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600">{{ formatQuantity((row as ReceiveLine).remaining) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="本次入库数量" width="160">
          <template #default="{ row }">
            <el-input
              :model-value="(row as ReceiveLine).thisQty"
              placeholder="0 < 本次 ≤ 剩余"
              :class="{ 'input-error': ((row as ReceiveLine).thisQty.trim() !== '' && lineInvalid(row as ReceiveLine)) }"
              @update:model-value="(v: string) => { (row as ReceiveLine).thisQty = v }"
            />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <span v-if="(row as ReceiveLine).thisQty.trim() === ''" class="text-muted">待录入</span>
            <el-tag v-else-if="!lineInvalid(row as ReceiveLine)" type="success" size="small">合法</el-tag>
            <el-tag v-else type="danger" size="small">{{ lineInvalid(row as ReceiveLine) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单价快照" width="110" align="right">
          <template #default="{ row }">{{ formatQuantity((row as ReceiveLine).unit_price) }}</template>
        </el-table-column>
      </el-table>

      <div class="submit-bar">
        <span class="text-muted" style="font-size: 12px">本次合计：{{ formatQuantity(receivableTotal) }} 单位</span>
        <div class="spacer" />
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="onSubmit">过账入库</el-button>
      </div>
      <p v-if="!canSubmit" class="hint text-muted">请选择 PO 与仓库，并录入合法的本次数量（每行 ≤ 剩余可收）</p>
    </template>
    <el-empty v-else description="请选择采购订单后录入收货明细" :image-size="80" style="margin-top: 24px" />
  </div>
</template>

<style scoped>
.ph-title {
  font-weight: 600;
  font-size: 16px;
  color: #1f2329;
}
.po-meta {
  margin: 8px 0 0;
}
.block-title {
  font-size: 14px;
  color: #1f2329;
  margin: 20px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #2f6fed;
}
.submit-bar {
  margin-top: 16px;
  display: flex;
  align-items: center;
}
.spacer {
  flex: 1;
}
.hint {
  margin: 8px 0 0;
  font-size: 12px;
}
.input-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px #d93026 inset;
}
</style>
