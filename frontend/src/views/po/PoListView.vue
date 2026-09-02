<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { apiPos } from '@/api/purchaseOrders'
import { apiSuppliers } from '@/api/suppliers'
import type { PurchaseOrder, Supplier } from '@/types/models'
import type { PoStatus } from '@/types/enums'
import { poStatusMeta } from '@/utils/status'
import { formatDate } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import StatusTag from '@/components/StatusTag.vue'
import MoneyText from '@/components/MoneyText.vue'

const router = useRouter()
const loading = ref(false)
const rows = ref<PurchaseOrder[]>([])
const total = ref(0)
const suppliers = ref<Supplier[]>([])
const query = reactive({
  page: 1,
  page_size: 20,
  po_no: '',
  supplier_id: null as number | null,
  status: '' as '' | PoStatus,
  order_date_from: '',
  order_date_to: '',
})

const STATUS_OPTIONS: { value: PoStatus; label: string }[] = [
  { value: 'DRAFT', label: '草稿' },
  { value: 'CONFIRMED', label: '已确认' },
  { value: 'PARTIALLY_RECEIVED', label: '部分收货' },
  { value: 'RECEIVED', label: '已收完' },
  { value: 'CANCELLED', label: '已取消' },
]

async function load() {
  loading.value = true
  try {
    const page = await apiPos({
      page: query.page,
      page_size: query.page_size,
      po_no: query.po_no || undefined,
      supplier_id: query.supplier_id ?? undefined,
      status: query.status || undefined,
      order_date_from: query.order_date_from || undefined,
      order_date_to: query.order_date_to || undefined,
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
  Object.assign(query, { po_no: '', supplier_id: null, status: '', order_date_from: '', order_date_to: '' })
  onSearch()
}

onMounted(async () => {
  load()
  try {
    const page = await apiSuppliers({ page: 1, page_size: 200 })
    suppliers.value = page.items
  } catch {
    /* 供应商下拉加载失败不阻塞 */
  }
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.po_no" placeholder="PO 编号" clearable style="width: 170px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.supplier_id" placeholder="全部供应商" clearable filterable style="width: 180px" @change="onSearch">
        <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.supplier_name" />
      </el-select>
      <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 140px" @change="onSearch">
        <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value" :label="s.label" />
      </el-select>
      <el-date-picker v-model="query.order_date_from" type="date" value-format="YYYY-MM-DD" placeholder="下单日期起" style="width: 150px" @change="onSearch" />
      <span class="text-muted">至</span>
      <el-date-picker v-model="query.order_date_to" type="date" value-format="YYYY-MM-DD" placeholder="下单日期止" style="width: 150px" @change="onSearch" />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('po:create')" type="primary" @click="router.push('/purchase-orders/create')">创建采购订单</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe border>
      <el-table-column label="PO No" width="175">
        <template #default="{ row }">
          <el-link type="primary" class="link-btn" @click="router.push(`/purchase-orders/${row.id}`)">{{ row.po_no }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="supplier_name" label="供应商" min-width="170">
        <template #default="{ row }">{{ row.supplier_name || '-' }}</template>
      </el-table-column>
      <el-table-column prop="buyer_name" label="采购员" width="100">
        <template #default="{ row }">{{ row.buyer_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="下单日期" width="110">
        <template #default="{ row }">{{ formatDate(row.order_date) }}</template>
      </el-table-column>
      <el-table-column label="期望到货" width="110">
        <template #default="{ row }">{{ row.expected_date ? formatDate(row.expected_date) : '-' }}</template>
      </el-table-column>
      <el-table-column label="总金额" width="130" align="right">
        <template #default="{ row }"><MoneyText :value="row.total_amount" /></template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><StatusTag :meta="poStatusMeta(row.status)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" class="link-btn" @click="router.push(`/purchase-orders/${row.id}`)">查看</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无采购订单" /></template>
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
