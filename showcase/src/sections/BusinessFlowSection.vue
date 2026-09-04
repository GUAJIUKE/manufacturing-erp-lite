<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';
import { FLOW } from '../data/business';

// Business Flow — 6 节点横向 stepper，进入视口激活。
const stepRefs = ref<HTMLElement[]>([]);
let io: IntersectionObserver | null = null;

function setRef(el: Element | any) {
  if (el && !stepRefs.value.includes(el as HTMLElement)) {
    stepRefs.value.push(el as HTMLElement);
  }
}

onMounted(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    stepRefs.value.forEach((el) => el.classList.add('is-active'));
    return;
  }
  io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add('is-active');
          io!.unobserve(e.target);
        }
      }
    },
    { threshold: 0.45 },
  );
  stepRefs.value.forEach((el) => io!.observe(el));
});
onBeforeUnmount(() => io?.disconnect());
</script>

<template>
  <section id="flow" class="section">
    <div class="container">
      <span class="section-eyebrow">业务闭环</span>
      <h2 class="section-title">一条完整的采购到库存链</h2>
      <p class="section-subtitle">
        滚动到每一节点，元素依次高亮激活。流程描述与 ERP 状态机严格一致（_TRANSITIONS 白名单）。
      </p>
      <div class="flow-stepper">
        <div
          v-for="(n, i) in FLOW"
          :key="n.key"
          :ref="setRef"
          class="flow-step"
        >
          <span class="num">{{ i + 1 }}</span>
          <h4>{{ n.title }}</h4>
          <div class="role">{{ n.role }}</div>
          <div class="muted" style="margin-top:8px;font-size:13px;">{{ n.detail }}</div>
          <span v-if="i < FLOW.length - 1" class="arrow" aria-hidden="true"></span>
        </div>
      </div>
    </div>
  </section>
</template>