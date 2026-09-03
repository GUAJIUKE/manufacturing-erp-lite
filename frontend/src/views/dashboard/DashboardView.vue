<script setup lang="ts">
// ---- 管理驾驶舱（Phase 11）----
// 数据契约：全部 KPI 由后端 SQL 聚合（app/services/dashboard_service.py），
// 前端零求和。金额/数量均为 Decimal-as-string，展示用 formatMoney/formatQuantity，
// 图表坐标仅做展示级 Number 转换，tooltip 始终回显后端原始字符串。
// 颜色：PO 状态图表颜色 = utils/status.TAG_COLOR（与 StatusTag 同源，构造级对齐）。

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { LocationQueryRaw } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
// 按需注册 ECharts（Tree-shaking）：仅仪表盘使用的 柱/折/饼 + 基础组件
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

type ChartOption = Parameters<echarts.ECharts['setOption']>[0]
import { useAuthStore } from '@/stores/auth'
import KpiCard from '@/components/KpiCard.vue'
import {
  formatDateTime,
  formatMoney,
  formatQuantity,
} from '@/utils/format'
import { poStatusMeta, tagColor, txnTypeMeta } from '@/utils/status'
import { actionLabel, todoLabel, todoRoute } from '@/utils/dashboard'
import {
  apiDashboardSummary,
  apiDashboardTodos,
  apiInventoryActivities,
  apiLowStock,
  apiPoStatusDistribution,
  apiPrTrend,
  apiRecentActivities,
  type ActivityItem,
  type DashboardSummary,
  type InventoryActivityItem,
  type LowStockRow,
  type StatusCount,
  type TodoItem,
  type TrendPoint,
} from '@/api/dashboard'

const auth = useAuthStore()
const router = useRouter()

// ------------------------------------------------------------------ state
const loading = ref(false)
const lastUpdated = ref('')
const summary = ref<DashboardSummary | null>(null)
const trendDays = ref(30)
const trend = ref<TrendPoint[]>([])
const poDist = ref<StatusCount[]>([])
const lowStock = ref<LowStockRow[]>([])
const todos = ref<TodoItem[]>([])
const activities = ref<ActivityItem[]>([])
const invActs = ref<InventoryActivityItem[]>([])

// ------------------------------------------------------------------ perms
const canViewPr = computed(() => auth.permissions.includes('pr:view'))
const canApprove = computed(() => auth.permissions.includes('pr:approve'))
const canCreatePo = computed(() => auth.permissions.includes('po:create'))
const canConfirm = computed(() => auth.permissions.includes('po:confirm'))
const canCreateReceipt = computed(() => auth.permissions.includes('receipt:create'))
const canViewInv = computed(() => auth.permissions.includes('inventory:view'))
const canViewTxn = computed(() => auth.permissions.includes('inventory_txn:view'))

// ------------------------------------------------------------------ KPI
interface KpiDef {
  key: string
  label: string
  value: string
  hint?: string
  icon: string
  accent: string
  to: string
  query?: LocationQueryRaw
}

const kpiCards = computed<KpiDef[]>(() => {
  if (!summary.value) return []
  const s = summary.value
  const cards: KpiDef[] = []
  if (canViewPr.value && canApprove.value) {
    cards.push({
      key: 'pending_pr', label: '待审批采购申请', value: String(s.pending_pr_count),
      hint: '等待部门主管/管理员审批', icon: 'Stamp', accent: '#b76e00',
      to: '/approvals',
    })
  }
  if (canCreatePo.value) {
    cards.push({
      key: 'pending_purchase', label: '待转采购订单', value: String(s.pending_purchase_count),
      hint: '已批准但未完全转 PO', icon: 'Switch', accent: '#2f6fed',
      to: '/purchase-requisitions',
    })
  }
  if (canConfirm.value) {
    cards.push({
      key: 'draft_po', label: '待确认采购订单', value: String(s.draft_po_count),
      hint: '草稿状态的 PO 等待确认', icon: 'DocumentChecked', accent: '#7c5cf0',
      to: '/purchase-orders', query: { status: 'DRAFT' },
    })
  }
  if (canCreateReceipt.value || auth.roleCode === 'BUYER') {
    cards.push({
      key: 'pending_po', label: '待收货采购订单', value: String(s.pending_po_count),
      hint: '已确认、尚未全部收货', icon: 'Van', accent: '#0a7d33',
      to: canCreateReceipt.value ? '/purchase-receipts/create' : '/purchase-orders',
    })
  }
  if (canViewInv.value) {
    cards.push({
      key: 'low_stock', label: '低库存预警', value: String(s.low_stock_count),
      hint: '库存低于安全库存', icon: 'Warning', accent: '#d93026',
      to: '/inventory', query: { below_safety_stock: 'true' },
    })
    cards.push({
      key: 'stock_amount', label: '库存账面金额', value: formatMoney(s.inventory_total_amount),
      hint: '按库存余额权威金额汇总', icon: 'Wallet', accent: '#2f6fed',
      to: '/inventory',
    })
  }
  return cards
})

// ------------------------------------------------------------------ charts
const trendEl = ref<HTMLDivElement | null>(null)
const distEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let distChart: echarts.ECharts | null = null

function buildTrendOption(pts: TrendPoint[]): ChartOption {
  const dates = pts.map((p) => p.date.slice(5)) // MM-DD
  const counts = pts.map((p) => p.count)
  const amountStrs = pts.map((p) => p.amount)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params: unknown) {
        const list = params as { axisIndex: number; dataIndex: number }[]
        const idx = list[0]?.dataIndex ?? 0
        const d = pts[idx]
        if (!d) return ''
        return [
          `<div style="font-weight:600">${d.date}</div>`,
          `采购申请：${d.count} 单`,
          `预估金额：${formatMoney(d.amount)}`,
        ].join('<br/>')
      },
    },
    legend: { data: ['申请数', '预估金额'], top: 0, right: 0, itemWidth: 14, itemHeight: 8 },
    grid: { left: 44, right: 44, top: 34, bottom: 0, containLabel: false },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#c9cdd4' } },
      axisTick: { show: false },
      axisLabel: { color: '#4e5969', fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#f0f2f5' } },
        axisLabel: { color: '#86909c', fontSize: 11 },
      },
      {
        type: 'value',
        splitLine: { show: false },
        axisLabel: {
          color: '#86909c',
          fontSize: 11,
          formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}w` : String(v)),
        },
      },
    ],
    series: [
      {
        name: '申请数', type: 'bar', data: counts, barMaxWidth: 16,
        itemStyle: { color: '#2f6fed', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '预估金额', type: 'line', yAxisIndex: 1, data: amountStrs,
        smooth: true, symbol: 'circle', symbolSize: 4,
        lineStyle: { color: '#f59a23', width: 2 },
        itemStyle: { color: '#f59a23' },
      },
    ],
  }
}

function buildDistOption(dist: StatusCount[]): ChartOption {
  const total = dist.reduce((acc, d) => acc + d.count, 0)
  const data = dist
    .filter((d) => d.count > 0)
    .map((d) => ({
      name: poStatusMeta(d.status).label,
      value: d.count,
      itemStyle: { color: tagColor(poStatusMeta(d.status).type) },
    }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 单（{d}%）' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: '#4e5969', fontSize: 12 } },
    title: {
      text: String(total), subtext: 'PO 总数', left: 'center', top: '32%',
      textStyle: { fontSize: 26, fontWeight: 600, color: '#1f2329' },
      subtextStyle: { fontSize: 12, color: '#8a919f' },
    },
    series: [
      {
        name: 'PO 状态', type: 'pie', radius: ['52%', '72%'], center: ['50%', '44%'],
        avoidLabelOverlap: true, itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { show: false }, emphasis: { label: { show: true, fontWeight: 600 } },
        data,
      },
    ],
  }
}

const trendTotalCount = computed(() => trend.value.reduce((a, p) => a + p.count, 0))
const distTotal = computed(() => poDist.value.reduce((a, d) => a + d.count, 0))

function renderCharts() {
  if (trendChart) {
    trendChart.resize() // 容器可能刚从 v-show 展开，先校准尺寸
    if (trend.value.length) {
      trendChart.setOption(buildTrendOption(trend.value), true)
    }
  }
  if (distChart) {
    distChart.resize()
    distChart.setOption(buildDistOption(poDist.value), true)
  }
}

function onResize() {
  trendChart?.resize()
  distChart?.resize()
}

// ------------------------------------------------------------------ data
async function loadTrend() {
  if (!canViewPr.value) return
  try {
    trend.value = await apiPrTrend(trendDays.value)
  } catch {
    trend.value = []
  }
}

async function loadAll() {
  loading.value = true
  const jobs: Promise<unknown>[] = []
  jobs.push(
    apiDashboardSummary()
      .then((d) => (summary.value = d))
      .catch(() => (summary.value = null)),
  )
  jobs.push(
    apiDashboardTodos()
      .then((d) => (todos.value = d))
      .catch(() => (todos.value = [])),
  )
  jobs.push(
    apiRecentActivities(10)
      .then((d) => (activities.value = d))
      .catch(() => (activities.value = [])),
  )
  if (canViewPr.value) jobs.push(loadTrend())
  if (auth.permissions.includes('po:view')) {
    jobs.push(
      apiPoStatusDistribution()
        .then((d) => (poDist.value = d))
        .catch(() => (poDist.value = [])),
    )
  }
  if (canViewInv.value) {
    jobs.push(
      apiLowStock(10)
        .then((d) => (lowStock.value = d))
        .catch(() => (lowStock.value = [])),
    )
  }
  if (canViewTxn.value) {
    jobs.push(
      apiInventoryActivities(6)
        .then((d) => (invActs.value = d))
        .catch(() => (invActs.value = [])),
    )
  }
  await Promise.allSettled(jobs)
  lastUpdated.value = formatDateTime(new Date().toISOString())
  loading.value = false
  // 等容器尺寸稳定后再渲染图表（首个数据到达后容器可能刚展开）
  requestAnimationFrame(renderCharts)
}

// ------------------------------------------------------------------ life
onMounted(() => {
  if (trendEl.value) trendChart = echarts.init(trendEl.value)
  if (distEl.value) distChart = echarts.init(distEl.value)
  window.addEventListener('resize', onResize)
  loadAll()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  distChart?.dispose()
  trendChart = null
  distChart = null
})

watch(trendDays, loadTrend)
watch([trend, poDist], () => requestAnimationFrame(renderCharts))

// ------------------------------------------------------------------ todo
function goTodo(type: string) {
  const target = todoRoute(type, { canCreateReceipt: canCreateReceipt.value })
  router.push(target)
}

// 采购动态动作色：审批类 success/primary，撤销/驳回类 danger
function actionDot(action: string): string {
  if (/REJECT|CANCEL|REVERSE/.test(action)) return '#d93026'
  if (/APPROVE|CONFIRM|POST/.test(action)) return '#0a7d33'
  if (/SUBMIT|REVISE/.test(action)) return '#b76e00'
  return '#2f6fed'
}

function txnAmountClass(txn: InventoryActivityItem): string {
  const neg = txn.transaction_type.includes('REVERSAL') || txn.transaction_type.includes('OUT')
  return neg ? 'txn-neg' : 'txn-pos'
}

function txnSigned(txn: InventoryActivityItem): string {
  const neg = txn.transaction_type.includes('REVERSAL') || txn.transaction_type.includes('OUT')
  const q = formatQuantity(txn.quantity)
  return `${neg ? '-' : '+'}${q}`
}
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <!-- 头部 -->
    <div class="page-head">
      <div>
        <div class="page-title">管理驾驶舱 <span class="en">Management Cockpit</span></div>
        <div class="page-sub">
          {{ auth.user?.real_name || auth.user?.username }} · {{ auth.user?.role_name }}
          <template v-if="auth.user?.department_name"> · {{ auth.user.department_name }}</template>
        </div>
      </div>
      <div class="page-actions">
        <span v-if="lastUpdated" class="updated">更新于 {{ lastUpdated }}</span>
        <el-button size="small" :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- KPI 卡片 -->
    <div class="kpi-grid">
      <KpiCard
        v-for="c in kpiCards"
        :key="c.key"
        :label="c.label"
        :value="c.value"
        :hint="c.hint"
        :icon="c.icon"
        :accent="c.accent"
        :to="c.to"
        :query="c.query"
      />
      <el-empty
        v-if="!loading && kpiCards.length === 0"
        description="当前账号没有可展示的指标，请让管理员为你分配权限"
        :image-size="60"
      />
    </div>

    <!-- 图表行 -->
    <div class="row">
      <el-card v-if="canViewPr" shadow="never" class="panel trend-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">采购申请趋势 <span class="en">PR Trend</span></span>
            <el-radio-group v-model="trendDays" size="small">
              <el-radio-button :value="7">7 天</el-radio-button>
              <el-radio-button :value="30">30 天</el-radio-button>
              <el-radio-button :value="90">90 天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <el-empty v-if="trendTotalCount === 0" description="所选区间暂无采购申请" :image-size="60" />
        <div v-show="trendTotalCount > 0" ref="trendEl" class="chart chart-lg" />
      </el-card>

      <el-card v-if="auth.permissions.includes('po:view')" shadow="never" class="panel dist-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">采购订单状态分布 <span class="en">PO Status</span></span>
          </div>
        </template>
        <el-empty v-if="distTotal === 0" description="暂无采购订单" :image-size="60" />
        <div v-show="distTotal > 0" ref="distEl" class="chart chart-dist" />
      </el-card>
    </div>

    <!-- 待办 + 低库存 -->
    <div class="row">
      <el-card shadow="never" class="panel todo-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">我的待办 <span class="en">To-dos</span></span>
          </div>
        </template>
        <div v-if="todos.length" class="todo-list">
          <div v-for="t in todos" :key="t.type" class="todo-item" @click="goTodo(t.type)">
            <span class="todo-count">{{ t.count }}</span>
            <span class="todo-label">{{ todoLabel(t.type) }}</span>
            <span class="todo-arrow">›</span>
          </div>
        </div>
        <el-empty v-else description="当前没有待办事项" :image-size="60" />
      </el-card>

      <el-card v-if="canViewInv" shadow="never" class="panel lowstock-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">低库存预警 <span class="en">Low Stock</span></span>
            <el-button
              v-if="lowStock.length"
              link type="primary"
              @click="router.push({ path: '/inventory', query: { below_safety_stock: 'true' } })"
            >查看全部</el-button>
          </div>
        </template>
        <el-empty v-if="!lowStock.length" description="库存均在安全线以上" :image-size="60" />
        <el-table v-else :data="lowStock" size="small">
          <el-table-column label="物料" min-width="150">
            <template #default="{ row }">
              <div class="cell-main">{{ (row as LowStockRow).material_name }}</div>
              <div class="cell-sub">{{ (row as LowStockRow).material_code }}</div>
            </template>
          </el-table-column>
          <el-table-column label="仓库" prop="warehouse_name" min-width="100" show-overflow-tooltip />
          <el-table-column label="现存量" width="110" align="right">
            <template #default="{ row }">
              <span class="qty-danger">{{ formatQuantity((row as LowStockRow).quantity) }} {{ (row as LowStockRow).unit }}</span>
            </template>
          </el-table-column>
          <el-table-column label="安全库存" width="110" align="right">
            <template #default="{ row }">{{ formatQuantity((row as LowStockRow).safety_stock) }} {{ (row as LowStockRow).unit }}</template>
          </el-table-column>
          <el-table-column label="缺口" width="100" align="right">
            <template #default="{ row }">
              <el-tag type="danger" size="small" effect="dark">{{ formatQuantity((row as LowStockRow).shortage_quantity) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- 动态区 -->
    <div class="row">
      <el-card shadow="never" class="panel acts-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">最近采购动态 <span class="en">Recent Activities</span></span>
          </div>
        </template>
        <el-empty v-if="!activities.length" description="暂无业务动态" :image-size="60" />
        <el-timeline v-else class="acts-timeline">
          <el-timeline-item
            v-for="a in activities"
            :key="a.id"
            :color="actionDot(a.action)"
            :timestamp="formatDateTime(a.created_at)"
            placement="top"
          >
            <div class="act-line">
              <span class="act-action">{{ actionLabel(a.action) }}</span>
              <span v-if="a.document_no" class="act-doc">{{ a.document_no }}</span>
              <span class="act-actor">{{ a.operator_name }}</span>
            </div>
            <div v-if="a.description" class="act-desc">{{ a.description }}</div>
          </el-timeline-item>
        </el-timeline>
      </el-card>

      <el-card v-if="canViewTxn" shadow="never" class="panel invact-panel">
        <template #header>
          <div class="panel-head">
            <span class="panel-title">最近库存动态 <span class="en">Inventory</span></span>
          </div>
        </template>
        <el-empty v-if="!invActs.length" description="暂无库存流水" :image-size="60" />
        <div v-else class="invact-list">
          <div v-for="t in invActs" :key="t.id" class="invact-item">
            <div class="invact-top">
              <span class="txn-tag" :style="{ color: tagColor(txnTypeMeta(t.transaction_type).type) }">
                {{ txnTypeMeta(t.transaction_type).label }}
              </span>
              <span class="invact-qty" :class="txnAmountClass(t)">{{ txnSigned(t) }} {{ t.unit || '' }}</span>
            </div>
            <div class="invact-main">{{ t.material_name }}</div>
            <div class="invact-sub">
              {{ t.warehouse_name }}
              <template v-if="t.reference_no"> · {{ t.reference_no }}</template>
              · {{ formatDateTime(t.transaction_at) }}
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #1f2329;
}
.page-title .en {
  font-size: 12px;
  font-weight: 400;
  color: #8a919f;
  margin-left: 8px;
}
.page-sub {
  margin-top: 4px;
  font-size: 13px;
  color: #86909c;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.updated {
  font-size: 12px;
  color: #8a919f;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}
.row {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 12px;
}
.panel {
  border-radius: 10px;
  min-width: 0;
}
.panel :deep(.el-card__header) {
  padding: 10px 16px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.panel-title {
  font-weight: 600;
  color: #1f2329;
  font-size: 14px;
}
.panel-title .en {
  font-size: 11px;
  font-weight: 400;
  color: #8a919f;
  margin-left: 6px;
}
.trend-panel {
  grid-column: span 8;
}
.dist-panel {
  grid-column: span 4;
}
.todo-panel {
  grid-column: span 4;
}
.lowstock-panel {
  grid-column: span 8;
}
.acts-panel {
  grid-column: span 6;
}
.invact-panel {
  grid-column: span 6;
}
.chart {
  width: 100%;
}
.chart-lg {
  height: 300px;
}
.chart-dist {
  height: 300px;
}
.todo-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #f0f2f5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.todo-item:hover {
  border-color: #2f6fed;
  background: #f5f8ff;
}
.todo-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 26px;
  padding: 0 6px;
  border-radius: 13px;
  background: #2f6fed;
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.todo-label {
  flex: 1;
  font-size: 14px;
  color: #1f2329;
}
.todo-arrow {
  color: #c9cdd4;
  font-size: 18px;
}
.cell-main {
  color: #1f2329;
}
.cell-sub {
  font-size: 12px;
  color: #8a919f;
}
.qty-danger {
  color: #d93026;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.acts-timeline {
  padding: 4px 2px 0;
}
.act-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.act-action {
  font-weight: 600;
  color: #1f2329;
}
.act-doc {
  color: #2f6fed;
  font-family: monospace;
  font-size: 12px;
  background: #eef4ff;
  border-radius: 4px;
  padding: 1px 6px;
}
.act-actor {
  color: #86909c;
  font-size: 12px;
}
.act-desc {
  color: #8a919f;
  font-size: 12px;
  margin-top: 2px;
}
.invact-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.invact-item {
  padding: 7px 4px;
  border-bottom: 1px dashed #f0f2f5;
}
.invact-item:last-child {
  border-bottom: none;
}
.invact-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.txn-tag {
  font-size: 12px;
  font-weight: 600;
}
.invact-qty {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.txn-pos {
  color: #0a7d33;
}
.txn-neg {
  color: #d93026;
}
.invact-main {
  font-size: 13px;
  color: #1f2329;
  margin-top: 2px;
}
.invact-sub {
  font-size: 12px;
  color: #8a919f;
  margin-top: 1px;
}
@media (max-width: 1100px) {
  .trend-panel,
  .dist-panel,
  .todo-panel,
  .lowstock-panel,
  .acts-panel,
  .invact-panel {
    grid-column: span 12;
  }
}
</style>
