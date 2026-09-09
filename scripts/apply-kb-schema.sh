#!/usr/bin/env bash
# Optional local helper. Containers run pending migrations via docker-entrypoint.sh
# (same idea as contenthub `alembic upgrade head` / platform `prisma migrate deploy`).
#
# Usage:
#   ./scripts/apply-kb-schema.sh          # apply pending only
#   ./scripts/apply-kb-schema.sh --check  # list pending, do not apply
#   ./scripts/apply-kb-schema.sh --hello  # apply pending + hello-world smoke
# Requires DATABASE_URL.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
python -m db.apply "$@"
