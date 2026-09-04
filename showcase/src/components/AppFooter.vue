<script setup lang="ts">
const year = new Date().getFullYear();
</script>

<template>
  <footer class="app-footer">
    <div class="container" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
      <div>
        © {{ year }} Manufacturing ERP Lite · Portfolio Showcase ·
        <span class="muted">独立 Vue 3 + TS + Vite 静态站，零后端依赖</span>
      </div>
      <div class="muted">设计：Clean / Technical / Manufacturing / Data-driven</div>
    </div>
  </footer>
</template>