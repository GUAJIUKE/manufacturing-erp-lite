<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { apiPrs, apiCancelPr, apiSubmitPr, apiRevisePr } from '@/api/purchaseRequisitions'
import { apiDepartments } from '@/api/system'
import { useAuthStore } from '@/stores/auth'
import type { Department, PurchaseRequisition } from '@/types/models'
import type { PrStatus } from '@/types/enums'
import { prStatusMeta } from '@/utils/status'
import { formatDate, formatMoney } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<PurchaseRequisition[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 20,
  pr_no: '',
  applicant: '',
  department_id: null as number | null,
  status: '' as '' | PrStatus,
  apply_date_from: '',
  apply_date_to: '',
})
const departments = ref<Department[]>([])

const STATUS_OPTIONS: { value: PrStatus; label: string }[] = [
  { value: 'DRAFT', label: '草稿' },
  { value: 'PENDING', label: '待审批' },
  { value: 'APPROVED', label: '已批准' },
  { value: 'REJECTED', label: '已驳回' },
  { value: 'CANCELLED', label: '已取消' },
  { value: 'CONVERTED', label: '已转PO' },
]

async function load() {
  loading.value = true
  try {
    const page = await apiPrs({
      page: query.page,
      page_size: query.page_size,
      pr_no: query.pr_no || undefined,
      applicant: query.applicant || undefined,
      department_id: query.department_id ?? undefined,
      status: query.status || undefined,
      apply_date_from: query.apply_date_from || undefined,
      apply_date_to: query.apply_date_to || undefined,
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
  Object.assign(query, { pr_no: '', applicant: '', department_id: null, status: '', apply_date_from: '', apply_date_to: '' })
  onSearch()
}

const isMine = (r: PurchaseRequisition) => r.applicant_id === auth.user?.id

/** 列表行快捷操作（依权限 + 状态 + 本人单据） */
async function quickSubmit(r: PurchaseRequisition) {
  try {
    await ElMessageBox.confirm(`提交采购申请 ${r.pr_no} 进入审批流程？`, '提交确认', { type: 'warning' })
  } catch {
    return
  }
  await apiSubmitPr(r.id)
  ElMessage.success('已提交审批')
  load()
}
async function quickCancel(r: PurchaseRequisition) {
  try {
    await ElMessageBox.confirm(`取消采购申请 ${r.pr_no}？`, '取消确认', { type: 'warning' })
  } catch {
    return
  }
  await apiCancelPr(r.id)
  ElMessage.success('已取消')
  load()
}
async function quickRevise(r: PurchaseRequisition) {
  // REJECTED → DRAFT 后跳编辑页
  await apiRevisePr(r.id, { version: r.version })
  ElMessage.success('申请已退回草稿，可重新编辑')
  router.push(`/purchase-requisitions/${r.id}/edit`)
}

onMounted(async () => {
  load()
  try {
    departments.value = await apiDepartments()
  } catch {
    /* 部门列表加载失败不阻塞主列表 */
  }
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.pr_no" placeholder="PR 编号" clearable style="width: 170px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.applicant" placeholder="申请人" clearable style="width: 140px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.department_id" placeholder="全部部门" clearable style="width: 160px" @change="onSearch">
        <el-option v-for="d in departments" :key="d.id" :value="d.id" :label="d.dept_name" />
      </el-select>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 130px" @change="onSearch">
        <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value" :label="s.label" />
      </el-select>
      <el-date-picker
        v-model="query.apply_date_from"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="申请日期起"
        style="width: 150px"
        @change="onSearch"
      />
      <span class="text-muted">至</span>
      <el-date-picker
        v-model="query.apply_date_to"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="申请日期止"
        style="width: 150px"
        @change="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('pr:create')" type="primary" :icon="Plus" @click="router.push('/purchase-requisitions/create')">
        新建采购申请
      </el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column label="PR No" width="170">
        <template #default="{ row }">
          <el-link type="primary" class="link-btn" @click="router.push(`/purchase-requisitions/${row.id}`)">{{ row.pr_no }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="applicant_name" label="申请人" width="100">
        <template #default="{ row }">{{ row.applicant_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="department_name" label="部门" width="120">
        <template #default="{ row }">{{ row.department_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="申请日期" width="110">
        <template #default="{ row }">{{ formatDate(row.apply_date) }}</template>
      </el-table-column>
      <el-table-column label="预估总金额" width="130" align="right">
        <template #default="{ row }"><MoneyText :value="row.total_estimated_amount" /></template>
      </el-table-column>
      <el-table-column label="状态" width="95">
        <template #default="{ row }"><StatusTag :meta="prStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="60" align="center" />
      <el-table-column label="创建时间" width="165">
        <template #default="{ row }">{{ row.created_at.slice(0, 19).replace('T', ' ') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" class="link-btn" @click="router.push(`/purchase-requisitions/${row.id}`)">查看</el-button>
          <!-- 草稿：编辑 / 提交 / 取消（本人 + 权限） -->
          <template v-if="row.status === 'DRAFT' && isMine(row as PurchaseRequisition)">
            <el-button v-if="hasPerm('pr:update')" link type="primary" class="link-btn" @click="router.push(`/purchase-requisitions/${row.id}/edit`)">编辑</el-button>
            <el-button v-if="hasPerm('pr:submit')" link type="success" class="link-btn" @click="quickSubmit(row as PurchaseRequisition)">提交</el-button>
            <el-button v-if="hasPerm('pr:cancel')" link type="danger" class="link-btn" @click="quickCancel(row as PurchaseRequisition)">取消</el-button>
          </template>
          <!-- 驳回：重新编辑（本人） -->
          <template v-else-if="row.status === 'REJECTED' && isMine(row as PurchaseRequisition)">
            <el-button v-if="hasPerm('pr:update')" link type="warning" class="link-btn" @click="quickRevise(row as PurchaseRequisition)">重新编辑</el-button>
          </template>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无采购申请" /></template>
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
  </div>
</template>
