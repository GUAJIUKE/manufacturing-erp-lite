// UI 元素侦察 — 列出关键页面可交互元素（供录屏脚本定位）
import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const FRONTEND = 'http://127.0.0.1:5173';
const PW = { admin: 'admin123', zhangsan: 'demo123', lisi: 'demo123', wangwu: 'demo123', zhaoliu: 'demo123' };

async function login(page, user) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await page.fill('input[placeholder="用户名"]', user);
  await page.fill('input[placeholder="密码"]', PW[user]);
  await page.locator('button.login-btn, button:has-text("登录")').first().click();
  await page.waitForURL((u) => !u.toString().includes('/login'), { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
}

async function probe(page, label, path, user) {
  await page.goto(`${FRONTEND}${path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(800);
  const els = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('button, .el-button, .el-tag, .el-input__inner, .el-select, a[href*="/purchase-"]').forEach(el => {
      const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
      if (t) out.push({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 50), text: t, ph: el.getAttribute('placeholder') || '' });
    });
    return out.slice(0, 45);
  });
  console.log(`\n===== ${label} (${user} @ ${path}) =====`);
  els.forEach((e, i) => console.log(`  [${i}] <${e.tag}> ${e.cls} | "${e.text}" | ph="${e.ph}"`));
}

(async () => {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN' });
    const page = await ctx.newPage();

    // lisi：审批中心（看有无直接审批入口）
    await login(page, 'lisi');
    await probe(page, '审批中心-ApprovalListView', '/approvals', 'lisi');

    // lisi：PR 列表 → PR 详情（PENDING 自己的 PR6 或 zhangsan 的 PR2？lisi 可见部门内）
    await probe(page, 'PR列表-lisi', '/purchase-requisitions', 'lisi');
    // 抓一个 PENDING PR 详情页 id
    const prRows = await page.evaluate(() => {
      const rows = [];
      document.querySelectorAll('table tbody tr, .el-table__row').forEach(tr => {
        const txt = (tr.textContent || '').replace(/\s+/g, ' ').slice(0, 120);
        rows.push(txt);
      });
      return rows.slice(0, 8);
    });
    console.log('\n-- PR 列表行（lisi）--');
    prRows.forEach((r, i) => console.log(`  row[${i}] ${r}`));

    // wangwu：PO 创建页（转 PO 表单）与 PO 详情（确认按钮）
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    await login(page, 'wangwu');
    await probe(page, 'PO创建-PoCreateView', '/purchase-orders/create', 'wangwu');
    await probe(page, 'PO列表', '/purchase-orders', 'wangwu');

    // zhaoliu：收货创建页 + 入库单列表（冲销入口）
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    await login(page, 'zhaoliu');
    await probe(page, '收货创建-ReceiptCreate', '/purchase-receipts/create', 'zhaoliu');
    await probe(page, '入库单列表', '/purchase-receipts', 'zhaoliu');
    await probe(page, '库存余额', '/inventory', 'zhaoliu');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });
