<script setup lang="ts">
import { ref, computed } from 'vue';
import { ROLES, type Role } from '../data/business';

// RBAC — 5 角色切换。明确：这是权限模型展示；真实强制由后端执行。

const activeKey = ref<Role['key']>('applicant');
const active = computed<Role>(() => ROLES.find((r) => r.key === activeKey.value)!);

function selectRole(k: Role['key']) { activeKey.value = k; }

function statusOf(m: { read: boolean; write: boolean; approve?: boolean }, key: Role['key']) {
  if (key === 'admin') return 'yes';
  return m.read || m.write || m.approve ? 'yes' : 'no';
}
</script>

<template>
  <section id="rbac" class="section">
    <div class="container">
      <span class="section-eyebrow">权限模型</span>
      <h2 class="section-title">三层权限模型（路由 + 对象级 + 单据状态）</h2>
      <p class="section-subtitle">
        路由层 <code>require_perm</code> + Service 层对象级（部门主管关系/申请人/BUYER 范围） + 单据状态机 <code>_TRANSITIONS</code>，
        三层 AND 关系。下方只是<strong>展示</strong>，真实权限仍由 FastAPI 后端强制执行。
      </p>

      <div class="rbac-tabs" role="tablist">
        <button
          v-for="r in ROLES"
          :key="r.key"
          role="tab"
          :aria-selected="activeKey === r.key"
          @click="selectRole(r.key)"
        >
          {{ r.label }} · {{ r.who }}
        </button>
      </div>

      <div class="rbac-panel">
        <div class="rbac-matrix" role="tabpanel">
          <table>
            <thead>
              <tr>
                <th>模块</th>
                <th style="text-align:center;width:80px;">读</th>
                <th style="text-align:center;width:80px;">写</th>
                <th style="text-align:center;width:80px;">审批</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in active.matrix" :key="m.module">
                <td>{{ m.module }}</td>
                <td style="text-align:center;">
                  <span :class="m.read ? 'yes' : 'no'">{{ m.read ? '✓' : '×' }}</span>
                </td>
                <td style="text-align:center;">
                  <span :class="m.write ? 'yes' : 'no'">{{ m.write ? '✓' : '×' }}</span>
                </td>
                <td style="text-align:center;">
                  <span v-if="m.approve !== undefined" :class="m.approve ? 'yes' : 'no'">{{ m.approve ? '✓' : '×' }}</span>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="rbac-side">
          <h4>{{ active.label }} · {{ active.who }}</h4>
          <div class="who">{{ active.focus }}</div>
          <ul>
            <li><strong>路由层</strong>：<code>require_perm</code> 控制可见模块；失败 → 2005 PERMISSION_DENIED。</li>
            <li><strong>对象层</strong>：跨部门 PR 申请批 → 4011 PR_NOT_APPROVER；BUYER 仅可见 status≥DRAFT。</li>
            <li><strong>状态层</strong>：所有写操作经 <code>_TRANSITIONS</code> 白名单，非法 → 4002。</li>
            <li><strong>真实执行</strong>：本模型仅展示决策；后端 <code>visible_*_stmt</code> 子查询保证隔离。</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>