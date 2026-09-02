import { http } from './request'
import type { PageResult, PageQuery } from '@/types/api'
import type { BalanceRow, Transaction } from '@/types/models'
import type { TxnType } from '@/types/enums'

export interface BalanceQuery extends PageQuery {
  warehouse_id?: number
  material_id?: number
  material_code?: string
  material_name?: string
  below_safety_stock?: boolean
}

export interface TxnQuery extends PageQuery {
  warehouse_id?: number
  material_id?: number
  transaction_type?: TxnType | ''
  reference_no?: string
  occurred_from?: string
  occurred_to?: string
}

export function apiBalances(params: BalanceQuery) {
  return http.get<PageResult<BalanceRow>>('/inventory/balances', params as Record<string, unknown>)
}

export function apiTransactions(params: TxnQuery) {
  return http.get<PageResult<Transaction>>('/inventory/transactions', params as Record<string, unknown>)
}
