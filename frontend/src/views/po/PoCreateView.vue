<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { apiCreatePo } from '@/api/purchaseOrders'
import { apiPr, apiPrs } from '@/api/purchaseRequisitions'
import { apiMaterial } from '@/api/materials'
import { formatMoney, formatQuantity } from '@/utils/format'
import type { Material, PurchaseRequisition } from '@/types/models'
import SupplierSelect from '@/components/SupplierSelect.vue'
import MaterialSelect from '@/components/MaterialSelect.vue'

const route = useRoute()
const router = useRouter()

interface PickRow {
  key: number
  pr_id: number
  pr_no: string
  pr_item_id: number
  line_no: number
  material_id: number
  material_code: string
  material_name: string
  unit: string | null
  remaining: number
  qty: string // 本次转出（0/空 = 不转）
}

interface AggItem {
  material_id: number
  material_code: string
  material_name: string
  unit: string | null
  ordered: number
  sources: { pr_item_id: number; pr_no: string; pr_item_line_no: number; quantity: number }[]
  unit_price: string
  remark: string
}

const loading = ref(false)
const sourceRows = ref<PickRow[]>([])
const header = reactive({
  supplier_id: null as number | null,
  expected_date: '',
  remark: '',
})
const aggItems = ref<AggItem[]>([])
const saving = ref(false)
const addingManual = ref(false)
const manualMaterialId = ref<number | null>(null)
const manualRemark = ref('')

let keySeq = 1

function num(v: string): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 拉取所有 APPROVED 且仍有剩余可转的 PR 明细 */
async function loadSources() {
  loading.value = true
  try {
    const prs: PurchaseRequisition[] = []
    // PR 列表不带明细：分页拉 APPROVED 后逐单取详情
    for (let page = 1; page <= 3; page++) {
      const p = await apiPrs({ page, page_size: 200, status: 'APPROVED' })
      prs.push(...p.items)
      if (page >= p.total_pages) break
    }
    const rows: PickRow[] = []
    for (const pr of prs) {
      const detail = await apiPr(pr.id)
      for (const it of detail.items ?? []) {
        const remaining = num(it.requested_quantity) - num(it.converted_quantity)
        if (remaining > 0) {
          rows.push({
            key: keySeq++,
            pr_id: detail.id,
            pr_no: detail.pr_no,
            pr_item_id: it.id,
            line_no: it.line_no,
            material_id: it.material_id,
            material_code: it.material_code || '',
            material_name: it.material_name || '',
            unit: null,
            remaining,
            qty: '',
          })
        }
      }
    }
    sourceRows.value = rows
    // 路由带 pr 参数 → 快捷整单转换
    const preselectPr = Number(route.query.pr)
    if (preselectPr) {
      const hit = rows.filter((r) => r.pr_id === preselectPr)
      if (hit.length > 0) {
        hit.forEach((r) => (r.qty = String(r.remaining)))
      }
    }
    rebuild()
  } catch {
    /* toast 已展示 */
  } finally {
    loading.value = false
  }
}

/** 前端实时聚合：同物料 source 合并 → ordered = Σ(source qty)；每行不超过剩余可转 */
function rebuild() {
  const picked = sourceRows.value.filter((r) => num(r.qty) > 0)
  const map = new Map<number, AggItem>()
  for (const r of picked) {
    const finalQty = Math.min(num(r.qty), r.remaining)
    if (finalQty <= 0) continue
    let agg = map.get(r.material_id)
    if (!agg) {
      agg = {
        material_id: r.material_id,
        material_code: r.material_code,
        material_name: r.material_name,
        unit: r.unit,
        ordered: 0,
        sources: [],
        unit_price: '',
        remark: '',
      }
      map.set(r.material_id, agg)
    }
    agg.ordered += finalQty
    agg.sources.push({
      pr_item_id: r.pr_item_id,
      pr_no: r.pr_no,
      pr_item_line_no: r.line_no,
      quantity: finalQty,
    })
  }
  aggItems.value = [...map.values()]
}

function onQtyChange() {
  rebuild()
}

async function addManualItem() {
  if (!manualMaterialId.value) return
  try {
    const m: Material = await apiMaterial(manualMaterialId.value)
    const existing = aggItems.value.find((a) => a.material_id === m.id)
    if (existing) {
      ElMessage.warning('该物料已在采购明细中，请直接编辑数量')
      return
    }
    aggItems.value.push({
      material_id: m.id,
      material_code: m.material_code,
      material_name: m.material_name,
      unit: m.unit,
      ordered: 0,
      sources: [],
      unit_price: '',
      remark: manualRemark.value || '无来源采购（补充数量后提交）',
    })
    manualMaterialId.value = null
    manualRemark.value = ''
    addingManual.value = false
  } catch {
    /* toast */
  }
}

function removeAgg(index: number) {
  aggItems.value.splice(index, 1)
}

function validate(): string | null {
  if (!header.supplier_id) return '请选择供应商'
  for (const r of sourceRows.value) {
    const q = num(r.qty)
    if (q < 0 || !Number.isFinite(q) || r.qty.trim() === '') continue
    if (q > r.remaining) return `${r.pr_no} 第 ${r.line_no} 行：转出数量 ${formatQuantity(q)} 超过剩余可转 ${formatQuantity(r.remaining)}`
  }
  const valid = aggItems.value.filter((a) => a.ordered > 0)
  if (valid.length === 0) return '请至少转出一条来源数量，或添加无来源采购明细'
  for (const a of valid) {
    const price = num(a.unit_price)
    if (!Number.isFinite(price) || price < 0) return `物料 ${a.material_name}：单价不能为负`
  }
  return null
}

async function onSubmit() {
  const err = validate()
  if (err) {
    ElMessage.warning(err)
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认创建采购订单？订单创建为 DRAFT 状态，需 Confirm 后采购员确认、仓库方可收货。',
      '创建确认',
      { type: 'info' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const items = aggItems.value
      .filter((a) => a.ordered > 0)
      .map((a) => ({
        material_id: a.material_id,
        ordered_quantity: String(a.ordered),
        unit_price: a.unit_price || '0',
        remark: a.remark || (a.sources.length === 0 ? '无来源采购' : null),
        sources: a.sources.map((s) => ({ pr_item_id: s.pr_item_id, quantity: String(s.quantity) })),
      }))
    const po = await apiCreatePo({
      supplier_id: header.supplier_id as number,
      order_date: null,
      expected_date: header.expected_date || null,
      remark: header.remark || null,
      items,
    })
    ElMessage.success('采购订单已创建（草稿）')
    router.replace(`/purchase-orders/${po.id}`)
  } catch {
    /* 业务错误（5010 source 数量不一致等）由 request client toast */
  } finally {
    saving.value = false
  }
}

const totalOrdered = computed(() => aggItems.value.filter((a) => a.ordered > 0).reduce((s, a) => s + a.ordered, 0))

onMounted(loadSources)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-page-header @back="router.back()">
      <template #content><span class="ph-title">创建采购订单</span></template>
    </el-page-header>

    <!-- 单头 -->
    <el-form label-width="90px" style="max-width: 760px; margin-top: 16px">
      <el-form-item label="供应商" required>
        <SupplierSelect v-model="header.supplier_id" placeholder="选择供应商（仅启用）" />
      </el-form-item>
      <el-form-item label="期望到货">
        <el-date-picker v-model="header.expected_date" type="date" value-format="YYYY-MM-DD" placeholder="可空" style="width: 200px" />
      </el-form-item>
      <el-form-item label="订单备注">
        <el-input v-model="header.remark" maxlength="255" placeholder="可空" />
      </el-form-item>
    </el-form>

    <el-divider content-position="left">
      <span class="text-muted" style="font-size: 12px">① 选择已批准 PR 的来源明细（可跨多张 PR，同物料自动合并）</span>
    </el-divider>
    <el-empty v-if="sourceRows.length === 0 && !loading" description="暂无 APPROVED 且未转完的采购申请，请先走完 PR 审批" :image-size="70" />
    <el-table v-else :data="sourceRows" border max-height="340">
      <el-table-column prop="pr_no" label="来源 PR" width="160" />
      <el-table-column prop="line_no" label="行" width="52" align="center" />
      <el-table-column label="物料" min-width="190">
        <template #default="{ row }">
          <span>{{ row.material_name }}</span>
          <span class="text-muted" style="font-size: 12px; margin-left: 6px">{{ row.material_code }}</span>
        </template>
      </el-table-column>
      <el-table-column label="剩余可转" width="110" align="right">
        <template #default="{ row }">{{ formatQuantity(row.remaining) }}</template>
      </el-table-column>
      <el-table-column label="本次转出数量" width="150">
        <template #default="{ row }">
          <el-input
            :model-value="(row as PickRow).qty"
            placeholder="0=不转，≤ 剩余"
            @update:model-value="(v: string) => { (row as PickRow).qty = v; onQtyChange() }"
            @blur="onQtyChange"
          />
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">
      <span class="text-muted" style="font-size: 12px">② 采购明细预览（ordered = Σ source quantity，实时校验）</span>
    </el-divider>
    <el-table :data="aggItems" border>
      <el-table-column label="物料" min-width="180">
        <template #default="{ row }">
          <span>{{ row.material_name }}</span>
          <span class="text-muted" style="font-size: 12px; margin-left: 6px">{{ row.material_code }}</span>
        </template>
      </el-table-column>
      <el-table-column label="来源（PR 明细 × 数量）" min-width="240">
        <template #default="{ row }">
          <template v-if="row.sources.length > 0">
            <div v-for="s in row.sources" :key="s.pr_item_id" class="src-line">
              <el-tag size="small" effect="plain" type="info">{{ s.pr_no }}</el-tag>
              <span class="text-muted"> 行 {{ s.pr_item_line_no }} × {{ formatQuantity(s.quantity) }}</span>
            </div>
          </template>
          <span v-else class="text-muted">无来源采购</span>
        </template>
      </el-table-column>
      <el-table-column label="订购数量" width="110" align="right">
        <template #default="{ row }">
          <el-input :model-value="String(row.ordered)" disabled />
        </template>
      </el-table-column>
      <el-table-column label="单价（Confirm 须 >0）" width="140">
        <template #default="{ row }">
          <el-input v-model="row.unit_price" placeholder="0" />
        </template>
      </el-table-column>
      <el-table-column label="金额预览" width="120" align="right">
        <template #default="{ row }">{{ formatMoney(row.ordered * Number(row.unit_price || 0)) }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="140">
        <template #default="{ row }">
          <el-input v-model="row.remark" maxlength="255" />
        </template>
      </el-table-column>
      <el-table-column label="" width="56" align="center">
        <template #default="{ $index }">
          <el-button link type="danger" :icon="Delete" @click="removeAgg($index)" />
        </template>
      </el-table-column>
    </el-table>

    <div class="row-actions">
      <el-button @click="addingManual = !addingManual">添加无来源明细</el-button>
      <template v-if="addingManual">
        <span style="display: inline-flex; gap: 8px; align-items: center">
          <span style="width: 220px; display: inline-block">
            <MaterialSelect :model-value="manualMaterialId" @update:model-value="manualMaterialId = $event" placeholder="选择物料（仅启用）" />
          </span>
          <el-input v-model="manualRemark" placeholder="说明（必填理由，如 MOQ）" style="width: 240px" />
          <el-button type="primary" @click="addManualItem">加入</el-button>
        </span>
      </template>
      <div class="spacer" />
      <span class="text-muted" style="font-size: 12px">共 {{ aggItems.filter((a) => a.ordered > 0).length }} 项明细，合计 {{ formatQuantity(totalOrdered) }} 单位</span>
      <el-button type="primary" :loading="saving" @click="onSubmit">创建采购订单</el-button>
    </div>
  </div>
</template>

<style scoped>
.ph-title {
  font-weight: 600;
  font-size: 16px;
  color: #1f2329;
}
.row-actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.spacer {
  flex: 1;
}
.src-line {
  display: flex;
  align-items: center;
  margin: 2px 0;
}
</style>
