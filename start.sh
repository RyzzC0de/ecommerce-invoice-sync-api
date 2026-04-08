#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Container entrypoint
#   1. Wait for PostgreSQL to be reachable (belt-and-suspenders over depends_on)
#   2. Run Alembic migrations
#   3. Start Uvicorn
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── 1. Wait for database ──────────────────────────────────────────────────────
# depends_on: condition: service_healthy already handles this at the compose
# level, but we add a lightweight in-container wait as a safety net in case
# the container is started outside compose (e.g. Kubernetes, CI).

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
MAX_WAIT=60
WAITED=0

echo "[start.sh] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
until python -c "
import socket, sys
try:
    s = socket.create_connection(('${DB_HOST}', ${DB_PORT}), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "[start.sh] ERROR: PostgreSQL did not become reachable after ${MAX_WAIT}s. Aborting."
        exit 1
    fi
    echo "[start.sh] Database not ready yet — retrying in 2s... (${WAITED}s elapsed)"
    sleep 2
    WAITED=$((WAITED + 2))
done

echo "[start.sh] PostgreSQL is reachable."

# ── 2. Run Alembic migrations ─────────────────────────────────────────────────
echo "[start.sh] Applying database migrations..."
alembic upgrade head
echo "[start.sh] Migrations applied."

# ── 3. Start the application ──────────────────────────────────────────────────
echo "[start.sh] Starting Uvicorn..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    --no-access-log
