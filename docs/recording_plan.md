# 录屏计划（Phase 13）

> 自动录屏工具在本环境**不可用** —— headless 浏览器不直接支持录屏、桌面录屏
> 软件（OBS、Bandicam 等）与沙箱冲突或需 GUI 安装。本仓库**不伪造录屏**，改为
> 给出可重复的人工录制步骤。
>
> 录屏产物建议格式：**WebM**（VP9/Opus，`muted` 嵌入 `<video>`）或 **MP4**
> （H.264）。**避免巨大 GIF**（>2MB 加载慢）。

---

## 0. 录制环境准备

```bash
# 1) 启动本地真实 ERP（任选其一）
#    a. 本机直接跑：
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm run dev

#    b. Docker Compose（仅在 daemon 可用环境）：
docker compose up -d --build
# 然后浏览器开 http://localhost:8080

# 2) 准备浏览器：Edge 1920×1080，无扩展弹出
# 3) 安装录屏工具（任选）：OBS Studio / Windows Game Bar (Win+Alt+R) / Edge 内置录屏插件
# 4) 输出格式：WebM（VP9），目标码率 4 Mbps，FPS 30
```

---

## 1. demo-01-business-flow.webm  ·  30–45s

> 展示 PR → Approval → PO 的端到端推进。

| 时段 | 屏幕 | 旁白要点 |
|---|---|---|
| 0–5s   | `01-login` 登录页 → admin 登录 | "演示账号来自 seed_demo，与测试一致" |
| 5–15s  | admin Dashboard（02） | "5 个角色收敛待办 + 库存金额 ¥1190.00" |
| 15–30s | 切换 zhangsan → 提交 PR（实际：`/purchase-requisitions/create`，补一个 demo 物料需求 50 件） | "DRAFT → Submit → PENDING" |
| 30–45s | 切回 admin → 看到该 PR PENDING → 切换 lisi → Approvals 列表 → 点 Approve | "DEPT_MANAGER 范围裁剪；状态 → APPROVED" |

**录制要点**：
- 不要录登录失败的画面
- 鼠标轨迹干净（不绕路）；切换账号前 hover 一下用户名提示"切换"

## 2. demo-02-receipt-inventory.webm  ·  20–30s

> 展示分批收货如何推动 Balance 数字增长。

| 时段 | 屏幕 | 旁白要点 |
|---|---|---|
| 0–5s   | admin PO 详情（06） | "PARTIALLY_RECEIVED；行项目 ordered=80 received=80（已收 80 但状态未到 RECEIVED）" |
| 5–12s  | 切 zhaoliu → `/purchase-receipts/create` → 选 PR5 的剩余行 → 收 40 → 提交 | "Receipt 头+明细+流水+Balance 同事务" |
| 12–18s | 切 zhaoliu → `/inventory` | "Balance 由 40 → 80；低于安全库存的提示消失（若满足）" |
| 18–25s | 切 zhaoliu → `/inventory/transactions` | "ledger append-only +60 / +¥600.00（按原始 PO 单价移动加权）" |

**录制要点**：
- 收到第 2 批时短暂特写 total_amount 列，强调加权平均 ROUND_HALF_UP/2
- 强调 ledger 不可改/不可删（仅冲销产生新行）

## 3. demo-03-reversal.webm  ·  15–25s

> 演示冲销流程与"按原始 receipt 金额回滚"。

| 时段 | 屏幕 | 旁白要点 |
|---|---|---|
| 0–5s   | zhaoliu → `/purchase-receipts` 选最近一个 RCV → 详情 | "POSTED 状态；点击冲销按钮（仅仓库+管理员）" |
| 5–12s  | 填写冲销原因 → 确认 → Receipt 状态 → REVERSED | "REVERSAL 流水插入；Balance -=60；不删除原行" |
| 12–18s | `/inventory` | "Balance 由 80 → 20（若之前是 80）" |
| 18–25s | `/inventory/transactions` | "ledger 新增 REVERSAL −60 / −¥600.00；PURCHASE_IN +60 / +¥600.00 行原封不动" |

**录制要点**：
- 不要演示重复冲销同一行（会报 6009 INVENTORY_NEGATIVE，保留为失败截图即可）
- 强调"按原始金额回滚"而非"current_avg × qty"

---

## 4. 上传到 GitHub 仓库（建议）

```bash
# 录制完成后放入 showcase/public/videos/（注意 .gitignore 不忽略视频）
mkdir -p showcase/public/videos
cp demo-*.webm showcase/public/videos/
git add showcase/public/videos/
git commit -m "feat(showcase): add 3 short demo videos (webm, real ERP recording)"
# Showcase 的 Gallery 节或 DocsSection 加 <video> 引用即可
```

`showcase/src/sections/GallerySection.vue` 增加 video 卡片示例：

```vue
<div class="frame">
  <video src="./videos/demo-01-business-flow.webm" muted loop playsinline
         preload="metadata" controls aria-label="业务流录屏"></video>
  <div class="cap">
    <span><span class="tag tag-info">Recorded Demo</span>业务流 · PR→PO</span>
    <span class="src">admin / zhangsan / lisi · 45s</span>
  </div>
</div>
```

## 5. 视频展示原则（与 Showcase 一致）

- `<video muted loop playsinline>` —— 默认静音、不自动播放音频
- 进入 viewport 后才播放 / 离开后暂停（用 IntersectionObserver）
- 不堆叠全部视频同时播放
- 三分类明确标注：`Recorded Demo` tag（与 `Real Screenshot` / `Concept Animation` 区分）

## 6. 录制失败时的回退

- 录屏工具装不上：用 Edge 内置 Ctrl+Shift+S（屏幕捕获）+ WebM 拼接；或用 macOS / 同事机器
- 时长控制失误：录制时间长一些（覆盖录制），后期 ffmpeg 剪裁
  ```bash
  ffmpeg -ss 00:00:05 -t 00:00:45 -i raw.webm -c copy demo-01-business-flow.webm
  ```
- 录屏画面中出现 devtools：重新录制；不要交付含 devtools 的版本

---

> 维护者：录屏建议每年回归测试一次（验证数据快照对得上 README 中的 KPI 数字）。