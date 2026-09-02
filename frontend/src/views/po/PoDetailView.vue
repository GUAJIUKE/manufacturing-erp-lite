<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiCancelPo, apiConfirmPo, apiPo } from '@/api/purchaseOrders'
import { ApiBusinessError } from '@/api/request'
import type { PurchaseOrder } from '@/types/models'
import { poStatusMeta } from '@/utils/status'
import { formatDate, formatDateTime, formatMoney, formatQuantity } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const route = useRoute()
const router = useRouter()
const poId = Number(route.params.id)

const loading = ref(false)
const acting = ref(false)
const po = ref<PurchaseOrder | null>(null)

async function load() {
  loading.value = true
  try {
    po.value = await apiPo(poId)
  } catch {
    router.replace('/purchase-orders')
  } finally {
    loading.value = false
  }
}

async function handleConflict(err: unknown) {
  if (err instanceof ApiBusinessError && (err.code === 5012 || err.code === 5013)) {
    await ElMessageBox.alert(err.message + '，点击确定重新加载最新状态。', '单据状态已变化', { type: 'warning' })
    await load()
    return true
  }
  return false
}

async function onConfirm() {
  if (!po.value) return
  try {
    await ElMessageBox.confirm(
      `确认采购订单 ${po.value.po_no}？确认后进入 CONFIRMED，仓库可按单收货。`,
      '确认订单',
      { type: 'warning', confirmButtonText: '确认' },
    )
  } catch {
    return
  }
  acting.value = true
  try {
    await apiConfirmPo(po.value.id, { version: po.value.version })
    ElMessage.success('订单已确认')
    await load()
  } catch (err) {
    await handleConflict(err)
  } finally {
    acting.value = false
  }
}

async function onCancel() {
  if (!po.value) return
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入取消原因（选填）', `取消订单 ${po.value.po_no}`, {
      confirmButtonText: '取消订单',
      cancelButtonText: '返回',
      type: 'warning',
      inputValue: '',
      inputPlaceholder: '取消原因（可空）',
    })
    reason = value?.trim() ?? ''
  } catch {
    return
  }
  acting.value = true
  try {
    await apiCancelPo(po.value.id, { version: po.value.version, reason: reason || null })
    ElMessage.success('订单已取消')
    await load()
  } catch (err) {
    await handleConflict(err)
  } finally {
    acting.value = false
  }
}

function canReceive(): boolean {
  const s = po.value?.status
  return s === 'CONFIRMED' || s === 'PARTIALLY_RECEIVED'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-page-header @back="router.back()">
      <template #content>
        <span class="ph-title">{{ po?.po_no || '采购订单' }}</span>
        <el-tag v-if="po" size="small" style="margin-left: 10px">{{ po.status }}</el-tag>
      </template>
    </el-page-header>

    <template v-if="po">
      <el-descriptions :column="3" border class="desc-block">
        <el-descriptions-item label="PO 编号">{{ po.po_no }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusTag :meta="poStatusMeta(po.status)" /></el-descriptions-item>
        <el-descriptions-item label="版本">v{{ po.version }}</el-descriptions-item>
        <el-descriptions-item label="供应商">{{ po.supplier_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="采购员">{{ po.buyer_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="下单日期">{{ formatDate(po.order_date) }}</el-descriptions-item>
        <el-descriptions-item label="期望到货">{{ po.expected_date ? formatDate(po.expected_date) : '-' }}</el-descriptions-item>
        <el-descriptions-item label="总金额"><MoneyText :value="po.total_amount" /></el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(po.updated_at) }}</el-descriptions-item>
        <el-descriptions-item label="备注" :span="3">{{ po.remark || '-' }}</el-descriptions-item>
      </el-descriptions>

      <div class="action-bar">
        <template v-if="po.status === 'DRAFT'">
          <el-button v-if="hasPerm('po:confirm')" type="primary" :loading="acting" @click="onConfirm">确认订单</el-button>
          <el-button v-if="hasPerm('po:cancel')" type="danger" plain :loading="acting" @click="onCancel">取消订单</el-button>
        </template>
        <template v-else-if="po.status === 'CONFIRMED'">
          <el-button v-if="hasPerm('po:cancel')" type="danger" plain :loading="acting" @click="onCancel">取消订单</el-button>
          <el-button v-if="hasPerm('receipt:create')" type="primary" @click="router.push(`/purchase-receipts/create?po=${po.id}`)">采购入库</el-button>
        </template>
        <template v-else-if="po.status === 'PARTIALLY_RECEIVED'">
          <el-button v-if="hasPerm('receipt:create')" type="primary" @click="router.push(`/purchase-receipts/create?po=${po.id}`)">继续收货</el-button>
        </template>
        <template v-else-if="po.status === 'RECEIVED'">
          <el-tag type="success" effect="plain">已全部收货</el-tag>
        </template>
        <template v-else>
          <el-tag type="info" effect="plain">订单已取消</el-tag>
        </template>
      </div>

      <h3 class="block-title">订单明细与 PR 来源</h3>
      <el-table :data="po.items || []" border stripe>
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="物料" min-width="180">
          <template #default="{ row }">
            <div>{{ row.material_name || '-' }}</div>
            <div class="text-muted" style="font-size: 12px">{{ row.material_code || '' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="来源 PR（PR 行 × 数量）" min-width="250">
          <template #default="{ row }">
            <template v-if="row.sources && row.sources.length > 0">
              <div v-for="s in row.sources" :key="s.id" class="src-line">
                <el-tag size="small" type="primary" effect="plain">{{ s.pr_no }}</el-tag>
                <span class="text-muted" style="font-size: 12px">
                  行 {{ s.pr_item_line_no }} × {{ formatQuantity(s.quantity) }}
                </span>
              </div>
            </template>
            <span v-else class="text-muted">无来源（独立采购）</span>
          </template>
        </el-table-column>
        <el-table-column label="订购数量" width="110" align="right">
          <template #default="{ row }">{{ formatQuantity(row.ordered_quantity) }}</template>
        </el-table-column>
        <el-table-column label="已收数量" width="100" align="right">
          <template #default="{ row }">{{ formatQuantity(row.received_quantity) }}</template>
        </el-table-column>
        <el-table-column label="剩余可收" width="100" align="right">
          <template #default="{ row }">
            {{ formatQuantity(Number(row.ordered_quantity) - Number(row.received_quantity)) }}
          </template>
        </el-table-column>
        <el-table-column label="单价" width="110" align="right">
          <template #default="{ row }"><MoneyText :value="row.unit_price" /></template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="right">
          <template #default="{ row }"><MoneyText :value="row.amount" /></template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="130">
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
      </el-table>
      <div v-if="canReceive()" class="receive-hint">
        <el-icon><InfoFilled /></el-icon>
        <span class="text-muted" style="font-size: 12px">
          提示：部分收货时，本页「剩余可收」即仓库端本次可入库上限；多次收货直至 PO 转 RECEIVED。
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ph-title {
  font-weight: 600;
  font-size: 16px;
  color: #1f2329;
}
.desc-block {
  margin-top: 16px;
}
.action-bar {
  margin: 16px 0;
  display: flex;
  gap: 10px;
  align-items: center;
}
.block-title {
  font-size: 14px;
  color: #1f2329;
  margin: 20px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #2f6fed;
}
.src-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0;
}
.receive-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 12px;
  background: #f6f8fc;
  border-radius: 6px;
}
</style>
