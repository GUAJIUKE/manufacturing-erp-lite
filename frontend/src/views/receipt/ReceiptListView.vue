<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { apiReceipts } from '@/api/purchaseReceipts'
import { apiWarehouses } from '@/api/warehouses'
import type { PurchaseReceipt, Warehouse } from '@/types/models'
import type { ReceiptStatus } from '@/types/enums'
import { receiptStatusMeta } from '@/utils/status'
import { formatDateTime } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const loading = ref(false)
const rows = ref<PurchaseReceipt[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const query = reactive({
  page: 1,
  page_size: 20,
  receipt_no: '',
  po_no: '',
  warehouse_id: null as number | null,
  status: '' as '' | ReceiptStatus,
  receipt_date_from: '',
  receipt_date_to: '',
})

async function load() {
  loading.value = true
  try {
    const page = await apiReceipts({
      page: query.page,
      page_size: query.page_size,
      receipt_no: query.receipt_no || undefined,
      po_no: query.po_no || undefined,
      warehouse_id: query.warehouse_id ?? undefined,
      status: query.status || undefined,
      receipt_date_from: query.receipt_date_from || undefined,
      receipt_date_to: query.receipt_date_to || undefined,
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
  Object.assign(query, { receipt_no: '', po_no: '', warehouse_id: null, status: '', receipt_date_from: '', receipt_date_to: '' })
  onSearch()
}

onMounted(async () => {
  load()
  try {
    const page = await apiWarehouses({ page: 1, page_size: 200 })
    warehouses.value = page.items
  } catch {
    /* 下拉加载失败不阻塞 */
  }
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.receipt_no" placeholder="入库单号" clearable style="width: 175px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.po_no" placeholder="PO 单号" clearable style="width: 165px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.warehouse_id" placeholder="全部仓库" clearable filterable style="width: 160px" @change="onSearch">
        <el-option v-for="w in warehouses" :key="w.id" :value="w.id" :label="w.warehouse_name" />
      </el-select>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px" @change="onSearch">
        <el-option value="POSTED" label="已过账" />
        <el-option value="REVERSED" label="已冲销" />
      </el-select>
      <el-date-picker v-model="query.receipt_date_from" type="date" value-format="YYYY-MM-DD" placeholder="收货日期起" style="width: 150px" @change="onSearch" />
      <span class="text-muted">至</span>
      <el-date-picker v-model="query.receipt_date_to" type="date" value-format="YYYY-MM-DD" placeholder="收货日期止" style="width: 150px" @change="onSearch" />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('receipt:create')" type="primary" @click="router.push('/purchase-receipts/create')">新建入库单</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column label="Receipt No" width="180">
        <template #default="{ row }">
          <el-link type="primary" class="link-btn" @click="router.push(`/purchase-receipts/${row.id}`)">{{ row.receipt_no }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="PO No" width="175">
        <template #default="{ row }">{{ row.po_no || '-' }}</template>
      </el-table-column>
      <el-table-column prop="supplier_name" label="供应商" min-width="150">
        <template #default="{ row }">{{ row.supplier_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="仓库" width="130">
        <template #default="{ row }">{{ row.warehouse_name || row.warehouse_code || '-' }}</template>
      </el-table-column>
      <el-table-column prop="received_by_name" label="收货人" width="100">
        <template #default="{ row }">{{ row.received_by_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="收货时间" width="165">
        <template #default="{ row }">{{ formatDateTime(row.received_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="95">
        <template #default="{ row }"><StatusTag :meta="receiptStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" class="link-btn" @click="router.push(`/purchase-receipts/${row.id}`)">查看</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无入库单" /></template>
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
