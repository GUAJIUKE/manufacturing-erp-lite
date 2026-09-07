// 深交互探测 R3 — 收货表单结构 + 入库单详情冲销按钮（只读不写）
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
async function dump(page, label) {
  const lines = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.el-drawer, .el-dialog, .el-select__popper').forEach(d => {
      const cs = getComputedStyle(d);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const t = (d.textContent || '').replace(/\s+/g, ' ').slice(0, 220);
      out.push(`[PANEL] ${t}`);
    });
    document.querySelectorAll('button, .el-input__inner, .el-select, .el-table__row').forEach(el => {
      const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
      const ph = el.getAttribute('placeholder') || '';
      if (t || ph) out.push(`  [${el.tagName}] "${t}" ph="${ph}"`);
    });
    return out;
  });
  console.log(`\n===== ${label} =====`);
  lines.slice(0, 45).forEach(x => console.log(x));
}

(async () => {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN' });
    const page = await ctx.newPage();

    // A. zhaoliu 收货创建页：展开 PO 下拉看选项（不提交）
    await login(page, 'zhaoliu');
    await page.goto(`${FRONTEND}/purchase-receipts/create`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const poSel = page.locator('.el-select:has-text("PO")').first();
    console.log('PO select count:', await poSel.count());
    if (await poSel.count()) {
      await poSel.click();
      await page.waitForTimeout(800);
      await dump(page, 'A. ReceiptCreate PO 下拉');
      // 点第一条 PO 选项
      const opt = page.locator('.el-select-dropdown__item').first();
      console.log('first option:', await opt.count());
      if (await opt.count()) {
        const optText = (await opt.textContent() || '').trim().slice(0, 60);
        console.log('  option text:', optText);
        await opt.click();
        await page.waitForTimeout(600);
      }
    }
    // 仓库下拉
    const whSel = page.locator('.el-select:has-text("仓库")').first();
    console.log('warehouse select count:', await whSel.count());
    if (await whSel.count()) {
      await whSel.click();
      await page.waitForTimeout(700);
      await dump(page, 'B. 仓库下拉 + 明细区');
      const whOpt = page.locator('.el-select-dropdown__item').first();
      if (await whOpt.count()) {
        console.log('  wh option:', ((await whOpt.textContent()) || '').trim().slice(0, 40));
        await whOpt.click();
        await page.waitForTimeout(800);
        await dump(page, 'C. 选 PO+仓库后明细（数量输入）');
      }
    }
    await page.keyboard.press('Escape').catch(() => {});

    // B. 入库单列表第一条详情 → 冲销按钮
    await page.goto(`${FRONTEND}/purchase-receipts`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const viewBtn = page.locator('tr:has(.el-tag) button:has-text("查看")').first();
    console.log('\nreceipt view btn:', await viewBtn.count());
    if (await viewBtn.count()) {
      await viewBtn.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(700);
      console.log('Receipt detail URL:', page.url());
      await dump(page, 'D. 入库单详情（冲销按钮?）');
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });
