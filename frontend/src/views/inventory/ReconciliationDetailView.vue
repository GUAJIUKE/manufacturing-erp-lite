<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiApproveReconciliation,
  apiReconciliation,
  apiRejectReconciliation,
  apiSubmitReconciliation,
} from '@/api/stockReconciliations'
import { useAuthStore } from '@/stores/auth'
import type { StockReconciliation } from '@/types/models'
import type { ReconciliationStatus } from '@/types/enums'
import { formatDate, formatDateTime, formatMoney, formatQuantity, formatSignedMoney, formatSignedQuantity } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const doc = ref<StockReconciliation | null>(null)
const loading = ref(false)
const actionLoading = ref(false)

const STATUS_TEXT: Record<ReconciliationStatus, string> = {
  DRAFT: '草稿',
  PENDING: '待审批',
  POSTED: '已过账',
  REJECTED: '已驳回',
  CANCELLED: '已撤销',
  REVERSED: '已冲销',
}

function statusType(s: ReconciliationStatus): 'info' | 'warning' | 'success' | 'danger' {
  if (s === 'POSTED') return 'success'
  if (s === 'PENDING') return 'warning'
  if (s === 'REJECTED' || s === 'REVERSED' || s === 'CANCELLED') return 'danger'
  return 'info'
}

const isMine = computed(() => !!doc.value && !!auth.user && doc.value.counted_by === auth.user.id)

function hasPerm(code: string): boolean {
  return auth.permissions.includes(code)
}

async function load() {
  loading.value = true
  try {
    doc.value = await apiReconciliation(Number(route.params.id))
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  if (!doc.value) return
  try {
    await ElMessageBox.confirm(
      `确认提交盘点单 ${doc.value.reconciliation_no} 进入审批？`,
      '提交审批',
      { type: 'warning', confirmButtonText: '提交', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  actionLoading.value = true
  try {
    doc.value = await apiSubmitReconciliation(doc.value.id, doc.value.version)
    ElMessage.success('已提交审批')
  } finally {
    actionLoading.value = false
  }
}

const approveComment = ref('')
const needOverride = ref(false)
const overrideReason = ref('')
const approveDialog = ref(false)

function openApprove() {
  approveComment.value = ''
  needOverride.value = false
  overrideReason.value = ''
  approveDialog.value = true
}

async function onApprove() {
  if (!doc.value) return
  if (isMine.value && needOverride.value && !overrideReason.value.trim()) {
    ElMessage.warning('SoD override 必须填写理由')
    return
  }
  actionLoading.value = true
  try {
    doc.value = await apiApproveReconciliation(doc.value.id, {
      approve_comment: approveComment.value.trim() || null,
      override_self_approval: isMine.value ? needOverride.value : false,
      override_reason: isMine.value && needOverride.value ? overrideReason.value.trim() : null,
    })
    approveDialog.value = false
    ElMessage.success('已审批过账（库存已调整）')
  } finally {
    actionLoading.value = false
  }
}

const rejectComment = ref('')
const rejectDialog = ref(false)

function openReject() {
  rejectComment.value = ''
  rejectDialog.value = true
}

async function onReject() {
  if (!doc.value) return
  if (!rejectComment.value.trim()) {
    ElMessage.warning('驳回意见必填')
    return
  }
  actionLoading.value = true
  try {
    doc.value = await apiRejectReconciliation(doc.value.id, rejectComment.value.trim())
    rejectDialog.value = false
    ElMessage.success('已驳回')
  } finally {
    actionLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card v-loading="loading" shadow="never">
    <template #header>
      <div class="head">
        <div class="title">
          <span>{{ doc?.reconciliation_no }}</span>
          <el-tag v-if="doc" :type="statusType(doc.status)" class="tag">{{ STATUS_TEXT[doc.status] }}</el-tag>
          <el-tag v-if="doc?.override_self_approval" type="warning" class="tag">SoD Override</el-tag>
        </div>
        <div class="actions">
          <el-button v-if="doc?.status === 'DRAFT' && hasPerm('reconcile:update')"
                     @click="router.push(`/stock-reconciliations/${doc.id}/edit`)">编辑</el-button>
          <el-button v-if="doc?.status === 'DRAFT' && hasPerm('reconcile:submit')"
                     type="primary" :loading="actionLoading" @click="onSubmit">提交审批</el-button>
          <el-button v-if="doc?.status === 'PENDING' && hasPerm('reconcile:approve')"
                     type="success" :loading="actionLoading" @click="openApprove">审批过账</el-button>
          <el-button v-if="doc?.status === 'PENDING' && hasPerm('reconcile:reject')"
                     type="danger" plain :loading="actionLoading" @click="openReject">驳回</el-button>
        </div>
      </div>
    </template>

    <template v-if="doc">
      <el-descriptions :column="3" border class="meta">
        <el-descriptions-item label="仓库">{{ doc.warehouse_name || doc.warehouse_code }}</el-descriptions-item>
        <el-descriptions-item label="盘点人">{{ doc.counted_by_name }}</el-descriptions-item>
        <el-descriptions-item label="盘点日期">{{ formatDate(doc.counted_on) }}</el-descriptions-item>
        <el-descriptions-item label="版本">{{ doc.version }}</el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ formatDateTime(doc.submitted_at) }}</el-descriptions-item>
        <el-descriptions-item label="过账时间">{{ formatDateTime(doc.posted_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="doc.approved_by_name" label="审批/过账人">{{ doc.approved_by_name }}</el-descriptions-item>
        <el-descriptions-item v-if="doc.override_reason" label="Override 理由">{{ doc.override_reason }}</el-descriptions-item>
        <el-descriptions-item v-if="doc.reason" label="盘点原因" :span="3">{{ doc.reason }}</el-descriptions-item>
      </el-descriptions>

      <h4 class="section">盘点明细（账面快照为创建时固化）</h4>
      <el-table :data="doc.items || []" border size="small">
        <el-table-column prop="material_code" label="物料编码" min-width="120" />
        <el-table-column prop="material_name" label="物料名称" min-width="140" />
        <el-table-column label="账面数量(快照)" width="130" align="right">
          <template #default="{ row }">{{ formatQuantity(row.book_quantity_snapshot) }}</template>
        </el-table-column>
        <el-table-column label="账面金额(快照)" width="130" align="right">
          <template #default="{ row }">{{ formatMoney(row.book_total_amount_snapshot) }}</template>
        </el-table-column>
        <el-table-column label="账面均价(快照)" width="120" align="right">
          <template #default="{ row }">{{ formatQuantity(row.book_avg_cost_snapshot) }}</template>
        </el-table-column>
        <el-table-column label="实盘数量" width="120" align="right">
          <template #default="{ row }">{{ formatQuantity(row.physical_quantity) }}</template>
        </el-table-column>
        <el-table-column label="差异" width="120" align="right">
          <template #default="{ row }">
            <span :class="{ gain: Number(row.difference_quantity) > 0, loss: Number(row.difference_quantity) < 0 }">
              {{ formatSignedQuantity(row.difference_quantity) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="入账单价" width="120" align="right">
          <template #default="{ row }">{{ row.valuation_rate ? formatQuantity(row.valuation_rate) : '—' }}</template>
        </el-table-column>
        <el-table-column label="调整金额(服务端)" width="140" align="right">
          <template #default="{ row }">{{ formatSignedMoney(row.adjustment_amount) }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" />
        <template #empty>无明细</template>
      </el-table>

      <div v-if="doc.approve_comment" class="note">
        <b>审批/驳回意见：</b>{{ doc.approve_comment }}
      </div>
      <div class="note dim">
        说明：差异与金额由后端权威计算；POSTED 单据不可编辑，录错时通过后续冲销能力处理（Implementation B）。这是库存成本演示，不生成会计凭证。
      </div>
    </template>
  </el-card>

  <el-dialog v-model="approveDialog" title="审批并过账" width="480px">
    <p class="dim">审批即过账：通过后立即生成 ADJUST_IN/OUT 流水并调整库存余额，事务内完成。</p>
    <el-form label-width="90px">
      <el-form-item label="审批意见">
        <el-input v-model="approveComment" type="textarea" :rows="2" maxlength="1000" />
      </el-form-item>
      <el-form-item v-if="isMine" label="SoD">
        <el-switch v-model="needOverride" active-text="本人盘点，需 Override" />
      </el-form-item>
      <el-form-item v-if="isMine && needOverride" label="Override 理由">
        <el-input v-model="overrideReason" maxlength="500" placeholder="必填：记录为何允许自审（审计留痕）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="approveDialog = false">取消</el-button>
      <el-button type="success" :loading="actionLoading" @click="onApprove">通过并过账</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="rejectDialog" title="驳回" width="480px">
    <el-form label-width="90px">
      <el-form-item label="驳回意见">
        <el-input v-model="rejectComment" type="textarea" :rows="3" maxlength="1000" placeholder="必填：驳回后将回到草稿可修改" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="rejectDialog = false">取消</el-button>
      <el-button type="danger" :loading="actionLoading" @click="onReject">确认驳回</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tag {
  margin-left: 4px;
}
.meta {
  margin-bottom: 8px;
}
.section {
  margin: 16px 0 8px;
}
.gain {
  color: #e65100;
  font-weight: 600;
}
.loss {
  color: #089981;
  font-weight: 600;
}
.note {
  margin-top: 12px;
  font-size: 13px;
}
.dim {
  color: #8a919f;
}
</style>
