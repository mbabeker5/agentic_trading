#!/usr/bin/env python3
"""Build the trading database, or bring it up to date. Safe to run again.

WHAT IT DOES

Applies every file in data/migrations/ that has not been applied yet, in name
order, and writes each name into the schema_version table as it goes. A name
already in that table is skipped. So the first run builds the whole thing and
the second run does nothing and says so.

RUN IT

    <root>/venv312/bin/python <root>/scripts/migrate_db.py

which on this machine today is

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/migrate_db.py

The database it builds is <root>/data/trading.sqlite. Point it somewhere else
with --db, which is what the tests do.

    --dry-run   say what would be applied and touch nothing
    --db PATH   use this file instead of data/trading.sqlite

It talks to no network and no broker. It creates and edits one file on disk.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_AGENT = _ROOT / "agent"
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import db as database  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or update the SQLite system of record. "
                    "Running it twice is safe and does nothing the second time.")
    parser.add_argument("--db", default=None,
                        help="the database file, instead of data/trading.sqlite")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be applied and change nothing")
    args = parser.parse_args(argv)

    target = Path(args.db) if args.db else database.db_path()
    folder = database.migrations_dir()
    files = sorted(p.name for p in folder.glob("*.sql") if p.is_file())

    print(f"database:   {target}")
    print(f"migrations: {folder}")
    if not files:
        print("Nothing to apply: that folder holds no .sql files.", file=sys.stderr)
        return 1

    if args.dry_run:
        existed = target.exists()
        if existed:
            conn = database.connect(target)
            try:
                done = database._applied(conn)
            finally:
                conn.close()
        else:
            done = set()
        pending = [name for name in files if name not in done]
        print(f"exists:     {existed}")
        for name in files:
            print(f"  {'already applied' if name in done else 'WOULD APPLY  '}  {name}")
        print(f"\nDRY RUN, nothing was written. {len(pending)} to apply.")
        return 0

    try:
        applied = database.migrate(target)
    except database.DatabaseError as exc:
        print(f"Migration failed, nothing was left half done: {exc}", file=sys.stderr)
        return 1

    if applied:
        for name in applied:
            print(f"  applied  {name}")
    else:
        print("  nothing to do, the database is already up to date")

    conn = database.connect(target)
    try:
        tables = database.counts(conn)
    finally:
        conn.close()
    print(f"\n{len(tables)} tables, {sum(tables.values())} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
