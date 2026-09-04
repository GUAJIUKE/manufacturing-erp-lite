<script setup lang="ts">
// Inventory Ledger Story — append-only ledger vs balance snapshot
// Timeline 动画：4 行流水逐条出现，最后总结 Transaction vs Balance 区别。

const ledgerRows = [
  { type: 'PURCHASE_IN', qty: '+40',  amount: '+¥400.00',  reason: 'W1 第一次入库',         ts: 'T+00:10' },
  { type: 'PURCHASE_IN', qty: '+60',  amount: '+¥600.00',  reason: 'W1 第二次入库',         ts: 'T+00:25' },
  { type: 'REVERSAL',    qty: '-60',  amount: '-¥600.00',  reason: '撤回第二批（用户冲销）', ts: 'T+00:30' },
  { type: 'BAL_SNAPSHOT',qty: '40',   amount: '¥400.00',   reason: '当前 Balance 快照',      ts: 'T+00:31', isBalance: true },
];
</script>

<template>
  <section id="ledger" class="section">
    <div class="container">
      <span class="section-eyebrow">库存账设计</span>
      <h2 class="section-title">Ledger（不可变流水）vs Balance（当前快照）</h2>
      <p class="section-subtitle">
        移动加权平均：10×10 + 10×20 = qty20 / 总额300 / 均价15。<br />
        冲销必须按原始 receipt 金额回滚，而不是 current_avg × qty。
      </p>

      <div class="grid grid-2 reveal">
        <!-- 时间线 -->
        <div class="card">
          <h4 style="margin:0 0 12px;font-size:14px;color:var(--c-ink-3);">inventory_transactions（MySQL 触发器 trg_it_no_update/no_delete）</h4>
          <ul style="list-style:none;margin:0;padding:0;display:grid;gap:8px;">
            <li
              v-for="(r, i) in ledgerRows"
              :key="i"
              class="tl-row"
              :style="{
                borderLeft: r.isBalance ? '3px solid var(--c-brand-500)' : (r.type === 'REVERSAL' ? '3px solid var(--c-err)' : '3px solid var(--c-ok)'),
                animation: 'ledger-slide .35s ease ' + (i * 0.15) + 's both',
              }"
            >
              <span class="tag tl-type" :class="r.isBalance ? 'tag-info' : (r.type === 'REVERSAL' ? 'tag-err' : 'tag-ok')">{{ r.type }}</span>
              <span class="tl-qty" :style="{ color: r.type === 'REVERSAL' ? 'var(--c-err-2)' : 'var(--c-ok-2)' }">{{ r.qty }}</span>
              <span class="tl-amt">{{ r.amount }}</span>
              <span class="tl-rsn">{{ r.reason }}</span>
              <span class="tl-ts">{{ r.ts }}</span>
            </li>
          </ul>
        </div>

        <!-- 设计原则 -->
        <div class="card">
          <h4 style="margin:0 0 12px;font-size:14px;color:var(--c-ink-3);">关键原则</h4>
          <ul style="margin:0;padding-left:18px;font-size:14px;color:var(--c-ink-3);line-height:1.8;">
            <li><b>append-only</b>：流水靠 MySQL 触发器强制（不可改/不可删）。</li>
            <li><b>Balance</b>：当前库存快照；quantity=40、total_amount=¥400.00。</li>
            <li><b>符号约定</b>：PURCHASE_IN(+)、REVERSAL(−)；SUM(sources)==Balance。</li>
            <li><b>加权平均</b>：total_amount 为权威（ROUND_HALF_UP/2 位），average_unit_cost 派生（4 位）。</li>
            <li><b>冲销金额</b>：回滚 <code>-original.amount</code>，而非 current_avg × qty。</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>