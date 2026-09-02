<script setup lang="ts">
import { computed } from 'vue'
import { formatQuantity, formatSignedQuantity } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    value: string | number | null | undefined
    /** 展示 + 号前缀（流水用） */
    signed?: boolean
  }>(),
  { signed: false },
)

const text = computed(() => (props.signed ? formatSignedQuantity(props.value) : formatQuantity(props.value)))
const isNegative = computed(() => Number(props.value ?? 0) < 0)
</script>

<template>
  <span :class="['table-money', { 'num-negative': isNegative }]">{{ text }}</span>
</template>
