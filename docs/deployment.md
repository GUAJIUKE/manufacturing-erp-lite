# 部署文档 — Docker Compose（Phase 13）

本地一键部署 Manufacturing ERP Lite（MySQL 8 + FastAPI 后端 + Vue3/Nginx 前端），
验收标准（roadmap Phase 13）：`docker compose up -d` 后浏览器访问
`http://localhost:8080` 可用演示账号登录并完成演示。

## 1. 架构

```
浏览器 ── http://localhost:8080 ──► nginx (frontend 容器)
                                      ├── /          静态 SPA（history 回退到 index.html）
                                      ├── /showcase/  Portfolio Showcase（独立 Vue 3 静态站）
                                      └── /api/ ──►  backend:8000（FastAPI, /api/v1）
                                                         └──► mysql:3306（仅容器内网）
```

Showcase 由同一 nginx 提供：`/showcase/` 指向镜像内 `/usr/share/nginx/html/showcase/`；
该目录由 `frontend/Dockerfile` 的第二阶段（`sc-build`）从 `showcase/` 构建产物拷入，
`docker compose up -d --build` 时**与 ERP SPA 一起构建**，维护成本最低。

设计要点：

| 项 | 说明 |
|---|---|
| 端口发布 | 仅 `8080:80`（前端）。MySQL 与后端**不发布宿主机端口**——本机 3306/8000 已有原生服务，避免冲突 |
| 同源 API | 前端构建时注入 `VITE_API_BASE_URL=/api/v1`，浏览器只访问 nginx，由 nginx 反代 `/api` → 后端，无跨域 |
| 启动序列 | 后端 entrypoint：等 MySQL → `alembic upgrade head` → `init_data`（RBAC，幂等）→ `seed_demo`（演示业务故事，幂等）→ `uvicorn` |
| 非 root | 后端容器以 uid 10001 运行；前端 nginx 官方镜像自带非 root 运行 |
| 数据卷 | `mysql_data` 持久化；`docker compose down -v` 才会清库 |

## 2. 前置条件

- Docker Desktop（Windows，WSL2 后端）已安装并启动，`docker version` 能返回 Server 版本。
  - 若引擎起不来：检查 **安全中心 → 命令安全 → 程序黑名单**，`wsl.exe` 必须被放行
    （Docker Desktop 的 WSL2 后端依赖它拉起 Linux 引擎；黑名单会终止其 backend 进程）。
- 端口 8080 空闲。
- 网络可访问 docker.io / registry.npmjs.org（国内慢可给 frontend 加
  `--build-arg NPM_REGISTRY=https://registry.npmmirror.com`，见 §5）。

## 3. 一键启动

```bash
cd <repo-root>                     # docker-compose.yml 所在目录
docker compose up -d --build       # 首次构建约几分钟
docker compose ps                  # 三个服务均应 (healthy)
```

启动完成后打开 **http://localhost:8080**。

### 演示账号（来自 init_data + seed_demo）

| 账号 | 密码 | 角色 | 能看什么 |
|---|---|---|---|
| `admin` | `admin123` | ADMIN | 全部（含仪表盘） |
| `zhangsan` | `demo123` | APPLICANT 研发部 | 自己提交的 PR |
| `lisi` | `demo123` | DEPT_MANAGER | 本部门审批 |
| `wangwu` | `demo123` | BUYER | 转 PO / 确认 |
| `zhaoliu` | `demo123` | WAREHOUSE | 收货入库 |

seed_demo 预置 9 张 PR / 2 张 PO / 5 张入库单的确定性业务故事（与
`tests/test_dashboard.py` 同一口径），登录即可看到仪表盘数据。

## 4. 常用运维

```bash
docker compose logs -f backend      # 看启动序列（migrate → seed → uvicorn）
docker compose logs -f frontend     # nginx 访问日志
docker compose restart backend      # 重启后端（会重放幂等 seed，业务数据复位为演示态）
docker compose down                 # 停止（保留 mysql_data 卷）
docker compose down -v              # 停止并删除数据卷（彻底清库）
docker compose config               # 静态校验（无需引擎）
```

健康检查链路：`frontend → /api/v1/health → nginx → backend → /api/v1/health → DB`，
任一环节异常对应容器都会在 `docker compose ps` 显示 unhealthy。

Showcase 是纯静态站，**不参与**健康检查（无后端依赖）。
如需校验 Showcase 是否成功构建到镜像：访问 `http://localhost:8080/showcase/`，看到
Manufacturing ERP Lite Hero 与 12 节页面即视为通过。

## 5. 可调参数（根目录 .env 或环境变量）

模板：根目录 `.env.example`（已纳入仓库，无任何真实 secret）。

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_PASSWORD` | `erp_lite_dev` | MySQL root 密码（mysql 容器与 backend 同步生效） |
| `DB_NAME` | `erp_lite` | 业务库名 |
| `SECRET_KEY` | demo 值 | **生产必须覆盖**（JWT 签名密钥） |
| `DEMO_SEED` | `1` | `0` 则跳过 seed_demo（真实部署建议关掉，业务数据走 API） |
| `NPM_REGISTRY` | `registry.npmjs.org` | 可改为 `https://registry.npmmirror.com` 加速国内构建 |

示例 `docker-compose.override.yml` 或根目录 `.env`：

```dotenv
DB_PASSWORD=YourStrongPass
SECRET_KEY=$(openssl rand -hex 32)   # 手填生成值
DEMO_SEED=0
```

前端 npm 源（仅构建期）：

```bash
docker compose build --build-arg NPM_REGISTRY=https://registry.npmmirror.com frontend
```

## 6. 安全与生产注意事项

- 本 compose 面向**本地演示**：`ENV=dev`、CORS 全放开、SECRET_KEY 默认值、DB 口令默认值。
- 上生产前必须：覆盖 `SECRET_KEY` / `DB_PASSWORD`；`DEMO_SEED=0`；
  收紧 CORS（`app/main.py` `allow_origins`）；mysql 卷单独备份；考虑后端不 root 直连而是专用账号。
- seed_demo 每次启动会**清空并重放业务数据**（幂等演示设计），有真实数据后切勿再以 `DEMO_SEED=1` 重启。

## 7. 故障排查

| 症状 | 处置 |
|---|---|
| `docker compose up` 报无法连接引擎 | Docker Desktop 未启动或 wsl.exe 被安全策略拦截（见 §2） |
| backend 反复重启/日志停在 waiting MySQL | `docker compose logs mysql`；确认 `mysql` 服务 healthy（启动冷启约 10–30s） |
| 页面能开但登录报网络异常 | `docker compose ps` 看 backend 是否 healthy；`curl http://localhost:8080/api/v1/health` |
| 前端构建慢/失败（registry.npmjs.org） | 用 §5 的 npmmirror 构建参数重试 |
| 想换宿主端口 | 改 compose `ports: "8080:80"` 左值，如 `9000:80` |
