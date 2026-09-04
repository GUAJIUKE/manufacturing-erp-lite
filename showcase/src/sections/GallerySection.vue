<script setup lang="ts">
// Gallery — 10 张真实 ERP 截图墙。明确标注「真实 ERP 截图」，与概念动画区分。

const items = [
  { file: '01-login',                 title: '登录',                  src: 'admin · /login' },
  { file: '02-dashboard',             title: '管理驾驶舱',            src: 'admin · /dashboard' },
  { file: '03-pr-list',               title: 'PR 列表',               src: 'admin · /purchase-requisitions' },
  { file: '04-pr-detail',             title: 'PR 详情（APPROVED）',    src: 'admin · /purchase-requisitions/57' },
  { file: '05-approval',              title: '审批中心',              src: 'lisi · /approvals' },
  { file: '06-po-detail',             title: 'PO 详情（部分收货）',    src: 'admin · /purchase-orders/30' },
  { file: '07-receipt',               title: '入库单',                src: 'zhaoliu · /purchase-receipts' },
  { file: '08-inventory-balance',     title: '库存余额',              src: 'zhaoliu · /inventory' },
  { file: '09-inventory-transactions',title: '库存流水',              src: 'zhaoliu · /inventory/transactions' },
  { file: '10-rbac',                  title: '用户与角色',            src: 'admin · /users' },
];
</script>

<template>
  <section id="gallery" class="section">
    <div class="container">
      <span class="section-eyebrow">系统截图</span>
      <h2 class="section-title">真实 ERP 截图（10 张）</h2>
      <p class="section-subtitle">
        全部基于 seed_demo 数据集、5 角色账号（admin / zhangsan / lisi / wangwu / zhaoliu），1920×1080 真实浏览器渲染。
        与上方 Quantity Chain / Ledger 动画严格区分：动画是「基于真实业务规则的交互示意」。
      </p>

      <div class="gallery">
        <a
          v-for="it in items"
          :key="it.file"
          class="frame"
          :href="`./screenshots/${it.file}.png`"
          target="_blank"
          rel="noopener"
        >
          <img :src="`./screenshots/${it.file}.png`" :alt="`真实截图 · ${it.title}`" loading="lazy" />
          <div class="cap">
            <span><span class="tag tag-info" style="margin-right:6px;">真实截图</span>{{ it.title }}</span>
            <span class="src">{{ it.src }}</span>
          </div>
        </a>
      </div>
    </div>
  </section>
</template>