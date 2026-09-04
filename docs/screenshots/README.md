# 真实截图与录屏素材（Phase 13）

> 本目录下的 `01-login.png` … `10-rbac.png` 是 **真实 ERP 截图**。
> 录屏素材（`.webm`）未自动生成 —— 详见 [`recording_plan.md`](./recording_plan.md)。
> 概念动画（Quantity Chain、Ledger Story）严格不归本目录，由
> [Showcase 网站](../showcase/) 内 `<Concept animation based on actual ERP rules>` 标签渲染。

## 1. 真实性三分类（面试官必读）

| 类型 | 来源 | 位置 |
|---|---|---|
| **Real ERP Screenshot** | Playwright + Microsoft Edge 驱动本地 `backend:8000` + `frontend:5173`（基于 seed_demo 数据） | 本目录 + `showcase/public/screenshots/`（同一份 PNG） |
| **Recorded Demo** | 自动录屏工具不可用（见 [`recording_plan.md`](./recording_plan.md)），以**人工录屏步骤**形式记录 | 待人工录制 |
| **Concept / Architecture Animation** | 由 Showcase 网站生成：IntersectionObserver + CSS transition，**不连接任何后端** | `showcase/dist/assets/index-*.js` |

三者在 UI 上均有显著标签 —— 真实截图带 `真实截图` tag、概念动画带 `Concept animation based on actual ERP rules` 黄色虚线 banner，避免混淆。

## 2. 截图清单（10 张 · 1920×1080）

| 文件 | 页面 | 账号 | 状态/口径 | 关键看点 |
|---|---|---|---|---|
| `01-login.png` | `/login` | — | — | 演示账号表 + Element Plus 登录页 |
| `02-dashboard.png` | `/dashboard` | admin | 6 KPI：待审 2 / 待转 2 / 待确认 1 / 待收货 1 / 低库存 2 / 库存金额 ¥1,190.00 | ECharts 趋势 + PO 状态环图 + 低库存表 |
| `03-pr-list.png` | `/purchase-requisitions` | admin | 全部 PR（CONVERTED/CANCELLED/APPROVED/PENDING） | 状态 tag 颜色 + 申请编号 |
| `04-pr-detail.png` | `/purchase-requisitions/57` | admin | APPROVED PR | 行项目 + 版本 + 操作历史 |
| `05-approval.png` | `/approvals` | lisi | 部门主管审批列表 | DEPT_MANAGER 范围裁剪（只看本部门 PR） |
| `06-po-detail.png` | `/purchase-orders/30` | admin | PARTIALLY_RECEIVED | recompute_po_status 推导逻辑体现 |
| `07-receipt.png` | `/purchase-receipts` | zhaoliu | 仓库收货列表 | 5 张 POSTED 入库单 |
| `08-inventory-balance.png` | `/inventory` | zhaoliu | 4 条 balance · 2 行低于安全库存 | 高亮 + 安全库存标签 |
| `09-inventory-transactions.png` | `/inventory/transactions` | zhaoliu | append-only ledger | PURCHASE_IN/REVERSAL + balance_after |
| `10-rbac.png` | `/users` | admin | 用户/角色管理 | 角色矩阵 + 启停用户 |

> 每张图均来自 seed_demo 业务故事（详见 `backend/seed_demo.py`），与
> `tests/test_dashboard.py` 同一口径；确定性结果：库存账面金额 ¥1,190.00。

## 3. 截图如何复现

```bash
# 前置：本地 backend:8000 + frontend:5173 已起
cd <repo-root>
cd showcase/scripts
node capture-screenshots.mjs
# 产物：
#   docs/screenshots/01..10.png          (master，文档用)
#   showcase/public/screenshots/01..10.png (build 内嵌，showcase 用)
```

实现细节：
- `playwright-core` 通过 `executablePath` 连接本机 `Microsoft Edge`（无需下载浏览器）
- viewport `1920×1080`，`deviceScaleFactor: 1`
- 登录走真实 UI（点击 `登录` 按钮），非 token 注入
- 切换账号：`localStorage.clear()` + 重新登录
- 等待 `networkidle` + 900ms（图表动画稳定）

## 4. 录屏（webm / mp4）

自动录屏工具**不可用**（headless 浏览器不直接支持录屏，桌面录屏需额外软件且与沙箱冲突），
故不伪造。请按 [`recording_plan.md`](./recording_plan.md) 的人工步骤录制 3 段短视频。

## 5. 不允许的做法

- ❌ 用 Figma / 截图工具伪造 ERP 界面后标注为"真实截图"
- ❌ 把 Showcase 动画截图后再标注为"真实 ERP 录屏"
- ❌ 拼接多个真实页面到一张图（除非明确标注是合成示意）
- ✅ 真实截图必须 1920×1080、统一 viewport、基于演示账号、不出现 devtools / 隐私