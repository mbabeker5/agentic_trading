#!/usr/bin/env bash
#
# One copy of the trading database a night, and throw away the old ones.
#
# Run it by hand any time. It is safe: it only ever reads the live database and
# writes a new file beside it.
#
#   <root>/scripts/backup_db.sh
#
# On this machine today that is
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/backup_db.sh
#
# WHAT IT WRITES
#   <root>/data/backups/trading_YYYY-MM-DD.sqlite
#
# Copies from today are overwritten, so running it twice in one day leaves one
# file rather than two. Anything older than 30 days is deleted. One line goes
# into <root>/output/backup_db.log saying what happened, and the same line is
# printed.
#
# WHY sqlite3 .backup AND NOT cp
#
# The database runs in WAL mode, which means the newest writes may still be
# sitting in a separate trading.sqlite-wal file rather than in the database
# itself. A plain cp of trading.sqlite would quietly miss them, and worse, a cp
# taken while the loop was mid write would produce a file that looks fine and
# is actually torn. The .backup command uses SQLite's own online backup, which
# takes a consistent snapshot of a database that is being written to at the
# time. That is the whole reason this is a script rather than one cp.
#
# It talks to no network and no broker, and it never writes to the live
# database.

set -euo pipefail

# The one line every shell script in this project uses to find the project.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

DB="$PROJECT/data/trading.sqlite"
BACKUPS="$PROJECT/data/backups"
LOG_DIR="$PROJECT/output"
LOG="$LOG_DIR/backup_db.log"
KEEP_DAYS=30

TODAY="$(date +%Y-%m-%d)"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"
TARGET="$BACKUPS/trading_${TODAY}.sqlite"

mkdir -p "$BACKUPS" "$LOG_DIR"

say() {
  # One line, to the screen and to the log, so a launchd run leaves a trail.
  echo "$STAMP | $1" | tee -a "$LOG"
}

if [ ! -f "$DB" ]; then
  say "nothing to back up, there is no database at $DB"
  exit 0
fi

# The online backup. sqlite3 is on every Mac. If it is somehow missing, fall
# back to Python's own connection.backup, which does exactly the same job
# through the same SQLite library.
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$TARGET'"
else
  PYTHON="$PROJECT/venv312/bin/python"
  [ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
  "$PYTHON" - "$DB" "$TARGET" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
live = sqlite3.connect(source)
copy = sqlite3.connect(target)
try:
    live.backup(copy)
finally:
    copy.close()
    live.close()
PY
fi

# Prove the copy is readable before anything old is deleted. A backup nobody
# checked is a backup nobody has.
if command -v sqlite3 >/dev/null 2>&1; then
  if ! sqlite3 "$TARGET" "PRAGMA quick_check;" | grep -q '^ok$'; then
    say "THE BACKUP IS BROKEN and nothing old was deleted: $TARGET"
    exit 1
  fi
fi

# Opening the copy to check it leaves a -wal and a -shm beside it. They are
# empty, because a backup is made with everything already folded in, but they
# would sit in the backups folder for ever: the tidy up below only looks for
# files called trading_*.sqlite, so it would never remove them. Delete them
# here, where we know the copy is sound and closed.
rm -f "$TARGET-wal" "$TARGET-shm"

SIZE="$(du -h "$TARGET" | cut -f1 | tr -d ' ')"

# Throw away anything older than 30 days. -mtime +30 means "last changed more
# than 30 days ago", which is what we want, and the name pattern means nothing
# else in that folder can be caught by it.
DELETED=0
while IFS= read -r old; do
  rm -f "$old"
  DELETED=$((DELETED + 1))
done < <(find "$BACKUPS" -maxdepth 1 -name 'trading_*.sqlite' -type f -mtime "+$KEEP_DAYS")

KEPT="$(find "$BACKUPS" -maxdepth 1 -name 'trading_*.sqlite' -type f | wc -l | tr -d ' ')"

say "backed up to $TARGET ($SIZE), deleted $DELETED older than $KEEP_DAYS days, $KEPT kept"
