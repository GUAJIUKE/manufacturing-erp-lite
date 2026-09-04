<script setup lang="ts">
import { KPIS } from '../data/business';

// Dashboard Preview — 真实 02-dashboard.png + KPI hover 显示口径
const imageSrc = './screenshots/02-dashboard.png';
</script>

<template>
  <section id="dashboard" class="section">
    <div class="container">
      <span class="section-eyebrow">管理驾驶舱</span>
      <h2 class="section-title">Dashboard Preview · 真实 ERP 截图</h2>
      <p class="section-subtitle">
        截图来自真实 admin 视角（seed_demo 数据；2026-09-04 13:38 拍摄）。下方是 6 个 KPI 的口径解释（桌面端 hover / 键盘 focus 查看；完整口径见 <a href="https://github.com/GUAJIUKE/erp-lite/blob/main/docs/dashboard_metrics.md" target="_blank" rel="noopener">dashboard_metrics.md</a>）：
      </p>

      <!-- KPI grid -->
      <div class="kpi-grid reveal" style="margin-bottom:24px;">
        <div
          v-for="kpi in KPIS"
          :key="kpi.label"
          class="kpi-card"
          tabindex="0"
        >
          <div class="label">{{ kpi.label }}</div>
          <div class="value">{{ kpi.value }}</div>
          <div class="tip" role="tooltip">{{ kpi.tip }}</div>
        </div>
      </div>

      <!-- 真实截图 -->
      <div class="dash-preview">
        <div class="dash-caption">
          <span class="tag tag-info">真实 ERP 截图</span>
          <span class="muted">admin · /dashboard · 1920×1080</span>
        </div>
        <div class="frame">
          <img :src="imageSrc" alt="Manufacturing ERP Lite — admin dashboard 真实截图" loading="lazy" />
        </div>
      </div>
    </div>
  </section>
</template>