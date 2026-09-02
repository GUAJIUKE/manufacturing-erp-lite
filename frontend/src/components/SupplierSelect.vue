<script setup lang="ts">
import { apiSuppliers, type SupplierQuery } from '@/api/suppliers'
import type { Supplier } from '@/types/models'
import { useActiveSelect } from './useActiveSelect'

const props = defineProps<{
  modelValue: number | null | undefined
  disabled?: boolean
  placeholder?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: number | null): void }>()

const { options, loading, load } = useActiveSelect<Supplier>(
  (p) => apiSuppliers(p as SupplierQuery),
  { searchKeys: ['name'], codeKey: 'supplier_code', nameKey: 'supplier_name' },
)

function onChange(v: number | null) {
  emit('update:modelValue', v)
}
</script>

<template>
  <el-select
    :model-value="props.modelValue ?? null"
    :disabled="props.disabled"
    :placeholder="props.placeholder || '选择供应商'"
    filterable
    remote
    clearable
    :remote-method="(q: string) => load(q)"
    :loading="loading"
    style="width: 100%"
    @change="onChange"
  >
    <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label">
      <span>{{ o.label }}</span>
      <span class="opt-sub">{{ o.sub }}</span>
    </el-option>
  </el-select>
</template>

<style scoped>
.opt-sub {
  float: right;
  color: #8a919f;
  font-size: 12px;
  margin-left: 16px;
  font-family: ui-monospace, monospace;
}
</style>
