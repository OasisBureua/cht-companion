#!/usr/bin/env bash
# Same pattern as cht-content-hub (alembic upgrade head) and
# cht-platform-tool (prisma migrate deploy): migrate then start the app.
# Only pending migrations run; already-applied files are skipped.
set -euo pipefail

cd /app

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "✗ DATABASE_URL is required for startup migrations"
  exit 1
fi

echo "→ Checking / applying pending KB migrations (python -m db.apply)"
max_attempts=12
attempt=1
until python -m db.apply; do
  if [[ "$attempt" -ge "$max_attempts" ]]; then
    echo "✗ Migrations failed after ${max_attempts} attempts"
    exit 1
  fi
  echo "… migration attempt ${attempt} failed, retrying in 10s (RDS may still be starting)"
  attempt=$((attempt + 1))
  sleep 10
done

PORT="${PORT:-8080}"
echo "→ Starting cht-companion on :${PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
