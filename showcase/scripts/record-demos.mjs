// ERP 真实操作录屏 — Phase 13 Portfolio（demo-01/02/03）
//
// 三支视频均为【真实 ERP 操作录屏】（playwright-core + Edge 驱动本地真实前后端），
// 非伪造、非概念动画：
//   demo-01-business-flow   PR→审批→PO（zhangsan 建/看 → lisi 批 → wangwu 转/确认）
//   demo-02-receipt         PO 分批收货 40 → 60 → 库存 100 + 流水 +40/+60
//   demo-03-reversal        冲销第二批 60 → 流水 REVERSAL −60 → 库存回 40
//
// 前置：
//   1) backend:8000 + frontend:5173 运行中
//   2) demo-01 前：python prep-demo.py reset
//      demo-02/03 前：python prep-demo.py prep-receive（含 reset + 造 CONFIRMED PO）
//   3) 视频输出 docs/videos/（context 关闭自动落盘 .webm）
//
// 用法：node record-demos.mjs [01|02|03|all]
import { chromium } from 'file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdirSync, readdirSync, renameSync, statSync } from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..', '..');
const VIDEO_DIR = resolve(ROOT, 'docs', 'videos');
mkdirSync(VIDEO_DIR, { recursive: true });

const FRONTEND = 'http://127.0.0.1:5173';
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const PW = { admin: 'admin123', zhangsan: 'demo123', lisi: 'demo123', wangwu: 'demo123', zhaoliu: 'demo123' };
const VIEW = { width: 1600, height: 900 };   // 录屏：1600x900（足够清晰、体积适中）

let P; // 当前 page

const sleep = (ms) => P.waitForTimeout(ms);

async function login(user, hold = 900) {
  await P.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await P.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await P.fill('input[placeholder="用户名"]', user);
  await sleep(350);
  await P.fill('input[placeholder="密码"]', PW[user]);
  await sleep(350);
  await P.locator('button.login-btn, button:has-text("登录")').first().click();
  await P.waitForURL((u) => !u.toString().includes('/login'), { timeout: 15000 });
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(hold);
}

async function switchUser(user, hold = 900) {
  await P.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await P.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await P.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await P.fill('input[placeholder="用户名"]', user);
  await sleep(300);
  await P.fill('input[placeholder="密码"]', PW[user]);
  await sleep(300);
  await P.locator('button.login-btn, button:has-text("登录")').first().click();
  await P.waitForURL((u) => !u.toString().includes('/login'), { timeout: 15000 });
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(hold);
}

async function goto(url, hold = 900) {
  await P.goto(`${FRONTEND}${url}`, { waitUntil: 'domcontentloaded' });
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(hold);
}

/** 点击表格中某行（按文本定位）内的按钮 */
async function rowBtn(rowText, btnText, { timeout = 12000, hold = 1200 } = {}) {
  const btn = P.locator(`.el-table__row:has-text("${rowText}") button:has-text("${btnText}")`).first();
  await btn.waitFor({ state: 'visible', timeout });
  await sleep(300);
  await btn.click();
  await sleep(hold);
}

/** 点 messagebox/dialog 确认按钮（文本优先，兜底取右侧按钮） */
async function confirmBox(hold = 1400) {
  const candidates = ['确定', '确认', '通过', '确认冲销'];
  for (const t of candidates) {
    const b = P.locator(`.el-message-box button:has-text("${t}"), .el-dialog button:has-text("${t}")`).first();
    if (await b.count()) { await b.click(); await sleep(hold); return; }
  }
  // 兜底：messagebox 按钮区最后一个
  const btns = P.locator('.el-message-box__btns button');
  if (await btns.count()) {
    await btns.last().click();
    await sleep(hold);
  }
}

// ============================================================ demo-01
async function demo01() {
  // —— 段 1：zhangsan（申请人）—— 看自己的待审批申请
  await login('zhangsan');
  await goto('/purchase-requisitions', 700);
  await rowBtn('STM32 芯片补充', '查看', { hold: 1200 });   // PENDING PR 详情
  await sleep(1600);                                        // 展示：状态/明细

  // —— 段 2：lisi（部门主管）—— 审批中心通过 ——
  await switchUser('lisi');
  await goto('/approvals', 900);
  await rowBtn('STM32 芯片补充', '审批', { hold: 1300 });   // 打开审批抽屉
  const opinion = P.locator('.el-drawer input[placeholder*="审批意见"]').first();
  if (await opinion.count()) {
    await opinion.fill('同意，研发备用');
    await sleep(500);
  }
  await P.locator('.el-drawer button:has-text("通过")').first().click();
  await sleep(1500);
  await P.keyboard.press('Escape').catch(() => {});
  await sleep(900);                                          // 展示：列表刷新，该单消失

  // —— 段 3：wangwu（采购员）—— 转 PO 并确认 ——
  await switchUser('wangwu');
  await goto('/purchase-requisitions', 700);
  await rowBtn('STM32 芯片补充', '查看', { hold: 1200 });   // APPROVED PR 详情
  const createPo = P.locator('button:has-text("创建采购订单")').first();
  await createPo.waitFor({ state: 'visible', timeout: 10000 });
  await sleep(300);
  await createPo.click();
  await P.waitForURL((u) => u.toString().includes('/purchase-orders/create'), { timeout: 15000 });
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);                                          // 展示：可转明细列表

  // 在可转列表中给 STM32 行填数量 20
  const qtyInput = P.locator('.el-table__row:has-text("STM32F103") input[placeholder*="不转"], .el-table__row:has-text("STM32F103") input').first();
  await qtyInput.waitFor({ state: 'visible', timeout: 10000 });
  await qtyInput.fill('20');
  await sleep(600);
  // 供应商
  const supSel = P.locator('.el-select:has-text("供应商")').first();
  if (await supSel.count()) {
    await supSel.click();
    await sleep(700);
    const supOpt = P.locator('.el-select-dropdown__item:visible:has-text("天津宏远电子")').first();
    await supOpt.waitFor({ state: 'visible', timeout: 8000 });
    await supOpt.click();
    await sleep(600);
  }
  const submitPo = P.locator('button:has-text("创建采购订单")').first();
  await submitPo.click();
  // 创建成功 → 跳 PO 详情（DRAFT）
  try {
    await P.waitForURL((u) => /\/purchase-orders\/\d+$/.test(u.toString()), { timeout: 12000 });
  } catch {
    await goto('/purchase-orders', 800);
    await rowBtn('¥100.00', '查看', { hold: 1000 });        // 兜底：进 PO 列表找新单
  }
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);                                          // 展示：新 PO DRAFT
  const confirmBtn = P.locator('button:has-text("确认订单")').first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 10000 });
  await sleep(300);
  await confirmBtn.click();
  await sleep(800);
  await confirmBox(1600);                                     // ElMessageBox 确认
  await sleep(1200);                                          // 展示：CONFIRMED / 待收货
}

// ============================================================ demo-02
async function demo02() {
  // zhaoliu：收 40 → 收 60 → 库存 100 + 流水
  await login('zhaoliu');
  await goto('/purchase-receipts/create', 700);

  // 收 40
  await P.locator('.el-select:has-text("选择 CONFIRMED")').first().click();
  await sleep(700);
  const poOpt = P.locator('.el-select-dropdown__item:visible:has-text("CONFIRMED")').first();
  await poOpt.waitFor({ state: 'visible', timeout: 10000 });
  await poOpt.click();
  await sleep(800);
  await P.locator('.el-select:has-text("选择仓库")').first().click();
  await sleep(700);
  const whOpt = P.locator('.el-select-dropdown__item:visible:has-text("成品仓")').first();
  await whOpt.waitFor({ state: 'visible', timeout: 8000 });
  await whOpt.click();
  await sleep(1000);                                          // 明细行出现
  const qty1 = P.locator('input[placeholder*="本次 ≤ 剩余"]').first();
  await qty1.waitFor({ state: 'visible', timeout: 10000 });
  await qty1.fill('40');
  await sleep(600);
  await P.locator('button:has-text("过账入库")').first().click();
  await P.locator('.el-message--success').waitFor({ timeout: 10000 }).catch(() => {});
  await sleep(1400);                                          // 展示：入库成功

  // 收 60（新开收货页，同一 PO）
  await goto('/purchase-receipts/create', 700);
  await P.locator('.el-select:has-text("选择 CONFIRMED")').first().click();
  await sleep(700);
  await P.locator('.el-select-dropdown__item:visible:has-text("CONFIRMED")').first().click();
  await sleep(800);
  await P.locator('.el-select:has-text("选择仓库")').first().click();
  await sleep(700);
  await P.locator('.el-select-dropdown__item:visible:has-text("成品仓")').first().click();
  await sleep(1000);
  const qty2 = P.locator('input[placeholder*="本次 ≤ 剩余"]').first();
  await qty2.waitFor({ state: 'visible', timeout: 10000 });
  await qty2.fill('60');
  await sleep(600);
  await P.locator('button:has-text("过账入库")').first().click();
  await P.locator('.el-message--success').waitFor({ timeout: 10000 }).catch(() => {});
  await sleep(1400);

  // 库存余额 100
  await goto('/inventory', 1300);
  await sleep(1600);
  // 库存流水 +40 / +60
  await goto('/inventory/transactions', 1600);
  await sleep(1800);
}

// ============================================================ demo-03
async function demo03() {
  // zhaoliu：冲销第二批 60 → 流水 −60 → 库存回 40
  await login('zhaoliu');
  await goto('/purchase-receipts', 900);
  // 最新入库单（第一行）→ 详情
  const viewBtn = P.locator('.el-table__row button:has-text("查看")').first();
  await viewBtn.waitFor({ state: 'visible', timeout: 10000 });
  await viewBtn.click();
  await P.waitForURL((u) => /\/purchase-receipts\/\d+$/.test(u.toString()), { timeout: 15000 });
  await P.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await sleep(1200);                                          // 展示：入库单详情（60）
  const revBtn = P.locator('button:has-text("冲销入库")').first();
  await revBtn.waitFor({ state: 'visible', timeout: 10000 });
  await sleep(300);
  await revBtn.click();
  await sleep(1000);                                          // prompt 出现
  const reason = P.locator('.el-message-box input, .el-message-box textarea').first();
  await reason.waitFor({ state: 'visible', timeout: 8000 });
  await reason.fill('录屏演示：冲销第二批收货');
  await sleep(600);
  await confirmBox(1800);                                     // 确认冲销
  await sleep(1200);                                          // 展示：已冲销状态

  // 库存余额 40
  await goto('/inventory', 1300);
  await sleep(1500);
  // 流水 REVERSAL −60
  await goto('/inventory/transactions', 1800);
  await sleep(2000);
}

// ============================================================ 主流程
async function run(which) {
  const wanted = (which === 'all') ? ['01', '02', '03'] : [which];
  const files = {};

  for (const w of wanted) {
    const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
    const ctx = await browser.newContext({
      viewport: VIEW,
      locale: 'zh-CN',
      recordVideo: { dir: VIDEO_DIR, size: VIEW },
    });
    P = await ctx.newPage();
    const t0 = Date.now();
    try {
      if (w === '01') await demo01();
      else if (w === '02') await demo02();
      else if (w === '03') await demo03();
    } finally {
      await ctx.close();
      await browser.close();
    }
    const dur = ((Date.now() - t0) / 1000).toFixed(1);
    const webm = readdirSync(VIDEO_DIR).filter((f) => f.endsWith('.webm') && !f.startsWith('demo-'));
    console.log(`[demo-${w}] recorded ${dur}s`);
    // 该 context 新产出的 webm（按时间最新取）
    const latest = webm
      .map((f) => ({ f, t: statSync(resolve(VIDEO_DIR, f)).mtimeMs }))
      .sort((a, b) => b.t - a.t)[0];
    if (!latest) throw new Error(`demo-${w}: no webm produced`);
    const target = resolve(VIDEO_DIR, `demo-${w === '01' ? '01-business-flow' : w === '02' ? '02-receipt-inventory' : '03-reversal'}.webm`);
    renameSync(resolve(VIDEO_DIR, latest.f), target);
    files[w] = target;
    console.log(`[demo-${w}] -> ${target} (${(statSync(target).size / 1024 / 1024).toFixed(2)} MB)`);
  }
  return files;
}

const which = process.argv[2] || 'all';
run(which).then((f) => {
  console.log('DONE', f);
  process.exit(0);
}).catch((e) => {
  console.error('FAIL:', e);
  process.exit(1);
});
