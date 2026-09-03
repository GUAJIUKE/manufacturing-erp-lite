<script setup lang="ts">
import { computed } from 'vue'
import type { StatusMeta } from '@/utils/status'
import { tagColor } from '@/utils/status'

const props = defineProps<{
  meta: StatusMeta
}>()

const tagType = computed(() => {
  // primary 不是 el-tag 标准 type，统一用 info 兜底 + 自定义色
  return props.meta.type === 'primary' ? 'info' : props.meta.type
})
const color = computed(() => tagColor(props.meta.type))
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
