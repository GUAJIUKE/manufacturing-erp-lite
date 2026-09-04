# syntax=docker/dockerfile:1
# Manufacturing ERP Lite — backend image (FastAPI + MySQL 8, Python 3.12)
#
# Single stage is sufficient: every pinned dependency (cryptography / bcrypt /
# pydantic-core / uvloop / httptools) publishes manylinux wheels for 3.12, so a
# slim image never needs a compiler. Entrypoint owns the boot sequence
# (wait-db -> alembic upgrade -> RBAC seed -> demo seed -> uvicorn), see
# docker-entrypoint.sh.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Dependencies first (layer cache friendly)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) Application code. tests/ is copied because app/db/seed_demo.py imports
#    tests/cleanup_helper.py to reset business data before replaying the demo
#    story (idempotent on every container start).
COPY alembic.ini ./
COPY alembic      ./alembic
COPY app          ./app
COPY tests        ./tests
COPY docker-entrypoint.sh ./

# 3) Non-root runtime user
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
