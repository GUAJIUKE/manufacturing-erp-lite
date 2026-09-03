// ---- Phase 11 Dashboard 前端单测 ----
// 覆盖：待办 type→文案/跳转映射、动态 action→文案、TAG_COLOR 全站色板、
// KpiCard 展示与点击下钻。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

import { actionLabel, todoLabel, todoRoute, TODO_LABEL } from '@/utils/dashboard'
import { tagColor } from '@/utils/status'
import KpiCard from '@/components/KpiCard.vue'

describe('待办 type → 文案映射（与后端 dashboard_service type 一一对应）', () => {
  it('四种待办全覆盖', () => {
    expect(todoLabel('PR_APPROVAL')).toBe('待审批采购申请')
    expect(todoLabel('PR_TO_PO')).toBe('待转采购订单')
    expect(todoLabel('PO_CONFIRM')).toBe('待确认采购订单')
    expect(todoLabel('PO_RECEIVE')).toBe('待收货入库')
  })
  it('未知 type 回退为原文', () => {
    expect(todoLabel('FOO_BAR')).toBe('FOO_BAR')
  })
  it('文案表不包含空串', () => {
    expect(Object.values(TODO_LABEL).every((v) => v.length > 0)).toBe(true)
  })
})

describe('待办 → 下钻跳转', () => {
  it('PR_APPROVAL → 审批中心', () => {
    expect(todoRoute('PR_APPROVAL', { canCreateReceipt: false })).toEqual({ path: '/approvals' })
  })
  it('PR_TO_PO → PR 列表（转单入口）', () => {
    expect(todoRoute('PR_TO_PO', { canCreateReceipt: false })).toEqual({
      path: '/purchase-requisitions',
    })
  })
  it('PO_CONFIRM → DRAFT 过滤的 PO 列表', () => {
    expect(todoRoute('PO_CONFIRM', { canCreateReceipt: false })).toEqual({
      path: '/purchase-orders',
      query: { status: 'DRAFT' },
    })
  })
  it('PO_RECEIVE 区分角色：能建入库单 → 入库登记页；否则 → PO 列表', () => {
    expect(todoRoute('PO_RECEIVE', { canCreateReceipt: true })).toEqual({
      path: '/purchase-receipts/create',
    })
    expect(todoRoute('PO_RECEIVE', { canCreateReceipt: false })).toEqual({
      path: '/purchase-orders',
    })
  })
  it('未知 type → 回退首页', () => {
    expect(todoRoute('UNKNOWN', { canCreateReceipt: false })).toEqual({ path: '/dashboard' })
  })
})

describe('采购动态 action → 中文文案（后端 _RECENT_ACTIONS 全量）', () => {
  it('关键业务动作全覆盖', () => {
    const actions = [
      'PR_CREATE', 'PR_SUBMIT', 'PR_APPROVE', 'PR_REJECT', 'PR_REVISE', 'PR_CANCEL',
      'PO_CREATE', 'PO_CONFIRM', 'PO_CANCEL', 'RECEIPT_POST', 'RECEIPT_REVERSE',
    ]
    for (const a of actions) {
      expect(actionLabel(a).length).toBeGreaterThan(0)
      expect(actionLabel(a)).not.toBe(a)
    }
  })
  it('LOGIN 等非业务动作不回退为空白', () => {
    // LOGIN 不在映射中：后端已过滤，前端兜底显示原文即可
    expect(actionLabel('LOGIN')).toBe('LOGIN')
  })
})

describe('全站状态色板 TAG_COLOR', () => {
  it('五类 TagType 均有色值', () => {
    for (const t of ['success', 'warning', 'danger', 'info', 'primary']) {
      expect(tagColor(t)).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
  it('未知类型回退中性灰', () => {
    expect(tagColor('nope')).toBe('#8a919f')
  })
})

describe('KpiCard', () => {
  beforeEach(() => {
    pushMock.mockReset()
  })

  it('渲染 label/value，并显示箭头（可点击）', () => {
    const wrapper = mount(KpiCard, {
      props: {
        label: '低库存预警',
        value: '3',
        accent: '#d93026',
        to: '/inventory',
        query: { below_safety_stock: true },
      },
      global: { plugins: [ElementPlus], components: { ArrowRight } },
    })
    expect(wrapper.text()).toContain('低库存预警')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.classes()).toContain('is-link')
  })

  it('点击后以下钻目标路由跳转', async () => {
    const wrapper = mount(KpiCard, {
      props: {
        label: '待确认采购订单',
        value: '2',
        to: '/purchase-orders',
        query: { status: 'DRAFT' },
      },
      global: { plugins: [ElementPlus], components: { ArrowRight } },
    })
    await wrapper.find('.kpi-card').trigger('click')
    expect(pushMock).toHaveBeenCalledWith({ path: '/purchase-orders', query: { status: 'DRAFT' } })
  })

  it('无 to 时不触发跳转', async () => {
    const wrapper = mount(KpiCard, {
      props: { label: '库存账面金额', value: '¥1,234.00' },
      global: { plugins: [ElementPlus], components: { ArrowRight } },
    })
    await wrapper.find('.kpi-card').trigger('click')
    expect(pushMock).not.toHaveBeenCalled()
  })
})
