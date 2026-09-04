#!/bin/sh
# Manufacturing ERP Lite — backend container boot sequence
#
#   1. wait for MySQL (DB_HOST:DB_PORT) to accept TCP connections
#   2. alembic upgrade head            — schema, idempotent
#   3. python -m app.db.init_data      — RBAC bootstrap (roles/permissions/users), idempotent
#   4. python -m app.db.seed_demo      — deterministic demo business story (skip with DEMO_SEED=0)
#   5. exec uvicorn                    — hand over PID 1
#
# NOTE: seed_demo wipes & replays business data on every start on purpose —
# this image targets the local demo deployment (roadmap Phase 13). For a real
# deployment set DEMO_SEED=0 (init_data keeps running) and feed business data
# through the API.

set -eu

echo "[entrypoint] waiting for MySQL ${DB_HOST:-mysql}:${DB_PORT:-3306} ..."
python - <<'PY'
import os, socket, sys, time
host = os.getenv("DB_HOST", "mysql")
port = int(os.getenv("DB_PORT", "3306"))
deadline = time.time() + float(os.getenv("DB_WAIT_SECONDS", "120"))
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=3):
            sys.exit(0)
    except OSError:
        time.sleep(2)
print(f"MySQL {host}:{port} did not become reachable in time", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] applying migrations (alembic upgrade head)"
alembic upgrade head

echo "[entrypoint] seeding RBAC bootstrap data (init_data)"
python -m app.db.init_data

if [ "${DEMO_SEED:-1}" = "1" ]; then
    echo "[entrypoint] seeding demo business story (seed_demo)"
    python -m app.db.seed_demo
else
    echo "[entrypoint] DEMO_SEED=0 — skip demo business data"
fi

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
