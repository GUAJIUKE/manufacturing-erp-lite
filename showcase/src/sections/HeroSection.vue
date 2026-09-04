<script setup lang="ts">
// Hero — 第一屏：标题 / 副标题 / 一句话 / 技术栈 chip / CTA
// 视觉原则：专业制造业，蓝色稳重，无粒子/3D/AI 紫渐变。
</script>

<template>
  <section class="hero">
    <div class="container">
      <span class="section-eyebrow">ERP Lite · Portfolio</span>
      <h1>Manufacturing ERP Lite</h1>
      <p class="lead">
        制造企业采购与库存协同 ERP Demo<br />
        围绕采购申请、审批、采购订单、收货、库存与管理驾驶舱构建的全栈 ERP Portfolio Project。
      </p>
      <div class="stack">
        <span class="chip">Vue 3</span>
        <span class="chip">FastAPI</span>
        <span class="chip">MySQL 8</span>
        <span class="chip">RBAC</span>
        <span class="chip">State Machine</span>
        <span class="chip">Optimistic Locking</span>
        <span class="chip">Inventory Ledger</span>
      </div>
      <div class="cta">
        <a class="btn btn-primary" href="#flow">查看业务流程</a>
        <a class="btn btn-ghost"   href="#gallery">查看系统截图</a>
        <a class="btn btn-ghost"   href="#arch">查看技术设计</a>
        <a class="btn btn-ghost"   href="https://github.com/GUAJIUKE/erp-lite" target="_blank" rel="noopener">GitHub ↗</a>
      </div>
    </div>
  </section>
</template>