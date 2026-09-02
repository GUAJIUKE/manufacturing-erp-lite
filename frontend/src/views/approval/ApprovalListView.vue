<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { apiApprovePr, apiPr, apiPrApprovals, apiPrs, apiRejectPr } from '@/api/purchaseRequisitions'
import { ApiBusinessError } from '@/api/request'
import type { ApprovalRecord, PurchaseRequisition } from '@/types/models'
import { formatDate, formatDateTime } from '@/utils/format'
import { prStatusMeta } from '@/utils/status'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const rows = ref<PurchaseRequisition[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, pr_no: '', applicant: '' })

async function load() {
  loading.value = true
  try {
    // status=PENDING：后端按审批人部门范围自然过滤（4007 同规则）
    const page = await apiPrs({
      page: query.page,
      page_size: query.page_size,
      pr_no: query.pr_no || undefined,
      applicant: query.applicant || undefined,
      status: 'PENDING',
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

// ---- 审批详情 Drawer ----
const drawerVisible = ref(false)
const detailLoading = ref(false)
const acting = ref(false)
const current = ref<PurchaseRequisition | null>(null)
const approvals = ref<ApprovalRecord[]>([])
const approveComment = ref('')
const rejectComment = ref('')
const rejectVisible = ref(false)
const rejectSaving = ref(false)

async function openDetail(pr: PurchaseRequisition) {
  drawerVisible.value = true
  detailLoading.value = true
  current.value = pr
  approvals.value = []
  approveComment.value = ''
  try {
    const [d, hist] = await Promise.all([apiPr(pr.id), apiPrApprovals(pr.id)])
    current.value = d
    approvals.value = hist
  } finally {
    detailLoading.value = false
  }
}

async function onApprove() {
  if (!current.value) return
  acting.value = true
  try {
    await apiApprovePr(current.value.id, { version: current.value.version, comment: approveComment.value || null })
    ElMessage.success('已通过')
    drawerVisible.value = false
    load()
  } catch (err) {
    if (err instanceof ApiBusinessError && (err.code === 4011 || err.code === 4012)) {
      await ElMessageBox.alert('单据已被其他人处理，请刷新列表查看最新状态。', '单据状态已变化', { type: 'warning' })
      drawerVisible.value = false
      load()
    }
  } finally {
    acting.value = false
  }
}

function openReject() {
  rejectComment.value = ''
  rejectVisible.value = true
}
async function onReject() {
  if (!current.value) return
  const comment = rejectComment.value.trim()
  if (!comment) {
    ElMessage.warning('驳回必须填写原因')
    return
  }
  rejectSaving.value = true
  try {
    await apiRejectPr(current.value.id, { version: current.value.version, comment })
    ElMessage.success('已驳回')
    rejectVisible.value = false
    drawerVisible.value = false
    load()
  } catch (err) {
    if (err instanceof ApiBusinessError && (err.code === 4011 || err.code === 4012)) {
      await ElMessageBox.alert('单据已被其他人处理，请刷新列表查看最新状态。', '单据状态已变化', { type: 'warning' })
      rejectVisible.value = false
      drawerVisible.value = false
      load()
    }
  } finally {
    rejectSaving.value = false
  }
}

function openFromRoute() {
  const prId = Number(route.query.pr)
  if (prId && rows.value.length === 0) {
    load().then(() => {
      const hit = rows.value.find((r) => r.id === prId)
      if (hit) openDetail(hit)
    })
  }
}

onMounted(() => {
  load().then(openFromRoute)
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.pr_no" placeholder="PR 编号" clearable style="width: 170px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.applicant" placeholder="申请人" clearable style="width: 150px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <div class="spacer" />
      <el-tag type="warning" effect="plain">列表仅显示待你审批（本部门）的申请</el-tag>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column label="PR No" width="175">
        <template #default="{ row }">
          <el-link type="primary" class="link-btn" @click="openDetail(row as PurchaseRequisition)">{{ row.pr_no }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="申请人" width="110">
        <template #default="{ row }">{{ row.applicant_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="部门" width="130">
        <template #default="{ row }">{{ row.department_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="预估金额" width="140" align="right">
        <template #default="{ row }"><MoneyText :value="row.total_estimated_amount" /></template>
      </el-table-column>
      <el-table-column label="提交时间" width="170">
        <template #default="{ row }">{{ row.submitted_at ? formatDateTime(row.submitted_at) : '-' }}</template>
      </el-table-column>
      <el-table-column label="申请原因" min-width="200">
        <template #default="{ row }">
          <el-text truncated>{{ row.reason || '-' }}</el-text>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link class="link-btn" @click="openDetail(row as PurchaseRequisition)">审批</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无待审批采购申请" /></template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[10, 20, 50]"
        @change="load"
      />
    </div>

    <!-- 审批详情抽屉 -->
    <el-drawer v-model="drawerVisible" size="760px" :title="current ? `审批 · ${current.pr_no}` : '审批详情'">
      <div v-loading="detailLoading">
        <template v-if="current">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="状态"><StatusTag :meta="prStatusMeta(current.status)" /></el-descriptions-item>
            <el-descriptions-item label="版本">v{{ current.version }}</el-descriptions-item>
            <el-descriptions-item label="申请人">{{ current.applicant_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="部门">{{ current.department_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="申请日期">{{ formatDate(current.apply_date) }}</el-descriptions-item>
            <el-descriptions-item label="预估总金额"><MoneyText :value="current.total_estimated_amount" /></el-descriptions-item>
            <el-descriptions-item label="申请原因" :span="2">{{ current.reason || '-' }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="block-title">明细</h3>
          <el-table :data="current.items || []" border size="small">
            <el-table-column prop="material_code" label="编码" width="110" />
            <el-table-column prop="material_name" label="物料名称" min-width="140" />
            <el-table-column label="数量" width="90" align="right">
              <template #default="{ row }">{{ row.requested_quantity }}</template>
            </el-table-column>
            <el-table-column label="预估单价" width="110" align="right">
              <template #default="{ row }"><MoneyText :value="row.estimated_unit_price" /></template>
            </el-table-column>
            <el-table-column label="预估金额" width="110" align="right">
              <template #default="{ row }"><MoneyText :value="row.estimated_amount" /></template>
            </el-table-column>
            <el-table-column label="需求日期" width="105">
              <template #default="{ row }">{{ row.required_date ? formatDate(row.required_date) : '-' }}</template>
            </el-table-column>
          </el-table>

          <h3 class="block-title">历史</h3>
          <el-empty v-if="approvals.length === 0" description="暂无记录" :image-size="50" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="a in approvals"
              :key="a.id"
              :timestamp="formatDateTime(a.created_at)"
              :type="a.action === 'APPROVE' ? 'success' : a.action === 'REJECT' ? 'danger' : 'info'"
            >
              <div>
                <b>{{ a.approver_name || '系统' }}</b> ·
                <span class="text-muted">{{ a.action }}</span>
                <span v-if="a.comment" class="tl-comment">：{{ a.comment }}</span>
              </div>
            </el-timeline-item>
          </el-timeline>

          <!-- 审批操作区（仅 PENDING + 有权限） -->
          <div v-if="current.status === 'PENDING' && hasPerm(['pr:approve', 'pr:reject'])" class="approve-bar">
            <el-input v-model="approveComment" placeholder="审批意见（通过时可选）" maxlength="1000" clearable />
            <div class="approve-btns">
              <el-button type="danger" plain :loading="acting" @click="openReject">驳回</el-button>
              <el-button type="success" :loading="acting" @click="onApprove">通过</el-button>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 驳回对话框（comment 必填） -->
    <el-dialog v-model="rejectVisible" title="驳回申请" width="480px">
      <el-form label-width="0">
        <el-form-item>
          <el-input
            v-model="rejectComment"
            type="textarea"
            :rows="3"
            maxlength="1000"
            placeholder="驳回原因（必填，将展示给申请人）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="rejectSaving" @click="onReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.block-title {
  font-size: 13px;
  color: #1f2329;
  margin: 18px 0 10px;
  padding-left: 8px;
  border-left: 3px solid #2f6fed;
}
.approve-bar {
  margin-top: 22px;
  border-top: 1px solid #e6e8eb;
  padding-top: 16px;
}
.approve-btns {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.tl-comment {
  color: #4b5563;
  font-size: 12px;
}
</style>
