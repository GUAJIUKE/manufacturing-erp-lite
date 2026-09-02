<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { apiTransactions } from '@/api/inventory'
import type { Transaction } from '@/types/models'
import type { TxnType } from '@/types/enums'
import { txnTypeMeta } from '@/utils/status'
import { formatDateTime, formatDecimal, formatSignedMoney, formatSignedQuantity, formatQuantity } from '@/utils/format'
import WarehouseSelect from '@/components/WarehouseSelect.vue'
import MaterialSelect from '@/components/MaterialSelect.vue'
import StatusTag from '@/components/StatusTag.vue'

const router = useRouter()
const loading = ref(false)
const rows = ref<Transaction[]>([])
const total = ref(0)

const TXN_OPTIONS: { value: TxnType; label: string }[] = [
  { value: 'PURCHASE_IN', label: '采购入库' },
  { value: 'PURCHASE_IN_REVERSAL', label: '入库冲销' },
  { value: 'ADJUST_IN', label: '调整入库' },
  { value: 'ADJUST_OUT', label: '调整出库' },
  { value: 'PRODUCTION_IN', label: '生产入库' },
  { value: 'PRODUCTION_OUT', label: '生产领料' },
]

const query = reactive({
  page: 1,
  page_size: 20,
  warehouse_id: null as number | null,
  material_id: null as number | null,
  transaction_type: '' as '' | TxnType,
  reference_no: '',
})

async function load() {
  loading.value = true
  try {
    const page = await apiTransactions({
      page: query.page,
      page_size: query.page_size,
      warehouse_id: query.warehouse_id ?? undefined,
      material_id: query.material_id ?? undefined,
      transaction_type: query.transaction_type || undefined,
      reference_no: query.reference_no || undefined,
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
  Object.assign(query, { warehouse_id: null, material_id: null, transaction_type: '', reference_no: '' })
  onSearch()
}

/** 来源单据可跳转详情（采购入库/冲销 → 入库单详情） */
function sourceLink(t: Transaction): string | null {
  if (!t.source_id) return null
  if (t.source_type === 'PURCHASE_RECEIPT' || t.source_type === 'PURCHASE_RECEIPT_REVERSAL') {
    return `/purchase-receipts/${t.source_id}`
  }
  return null
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <WarehouseSelect v-model="query.warehouse_id" placeholder="全部仓库" clearable style="width: 170px" @change="onSearch" />
      <MaterialSelect v-model="query.material_id" placeholder="全部物料" clearable style="width: 210px" @change="onSearch" />
      <el-select v-model="query.transaction_type" placeholder="全部类型" clearable style="width: 130px" @change="onSearch">
        <el-option v-for="o in TXN_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
      <el-input v-model="query.reference_no" placeholder="来源单据号" clearable style="width: 165px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column label="业务时间" width="165">
        <template #default="{ row }">{{ formatDateTime((row as Transaction).transaction_at) }}</template>
      </el-table-column>
      <el-table-column prop="txn_no" label="流水号" width="190">
        <template #default="{ row }">
          <span class="mono">{{ (row as Transaction).txn_no }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="100">
        <template #default="{ row }"><StatusTag :meta="txnTypeMeta((row as Transaction).transaction_type)" /></template>
      </el-table-column>
      <el-table-column label="物料" min-width="190">
        <template #default="{ row }">
          <div>{{ (row as Transaction).material_name || '-' }}</div>
          <div class="text-muted" style="font-size: 12px">{{ (row as Transaction).material_code || '' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="仓库" width="130">
        <template #default="{ row }">{{ (row as Transaction).warehouse_name || (row as Transaction).warehouse_code || '-' }}</template>
      </el-table-column>
      <el-table-column label="数量" width="100" align="right">
        <template #default="{ row }">
          <span :class="Number((row as Transaction).quantity) < 0 ? 'qty-out' : 'qty-in'">
            {{ formatSignedQuantity((row as Transaction).quantity) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="单位成本" width="100" align="right">
        <template #default="{ row }">{{ formatDecimal((row as Transaction).unit_cost) }}</template>
      </el-table-column>
      <el-table-column label="金额" width="120" align="right">
        <template #default="{ row }">
          <span :class="Number((row as Transaction).amount) < 0 ? 'qty-out' : 'qty-in'">
            {{ formatSignedMoney((row as Transaction).amount) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="结存" width="100" align="right">
        <template #default="{ row }">{{ formatQuantity((row as Transaction).balance_after) }}</template>
      </el-table-column>
      <el-table-column label="来源单据" width="180">
        <template #default="{ row }">
          <el-link
            v-if="sourceLink(row as Transaction)"
            type="primary"
            class="link-btn"
            @click="router.push(sourceLink(row as Transaction)!)"
          >
            {{ (row as Transaction).reference_no || `#${(row as Transaction).source_id}` }}
          </el-link>
          <span v-else-if="(row as Transaction).reference_no" class="text-muted">{{ (row as Transaction).reference_no }}</span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="120">
        <template #default="{ row }">{{ (row as Transaction).remark || '-' }}</template>
      </el-table-column>
      <template #empty><el-empty description="暂无库存流水" /></template>
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

<style scoped>
.spacer {
  flex: 1;
}
.qty-in {
  color: #1f2329;
  font-weight: 600;
}
.qty-out {
  color: #d93026;
  font-weight: 700;
}
.mono {
  font-family: 'Consolas', 'Sarasa Mono SC', monospace;
  font-size: 12px;
}
</style>
