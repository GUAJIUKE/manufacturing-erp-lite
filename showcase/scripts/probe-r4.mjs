// 探测 R4 — 录屏脚本前置细节确认（只读，不提交任何写操作）
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

(async () => {
  const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN' });
    const page = await ctx.newPage();

    // 1. wangwu 打开 PoCreate?pr=57：来源行数量默认值
    await login(page, 'wangwu');
    await page.goto(`${FRONTEND}/purchase-orders/create?pr=57`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(700);
    const qtyInputs = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('input[placeholder="0=不转，≤ 剩余"], input[placeholder="0"]').forEach((el, i) => {
        out.push({ i, val: el.value, ph: el.getAttribute('placeholder') });
      });
      return out;
    });
    console.log('PoCreate qty inputs (defaults):', JSON.stringify(qtyInputs));
    // 供应商 select 当前值
    const supVal = await page.evaluate(() => {
      const sel = document.querySelector('.el-select');
      return sel ? (sel.textContent || '').trim().slice(0, 40) : 'none';
    });
    console.log('supplier select text:', supVal);

    // 2. lisi 看 PR 详情页（PENDING 自己部门）按钮布局
    await switchUser(page, 'lisi');
    await page.goto(`${FRONTEND}/purchase-requisitions/58`, { waitUntil: 'domcontentloaded' }); // PR 详情 id 可能不对，改用列表点入
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.goto(`${FRONTEND}/approvals`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(500);
    // 审批中心行文本（含 PR 编号？）
    const rows = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('.el-table__row').forEach(tr => {
        out.push((tr.textContent || '').replace(/\s+/g, ' ').slice(0, 90));
      });
      return out;
    });
    console.log('\napproval center rows:', rows);

    // 3. PO 列表 tag 文案（CONFIRMED）
    await switchUser(page, 'wangwu');
    await page.goto(`${FRONTEND}/purchase-orders`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(500);
    const poRows = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('.el-table__row').forEach(tr => {
        out.push((tr.textContent || '').replace(/\s+/g, ' ').slice(0, 100));
      });
      return out.slice(0, 6);
    });
    console.log('\nPO list rows:', poRows);

    // 4. PoDetail DRAFT 确认弹窗按钮
    await page.goto(`${FRONTEND}/purchase-orders/31`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(600);
    const confirmBtn = page.locator('button:has-text("确认订单")').first();
    console.log('\nPO31 confirm btn:', await confirmBtn.count());
    if (await confirmBtn.count()) {
      await confirmBtn.click();
      await page.waitForTimeout(700);
      const mb = await page.evaluate(() => {
        const out = [];
        document.querySelectorAll('.el-message-box, .el-dialog').forEach(d => {
          const cs = getComputedStyle(d);
          if (cs.display === 'none') return;
          out.push((d.textContent || '').replace(/\s+/g, ' ').slice(0, 120));
        });
        return out;
      });
      console.log('confirm dialog text:', mb);
      const ok = page.locator('.el-message-box button:has-text("确定"), .el-message-box__btns button').first();
      console.log('msgbox ok count:', await ok.count());
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    }

    // 5. ReceiptDetail 冲销按钮文案（找一张已过账入库单）
    await switchUser(page, 'zhaoliu');
    await page.goto(`${FRONTEND}/purchase-receipts`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(500);
    const rView = page.locator('.el-table__row button:has-text("查看")').first();
    console.log('\nreceipt view btn:', await rView.count());
    if (await rView.count()) {
      await rView.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(700);
      const rBtns = await page.evaluate(() => {
        const out = [];
        document.querySelectorAll('button').forEach(b => {
          const t = (b.textContent || '').trim();
          if (t) out.push(t.slice(0, 30));
        });
        return out;
      });
      console.log('ReceiptDetail buttons:', rBtns);
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('FAIL:', e); process.exit(1); });
