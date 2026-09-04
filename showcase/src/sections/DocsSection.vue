<script setup lang="ts">
// Docs / GitHub — 文档入口与仓库
</script>

<template>
  <section id="docs" class="section">
    <div class="container">
      <span class="section-eyebrow">文档与仓库</span>
      <h2 class="section-title">从代码到访谈：完整知识资产</h2>
      <p class="section-subtitle">
        11 份 docs/ 文档 + Phase 12/13 的 portfolio 资料，按主题组织；与代码引用严格一致。
      </p>

      <div class="grid grid-3">
        <a class="card" href="./README.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">README.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            招聘者首页 · 业务闭环 · 5 角色演示 · 30 秒速览 · Showcase 入口。
          </p>
        </a>
        <a class="card" href="./docs/architecture.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/architecture.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            分层 · 为什么业务规则在 Service · 请求生命周期 · 演进边界。
          </p>
        </a>
        <a class="card" href="./docs/business_flow.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/business_flow.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            PR/PO/Receipt 状态机 · _TRANSITIONS · 状态为什么存在 · 推导优于记忆。
          </p>
        </a>
        <a class="card" href="./docs/concurrency.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/concurrency.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            乐观锁 + CAS + 行锁 + 统一锁序 + 冲销保护。错误码 4011/4012/6002/6009。
          </p>
        </a>
        <a class="card" href="./docs/transaction.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/transaction.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            7 类写入同 session 提交 · 第二行超收回滚 · 事务 vs 乐观锁。
          </p>
        </a>
        <a class="card" href="./docs/rbac.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/rbac.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            路由 + 对象级 + 状态机三层 · 反例「有 pr:approve ≠ 能批任意部门 PR」。
          </p>
        </a>
        <a class="card" href="./docs/inventory_design.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/inventory_design.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            ledger vs snapshot · 加权平均 10×10+10×20=300 · 冲销按原始金额。
          </p>
        </a>
        <a class="card" href="./docs/quantity_chain.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/quantity_chain.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            requested → converted → ordered → received → Balance 七字段链。
          </p>
        </a>
        <a class="card" href="./docs/interview_qa.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/interview_qa.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            22 个真实面试追问 · 答案锚定真实函数名与错误码。
          </p>
        </a>
        <a class="card" href="./docs/resume_project.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/resume_project.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            简历 bullet / 平台版 / 一分钟口述稿 · 措辞红线表。
          </p>
        </a>
        <a class="card" href="./docs/demo_script.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/demo_script.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            5–7 分钟面试演示脚本 · 10 步 · 操作/展示/讲什么。
          </p>
        </a>
        <a class="card" href="./docs/deployment.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/deployment.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            docker compose 部署 · 静态验证通过 · runtime 受 wsl.exe 黑名单阻塞（环境）。
          </p>
        </a>
        <a class="card" href="./docs/roadmap.md" target="_blank" rel="noopener">
          <h4 style="margin:0 0 6px;font-size:14px;">docs/roadmap.md</h4>
          <p class="muted" style="font-size:13px;line-height:1.6;margin:0;">
            14 个 Phase 门禁记录 · Phase 13 暂停/阻塞原因 · 复盘脉络。
          </p>
        </a>
      </div>

      <div class="card" style="margin-top:24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
        <div>
          <strong>仓库</strong>
          <a href="https://github.com/GUAJIUKE/erp-lite" target="_blank" rel="noopener" style="margin-left:6px;">github.com/GUAJIUKE/erp-lite ↗</a>
        </div>
        <div class="muted" style="font-size:13px;">
          License · MIT（仅源码；截图为真实 ERP 渲染，仅作 Portfolio 用途）
        </div>
      </div>
    </div>
  </section>
</template>