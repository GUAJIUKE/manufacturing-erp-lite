// 深交互探测 R2 — 通过审批 / PoCreate 表单 / PO 确认 / 收货表单 / 冲销按钮
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
    document.querySelectorAll('.el-drawer, .el-dialog, .el-message-box, .el-select__popper, .el-dropdown-menu').forEach(d => {
      const cs = getComputedStyle(d);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const t = (d.textContent || '').replace(/\s+/g, ' ').slice(0, 260);
      out.push(`[PANEL:${d.className.split(' ')[0]}] ${t}`);
    });
    document.querySelectorAll('button, .el-input__inner, .el-textarea__inner, .el-table__row').forEach(el => {
      const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
      const ph = el.getAttribute('placeholder') || '';
      if (t || ph) out.push(`  [${el.tagName}] "${t}" ph="${ph}"`);
    });
    return out;
  });
  console.log(`\n===== ${label} =====`);
  lines.slice(0, 50).forEach(x => console.log(x));
}

(async () => {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN' });
    const page = await ctx.newPage();

    // A. lisi 审批中心：点"审批" → 抽屉 → 点"通过"（选 PR-0002 zhangsan 的？第一条是 0003 lisi 自己的）
    // 第 2 条审批按钮对应另一行（0002 zhangsan STM32 20 或 0003）。取第二条试试
    await login(page, 'lisi');
    await page.goto(`${FRONTEND}/approvals`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const btns = page.locator('button:has-text("审批")');
    // 先点第二条看是哪条 PR
    await btns.nth(1).click();
    await page.waitForTimeout(700);
    await dump(page, 'A. 第2条审批抽屉');
    // 点"通过"
    const pass = page.locator('.el-drawer button:has-text("通过")').first();
    console.log('pass btn:', await pass.count());
    if (await pass.count()) { await pass.click(); await page.waitForTimeout(1000); }
    await dump(page, 'A2. 点击通过后');
    // 关闭抽屉若残留
    await page.keyboard.press('Escape').catch(()=>{}); await page.waitForTimeout(300);

    // B. wangwu：PR-57（已批准）详情 → 创建采购订单 → 表单
    await switchUser(page, 'wangwu');
    await page.goto(`${FRONTEND}/purchase-requisitions/57`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const createBtn = page.locator('button:has-text("创建采购订单")').first();
    console.log('\ncreate PO btn:', await createBtn.count());
    if (await createBtn.count()) {
      await createBtn.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(800);
      console.log('URL:', page.url());
      await dump(page, 'B. PoCreate 表单');
    }
    // 回 PO 列表找一个 DRAFT 的 PO 详情看确认按钮
    await page.goto(`${FRONTEND}/purchase-orders`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const draftView = page.locator('tr:has(.el-tag--info) button:has-text("查看")').first();
    console.log('\ndraft PO 查看按钮:', await draftView.count());
    if (await draftView.count()) {
      await draftView.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(700);
      console.log('PO 详情 URL:', page.url());
      await dump(page, 'C. PO详情(DRAFT) 按钮区');
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });
