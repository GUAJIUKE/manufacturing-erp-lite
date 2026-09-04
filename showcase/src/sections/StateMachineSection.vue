<script setup lang="ts">
import { ref } from 'vue';

// State Machine — PR 状态机展示。点击节点展示允许/禁止的操作 + 错误码。

interface SMNode {
  key: string;
  label: string;
  allow: string[];
  forbid: string[];
  why: string;
  code?: number;
}

const nodes: SMNode[] = [
  {
    key: 'DRAFT',
    label: 'DRAFT',
    allow: ['Edit', 'Submit', 'Cancel'],
    forbid: ['Approve', 'Reject'],
    why: '申请人撰写中，未进入审批流。',
  },
  {
    key: 'PENDING',
    label: 'PENDING',
    allow: ['Approve', 'Reject'],
    forbid: ['Edit'],
    why: '已提交审批；编辑会破坏审计链。',
    code: 4002,
  },
  {
    key: 'APPROVED',
    label: 'APPROVED',
    allow: ['Convert to PO', 'Cancel'],
    forbid: ['Edit'],
    why: '采购员可转 PO；取消需 ADMIN。',
  },
  {
    key: 'REJECTED',
    label: 'REJECTED',
    forbid: ['Edit'],
    allow: ['回退为 DRAFT'],
    why: '审批驳回后允许申请人重新编辑。',
  },
  {
    key: 'CONVERTED',
    label: 'CONVERTED',
    allow: ['查看关联 PO'],
    forbid: ['Edit', 'Cancel'],
    why: '已转 PO；任何修改须走 PO 反向流程。',
  },
  {
    key: 'CANCELLED',
    label: 'CANCELLED',
    allow: ['（终态）'],
    forbid: ['Edit', 'Approve'],
    why: '终态；不可再变更。',
  },
];

const active = ref<SMNode>(nodes[1]);
function pick(n: SMNode) { active.value = n; }
</script>

<template>
  <section id="state" class="section">
    <div class="container">
      <span class="section-eyebrow">状态机</span>
      <h2 class="section-title">PR 状态机：为什么审批中的单据不能编辑</h2>
      <p class="section-subtitle">
        所有状态变更走 <code>_TRANSITIONS</code> 白名单；非法流转统一报 4002 PR_INVALID_STATUS_TRANSITION。
        点击节点查看允许/禁止的操作。
      </p>

      <div class="sm-grid">
        <div class="sm-nodes">
          <div
            v-for="n in nodes"
            :key="n.key"
            class="sm-node"
            :style="{ borderColor: active.key === n.key ? 'var(--c-brand-500)' : '', background: active.key === n.key ? 'var(--c-brand-50)' : '' }"
            tabindex="0"
            @click="pick(n)"
            @keydown.enter="pick(n)"
            role="button"
            :aria-pressed="active.key === n.key"
          >
            <div class="label">{{ n.label }}</div>
            <div class="hint">{{ n.allow.length }} allow · {{ n.forbid.length }} forbid</div>
          </div>
        </div>

        <div class="sm-detail" role="region" aria-live="polite">
          <h5>{{ active.label }} 状态详情</h5>
          <div style="margin-bottom:8px;color:var(--c-ink-3);">{{ active.why }}</div>
          <div class="row" style="margin-bottom:6px;">
            <span class="tag tag-ok">允许</span>
            <span v-for="a in active.allow" :key="a" class="tag">{{ a }}</span>
          </div>
          <div class="row">
            <span class="tag tag-err">禁止</span>
            <span v-for="f in active.forbid" :key="f" class="tag">{{ f }}</span>
          </div>
          <div v-if="active.code" class="muted" style="margin-top:10px;font-size:12px;">
            非法流转错误码：<code>{{ active.code }}</code>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>