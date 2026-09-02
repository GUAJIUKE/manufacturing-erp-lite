// 通用「ACTIVE 主数据远程下拉」逻辑：组件内只拉启用数据
import { onMounted, ref } from 'vue'

export interface SelectOption {
  value: number
  label: string
  sub?: string
}

/** 主数据行必须含 id 与 status（用于过滤 ACTIVE） */
export interface ActiveRow {
  id: number
  status: string
}

export function useActiveSelect<T extends ActiveRow>(
  fetcher: (params: Record<string, unknown>) => Promise<{ items: T[] }>,
  opts: {
    searchKeys?: string[]
    codeKey?: keyof T
    nameKey?: keyof T
    pageSize?: number
  } = {},
) {
  const { searchKeys = [], codeKey = 'code' as keyof T, nameKey = 'name' as keyof T, pageSize = 50 } = opts
  const options = ref<SelectOption[]>([])
  const loading = ref(false)

  async function load(search = ''): Promise<void> {
    loading.value = true
    try {
      const params: Record<string, unknown> = { page: 1, page_size: pageSize, status: 'ACTIVE' }
      for (const k of searchKeys) {
        params[k] = search || undefined
      }
      const page = await fetcher(params)
      options.value = page.items.map((it) => {
        const code = String(it[codeKey] ?? '')
        const name = String(it[nameKey] ?? '')
        return { value: it.id, label: name, sub: code }
      })
    } catch {
      options.value = []
    } finally {
      loading.value = false
    }
  }

  onMounted(() => load())

  return { options, loading, load }
}
