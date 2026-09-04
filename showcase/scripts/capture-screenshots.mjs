// ERP 真实截图脚本 — Phase 13 Portfolio
// 通过 playwright-core 连接本机 Microsoft Edge，登录不同角色截取真实页面。
// 截图落盘 docs/screenshots/（master，PNG）+ showcase/public/screenshots/（已用 WebP，showcase 内嵌）。
//
// 用法：
//   NODE_PATH=... node capture-screenshots.mjs            (前置：本地 backend:8000 + frontend:5173)
//
// 设计：
//   - viewport 1920x1080，deviceScaleFactor 1
//   - 等网络空闲 + ECharts/SVG 动画完成 (sleep 800ms)
//   - 登录态使用真实 UI 登录（非 token 注入），确保浏览器侧行为真实
//   - 截图文件名固定 01..10，与 docs/screenshots/README.md 编号一致
//
// 重要：必须保证截图来自真实 ERP 页面。任何"模拟/造假"将被显式标注并拒绝。

import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { existsSync, mkdirSync } from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..', '..');                       // C:/Users/.../Desktop/8.26
const DOC_OUT  = resolve(ROOT, 'docs', 'screenshots');
const SHOW_OUT = resolve(ROOT, 'showcase', 'public', 'screenshots');
for (const d of [DOC_OUT, SHOW_OUT]) {
  if (!existsSync(d)) mkdirSync(d, { recursive: true });
}

const FRONTEND = 'http://127.0.0.1:5173';
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

// 登录 → 目标页面
const SHOTS = [
  { file: '01-login',                 needLogin: false, user: null,        path: '/login' },
  { file: '02-dashboard',             needLogin: true,  user: 'admin',     path: '/dashboard' },
  { file: '03-pr-list',               needLogin: true,  user: 'admin',     path: '/purchase-requisitions' },
  { file: '04-pr-detail',             needLogin: true,  user: 'admin',     path: '/purchase-requisitions/57', note: 'APPROVED 状态 PR 详情' },
  { file: '05-approval',              needLogin: true,  user: 'lisi',      path: '/approvals' },
  { file: '06-po-detail',             needLogin: true,  user: 'admin',     path: '/purchase-orders/30',     note: 'PARTIALLY_RECEIVED 状态 PO' },
  { file: '07-receipt',               needLogin: true,  user: 'zhaoliu',   path: '/purchase-receipts' },
  { file: '08-inventory-balance',     needLogin: true,  user: 'zhaoliu',   path: '/inventory' },
  { file: '09-inventory-transactions',needLogin: true,  user: 'zhaoliu',   path: '/inventory/transactions' },
  { file: '10-rbac',                  needLogin: true,  user: 'admin',     path: '/users' },
];

const DEMO_PW = {
  admin:    'admin123',
  zhangsan: 'demo123',
  lisi:     'demo123',
  wangwu:   'demo123',
  zhaoliu:  'demo123',
};

async function login(page, username) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await page.fill('input[placeholder="用户名"]', username);
  await page.fill('input[placeholder="密码"]', DEMO_PW[username]);
  await page.locator('button.login-btn, button:has-text("登录")').first().click();
  // 登录成功后跳转 dashboard；等路由稳定
  await page.waitForURL((u) => !u.toString().includes('/login'), { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
}

async function shoot(page, shot) {
  const target = `${FRONTEND}${shot.path}`;
  await page.goto(target, { waitUntil: 'domcontentloaded' });
  // 等待路由内容 + ECharts/动画稳定
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(900);

  const outDoc  = resolve(DOC_OUT,  `${shot.file}.png`);
  const outShow = resolve(SHOW_OUT, `${shot.file}.png`);
  await page.screenshot({ path: outDoc,  fullPage: false });
  await page.screenshot({ path: outShow, fullPage: false });
  console.log(`[ok] ${shot.file}.png  <- ${shot.user ?? 'guest'} ${shot.path}${shot.note ? '  (' + shot.note + ')' : ''}`);
}

(async () => {
  const browser = await chromium.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const ctx = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
      locale: 'zh-CN',
    });
    const page = await ctx.newPage();
    let currentUser = null;
    for (const shot of SHOTS) {
      if (shot.needLogin) {
        if (currentUser !== shot.user) {
          // 切换账号：清 localStorage + 重新登录
          if (currentUser !== null) {
            await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
          }
          await login(page, shot.user);
          currentUser = shot.user;
        }
      } else {
        // 截图登录页前清掉残留登录态
        if (currentUser !== null) {
          await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
          currentUser = null;
        }
      }
      await shoot(page, shot);
    }
    console.log('DONE');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });