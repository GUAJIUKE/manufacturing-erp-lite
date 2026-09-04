# 权限设计（RBAC / Object-Level Permission / Document Status）

> 三种机制各有分工，叠加之后才构成「这一步能不能做」的完整判定。
> 代码事实来源：`app/api/v1/deps.py`、`app/models/system.py`、
> 各 Service 的 `_assert_*` 与 `visible_*` 函数、`app/db/init_data.py` 权限矩阵。

---

## 1. 三种机制的区别（先给结论）

| 机制 | 回答的问题 | 判断依据 | 落点 | 例子 |
|---|---|---|---|---|
| RBAC 权限点（Permission） | **「你能调这个功能吗？」** | 用户角色 → `role_permissions` → 权限点集合 | 路由层 `require_perm("pr:approve")` | 有 `pr:approve` 才能进审批接口 |
| 对象级权限（Object-Level） | **「你能对这个**具体单据/数据**操作吗？」** | 单据归属、部门主管关系、数据范围 | Service 层 `_assert_*` / 查询范围子查询 | 只能批**自己主管部门**的 PR；只能确认**自己创建**的 PO |
| 单据状态（Document Status） | **「这个单据当前**状态**允许这个操作吗？」** | 单据当前状态 + 状态机白名单 | Service 层 `_TRANSITIONS` / CAS WHERE 条件 | 只有 `PENDING` 才能批；`CONFIRMED` 才能收货 |

**三者是 AND 关系**：路由权限点放行 → Service 做对象级校验 → 再做状态机校验，
任意一层不过即拒绝（403 / 4002 / 409…）。

## 2. 角色与权限点（RBAC）

五个系统角色（`RoleCode`，闭合枚举 + `is_system` 不可删）：

| 角色 | 定位 | 权限域（典型权限点） |
|---|---|---|
| `APPLICANT` 采购申请人 | 提需求 | PR 创建/编辑/提交/取消（自己的）、查看自己的 PR/PO 链路 |
| `DEPT_MANAGER` 部门主管 | 审需求 | `pr:approve` / `pr:reject`（自己主管的部门）、Dashboard |
| `BUYER` 采购员 | 执行采购 | `po:create` / `po:confirm` / `po:cancel`、主数据查看、Dashboard |
| `WAREHOUSE` 仓库管理员 | 收货与库存 | `receipt:create` / `receipt:reverse`、库存查询、Dashboard |
| `ADMIN` 系统管理员 | 全权 | 系统管理（用户/角色/部门/权限分配）、全模块；审批可 override |

- 用户 v1 **单角色**（`users.role_id`），多角色不在本期范围。
- 权限点：`permissions.perm_code`（如 `pr:approve`、`material:view`、`user:manage`），
  前端菜单/按钮显隐也以同一份权限点为依据（登录后 `/auth/me` 返回），前后端
  口径一致；但前端隐藏只是体验，后端 `require_perm` 才是裁决。

## 3. 对象级权限（本项目最重要的权限设计）

`require_perm("pr:approve")` 只证明「你是主管这个角色」，**不证明**「你能批这张
PR」。对象级规则在 Service 层逐单校验：

| 规则 | 实现函数 | 拒绝表现 |
|---|---|---|
| PR 只能由**申请人本人**或 ADMIN 编辑/提交/取消/修订 | `_assert_self_or_admin`（`PR_NOT_APPLICANT`） | 403 |
| PR 只能由**申请部门的主管**审批（查 `department_managers`，ADMIN override 例外且审计标注） | `_assert_approver`（`PR_NOT_APPROVER`） | 403 |
| PO 只能由**创建它的 BUYER** 确认/取消（ADMIN 全量） | `_assert_buyer_or_admin` | 403 |
| 列表/详情可见范围：APPLICANT 只看**自己 PR 转出**的 PO/Receipt；DEPT_MANAGER 只看**所管部门 PR 转出**的 | `visible_po_id_stmt` / `_assert_visible`（子查询 EXISTS 链路） | 403（不泄漏存在性） |
| 收货人/审批人等业务主体字段一律由服务端从登录用户推导 | `received_by=user.id` 等 | — |

> 为什么对象级判断必须在 Service 而不是路由依赖：它需要读数据库（部门主管关系、
> 单据归属、PR→PO→Receipt 链路），是业务规则的组成部分；放路由层会导致规则
> 散落且无法复用（多个接口共用同一套范围逻辑——`visible_po_id_stmt` 被 PO 与
> Receipt 两处复用即是证据）。

## 4. 数据范围（可见性）矩阵

| 数据域 | ADMIN | BUYER | WAREHOUSE | DEPT_MANAGER | APPLICANT |
|---|---|---|---|---|---|
| 用户/角色/部门管理 | 全量 | — | — | — | — |
| 主数据（物料/供应商/仓库/策略） | 全量 | 查看 | 查看 | 查看 | 查看 |
| PR 列表 | 全量 | 全量 | 无 PR 权限（不可见） | 所管部门 | 自己 |
| PO 列表 | 全量 | 全量（含自己创建的） | 全量（收货需要） | 所管部门 PR 转出的 | 自己 PR 转出的 |
| Receipt 列表 | 全量 | 自己 PO 的收货 | 全量（收货职责） | 所管部门 PR 链路 | 自己 PR 链路 |
| 库存余额/流水 | 全量 | 全量 | 全量 | 全量 | 全量 |
| Dashboard | 全景 KPI | 执行类待办聚焦 | 收货/低库存视角 | 本部门 PR 统计 | 自己 PR 统计 |

> 例：WAREHOUSE 没有 `pr:view`，Dashboard 的 PR 类 KPI 直接为 0（不是空数据，
> 是权限隔离）；APPLICANT 看不到别人 PENDING 的 PR（seed_demo 自检断言此点）。

## 5. 经典反例：有 `pr:approve` ≠ 能批任意部门 PR

```
主管 lisi 管研发部。PR-1001 属于 采购部。
lisi 调用 approve(PR-1001)：
  ① require_perm("pr:approve")   → 通过（lisi 角色是 DEPT_MANAGER）
  ② _assert_approver：
       查 department_managers WHERE dept_id=采购部 AND user_id=lisi → 无记录
       → 403 PR_NOT_APPROVER「只有申请部门的主管才能审批」
```

没有第 ② 层，任何主管都能批全公司的单——这正是「菜单级权限」与「业务级授权」
必须分离的原因。

## 6. 单据状态作为第三层「权限」

即便通过了 ① ②，仍可能被状态机拒绝：

```
lisi 审批一张已 APPROVED 的 PR → _TRANSITIONS[APPROVED] 无 APPROVE → 4002
zhangsan 编辑已 PENDING 的 PR → PENDING 不在 DRAFT 编辑前提 → 拒绝
```

对象级校验常发生在状态机校验之前（先确认「你有权操作这张单」，再确认
「这张单现在让不让你操作」），但语义上是并存的第三层。

## 7. Dashboard 也需要对象级权限

Dashboard 不是"所有人看同一份聚合"，而是**按角色算好范围再聚合**（SQL 里先
WHERE 范围再 COUNT/SUM）：

- 待审批 PR 数：按 `visible_pr_condition`（主管=所管部门；申请人=自己）过滤
- 待转采购/待确认 PO：按可执行角色收敛（BUYER 只看自己名下的 DRAFT PO）
- 待收货 PO / 低库存：仓库与采购按各自职责
- 缺权限的角色 KPI 恒为 0（如 WAREHOUSE 的 PR 指标），避免"看着像没数据"

口径细节见 docs/dashboard_metrics.md。

## 8. 审计与权限的关系

关键业务动作（登录、PR/PO/Receipt 流转、主数据变更、权限变更）写 `audit_logs`；
权限变更本身是审计动作（`PERMISSION_CHANGE`）——「谁在什么时候把什么权限给了
谁」可回放。ADMIN 越权审批在审批记录 step_name/描述中显式标注 override，
不允许静默越权。

## 9. 测试锚点

- `tests/test_auth.py`：登录/禁用/无权限
- `tests/test_rbac_crud.py` / `test_rbac_extra.py`：角色权限点、对象级 403、
  部门停用筛选
- Phase 12 E2E：BUYER 越权审批 → 2005、zh 越权入库 → 2005 等断言
- `test_dashboard.py`：五角色 KPI 隔离断言
