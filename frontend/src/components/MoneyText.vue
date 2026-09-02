<script setup lang="ts">
import { computed } from 'vue'
import { formatMoney, formatSignedMoney } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    value: string | number | null | undefined
    /** 展示 + 号前缀（流水用） */
    signed?: boolean
    negativeClass?: boolean
  }>(),
  { signed: false, negativeClass: true },
)

const text = computed(() => (props.signed ? formatSignedMoney(props.value) : formatMoney(props.value)))
const isNegative = computed(() => Number(props.value ?? 0) < 0)
</script>

<template>
  <span :class="['table-money', { 'num-negative': isNegative && negativeClass }]">{{ text }}</span>
</template>
