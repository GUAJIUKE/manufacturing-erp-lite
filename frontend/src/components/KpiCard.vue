<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { LocationQueryRaw } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'

/**
 * 管理驾驶舱 KPI 卡片。
 * - 值由后端聚合而来（string/格式化后），组件只负责展示
 * - 传入 to/query 时整卡可点击 → 下钻到对应列表页
 */
const props = withDefaults(
  defineProps<{
    label: string
    value: string
    hint?: string
    icon?: string // Element Plus 图标名（MainLayout 同款字符串渲染）
    accent?: string
    to?: string
    query?: LocationQueryRaw
    clickable?: boolean
  }>(),
  {
    icon: 'DataBoard',
    accent: '#2f6fed',
    clickable: true,
  },
)

const router = useRouter()

const ACCENT = computed(() => props.accent)

function onClick() {
  if (props.to) {
    router.push({ path: props.to, query: props.query })
  }
}
</script>

<template>
  <div
    class="kpi-card"
    :class="{ 'is-link': clickable && to }"
    :style="{ '--accent': ACCENT }"
    @click="onClick"
  >
    <div class="kpi-head">
      <span class="kpi-icon" :style="{ backgroundColor: ACCENT + '1a', color: ACCENT }">
        <el-icon :size="18"><component :is="icon" /></el-icon>
      </span>
      <span class="kpi-label">{{ label }}</span>
      <el-icon v-if="clickable && to" class="kpi-arrow" :size="14"><ArrowRight /></el-icon>
    </div>
    <div class="kpi-value" :style="{ color: ACCENT }">{{ value }}</div>
    <div v-if="hint" class="kpi-hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.kpi-card {
  position: relative;
  background: #fff;
  border: 1px solid #e6e8eb;
  border-radius: 10px;
  padding: 14px 16px 12px;
  transition: all 0.15s;
  overflow: hidden;
}
.kpi-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent);
  opacity: 0;
  transition: opacity 0.15s;
}
.kpi-card.is-link {
  cursor: pointer;
}
.kpi-card.is-link:hover {
  border-color: var(--accent);
  box-shadow: 0 4px 14px rgba(31, 35, 41, 0.08);
  transform: translateY(-1px);
}
.kpi-card.is-link:hover::before {
  opacity: 1;
}
.kpi-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kpi-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  flex: none;
}
.kpi-label {
  font-size: 13px;
  color: #4e5969;
  flex: 1;
  line-height: 1.3;
}
.kpi-arrow {
  color: #c9cdd4;
}
.kpi-value {
  margin-top: 10px;
  font-size: 24px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  word-break: break-all;
}
.kpi-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8a919f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
