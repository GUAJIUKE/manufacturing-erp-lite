<script setup lang="ts">
import { TEST_EVIDENCE } from '../data/business';
</script>

<template>
  <section id="testing" class="section">
    <div class="container">
      <span class="section-eyebrow">测试</span>
      <h2 class="section-title">验证证据（Phase 12 checkpoint）</h2>
      <p class="section-subtitle">
        所有数字均来自 Phase 12 验收（2026-09-04）。后续 Phase 13 不重写业务代码，因此数字继续有效。
      </p>

      <div class="grid grid-4 reveal" style="margin-bottom:24px;">
        <div v-for="t in TEST_EVIDENCE" :key="t.name" class="card">
          <div class="muted" style="font-size:12px;">{{ t.name }}</div>
          <div style="font-size:28px;font-weight:700;color:var(--c-ink-1);margin-top:6px;">{{ t.value }}</div>
          <div class="muted" style="font-size:12px;margin-top:6px;">{{ t.note }}</div>
        </div>
      </div>

      <div class="card" style="background:var(--c-surface-2);">
        <h4 style="margin:0 0 8px;font-size:14px;">验收命令</h4>
        <ul style="margin:0;padding-left:18px;font-size:13px;color:var(--c-ink-3);font-family:var(--font-mono);line-height:1.9;">
          <li>cd backend &amp;&amp; pytest                         <span style="color:var(--c-ink-5);"># 229 passed · 3m06s</span></li>
          <li>cd frontend &amp;&amp; npm run typecheck              <span style="color:var(--c-ink-5);"># vue-tsc -b --noEmit ✓</span></li>
          <li>cd frontend &amp;&amp; npm run build                  <span style="color:var(--c-ink-5);"># vite build ✓</span></li>
          <li>cd frontend &amp;&amp; npm test                       <span style="color:var(--c-ink-5);"># vitest 47 passed</span></li>
          <li>cd backend &amp;&amp; alembic check                   <span style="color:var(--c-ink-5);"># No new upgrade operations detected</span></li>
          <li>docker compose config                              <span style="color:var(--c-ink-5);"># STATIC VALIDATION PASSED</span></li>
          <li>docker compose up -d --build                       <span style="color:var(--c-warn-2);"># RUNTIME BLOCKED BY ENVIRONMENT</span></li>
        </ul>
      </div>
    </div>
  </section>
</template>