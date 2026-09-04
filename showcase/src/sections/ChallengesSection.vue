<script setup lang="ts">
import { ref } from 'vue';
import { CHALLENGES, SNIPPETS } from '../data/business';

// Engineering Challenges — 5 个真实工程挑战 + 3 个真实代码片段

const opened = ref<number>(-1);
function toggle(i: number) { opened.value = opened.value === i ? -1 : i; }

function hl(line: string): string {
  // 极简语法高亮（注释/字符串/关键字/函数名）
  return line
    .replace(/(#[^\n]*)$/gm, '<span class="c">$1</span>')
    .replace(/(&quot;[^&]*?&quot;)/g, '<span class="s">$1</span>')
    .replace(/\b(import|from|class|def|return|if|elif|else|raise|for|in|self|None|True|False|async|await|with|as|where|values|update|select|insert)\b/g, '<span class="k">$1</span>')
    .replace(/\b(rowcount|sorted|min|max|sum|tuple_)\b/g, '<span class="f">$1</span>');
}
</script>

<template>
  <section id="challenges" class="section">
    <div class="container">
      <span class="section-eyebrow">工程挑战</span>
      <h2 class="section-title">5 个真实并发 / 一致性问题</h2>
      <p class="section-subtitle">
        只展示 5 个（不列 30 个）。每个问题—解决方案—为什么—代码在哪。
      </p>

      <div class="grid grid-3 reveal">
        <article
          v-for="c in CHALLENGES"
          :key="c.n"
          class="ch-card"
          :style="{ cursor: 'pointer', borderColor: opened === c.n - 1 ? 'var(--c-brand-500)' : '' }"
          @click="toggle(c.n - 1)"
        >
          <div class="num">{{ c.n }}</div>
          <h4>{{ c.title }}</h4>
          <div class="row"><b>Problem</b><span>{{ c.problem }}</span></div>
          <div class="row"><b>Solution</b><span>{{ c.solution }}</span></div>
          <div class="row"><b>Why</b><span>{{ c.why }}</span></div>
          <div class="row"><b>Where</b><span style="font-family:var(--font-mono);font-size:12px;color:var(--c-ink-5);">{{ c.where }}</span></div>
          <div class="muted" style="font-size:12px;margin-top:6px;">{{ opened === c.n - 1 ? '▲ 点击收起' : '▼ 点击展开代码' }}</div>
        </article>
      </div>

      <!-- 3 个真实代码片段 -->
      <div class="grid grid-3" style="margin-top:32px;">
        <div v-for="s in SNIPPETS" :key="s.title" class="card" style="grid-column: span 3; padding: 0; overflow:hidden;">
          <div style="padding:12px 16px;border-bottom:1px solid var(--c-line);background:var(--c-surface-2);">
            <div style="font-weight:700;font-size:14px;color:var(--c-ink-1);">{{ s.title }}</div>
            <div class="muted" style="font-size:12px;margin-top:2px;font-family:var(--font-mono);">{{ s.file }}</div>
          </div>
          <pre class="code" style="margin:0;border-radius:0;border:0;"><code v-html="hl(s.code)"></code></pre>
        </div>
      </div>
    </div>
  </section>
</template>