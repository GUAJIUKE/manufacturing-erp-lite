<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiReceipt, apiReverseReceipt } from '@/api/purchaseReceipts'
import type { PurchaseReceipt } from '@/types/models'
import { receiptStatusMeta } from '@/utils/status'
import { formatDateTime, formatQuantity } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const route = useRoute()
const router = useRouter()
const receiptId = Number(route.params.id)

const loading = ref(false)
const acting = ref(false)
const rc = ref<PurchaseReceipt | null>(null)

async function load() {
  loading.value = true
  try {
    rc.value = await apiReceipt(receiptId)
  } catch {
    router.replace('/purchase-receipts')
  } finally {
    loading.value = false
  }
}

async function onReverse() {
  if (!rc.value) return
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt(
      `冲销将【回退库存余额】并【减少 PO 已收数量】，操作不可撤销。\n请填写冲销原因（必填）：`,
      `冲销入库单 ${rc.value.receipt_no}`,
      {
        type: 'warning',
        confirmButtonText: '确认冲销',
        cancelButtonText: '返回',
        inputType: 'textarea',
        inputPlaceholder: '冲销原因（必填）',
        inputValidator: (v: string) => (v && v.trim() ? true : '冲销原因不能为空'),
      },
    )
    reason = value?.trim() ?? ''
  } catch {
    return // 用户取消或校验未通过
  }
  acting.value = true
  try {
    const updated = await apiReverseReceipt(receiptId, { reason })
    rc.value = updated
    ElMessage.success(`入库单 ${updated.receipt_no} 已冲销，库存已回退`)
  } catch {
    // 6005-6008 / 已处理等业务错误 message 由 request client 展示
  } finally {
    acting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-page-header @back="router.back()">
      <template #content>
        <span class="ph-title">{{ rc?.receipt_no || '入库单' }}</span>
        <StatusTag v-if="rc" :meta="receiptStatusMeta(rc.status)" style="margin-left: 10px" />
      </template>
    </el-page-header>

    <template v-if="rc">
      <el-descriptions :column="3" border class="desc-block">
        <el-descriptions-item label="PO 编号">
          <el-link v-if="rc.po_id" type="primary" class="link-btn" @click="router.push(`/purchase-orders/${rc.po_id}`)">{{ rc.po_no || '-' }}</el-link>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="供应商">{{ rc.supplier_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="仓库">{{ rc.warehouse_name || rc.warehouse_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="收货人">{{ rc.received_by_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="收货时间">{{ formatDateTime(rc.received_at) }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusTag :meta="receiptStatusMeta(rc.status)" /></el-descriptions-item>
        <el-descriptions-item label="备注" :span="3">{{ rc.remark || '-' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 冲销信息（REVERSED） -->
      <el-alert
        v-if="rc.status === 'REVERSED'"
        type="error"
        :closable="false"
        class="reversed-alert"
        title="该入库单已冲销，库存与 PO 已收数量已回退"
      >
        <div class="reversed-meta">
          冲销人：{{ rc.reversed_by_name || '-' }} ｜ 冲销时间：{{ rc.reversed_at ? formatDateTime(rc.reversed_at) : '-' }}
        </div>
        <div class="reversed-meta">冲销原因：{{ rc.reverse_reason || '-' }}</div>
      </el-alert>

      <!-- 操作 -->
      <div class="action-bar">
        <template v-if="rc.status === 'POSTED'">
          <el-button v-if="hasPerm('receipt:reverse')" type="danger" plain :loading="acting" @click="onReverse">
            冲销入库
          </el-button>
          <el-button v-if="hasPerm('receipt:create')" type="primary" plain @click="router.push(`/purchase-receipts/create?po=${rc.po_id}`)">
            对同一 PO 继续收货
          </el-button>
        </template>
        <template v-else>
          <el-tag type="info" effect="plain">已冲销单据不可再操作</el-tag>
        </template>
      </div>

      <h3 class="block-title">入库明细</h3>
      <el-table :data="rc.items || []" border stripe>
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="物料" min-width="190">
          <template #default="{ row }">
            <div>{{ row.material_name || '-' }}</div>
            <div class="text-muted" style="font-size: 12px">{{ row.material_code || '' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="PO 订购数量" width="110" align="right">
          <template #default="{ row }">{{ row.ordered_quantity != null ? formatQuantity(row.ordered_quantity) : '-' }}</template>
        </el-table-column>
        <el-table-column label="本次入库数量" width="110" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600">{{ formatQuantity(row.received_quantity) }}</span>
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
.reversed-alert {
  margin-top: 16px;
}
.reversed-meta {
  margin-top: 4px;
  font-size: 13px;
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
</style>
