<script setup lang="ts">
import { computed } from 'vue'
import type { StatusMeta, TagType } from '@/utils/status'

const props = defineProps<{
  meta: StatusMeta
}>()

// Element Plus tag 类型与自定义色的映射
const TYPE_COLOR: Record<TagType, string> = {
  success: '#0a7d33',
  warning: '#b76e00',
  danger: '#d93026',
  info: '#8a919f',
  primary: '#2f6fed',
}

const tagType = computed(() => {
  // primary 不是 el-tag 标准 type，统一用 info 兜底 + 自定义色
  return props.meta.type === 'primary' ? 'info' : props.meta.type
})
const color = computed(() => TYPE_COLOR[props.meta.type] ?? '#8a919f')
</script>

<template>
  <el-tag :type="tagType" size="small" :style="{ color, borderColor: color, backgroundColor: color + '14' }" effect="light" class="status-tag">
    {{ meta.label }}
  </el-tag>
</template>

<style scoped>
.status-tag {
  font-weight: 500;
}
</style>
