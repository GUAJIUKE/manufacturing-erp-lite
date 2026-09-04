# syntax=docker/dockerfile:1
# Manufacturing ERP Lite — frontend image (Vite SPA + Portfolio Showcase + nginx)
#
# Stage 1 builds the SPA (ERP admin) with VITE_API_BASE_URL defaulting to the
# same-origin path /api/v1, so the browser talks to nginx only and nginx
# reverse-proxies /api to the backend container (no CORS issues).
#   * 国内网络可换 npm 源：--build-arg NPM_REGISTRY=https://registry.npmmirror.com
# Stage 2 builds the Portfolio Showcase site (showcase/) — a Vue 3 + TS + Vite
# SPA that ships entirely as static files (zero backend dependency).
# Stage 3 (nginx) serves both: ERP admin at /, Portfolio at /showcase/.

# ---- Stage 1: ERP frontend SPA ----
FROM node:22-alpine AS fe-build

ARG VITE_API_BASE_URL=/api/v1
ARG NPM_REGISTRY=https://registry.npmjs.org/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry "$NPM_REGISTRY" \
    && npm ci

COPY frontend/ .
RUN npm run build

# ---- Stage 2: Portfolio Showcase ----
FROM node:22-alpine AS sc-build

ARG NPM_REGISTRY=https://registry.npmjs.org/

WORKDIR /app/showcase

COPY showcase/package.json showcase/package-lock.json* ./
RUN npm config set registry "$NPM_REGISTRY" \
    && (npm ci || npm install --no-audit --no-fund)

COPY showcase/ .
RUN npm run build

# ---- Stage 3: nginx runtime ----
FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# ERP admin SPA at /
COPY --from=fe-build /app/frontend/dist /usr/share/nginx/html

# Portfolio Showcase at /showcase/
COPY --from=sc-build /app/showcase/dist /usr/share/nginx/html/showcase

EXPOSE 80

# Full-stack health: /api/v1/health is proxied to the backend container.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
    CMD wget -q -O /dev/null http://127.0.0.1/api/v1/health || exit 1