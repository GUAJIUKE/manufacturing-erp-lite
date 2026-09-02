<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { apiCreatePr, apiPr, apiUpdatePr } from '@/api/purchaseRequisitions'
import { apiMaterial } from '@/api/materials'
import { ApiBusinessError } from '@/api/request'
import type { Material, PrItem } from '@/types/models'
import { formatMoney } from '@/utils/format'
import MaterialSelect from '@/components/MaterialSelect.vue'

const route = useRoute()
const router = useRouter()

const isEdit = computed(() => Boolean(route.params.id))
const prId = computed(() => Number(route.params.id))
const version = ref(0)
const originalVersion = ref(0)
const loading = ref(false)
const saving = ref(false)

interface Row {
  key: number
  id?: number | null
  material_id: number | null
  material_code?: string | null
  material_name?: string | null
  specification?: string | null
  unit?: string | null
  requested_quantity: string
  estimated_unit_price: string
  required_date: string | null
  remark: string
}

let keySeq = 1
function newRow(): Row {
  return {
    key: keySeq++,
    id: null,
    material_id: null,
    material_code: null,
    material_name: null,
    specification: null,
    unit: null,
    requested_quantity: '1',
    estimated_unit_price: '0',
    required_date: null,
    remark: '',
  }
}

const headerFormRef = ref<FormInstance>()
const header = reactive({ apply_date: '', reason: '' })
const rows = ref<Row[]>([newRow()])
const rules: FormRules = {
  apply_date: [{ required: true, message: '请选择申请日期', trigger: 'change' }],
}

async function loadPr() {
  if (!isEdit.value) return
  loading.value = true
  try {
    const pr = await apiPr(prId.value)
    if (pr.status !== 'DRAFT') {
      await ElMessageBox.alert('该申请当前状态不可编辑（仅 DRAFT 可编辑）', '无法编辑', { type: 'warning' })
      router.replace(`/purchase-requisitions/${pr.id}`)
      return
    }
    version.value = pr.version
    originalVersion.value = pr.version
    header.apply_date = pr.apply_date || ''
    header.reason = pr.reason || ''
    rows.value = (pr.items ?? []).map((it: PrItem) => ({
      key: keySeq++,
      id: it.id,
      material_id: it.material_id,
      material_code: it.material_code,
      material_name: it.material_name,
      specification: '',
      unit: '',
      requested_quantity: it.requested_quantity,
      estimated_unit_price: it.estimated_unit_price,
      required_date: it.required_date || null,
      remark: it.remark || '',
    }))
    // 补 spec/unit 展示
    await Promise.all(rows.value.filter((r) => r.material_id).map((r) => refreshMaterial(r)))
  } catch {
    router.replace('/purchase-requisitions')
  } finally {
    loading.value = false
  }
}

/** 选中物料后拉详情自动带出规格/单位（仅展示） */
async function refreshMaterial(row: Row) {
  if (!row.material_id) return
  try {
    const m: Material = await apiMaterial(row.material_id)
    row.material_code = m.material_code
    row.material_name = m.material_name
    row.specification = m.specification
    row.unit = m.unit
  } catch {
    /* toast 已展示 */
  }
}

function rowAmount(r: Row): string {
  const q = Number(r.requested_quantity || 0)
  const p = Number(r.estimated_unit_price || 0)
  return (q * p).toFixed(2)
}

function addRow() {
  rows.value.push(newRow())
}
function removeRow(i: number) {
  rows.value.splice(i, 1)
}

function validateRows(): string | null {
  if (rows.value.length === 0) return '至少保留 1 行明细'
  for (let i = 0; i < rows.value.length; i++) {
    const r = rows.value[i]
    if (!r.material_id) return `第 ${i + 1} 行：请选择物料`
    const qty = Number(r.requested_quantity)
    if (!Number.isFinite(qty) || qty <= 0) return `第 ${i + 1} 行：申请数量必须大于 0`
    const price = Number(r.estimated_unit_price)
    if (!Number.isFinite(price) || price < 0) return `第 ${i + 1} 行：预估单价不能为负`
  }
  return null
}

async function onSave() {
  if (headerFormRef.value) {
    const ok = await headerFormRef.value.validate().catch(() => false)
    if (!ok) return
  }
  const err = validateRows()
  if (err) {
    ElMessage.warning(err)
    return
  }
  saving.value = true
  try {
    const items = rows.value.map((r) => ({
      id: isEdit.value ? (r.id ?? null) : undefined,
      material_id: r.material_id as number,
      requested_quantity: r.requested_quantity.trim(),
      estimated_unit_price: r.estimated_unit_price.trim(),
      required_date: r.required_date || null,
      remark: r.remark || null,
    }))
    if (isEdit.value) {
      const pr = await apiUpdatePr(prId.value, {
        version: version.value,
        apply_date: header.apply_date || null,
        reason: header.reason || null,
        items: items as never,
      })
      ElMessage.success('已保存（版本更新）')
      router.replace(`/purchase-requisitions/${pr.id}`)
    } else {
      const pr = await apiCreatePr({
        apply_date: header.apply_date || null,
        reason: header.reason || null,
        items: items as never,
      })
      ElMessage.success('采购申请已创建')
      router.replace(`/purchase-requisitions/${pr.id}`)
    }
  } catch (err) {
    if (err instanceof ApiBusinessError && err.code === 4011) {
      // 乐观锁冲突：提示重新加载
      try {
        await ElMessageBox.confirm(
          '该采购申请已被其他操作修改，保存已拒绝。是否重新加载最新版本？',
          '版本冲突',
          { type: 'warning', confirmButtonText: '重新加载', cancelButtonText: '返回列表' },
        )
        router.go(0)
      } catch {
        router.replace(`/purchase-requisitions/${prId.value}`)
      }
    }
    // 其余业务错误已由 request client toast
  } finally {
    saving.value = false
  }
}

onMounted(loadPr)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-page-header @back="router.back()" class="ph">
      <template #content>
        <span class="ph-title">{{ isEdit ? `编辑采购申请 #${prId}` : '新建采购申请' }}</span>
        <span v-if="isEdit" class="text-muted" style="font-size: 12px; margin-left: 10px">版本 v{{ version }}</span>
      </template>
    </el-page-header>

    <el-form ref="headerFormRef" :model="header" :rules="rules" label-width="90px" style="max-width: 640px; margin-top: 16px">
      <el-form-item label="申请原因">
        <el-input v-model="header.reason" type="textarea" :rows="2" maxlength="500" placeholder="申请事由（可空）" />
      </el-form-item>
      <el-form-item label="申请日期" prop="apply_date">
        <el-date-picker v-model="header.apply_date" type="date" value-format="YYYY-MM-DD" placeholder="默认今天" style="width: 200px" />
      </el-form-item>
    </el-form>

    <!-- 明细 -->
    <el-divider content-position="left"><span class="text-muted" style="font-size: 12px">申请明细</span></el-divider>
    <el-table :data="rows" border>
      <el-table-column label="#" width="46" align="center" type="index" />
      <el-table-column label="物料（仅启用物料）" min-width="230">
        <template #default="{ row }">
          <MaterialSelect
            :model-value="(row as Row).material_id"
            @update:model-value="(v: number | null) => { (row as Row).material_id = v; refreshMaterial(row as Row) }"
          />
        </template>
      </el-table-column>
      <el-table-column label="规格" width="140">
        <template #default="{ row }"><span class="text-muted">{{ (row as Row).specification || '-' }}</span></template>
      </el-table-column>
      <el-table-column label="单位" width="80">
        <template #default="{ row }"><span class="text-muted">{{ (row as Row).unit || '-' }}</span></template>
      </el-table-column>
      <el-table-column label="申请数量" width="140">
        <template #default="{ row }">
          <el-input v-model="(row as Row).requested_quantity" placeholder="> 0" />
        </template>
      </el-table-column>
      <el-table-column label="预估单价" width="140">
        <template #default="{ row }">
          <el-input v-model="(row as Row).estimated_unit_price" placeholder=">= 0" />
        </template>
      </el-table-column>
      <el-table-column label="预估金额" width="120" align="right">
        <template #default="{ row }">
          <span class="table-money">{{ formatMoney(rowAmount(row as Row)) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="需求日期" width="150">
        <template #default="{ row }">
          <el-date-picker v-model="(row as Row).required_date" type="date" value-format="YYYY-MM-DD" placeholder="可空" style="width: 100%" />
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="140">
        <template #default="{ row }">
          <el-input v-model="(row as Row).remark" maxlength="255" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="70" align="center" fixed="right">
        <template #default="{ $index }">
          <el-button link type="danger" :icon="Delete" :disabled="rows.length <= 1" @click="removeRow($index)" />
        </template>
      </el-table-column>
    </el-table>

    <div class="row-actions">
      <el-button :icon="Plus" @click="addRow">添加一行</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      <el-button @click="router.back()">取消</el-button>
      <span class="text-muted" style="font-size: 12px; margin-left: 8px">
        金额为前端实时预览，最终以服务端计算结果为准
      </span>
    </div>
  </div>
</template>

<style scoped>
.ph {
  margin-bottom: 4px;
}
.ph-title {
  font-weight: 600;
  font-size: 16px;
  color: #1f2329;
}
.row-actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
}
</style>
