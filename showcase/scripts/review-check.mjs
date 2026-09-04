// Portfolio Review 自查：渲染质量 + console 错误 + 各 section 截图
import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';

const exe = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const b = await chromium.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });

const errors = [];
const consoleMsgs = [];
p.on('console', m => { if (m.type() === 'error') consoleMsgs.push(m.text()); });
p.on('pageerror', e => errors.push(String(e)));

await p.goto('http://127.0.0.1:5174/', { waitUntil: 'networkidle' });
console.log('TITLE:', await p.title());

// 收集所有 section 标题与其 bounding box
const sections = await p.evaluate(() => {
  return [...document.querySelectorAll('section, [data-section], main > *')]
    .map((el, i) => {
      const r = el.getBoundingClientRect();
      const id = el.id || el.className?.toString().slice(0, 60) || el.tagName;
      return { i, id, y: Math.round(r.top + window.scrollY), h: Math.round(r.height), w: Math.round(r.width) };
    })
    .filter(s => s.h > 100 && s.w > 400);
});
console.log('SECTION COUNT:', sections.length);
sections.forEach(s => console.log(`  [${s.i}] ${s.id}  y=${s.y} h=${s.h}`));

// 依次滚动每个 section 截图
const dir = 'C:/Users/Administrator/Desktop/8.26/docs/screenshots/showcase-review';
import { mkdirSync } from 'node:fs';
mkdirSync(dir, { recursive: true });
for (const s of sections) {
  await p.evaluate(y => window.scrollTo({ top: y - 20, behavior: 'instant' }), s.y);
  await p.waitForTimeout(350);
  await p.screenshot({ path: `${dir}/sec-${String(s.i).padStart(2, '0')}-${s.id.replace(/[^\w\u4e00-\u9fa5-]/g, '').slice(0, 30)}.png` });
}

// 底部滚动以触发全部 reveal
await p.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' }));
await p.waitForTimeout(800);
const totalH = await p.evaluate(() => document.body.scrollHeight);
console.log('PAGE HEIGHT:', totalH);

// 移动端冒烟（375 宽，可读性）
const p2 = await b.newPage({ viewport: { width: 375, height: 812 } });
await p2.goto('http://127.0.0.1:5174/', { waitUntil: 'networkidle' });
const overflow = await p2.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
console.log('MOBILE 375px horizontal-overflow:', overflow);
await p2.screenshot({ path: `${dir}/mobile-top.png` });
await p2.close();

// reduced-motion 冒烟
const p3 = await b.newPage({ viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce' });
await p3.goto('http://127.0.0.1:5174/', { waitUntil: 'networkidle' });
await p3.evaluate(() => window.scrollTo({ top: 3000, behavior: 'instant' }));
await p3.waitForTimeout(400);
const rmOk = await p3.evaluate(() => {
  const revealed = document.querySelectorAll('.is-in, .reveal, [class*="active"]');
  return revealed.length;
});
console.log('REDUCED-MOTION elements visible count:', rmOk);
await p3.close();

console.log('PAGE ERRORS:', errors.length ? errors : 'none');
console.log('CONSOLE ERRORS:', consoleMsgs.length ? consoleMsgs.slice(0, 10) : 'none');
await b.close();
console.log('DONE');
