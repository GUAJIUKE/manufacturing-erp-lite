// recordVideo 可用性 + 体积测试：录 6s 登录页
import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';
import { mkdirSync, readdirSync, statSync } from 'node:fs';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const OUT = 'C:/Users/Administrator/Desktop/8.26/docs/videos';
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  locale: 'zh-CN',
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const page = await ctx.newPage();
await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);
await page.fill('input[placeholder="用户名"]', 'admin');
await page.waitForTimeout(1500);
await page.fill('input[placeholder="密码"]', 'admin123');
await page.waitForTimeout(1500);
await ctx.close();
await browser.close();

const files = readdirSync(OUT).filter(f => f.endsWith('.webm'));
console.log('video files:', files);
for (const f of files) {
  const p = `${OUT}/${f}`;
  const mb = (statSync(p).size / 1024 / 1024).toFixed(2);
  console.log(`  ${f}  ${mb} MB`);
}
