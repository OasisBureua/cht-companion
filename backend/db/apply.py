"""Apply pending SCRUM-196 KB migrations (alembic upgrade head / prisma migrate deploy style).

Usage:
  DATABASE_URL=... python -m db.apply
  DATABASE_URL=... python -m db.apply --hello
"""

from __future__ import annotations

import argparse
import json
import sys

from db import (
    apply_migrations,
    check_connectivity,
    hello_world,
    pending_migrations,
    schema_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending cht-companion KB schema migrations only"
    )
    parser.add_argument(
        "--hello",
        action="store_true",
        help="After migrations, upsert hello-world source/chunk and verify read",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print pending migrations and exit without applying",
    )
    args = parser.parse_args()

    try:
        print(json.dumps({"connectivity": check_connectivity()}, default=str))
        pending = pending_migrations()
        if args.check:
            print(json.dumps({"pending_migrations": pending, "schema": schema_status()}))
            return 0
        if not pending:
            print(
                json.dumps(
                    {
                        "applied_migrations": [],
                        "message": "no pending migrations (already up to date)",
                        "schema": schema_status(),
                    }
                )
            )
        else:
            applied = apply_migrations()
            print(
                json.dumps(
                    {
                        "applied_migrations": applied,
                        "message": f"applied {len(applied)} migration(s)",
                        "schema": schema_status(),
                    }
                )
            )
        if args.hello:
            print(json.dumps({"hello": hello_world()}, default=str))
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
