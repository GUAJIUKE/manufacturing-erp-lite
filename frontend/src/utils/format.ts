// ---- 展示格式化工具（金额/数量保持字符串语义，不参与业务计算）----

/** 金额：¥1,234.56（负数显示 -¥1,000.00） */
export function formatMoney(value: string | number | null | undefined, symbol = '¥'): string {
  if (value === null || value === undefined || value === '') return `${symbol}0.00`
  const num = toFiniteNumber(value)
  const sign = num < 0 ? '-' : ''
  const abs = Math.abs(num)
  const fixed = abs.toFixed(2)
  const [int, dec] = fixed.split('.')
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${symbol}${grouped}.${dec}`
}

/** 数量：去尾零保留最多 4 位小数（默认 4 位进制），空显示 0 */
export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0'
  const num = toFiniteNumber(value)
  if (Number.isInteger(num)) return String(num)
  // 保留最多 4 位小数并去除尾零
  return String(num).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

/** 单价/成本：展示为原样字符串（避免浮点误差），如 "10" / "1,234.5000" */
export function formatDecimal(value: string | number | null | undefined, maxDigits = 4): string {
  if (value === null || value === undefined || value === '') return ''
  const s = String(value)
  if (!/^-?\d+(\.\d+)?$/.test(s)) return s // 非纯数字原样返回
  const neg = s.startsWith('-')
  const body = neg ? s.slice(1) : s
  const [int, frac = ''] = body.split('.')
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  if (!frac) return `${neg ? '-' : ''}${grouped}`
  const trimmed = frac.slice(0, maxDigits).replace(/0+$/, '')
  return `${neg ? '-' : ''}${grouped}${trimmed ? '.' + trimmed : ''}`
}

/** 带符号数量（流水等）：正数 +40，负数 -40 */
export function formatSignedQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0'
  const num = toFiniteNumber(value)
  if (num === 0) return '0'
  const q = formatQuantity(Math.abs(num))
  return num > 0 ? `+${q}` : `-${q}`
}

/** 带符号金额 */
export function formatSignedMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '¥0.00'
  const num = toFiniteNumber(value)
  if (num === 0) return '¥0.00'
  return num > 0 ? `+${formatMoney(num)}` : `-${formatMoney(Math.abs(num))}`
}

/** 日期（YYYY-MM-DD → YYYY-MM-DD，原样安全） */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '-'
  return String(value).slice(0, 10)
}

/** 时间（ISO → YYYY-MM-DD HH:mm:ss） */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function toFiniteNumber(value: string | number): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}
