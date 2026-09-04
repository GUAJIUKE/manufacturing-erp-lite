# 截图规划（Screenshots）

> 目标：为 README / 简历 / 面试材料准备一套**真实页面**截图。
>
> **原则**：只用真实运行中的页面截图；不伪造、不用 mock 页面、不 P 图。
> 本文件是人工拍摄清单——自动浏览器不可用时，按此清单在本地手动截图即可。

---

## 0. 拍摄前置准备

```bash
# 后端（终端 1）
cd backend
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m app.db.init_data
./.venv/Scripts/python.exe -m app.db.seed_demo     # 确定性业务故事 + KPI 自检
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（终端 2）
cd frontend
npm run dev                                        # http://localhost:5173
```

浏览器建议：Chrome/Edge，窗口 1440×900+，系统缩放 100%，登录页点演示账号卡片填充。

## 1. 截图清单（10 张）

| # | 文件名 | 页面 | 登录账号 | 拍摄要点 |
|---|---|---|---|---|
| 01 | `01-login.png` | 登录页 | — | 演示账号卡片 + 品牌感；干净无报错 |
| 02 | `02-dashboard.png` | 数据看板 | admin | KPI 六卡齐全：待审批 2 / 待转 2 / 待确认 1 / 待收货 1 / 低库存 2 / ¥1,190.00；下方趋势与分布图 |
| 03 | `03-pr-list.png` | 采购申请列表 | zhangsan | 列表带状态标签（DRAFT/PENDING/APPROVED…）、分页、筛选条 |
| 04 | `04-pr-detail.png` | PR 详情 | zhangsan | 单头（编号/申请人/部门/金额）+ 明细行 + 状态流转/审批记录区 |
| 05 | `05-approval.png` | 审批中心 | lisi | 待审批列表；打开一条 PENDING PR 展示「通过 / 驳回」按钮与意见框 |
| 06 | `06-po-detail.png` | 采购订单详情 | wangwu | 来源映射（sources 展示 PR 来源）、确认按钮、金额汇总；建议抓 CONFIRMED 或 PARTIALLY_RECEIVED 态 |
| 07 | `07-receipt.png` | 采购入库 | zhaoliu | 新建入库（选 PO + 仓库 + 数量）；或入库单详情（POSTED + 明细 + 冲销按钮） |
| 08 | `08-inventory-balance.png` | 当前库存 | zhaoliu | 余额表 + 低库存红标/「低于安全库存」标记 + 平均成本列 |
| 09 | `09-inventory-transactions.png` | 库存流水 | zhaoliu | 带符号数量（+40 / +60 / -60）、类型列（PURCHASE_IN / PURCHASE_IN_REVERSAL）、来源单号 |
| 10 | `10-system-rbac.png` | 系统管理 | admin | 用户列表（五角色 demo 账号）或 角色权限分配页（勾选权限点矩阵） |

## 2. 每张截图想传达什么（讲解角度）

| 截图 | 面试/README 讲什么 |
|---|---|
| 01 login | 界面完整（Vue3 + Element Plus），演示账号设计 |
| 02 dashboard | 角色隔离 KPI + 口径一致性（admin 全景） |
| 03/04 PR | 单据 + 状态机 + 乐观锁版本号可见 |
| 05 approval | 审批流 + 部门主管对象级权限 |
| 06 PO | PR→PO 数量链、来源可追溯 |
| 07 receipt | 分批收货 + 事务过账 + 冲销 |
| 08 balance | 移动加权平均成本、低库存口径 |
| 09 transactions | append-only 流水 + 反向冲销记录（审计链） |
| 10 rbac | 权限点管理、五角色体系 |

## 3. 可选进阶素材

- **状态标签放大图**：StatusTag 组件五种色（PR/PO/Receipt 各状态）可拼一张小图
  放进 architecture 或 business_flow 文档。
- **ER / 架构图**：docs/ERD.md 与 docs/architecture.md 的 mermaid 图渲染成 PNG。
- **演示录屏**：按 docs/demo_script.md 的 10 步录 3–5 分钟屏（建议 OBS/系统录屏），
  比静态截图更适合作品集链接。

## 4. 存放位置与命名

```
docs/screenshots/
├── README.md          ← 本文件（清单 + 拍摄指引）
├── 01-login.png
├── 02-dashboard.png
├── ...
└── 10-system-rbac.png
```

> 截图产出后：README「项目文档」区补一节截图画廊，并在 docs/demo_script.md
> 每步标注对应截图文件名，方便面试讲述时对照。
