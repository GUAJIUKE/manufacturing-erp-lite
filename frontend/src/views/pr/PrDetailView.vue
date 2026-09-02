<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  apiApprovePr,
  apiCancelPr,
  apiPr,
  apiPrApprovals,
  apiRejectPr,
  apiRevisePr,
  apiSubmitPr,
} from '@/api/purchaseRequisitions'
import { ApiBusinessError } from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import type { ApprovalRecord, PurchaseRequisition } from '@/types/models'
import type { PrStatus } from '@/types/enums'
import { prStatusMeta } from '@/utils/status'
import { formatDate, formatDateTime, formatMoney } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const prId = Number(route.params.id)

const loading = ref(false)
const acting = ref(false)
const pr = ref<PurchaseRequisition | null>(null)
const approvals = ref<ApprovalRecord[]>([])

const isMine = computed(() => pr.value?.applicant_id === auth.user?.id)

const ACTION_LABEL: Record<string, string> = {
  SUBMIT: '提交',
  APPROVE: '通过',
  REJECT: '驳回',
  CANCEL: '取消',
}

async function load() {
  loading.value = true
  try {
    const [detail, hist] = await Promise.all([apiPr(prId), apiPrApprovals(prId)])
    pr.value = detail
    approvals.value = hist
  } catch {
    router.replace('/purchase-requisitions')
  } finally {
    loading.value = false
  }
}

async function act(fn: () => Promise<unknown>, successMsg: string) {
  acting.value = true
  try {
    await fn()
    ElMessage.success(successMsg)
    await load()
  } catch (err) {
    if (err instanceof ApiBusinessError && (err.code === 4011 || err.code === 4012)) {
      // 版本冲突 / 已被处理 → 强制刷新
      try {
        await ElMessageBox.confirm(err.message + '，点击确定重新加载最新状态。', '单据状态已变化', { type: 'warning' })
      } catch {
        /* 用户取消仍刷新 */
      }
      await load()
    }
  } finally {
    acting.value = false
  }
}

function onSubmit() {
  if (!pr.value) return
  ElMessageBox.confirm(`提交 ${pr.value.pr_no} 进入审批流程？`, '提交确认', { type: 'warning' }).then(() => {
    act(() => apiSubmitPr(pr.value!.id), '已提交审批')
  }).catch(() => undefined)
}
function onCancel() {
  if (!pr.value) return
  ElMessageBox.confirm(`取消 ${pr.value.pr_no}？取消后不可恢复。`, '取消确认', { type: 'warning' }).then(() => {
    act(() => apiCancelPr(pr.value!.id), '已取消')
  }).catch(() => undefined)
}
async function onRevise() {
  if (!pr.value) return
  await apiRevisePr(pr.value.id, { version: pr.value.version })
  ElMessage.success('已退回草稿，进入编辑页')
  router.push(`/purchase-requisitions/${pr.value.id}/edit`)
}
function goApprove() {
  router.push(`/approvals?pr=${prId}`)
}
function goCreatePo() {
  router.push(`/purchase-orders/create?pr=${prId}`)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-page-header @back="router.back()">
      <template #content>
        <span class="ph-title">{{ pr?.pr_no || '采购申请' }}</span>
        <el-tag v-if="pr" size="small" style="margin-left: 10px">{{ pr.status }}</el-tag>
      </template>
    </el-page-header>

    <template v-if="pr">
      <el-descriptions :column="3" border class="desc-block">
        <el-descriptions-item label="PR 编号">{{ pr.pr_no }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusTag :meta="prStatusMeta(pr.status)" /></el-descriptions-item>
        <el-descriptions-item label="版本">v{{ pr.version }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ pr.applicant_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="部门">{{ pr.department_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="申请日期">{{ formatDate(pr.apply_date) }}</el-descriptions-item>
        <el-descriptions-item label="预估总金额"><MoneyText :value="pr.total_estimated_amount" /></el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ pr.submitted_at ? formatDateTime(pr.submitted_at) : '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(pr.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="申请原因" :span="3">{{ pr.reason || '-' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 业务操作区：permission + status + 本人 -->
      <div class="action-bar">
        <template v-if="pr.status === 'DRAFT' && isMine">
          <el-button v-if="hasPerm('pr:update')" type="primary" plain @click="router.push(`/purchase-requisitions/${pr.id}/edit`)">编辑</el-button>
          <el-button v-if="hasPerm('pr:submit')" type="primary" :loading="acting" @click="onSubmit">提交审批</el-button>
          <el-button v-if="hasPerm('pr:cancel')" type="danger" plain :loading="acting" @click="onCancel">取消申请</el-button>
        </template>
        <template v-else-if="pr.status === 'REJECTED' && isMine">
          <el-button v-if="hasPerm('pr:update')" type="warning" :loading="acting" @click="onRevise">重新编辑</el-button>
        </template>
        <template v-else-if="pr.status === 'APPROVED'">
          <el-button v-if="hasPerm('po:create')" type="primary" @click="goCreatePo">创建采购订单</el-button>
          <el-button v-if="hasPerm('pr:approve')" plain @click="goApprove">去审批中心</el-button>
        </template>
        <template v-else-if="pr.status === 'PENDING'">
          <el-tag type="warning" effect="plain">等待审批中</el-tag>
        </template>
        <template v-else-if="pr.status === 'CONVERTED'">
          <el-tag type="primary" effect="plain">已转换为采购订单</el-tag>
        </template>
      </div>

      <!-- 明细 -->
      <h3 class="block-title">申请明细</h3>
      <el-table :data="pr.items || []" border stripe>
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="物料编码" width="140">
          <template #default="{ row }">{{ row.material_code || '-' }}</template>
        </el-table-column>
        <el-table-column label="物料名称" min-width="160">
          <template #default="{ row }">{{ row.material_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="申请数量" width="110" align="right">
          <template #default="{ row }">{{ row.requested_quantity }}</template>
        </el-table-column>
        <el-table-column label="预估单价" width="120" align="right">
          <template #default="{ row }"><MoneyText :value="row.estimated_unit_price" /></template>
        </el-table-column>
        <el-table-column label="预估金额" width="120" align="right">
          <template #default="{ row }"><MoneyText :value="row.estimated_amount" /></template>
        </el-table-column>
        <el-table-column label="已转出" width="90" align="right">
          <template #default="{ row }">{{ row.converted_quantity }}</template>
        </el-table-column>
        <el-table-column label="需求日期" width="110">
          <template #default="{ row }">{{ row.required_date ? formatDate(row.required_date) : '-' }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120">
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
      </el-table>

      <!-- 审批历史 -->
      <h3 class="block-title">审批历史</h3>
      <el-empty v-if="approvals.length === 0" description="暂无审批记录（提交后生成）" :image-size="60" />
      <el-timeline v-else style="padding-left: 4px">
        <el-timeline-item
          v-for="a in approvals"
          :key="a.id"
          :timestamp="formatDateTime(a.created_at)"
          :type="a.action === 'APPROVE' ? 'success' : a.action === 'REJECT' ? 'danger' : 'info'"
          placement="top"
        >
          <div class="timeline-row">
            <el-tag size="small" effect="plain">{{ ACTION_LABEL[a.action] || a.action }}</el-tag>
            <span class="tl-approver">{{ a.approver_name || '系统' }}</span>
            <span v-if="a.from_status || a.to_status" class="text-muted tl-status">
              {{ a.from_status || '' }} → {{ a.to_status || '' }}
            </span>
            <span v-if="a.comment" class="tl-comment">备注：{{ a.comment }}</span>
          </div>
        </el-timeline-item>
      </el-timeline>
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
  gap: 8px;
  align-items: center;
}
.block-title {
  font-size: 14px;
  color: #1f2329;
  margin: 20px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #2f6fed;
}
.timeline-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.tl-approver {
  font-weight: 500;
}
.tl-status {
  font-size: 12px;
  font-family: ui-monospace, monospace;
}
.tl-comment {
  font-size: 12px;
  color: #4b5563;
}
</style>
