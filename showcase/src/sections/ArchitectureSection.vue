<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';

// Architecture — 7 层架构。滚动到该节时，层从顶部向下逐层激活。

const tiers = [
  { name: 'Browser',   desc: '用户交互 / 路由' },
  { name: 'Vue 3',     desc: 'SPA / Element Plus' },
  { name: 'REST',      desc: '/api/v1 · JWT' },
  { name: 'FastAPI',   desc: 'API · validation' },
  { name: 'Service',   desc: '业务规则 · 事务边界 · 状态机' },
  { name: 'SQLAlchemy',desc: 'ORM · 仓储模式' },
  { name: 'MySQL 8',   desc: '约束 · 触发器 · 持久化' },
];

const tierRefs = ref<HTMLElement[]>([]);
let io: IntersectionObserver | null = null;

function setRef(el: Element | any) {
  if (el && !tierRefs.value.includes(el as HTMLElement)) {
    tierRefs.value.push(el as HTMLElement);
  }
}

onMounted(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    tierRefs.value.forEach((el) => el.classList.add('is-in'));
    return;
  }
  io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add('is-in');
          io!.unobserve(e.target);
        }
      }
    },
    { threshold: 0.3 },
  );
  tierRefs.value.forEach((el) => io!.observe(el));
});
onBeforeUnmount(() => io?.disconnect());
</script>

<template>
  <section id="arch" class="section">
    <div class="container">
      <span class="section-eyebrow">技术架构</span>
      <h2 class="section-title">分层 + Service 是事务边界</h2>
      <p class="section-subtitle">
        业务规则放 Service 层（而非 API）的原因：可测性、事务边界、跨接口复用、状态机单点收口、审计编号一致性、信任边界。
        滚动到本节时层从顶部向下依次高亮。
      </p>

      <div class="arch">
        <div v-for="t in tiers" :key="t.name" :ref="setRef" class="arch-tier">
          <div class="tname">{{ t.name }}</div>
          <div class="tdesc">{{ t.desc }}</div>
        </div>
      </div>

      <div class="grid grid-3" style="margin-top:32px;">
        <div class="card">
          <h4 style="margin:0 0 8px;font-size:14px;">API Layer</h4>
          <p class="muted" style="font-size:13px;line-height:1.7;">HTTP 入参校验、Pydantic schema、异常处理；不写业务规则。</p>
        </div>
        <div class="card">
          <h4 style="margin:0 0 8px;font-size:14px;">Service Layer</h4>
          <p class="muted" style="font-size:13px;line-height:1.7;">事务边界 + 状态机 + 乐观锁 + CAS + 审计；唯一允许直接 UPDATE 业务字段的层。</p>
        </div>
        <div class="card">
          <h4 style="margin:0 0 8px;font-size:14px;">Database</h4>
          <p class="muted" style="font-size:13px;line-height:1.7;">约束 / 触发器 / 唯一索引；append-only 流水由 MySQL 触发器强制。</p>
        </div>
      </div>
    </div>
  </section>
</template>