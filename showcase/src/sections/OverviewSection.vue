<script setup lang="ts">
// Project Overview — 30 秒招聘者速览：是什么/解决什么/技术栈/业务闭环/亮点/如何运行
const facts = [
    { k: '是什么',  v: '面向制造企业的采购-库存协同 ERP Demo（Portfolio）' },
    { k: '解决什么', v: '采购→审批→PO→分批收货→库存账→管理驾驶舱 的完整业务闭环' },
    { k: '技术栈', v: 'Vue 3 + Vite + Element Plus / SQLAlchemy + PyMySQL / MySQL 8 / Alembic' },
    { k: '亮点',   v: '状态机 + 乐观锁 + CAS 防超转/超收 + append-only ledger + 移动加权平均' },
    { k: '如何运行', v: 'docker compose up -d --build → http://localhost:8080' },
];
</script>

<template>
  <section id="overview" class="section">
    <div class="container">
      <span class="section-eyebrow">30 秒</span>
      <h2 class="section-title">项目速览</h2>
      <p class="section-subtitle">招聘者视角：5 行读懂项目定位、价值、技术栈与运行方式。</p>
      <div class="card reveal">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tbody>
            <tr v-for="r in facts" :key="r.k" style="border-top:1px solid var(--c-line);">
              <th style="width:120px;text-align:left;padding:10px 12px;color:var(--c-ink-5);font-weight:600;background:var(--c-surface-2);">
                {{ r.k }}
              </th>
              <td style="padding:10px 12px;color:var(--c-ink-2);">{{ r.v }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>