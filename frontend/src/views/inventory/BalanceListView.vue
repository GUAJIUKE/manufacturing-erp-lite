<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Search, WarningFilled } from '@element-plus/icons-vue'
import { apiBalances } from '@/api/inventory'
import type { BalanceRow } from '@/types/models'
import { formatDateTime, formatDecimal, formatQuantity } from '@/utils/format'
import { hasPerm } from '@/utils/permission'
import WarehouseSelect from '@/components/WarehouseSelect.vue'
import MoneyText from '@/components/MoneyText.vue'

const loading = ref(false)
const rows = ref<BalanceRow[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 20,
  warehouse_id: null as number | null,
  material_code: '',
  material_name: '',
  below_safety_stock: false,
})

async function load() {
  loading.value = true
  try {
    const page = await apiBalances({
      page: query.page,
      page_size: query.page_size,
      warehouse_id: query.warehouse_id ?? undefined,
      material_code: query.material_code || undefined,
      material_name: query.material_name || undefined,
      below_safety_stock: query.below_safety_stock || undefined,
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
  Object.assign(query, { warehouse_id: null, material_code: '', material_name: '', below_safety_stock: false })
  onSearch()
}

function rowClass({ row }: { row: BalanceRow }): string {
  return row.is_below_safety_stock ? 'row-below-safety' : ''
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <WarehouseSelect v-model="query.warehouse_id" placeholder="全部仓库" clearable style="width: 170px" @change="onSearch" />
      <el-input v-model="query.material_code" placeholder="物料编码" clearable style="width: 160px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="query.material_name" placeholder="物料名称" clearable style="width: 160px" @keyup.enter="onSearch" @clear="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-switch
        v-model="query.below_safety_stock"
        active-text="仅看低于安全库存"
        inline-prompt
        style="--el-switch-on-color: #d93026"
        @change="onSearch"
      />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button @click="onReset">重置</el-button>
      <div class="spacer" />
      <el-button v-if="hasPerm('inventory_txn:view')" @click="$router.push('/inventory/transactions')">查看库存流水</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      border
      stripe
      :row-class-name="rowClass"
    >
      <el-table-column label="仓库" width="140">
        <template #default="{ row }">
          <div>{{ (row as BalanceRow).warehouse_name }}</div>
          <div class="text-muted" style="font-size: 12px">{{ (row as BalanceRow).warehouse_code }}</div>
        </template>
      </el-table-column>
      <el-table-column label="物料" min-width="200">
        <template #default="{ row }">
          <div>{{ (row as BalanceRow).material_name }}</div>
          <div class="text-muted" style="font-size: 12px">{{ (row as BalanceRow).material_code }} · {{ (row as BalanceRow).unit }}</div>
        </template>
      </el-table-column>
      <el-table-column label="当前数量" width="120" align="right">
        <template #default="{ row }">
          <span :class="{ 'qty-danger': (row as BalanceRow).is_below_safety_stock }">
            {{ formatQuantity((row as BalanceRow).quantity) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="平均成本" width="110" align="right">
        <template #default="{ row }"><MoneyText :value="(row as BalanceRow).average_unit_cost" /></template>
      </el-table-column>
      <el-table-column label="库存金额" width="130" align="right">
        <template #default="{ row }"><MoneyText :value="(row as BalanceRow).total_amount" /></template>
      </el-table-column>
      <el-table-column label="安全库存" width="110" align="right">
        <template #default="{ row }">
          <span v-if="(row as BalanceRow).safety_stock != null">{{ formatQuantity((row as BalanceRow).safety_stock) }}</span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="安全状态" width="130">
        <template #default="{ row }">
          <el-tag v-if="(row as BalanceRow).is_below_safety_stock" type="danger" size="small" effect="dark">
            <el-icon style="vertical-align: -2px; margin-right: 3px"><WarningFilled /></el-icon>低于安全库存
          </el-tag>
          <el-tag v-else type="success" size="small" effect="plain">正常</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最后变动" width="165">
        <template #default="{ row }">{{ formatDateTime((row as BalanceRow).last_transaction_at) }}</template>
      </el-table-column>
      <template #empty><el-empty description="暂无库存数据" /></template>
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
.qty-danger {
  color: #d93026;
  font-weight: 700;
}
:deep(.row-below-safety > td.el-table__cell) {
  background-color: #fef0ef !important;
}
</style>
