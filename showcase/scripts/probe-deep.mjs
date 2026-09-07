// 深交互探测 — 审批弹窗 / PR 转 PO 入口 / PO 确认 / 收货表单 / 冲销
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
async function switchUser(page, user) {
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await login(page, user);
}
async function dump(page, label) {
  const lines = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.el-dialog, .el-message-box, .el-drawer, .el-popper').forEach(d => {
      const cs = getComputedStyle(d);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const t = (d.textContent || '').replace(/\s+/g, ' ').slice(0, 200);
      out.push(`[DIALOG:${d.className.split(' ')[0]}] ${t}`);
    });
    document.querySelectorAll('button, .el-button, .el-input__inner, .el-textarea__inner').forEach(el => {
      const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50);
      const ph = el.getAttribute('placeholder') || '';
      if (t || ph) out.push(`  [${el.tagName}] "${t}" ph="${ph}" cls=${(el.className||'').toString().slice(0,45)}`);
    });
    return out;
  });
  console.log(`\n===== ${label} =====`);
  lines.slice(0, 60).forEach(x => console.log(x));
}

(async () => {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN' });
    const page = await ctx.newPage();

    // A. lisi 审批中心：点"审批"看弹窗
    await login(page, 'lisi');
    await page.goto(`${FRONTEND}/approvals`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const approveBtns = page.locator('button:has-text("审批")');
    console.log('approve buttons:', await approveBtns.count());
    if (await approveBtns.count() > 0) {
      await approveBtns.first().click();
      await page.waitForTimeout(700);
      await dump(page, 'A. lisi 点[审批]后弹窗');
      const okBtn = page.locator('.el-dialog button:has-text("通过"), .el-dialog button:has-text("同意"), .el-dialog button:has-text("确定"), .el-message-box button:has-text("确定"), .el-dialog button:has-text("批准")').first();
      console.log('dialog ok btn count:', await okBtn.count());
      if (await okBtn.count()) {
        await okBtn.click(); await page.waitForTimeout(800);
        await dump(page, 'A2. 点击通过后');
      }
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(400);
    }

    // B. wangwu：PR 列表 APPROVED → 详情 → 转 PO
    await switchUser(page, 'wangwu');
    await page.goto(`${FRONTEND}/purchase-requisitions`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const approvedView = page.locator('tr:has(.el-tag--success) button:has-text("查看")').first();
    console.log('\napproved PR 查看按钮:', await approvedView.count());
    if (await approvedView.count()) {
      await approvedView.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(700);
      console.log('PR 详情 URL:', page.url());
      await dump(page, 'B. wangwu PR详情(已批准)');
      const convBtn = page.locator('button:has-text("转为采购订单")').first();
      console.log('convert btn count:', await convBtn.count());
      if (await convBtn.count()) {
        await convBtn.click();
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(800);
        console.log('URL after convert:', page.url());
        await dump(page, 'C. 转PO页面(应带明细)');
      }
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });
