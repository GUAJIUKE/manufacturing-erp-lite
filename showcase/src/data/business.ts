// Manufacturing ERP Lite — Showcase 数据常量
// 所有数字/字段/错误码与真实代码严格一致，引用自 backend/app/core/exceptions.py 等事实源。

// ---- 业务链节点 -------------------------------------------------------
export interface FlowNode {
  key: string;
  code: string;
  title: string;
  role: string;        // 演示中的执行角色
  detail: string;      // 触发动作
  path: string;        // ERP 真实路由（仅参考）
}

export const FLOW: FlowNode[] = [
  { key: 'pr',        code: 'PR',     title: '采购申请',     role: '申请人 zhangsan',  detail: '基于研发样机物料提出需求，状态 DRAFT', path: '/purchase-requisitions/create' },
  { key: 'approval',  code: '审批',   title: '部门主管审批', role: '主管 lisi',        detail: '审批通过 → APPROVED；驳回可改回 DRAFT', path: '/approvals' },
  { key: 'po',        code: 'PO',     title: '采购订单',     role: '采购员 wangwu',    detail: '从 APPROVED PR 转 PO → CONFIRMED',       path: '/purchase-orders' },
  { key: 'receipt',   code: '入库',   title: '分批收货',     role: '仓库 zhaoliu',     detail: 'CAS 防超收（错误码 6002）',             path: '/purchase-receipts' },
  { key: 'inventory', code: '库存',   title: '库存账更新',   role: 'append-only ledger', detail: 'PURCHASE_IN(+) / REVERSAL(-)',          path: '/inventory' },
  { key: 'dashboard', code: '看板',   title: '管理驾驶舱',   role: '管理层',           detail: '5 个角色收敛待办 + 库存金额 ¥1190.00',  path: '/dashboard' },
];

// ---- RBAC 角色 × 模块 -----------------------------------------------
export interface RoleModule {
  module: string;
  read: boolean;
  write: boolean;
  approve?: boolean;
}

export interface Role {
  key: string;
  label: string;
  who: string;
  focus: string;          // Dashboard 重点
  matrix: RoleModule[];
}

export const ROLES: Role[] = [
  {
    key: 'applicant', label: '申请人', who: 'zhangsan · 研发部',
    focus: '只看自己的 PR；待办=自己 PENDING',
    matrix: [
      { module: '采购申请 PR',   read: true,  write: true },
      { module: '审批 Approvals',read: false, write: false, approve: false },
      { module: '采购订单 PO',   read: true,  write: false },
      { module: '入库 Receipt',  read: false, write: false },
      { module: '库存余额',      read: true,  write: false },
      { module: 'Dashboard',     read: true,  write: false },
    ],
  },
  {
    key: 'manager', label: '部门主管', who: 'lisi · 研发部主管',
    focus: '本部门审批；可见本部门 PR',
    matrix: [
      { module: '采购申请 PR',   read: true,  write: false, approve: true },
      { module: '审批 Approvals',read: true,  write: false, approve: true },
      { module: '采购订单 PO',   read: true,  write: false },
      { module: '入库 Receipt',  read: false, write: false },
      { module: '库存余额',      read: true,  write: false },
      { module: 'Dashboard',     read: true,  write: false },
    ],
  },
  {
    key: 'buyer', label: '采购员', who: 'wangwu · 采购部',
    focus: '转 PO / 确认 PO；与申请人跨部门',
    matrix: [
      { module: '采购申请 PR',   read: true,  write: false },
      { module: '审批 Approvals',read: true,  write: false },
      { module: '采购订单 PO',   read: true,  write: true,  approve: true },
      { module: '入库 Receipt',  read: true,  write: false },
      { module: '库存余额',      read: true,  write: false },
      { module: 'Dashboard',     read: true,  write: false },
    ],
  },
  {
    key: 'warehouse', label: '仓库管理员', who: 'zhaoliu · 仓库',
    focus: '收货入库；平衡 PR/PO 与 Balance',
    matrix: [
      { module: '采购申请 PR',   read: false, write: false },
      { module: '审批 Approvals',read: false, write: false },
      { module: '采购订单 PO',   read: true,  write: false },
      { module: '入库 Receipt',  read: true,  write: true },
      { module: '库存余额',      read: true,  write: false },
      { module: '库存流水',      read: true,  write: false },
      { module: 'Dashboard',     read: true,  write: false },
    ],
  },
  {
    key: 'admin', label: '管理员', who: 'admin',
    focus: '全部模块 + 用户/角色配置',
    matrix: [
      { module: '采购申请 PR',   read: true,  write: true,  approve: true },
      { module: '审批 Approvals',read: true,  write: false, approve: true },
      { module: '采购订单 PO',   read: true,  write: true,  approve: true },
      { module: '入库 Receipt',  read: true,  write: true },
      { module: '库存余额',      read: true,  write: false },
      { module: '库存流水',      read: true,  write: false },
      { module: '用户/角色',     read: true,  write: true },
      { module: 'Dashboard',     read: true,  write: false },
    ],
  },
];

// ---- 错误码域（与 exceptions.py 一致） -------------------------------
export interface ErrCode { code: number; name: string; tag: '通用'|'认证'|'主数据'|'PR'|'PO'|'库存'; meaning: string; }
export const ERR_CODES: ErrCode[] = [
  { code: 4002, name: 'PR_INVALID_STATUS_TRANSITION', tag: 'PR',   meaning: 'PR 状态非法流转（_TRANSITIONS 白名单）' },
  { code: 4011, name: 'PR_VERSION_CONFLICT',          tag: 'PR',   meaning: 'PR 乐观锁冲突（version 不匹配）' },
  { code: 4012, name: 'PR_ALREADY_PROCESSED',         tag: 'PR',   meaning: 'PR 已被并发审批处理' },
  { code: 5012, name: 'PO_VERSION_CONFLICT',          tag: 'PO',   meaning: 'PO 乐观锁冲突' },
  { code: 6002, name: 'INVENTORY_OVER_RECEIPT',       tag: '库存', meaning: '入库数量超过 PO 已订量（CAS 拒绝）' },
  { code: 6009, name: 'INVENTORY_NEGATIVE',           tag: '库存', meaning: '冲销后余额为负（违反单调性）' },
  { code: 2005, name: 'PERMISSION_DENIED',            tag: '认证', meaning: '路由层 RBAC 拒绝（require_perm）' },
];

// ---- 5 个工程挑战 ----------------------------------------------------
export interface Challenge {
  n: number;
  title: string;
  problem: string;
  solution: string;
  why: string;
  where: string;        // 代码位置
}

export const CHALLENGES: Challenge[] = [
  {
    n: 1, title: 'Lost Update（PR/PO 状态并发改写）',
    problem: '两个审批人同时点击 Approve，后写覆盖先写 → 一份审批被静默吞掉。',
    solution: '乐观锁 version：UPDATE … WHERE id=? AND version=?；rowcount==0 → 4011/4012。',
    why: '状态字段是审计的最小事实；不能用 SELECT-then-UPDATE。',
    where: 'services/purchase_requisition_service.py · purchase_order_service.py',
  },
  {
    n: 2, title: 'Converted 字段并发超转（PR→PO）',
    problem: '两个采购员同时把同一 PR 部分转 PO，总量超过 requested。',
    solution: 'CAS：`converted_quantity + qty <= requested_quantity`；失败 → 4009。',
    why: 'requested/converted/ordered/received 是审计链四字段，不能合并也不能省略。',
    where: 'purchase_requisition_service.convert_to_po()',
  },
  {
    n: 3, title: 'Concurrent Over-receipt（超收）',
    problem: '两个仓库同时收同一 PO 的同一行 → 账实不符。',
    solution: 'CAS：`received_quantity + qty <= ordered_quantity`；失败 → 6002。',
    why: '收货是库存的入口；入口失守则流水/Balance 全部失真。',
    where: 'services/purchase_receipt_service.py',
  },
  {
    n: 4, title: 'Inventory Consistency（事务原子）',
    problem: '收货成功但流水/Balance/PO 状态散落写，机器宕机则账实分裂。',
    solution: 'Receipt + PO CAS + Txn + Balance + 状态 + 审计，七类写入同 session 提交；任一失败整体回滚。',
    why: 'append-only 流水靠 MySQL 触发器 trg_it_no_update/trg_it_no_delete 强制，事务边界是唯一保护。',
    where: 'purchase_receipt_service.create()',
  },
  {
    n: 5, title: 'Deadlock Risk（统一锁序）',
    problem: '多物料并发入库时，对 (warehouse,material) 的行锁方向不一致 → 死锁。',
    solution: '`lock_balances` 按 (warehouse_id, material_id) 升序一次取齐，事务内所有行锁之前获取。',
    why: '死锁检测/回滚成本不可控；预防优于治疗。',
    where: 'inventory_service.lock_balances()',
  },
];

// ---- 真实代码片段（3 个） --------------------------------------------
export interface Snippet { title: string; file: string; lang: 'python'; code: string; }
export const SNIPPETS: Snippet[] = [
  {
    title: 'PO Optimistic Lock（version 条件更新）',
    file: 'backend/app/services/purchase_order_service.py · confirm_po()',
    lang: 'python',
    code: `row = self.db.execute(
    update(PurchaseOrder)
    .where(PurchaseOrder.id == po_id,
            PurchaseOrder.version == expected_version,
            PurchaseOrder.status == 'DRAFT')
    .values(status='CONFIRMED', version=expected_version + 1,
            confirmed_at=now())
).rowcount

if row == 0:
    # 区分：版本冲突 vs 状态非法
    cur = self.db.get(po_id)
    if cur.version != expected_version:
        raise BizError(5012, 'PO_VERSION_CONFLICT')
    raise BizError(5002, 'PO_INVALID_STATUS_TRANSITION')`,
  },
  {
    title: 'Receipt CAS（防超收 + 原子化）',
    file: 'backend/app/services/purchase_receipt_service.py · create()',
    lang: 'python',
    code: `row = self.db.execute(
    update(PurchaseOrderLine)
    .where(PurchaseOrderLine.id == line_id,
           PurchaseOrderLine.received_quantity + qty
             <= PurchaseOrderLine.ordered_quantity)
    .values(received_quantity =
            PurchaseOrderLine.received_quantity + qty,
            version=PurchaseOrderLine.version + 1)
).rowcount
if row == 0:
    raise BizError(6002, 'INVENTORY_OVER_RECEIPT')

# 同 session 内继续：流水 + Balance + PO 状态 + 审计
self._append_txn(...); self._upsert_balance(...);
self._recompute_po_status(...); self._audit(...)`,
  },
  {
    title: 'Deterministic Balance Lock Ordering',
    file: 'backend/app/services/inventory_service.py · lock_balances()',
    lang: 'python',
    code: `# 关键：先排序再一次性拿锁，避免两个事务相反顺序锁同一组行
keys = sorted({(wh, mat) for (wh, mat, _qty) in pairs})
# 取快照行（upsert 触发器让 id 自增可重入）
for wh, mat in keys:
    self.db.execute(
        text("INSERT INTO inventory_balances(warehouse_id,material_id,quantity) "
             "VALUES(:w,:m,0) "
             "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)"),
        {"w": wh, "m": mat},
    )
# 然后按同序 SELECT FOR UPDATE 真正持锁
self.db.execute(
    select(Balance).where(tuple_(Balance.warehouse_id, Balance.material_id)
                          .in_(keys))
    .with_for_update()
)`,
  },
];

// ---- 真实 KPI（admin 视角） -----------------------------------------
export interface KPI { label: string; value: string; tip: string; }
export const KPIS: KPI[] = [
  { label: '待审批 PR',        value: '2',   tip: 'status == PENDING 且可见性命中（visible_pr_condition）' },
  { label: '待转采购订单',     value: '2',   tip: 'status == APPROVED 且 EXISTS converted<requested，再 COUNT DISTINCT PR' },
  { label: '待确认 PO',        value: '1',   tip: 'status == DRAFT（采购员尚未 Confirm）' },
  { label: '待收货 PO',        value: '1',   tip: 'status ∈ {CONFIRMED, PARTIALLY_RECEIVED}（自动收）' },
  { label: '低库存预警',       value: '2',   tip: 'quantity < safety_stock（严格小于；无策略行不计入）' },
  { label: '库存账面金额',     value: '¥1,190.00', tip: 'SUM(inventory_balances.total_amount)；同单位' },
];

// ---- 测试数字（Phase 12 checkpoint） ---------------------------------
export const TEST_EVIDENCE = [
  { name: 'backend pytest', value: '229 passed', note: '覆盖核心业务、并发、流水、RBAC 隔离' },
  { name: '覆盖率',          value: '91%',      note: 'business-critical services / repositories / schemas' },
  { name: 'frontend vitest',value: '47 passed', note: '组件级 + store + composables' },
  { name: 'API smoke',       value: '35 checks',note: '5 角色收敛 + 业务链冒烟' },
  { name: 'alembic check',   value: '无新迁移',  note: '当前代码与 schema 一致' },
];

// ---- Header 导航 -----------------------------------------------------
export const NAV = [
  { href: '#overview',  label: '概览' },
  { href: '#flow',      label: '业务流' },
  { href: '#qty',       label: '数量链' },
  { href: '#ledger',    label: '库存账' },
  { href: '#rbac',      label: '权限模型' },
  { href: '#dashboard', label: '驾驶舱' },
  { href: '#arch',      label: '架构' },
  { href: '#challenges',label: '挑战' },
  { href: '#testing',   label: '测试' },
  { href: '#gallery',   label: '截图' },
  { href: '#docs',      label: '文档' },
];