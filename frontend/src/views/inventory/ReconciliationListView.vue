<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiReconciliations, type ReconciliationQuery } from '@/api/stockReconciliations'
import { useAuthStore } from '@/stores/auth'
import type { StockReconciliation } from '@/types/models'
import type { ReconciliationStatus } from '@/types/enums'
import { formatDate, formatDateTime } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

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

function statusText(s: string): string {
  return (STATUS_TEXT as Record<string, string>)[s] ?? s
}

const query = reactive<ReconciliationQuery>({ page: 1, page_size: 20 })
const rows = ref<StockReconciliation[]>([])
const total = ref(0)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await apiReconciliations({ ...query })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onSearch() {
  query.page = 1
  load()
}

function onPageChange(p: number) {
  query.page = p
  load()
}

function canCreate(): boolean {
  return auth.permissions.includes('reconcile:create')
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>库存盘点</span>
        <el-button v-if="canCreate()" type="primary" @click="router.push('/stock-reconciliations/create')">
          新建盘点
        </el-button>
      </div>
    </template>

    <el-form inline @submit.prevent="onSearch">
      <el-form-item label="盘点单号">
        <el-input
          v-model="query.reconciliation_no"
          placeholder="CNT-…"
          clearable
          style="width: 190px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 140px" @change="onSearch">
          <el-option v-for="(text, code) in STATUS_TEXT" :key="code" :value="code" :label="text" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSearch">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="reconciliation_no" label="盘点单号" min-width="170" />
      <el-table-column label="仓库" min-width="140">
        <template #default="{ row }">{{ row.warehouse_name || row.warehouse_code }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="counted_by_name" label="盘点人" width="110" />
      <el-table-column label="盘点日期" width="110">
        <template #default="{ row }">{{ formatDate(row.counted_on) }}</template>
      </el-table-column>
      <el-table-column prop="item_count" label="明细数" width="90" align="right" />
      <el-table-column prop="version" label="版本" width="70" align="right" />
      <el-table-column label="提交/过账" min-width="150">
        <template #default="{ row }">
          <span v-if="row.status === 'PENDING' && row.submitted_at">提交于 {{ formatDateTime(row.submitted_at) }}</span>
          <span v-else-if="row.status === 'POSTED' && row.posted_at">过账于 {{ formatDateTime(row.posted_at) }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/stock-reconciliations/${row.id}`)">详情</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无盘点数据</template>
    </el-table>

    <div class="pager">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="query.page_size || 20"
        :current-page="query.page || 1"
        @current-change="onPageChange"
      />
    </div>
  </el-card>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
