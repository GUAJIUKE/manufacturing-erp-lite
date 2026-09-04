<script setup lang="ts">
import { ref, computed, watch } from 'vue';

// Quantity Chain — 基于真实业务规则的交互示意（非实时数据库）
// 7 字段链：Requested → Converted → Ordered → Received → Receipt → Txn → Balance
// 演示动作：第一次收 40 / 第二次收 60 / 冲销第二批 -60

const requested = ref(100);
const converted = ref(100);
const ordered = ref(100);
const received = ref(0);
const balance = ref(0);

const ledger = ref<{ id: number; type: string; qty: number; reason: string; sign: 'in'|'out' }[]>([]);
let nextId = 1;

function flash(name: string) {
  const el = document.querySelector(`[data-qc="${name}"]`);
  if (!el) return;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 600);
}

function recv40() {
  if (received.value >= 100) return;
  const qty = 40;
  received.value += qty;
  balance.value += qty;
  ledger.value.unshift({ id: nextId++, type: 'PURCHASE_IN', qty, reason: '第一次收货 (40 pcs @W1)', sign: 'in' });
  flash('received'); flash('balance');
}
function recv60() {
  if (received.value >= 100) return;
  const remaining = 100 - received.value;
  const qty = Math.min(60, remaining);
  received.value += qty;
  balance.value += qty;
  ledger.value.unshift({ id: nextId++, type: 'PURCHASE_IN', qty, reason: '第二次收货 (60 pcs @W1)', sign: 'in' });
  flash('received'); flash('balance');
}
function reverse60() {
  // 冲销第二批 60：余额 60 → 0；并发流水 REVERSAL(-60)
  if (received.value < 60) return;
  const qty = 60;
  received.value -= qty;
  balance.value -= qty;
  ledger.value.unshift({ id: nextId++, type: 'REVERSAL', qty: -qty, reason: '冲销第二批（用户撤回入库单）', sign: 'out' });
  flash('received'); flash('balance');
}
function reset() {
  received.value = 0;
  balance.value = 0;
  ledger.value = [];
  nextId = 1;
}

const fields = computed(() => [
  { name: 'requested', label: 'Requested', value: requested.value, max: requested.value },
  { name: 'converted', label: 'Converted', value: converted.value, max: requested.value },
  { name: 'ordered',   label: 'Ordered',   value: ordered.value,   max: requested.value },
  { name: 'received',  label: 'Received',  value: received.value,  max: ordered.value },
  { name: 'balance',   label: 'Balance',   value: balance.value,   max: requested.value },
]);
</script>

<template>
  <section id="qty" class="section">
    <div class="container">
      <span class="section-eyebrow">数量链</span>
      <h2 class="section-title">Requested → Balance 七字段链</h2>
      <p class="section-subtitle">
        四字段（requested/converted/ordered/received）无法合并：拆分 PO 需要 converted，分批收货需要 received。
        下方动作按真实业务规则模拟，访问者应将其视为「基于真实业务规则的交互示意」。
      </p>
      <span class="concept-banner" style="margin-bottom:16px;">
        ⚠️ Concept animation based on actual ERP rules
      </span>

      <div class="qc-wrap">
        <!-- 左：字段状态 + 操作按钮 -->
        <div class="qc-fields">
          <div
            v-for="f in fields"
            :key="f.name"
            class="qc-row"
            :data-qc="f.name"
          >
            <div class="name">{{ f.label }}</div>
            <div class="bar"><i :style="{ width: ((f.value / Math.max(1,f.max)) * 100) + '%' }"></i></div>
            <div class="val">{{ f.value }}</div>
          </div>

          <div class="qc-actions">
            <button class="btn btn-primary" :disabled="received >= 100" @click="recv40">第一次收货 +40</button>
            <button class="btn btn-primary" :disabled="received >= 100" @click="recv60">第二次收货 +60</button>
            <button class="btn btn-ghost"   :disabled="received < 60"   @click="reverse60">冲销第二批 -60</button>
            <button class="btn btn-ghost"   :disabled="received === 0 && ledger.length === 0" @click="reset">重置</button>
          </div>
        </div>

        <!-- 右：append-only ledger 实时追加 -->
        <div class="qc-ledger" aria-live="polite">
          <h4>inventory_transactions（append-only）</h4>
          <ul v-if="ledger.length">
            <li v-for="row in ledger" :key="row.id" :class="row.sign">
              <span :class="row.sign === 'in' ? 'tag tag-ok' : 'tag tag-err'">
                {{ row.sign === 'in' ? '+' : '-' }}
              </span>
              <span class="type">{{ row.type }}</span>
              <span class="reason muted">{{ row.reason }}</span>
              <span class="qty" :style="{ color: row.sign === 'in' ? 'var(--c-ok-2)' : 'var(--c-err-2)' }">
                {{ row.sign === 'in' ? '+' : '' }}{{ row.qty }}
              </span>
            </li>
          </ul>
          <p v-else class="muted" style="margin:0;">点击按钮开始模拟。</p>
        </div>
      </div>
    </div>
  </section>
</template>