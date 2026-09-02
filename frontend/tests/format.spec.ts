// ---- 展示格式化工具单测（金额/数量保持字符串语义）----
import { describe, expect, it } from 'vitest'
import {
  formatDate,
  formatDateTime,
  formatDecimal,
  formatMoney,
  formatQuantity,
  formatSignedMoney,
  formatSignedQuantity,
} from '@/utils/format'

describe('formatMoney', () => {
  it('千分位分组 + ¥ 符号', () => {
    expect(formatMoney('1234.56')).toBe('¥1,234.56')
    expect(formatMoney(1234567.891)).toBe('¥1,234,567.89')
  })
  it('负数显示 -¥', () => {
    expect(formatMoney('-1000')).toBe('-¥1,000.00')
    expect(formatMoney('-0.5')).toBe('-¥0.50')
  })
  it('空/非法回退 ¥0.00', () => {
    expect(formatMoney(null)).toBe('¥0.00')
    expect(formatMoney('')).toBe('¥0.00')
    expect(formatMoney(undefined)).toBe('¥0.00')
  })
})

describe('formatQuantity', () => {
  it('去掉尾零，整数不带小数点', () => {
    expect(formatQuantity('40.0000')).toBe('40')
    expect(formatQuantity('1.5000')).toBe('1.5')
    expect(formatQuantity('0')).toBe('0')
    expect(formatQuantity('-3.2500')).toBe('-3.25')
  })
  it('空显示 0', () => {
    expect(formatQuantity(null)).toBe('0')
    expect(formatQuantity('')).toBe('0')
  })
})

describe('formatDecimal', () => {
  it('千分位但保留有效小数', () => {
    expect(formatDecimal('1234.5000')).toBe('1,234.5')
    expect(formatDecimal('12.3400')).toBe('12.34')
    expect(formatDecimal('88')).toBe('88')
  })
  it('负数保留符号', () => {
    expect(formatDecimal('-1234.5000')).toBe('-1,234.5')
  })
  it('非数字原样返回（如币种占位）', () => {
    expect(formatDecimal('abc')).toBe('abc')
    expect(formatDecimal(null)).toBe('')
  })
})

describe('formatSignedQuantity / formatSignedMoney（带符号流水展示）', () => {
  it('正数带 +，负数带 -，零不带符号', () => {
    expect(formatSignedQuantity('40')).toBe('+40')
    expect(formatSignedQuantity('-40')).toBe('-40')
    expect(formatSignedQuantity('0')).toBe('0')
    expect(formatSignedQuantity(null)).toBe('0')
  })
  it('金额同理', () => {
    expect(formatSignedMoney('1000.00')).toBe('+¥1,000.00')
    expect(formatSignedMoney('-1000.00')).toBe('-¥1,000.00')
    expect(formatSignedMoney('0')).toBe('¥0.00')
  })
})

describe('date / datetime', () => {
  it('formatDate 截取 YYYY-MM-DD', () => {
    expect(formatDate('2026-09-01T10:30:00')).toBe('2026-09-01')
    expect(formatDate(null)).toBe('-')
  })
  it('formatDateTime 输出本地时间', () => {
    const d = formatDateTime('2026-09-01T10:05:09')
    expect(d).toMatch(/^2026-09-01 \d{2}:05:09$/)
    expect(formatDateTime(null)).toBe('-')
  })
})
