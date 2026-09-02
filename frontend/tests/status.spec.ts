// ---- 集中状态映射单测（全站唯一权威映射，禁止页面各自判断）----
import { describe, expect, it } from 'vitest'
import {
  activeStatusMeta,
  poStatusMeta,
  prStatusMeta,
  receiptStatusMeta,
  roleCodeLabel,
  txnTypeMeta,
  userStatusMeta,
  type StatusMeta,
} from '@/utils/status'

function expectMeta(meta: StatusMeta, label: string, type: string) {
  expect(meta.label).toBe(label)
  expect(meta.type).toBe(type)
}

describe('PR 状态映射', () => {
  it('六态全覆盖', () => {
    expectMeta(prStatusMeta('DRAFT'), '草稿', 'info')
    expectMeta(prStatusMeta('PENDING'), '待审批', 'warning')
    expectMeta(prStatusMeta('APPROVED'), '已批准', 'success')
    expectMeta(prStatusMeta('REJECTED'), '已驳回', 'danger')
    expectMeta(prStatusMeta('CANCELLED'), '已取消', 'info')
    expectMeta(prStatusMeta('CONVERTED'), '已转PO', 'primary')
  })
  it('未知值回退为原文', () => {
    expectMeta(prStatusMeta('FOO'), 'FOO', 'info')
  })
})

describe('PO 状态映射', () => {
  it('五态全覆盖', () => {
    expectMeta(poStatusMeta('DRAFT'), '草稿', 'info')
    expectMeta(poStatusMeta('CONFIRMED'), '已确认', 'primary')
    expectMeta(poStatusMeta('PARTIALLY_RECEIVED'), '部分收货', 'warning')
    expectMeta(poStatusMeta('RECEIVED'), '已收完', 'success')
    expectMeta(poStatusMeta('CANCELLED'), '已取消', 'info')
  })
})

describe('Receipt 状态映射', () => {
  it('POSTED/REVERSED', () => {
    expectMeta(receiptStatusMeta('POSTED'), '已过账', 'success')
    expectMeta(receiptStatusMeta('REVERSED'), '已冲销', 'danger')
  })
})

describe('启停/用户状态', () => {
  it('主数据 ACTIVE/DISABLED', () => {
    expectMeta(activeStatusMeta('ACTIVE'), '启用', 'success')
    expectMeta(activeStatusMeta('DISABLED'), '停用', 'info')
  })
  it('用户状态', () => {
    expectMeta(userStatusMeta('ACTIVE'), '启用', 'success')
    expectMeta(userStatusMeta('DISABLED'), '停用', 'danger')
  })
})

describe('流水类型映射', () => {
  it('六类全覆盖', () => {
    expectMeta(txnTypeMeta('PURCHASE_IN'), '采购入库', 'success')
    expectMeta(txnTypeMeta('PURCHASE_IN_REVERSAL'), '入库冲销', 'danger')
    expectMeta(txnTypeMeta('ADJUST_IN'), '调整入库', 'primary')
    expectMeta(txnTypeMeta('ADJUST_OUT'), '调整出库', 'warning')
    expectMeta(txnTypeMeta('PRODUCTION_IN'), '生产入库', 'success')
    expectMeta(txnTypeMeta('PRODUCTION_OUT'), '生产领料', 'warning')
  })
})

describe('角色编码 → 中文名', () => {
  it('五角色全覆盖', () => {
    expect(roleCodeLabel('ADMIN')).toBe('系统管理员')
    expect(roleCodeLabel('APPLICANT')).toBe('采购申请人')
    expect(roleCodeLabel('DEPT_MANAGER')).toBe('部门主管')
    expect(roleCodeLabel('BUYER')).toBe('采购员')
    expect(roleCodeLabel('WAREHOUSE')).toBe('仓库管理员')
  })
})
