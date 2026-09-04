// 页面级横向溢出检测（scrollWidth 权威判据）
import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';

const exe = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const b = await chromium.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] });
for (const w of [1920, 1440, 1366, 900, 600, 375]) {
  const p = await b.newPage({ viewport: { width: w, height: 900 } });
  await p.goto('http://127.0.0.1:5174/', { waitUntil: 'networkidle' });
  const r = await p.evaluate(() => {
    const de = document.documentElement;
    const sw = de.scrollWidth, cw = de.clientWidth;
    if (sw > cw + 1) {
      // 找最宽的越界元素
      let worst = null;
      document.querySelectorAll('body *').forEach(el => {
        const b = el.getBoundingClientRect();
        if (b.right > cw + 1 && (!worst || b.right > worst.right)) {
          worst = { tag: el.tagName, cls: (el.className||'').toString().slice(0,50), right: Math.round(b.right), w: Math.round(b.width) };
        }
      });
      return { overflow: true, sw, cw, worst };
    }
    return { overflow: false, sw, cw };
  });
  console.log(`${w}px →`, JSON.stringify(r));
  await p.close();
}
await b.close();
