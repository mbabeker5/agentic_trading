"""The system of record: one SQLite file that every part of the agent writes to.

WHERE IT LIVES

    <project root>/data/trading.sqlite

which on this machine today is

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/data/trading.sqlite

The path is worked out by agent/paths.py, so a clone anywhere finds its own
database and nothing has to be edited on a new Mac. The whole of data/ is
gitignored apart from the schema and the migrations, because a database is
state, not source.

WHY THERE IS A DATABASE AT ALL

Until now the day was scattered: state files in output/, a shortlist JSON, a
pdt JSON per book, a watchdog JSON, a text log for alerts, and a Google Sheet
holding the score. Every one of those is a different shape, none of them can be
asked a question, and the Sheet is over a network connection that is allowed to
fail. So the Sheet cannot be the truth.

From here the database is the truth, and the Sheet is a view of it that gets
rewritten once a night by ledger/sync_sheet.py. If the wifi is off, nothing is
lost. If the Sheet is deleted, it can be rebuilt.

HOW IT IS SET UP FOR TWO WRITERS AT ONCE

The loop and the watchdog both run on a schedule and will sometimes overlap, so
connect() turns on three things every single time:

    journal_mode = WAL     A reader never blocks a writer and a writer never
                           blocks a reader. Without this the watchdog waking up
                           mid tick could make the loop wait, or fail.
    busy_timeout = 5000    Five seconds. If the other process is mid write, wait
                           for it rather than raising "database is locked"
                           straight away. Every write in here is milliseconds,
                           so five seconds is an eternity and a timeout means
                           something is genuinely wrong.
    foreign_keys = ON      SQLite has foreign keys switched OFF by default, per
                           connection. A fill pointing at an order that does not
                           exist is a bug worth hearing about at once.

TWO RULES FOR EVERY HELPER IN HERE

1. One short transaction each, opened and closed inside the call. Nothing holds
   a connection open, and nothing holds one across a network call. A connection
   left open while waiting on IBKR or on Google is a lock held for seconds,
   which is exactly how two processes deadlock.
2. It never raises for the ordinary reasons. A write that fails complains to
   stderr and returns None. Recording what happened must never be the thing
   that stops the loop, because the loop is what holds the risk limits. A
   caller that genuinely needs to know can check for None.

Programmer error is different: passing a dictionary where a number belongs will
still raise, because that is a bug to fix rather than a condition to survive.

FIRST TIME SETUP

    <root>/venv312/bin/python <root>/scripts/migrate_db.py

Safe to run again as many times as you like. It applies anything in
data/migrations/ that has not been applied yet and nothing else.

A LOOK AT WHAT IS IN THERE, WITHOUT WRITING ANYTHING

    <root>/venv312/bin/python <root>/agent/db.py

Nothing in this file touches the network or the broker. It is a file on disk.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo

_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from paths import data_dir, project_root  # noqa: E402

#: Every time in this project is New York time. The strategies are written in
#: it, the market keeps it, and the Google Sheet displays it, so the database
#: stores it and no conversion is needed anywhere.
NEW_YORK = ZoneInfo("America/New_York")

#: The filename under data/. One database, not one per book: five books share
#: one account and most questions worth asking cross book boundaries.
DB_NAME = "trading.sqlite"

#: How long a write waits for the other process before giving up, in seconds.
BUSY_TIMEOUT_S = 5.0

#: The json columns, per table, so a helper can turn a dict into text without
#: every caller remembering which ones need it.
_JSON_COLUMNS = {
    "scans": ("stage_counts", "diagnostics"),
    "shortlist_entries": ("tags", "reasons"),
    "alerts": ("channels",),
    "preflight_results": ("detail",),
    "regime_flags": ("evidence",),
}


class DatabaseError(RuntimeError):
    """Raised only by migrate(), which is a setup step and should fail loudly."""


def _warn(message: str) -> None:
    print(f"db: {message}", file=sys.stderr)


# ------------------------------------------------------------------ where and when

def db_path() -> Path:
    """The database file itself. Created on first connect, not here."""
    return data_dir() / DB_NAME


def migrations_dir() -> Path:
    """data/migrations/, the .sql files applied in name order."""
    return project_root() / "data" / "migrations"


def backups_dir(create: bool = True) -> Path:
    """data/backups/, where scripts/backup_db.sh drops the nightly copy."""
    path = data_dir() / "backups"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def now_et() -> str:
    """Right now, New York, as "YYYY-MM-DD HH:MM:SS"."""
    return datetime.now(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S")


def as_ts(value: Any = None) -> str:
    """Any sensible timestamp turned into the one text shape the database uses.

    A datetime with a timezone is converted to New York. A datetime without one
    is assumed to already be New York, because everything in this project is.
    A string is trimmed and passed through, so an ISO string with a "T" and an
    offset is tidied into the same shape rather than stored two ways. None
    means now.
    """
    if value is None:
        return now_et()
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=NEW_YORK)
        return moment.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date_type):
        return f"{value:%Y-%m-%d} 00:00:00"
    text = str(value).strip()
    if not text:
        return now_et()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    return as_ts(parsed)


def as_date(value: Any = None) -> str:
    """Any sensible date turned into "YYYY-MM-DD", New York."""
    if value is None:
        return datetime.now(NEW_YORK).strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return as_ts(value)[:10]
    if isinstance(value, date_type):
        return f"{value:%Y-%m-%d}"
    return str(value).strip()[:10]


def _flag(value: Any) -> int:
    """A truthy thing as the 0 or 1 SQLite stores, because it has no boolean."""
    return 1 if value else 0


def _json(value: Any) -> str | None:
    """A dict or list on its way into a json column. None stays None.

    A string is assumed to be JSON already and passed through, so a caller that
    has serialised it itself is not double encoded. Anything that will not
    serialise is stored as its repr rather than lost, because a diagnostic that
    cannot be written down is worse than an ugly one.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, sort_keys=False)
    except (TypeError, ValueError):
        return json.dumps({"unserialisable": repr(value)})


def _loads(value: Any) -> Any:
    """A json column on its way back out. Bad text comes back as itself."""
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


# ------------------------------------------------------------------ connecting

def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """A connection set up the way every writer in this project needs it.

    Caller closes it. Almost nothing should call this directly: the helpers
    below open and close their own, which is the point. Use it in a test, in a
    one off query, or when writing many rows in one transaction.
    """
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_S,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL is a property of the file and survives, but setting it every time
    # costs nothing and means a database restored from a backup is right too.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    # Full sync is the default and is what we want: this is money, and the
    # write rate is a handful of rows a minute, so durability is free.
    conn.execute("PRAGMA synchronous=FULL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    """One short transaction, committed on the way out and rolled back on error.

    Pass an existing connection and it joins that caller's transaction instead
    of opening its own, which is how record_scan writes a scan and its
    shortlist rows as one all or nothing change.
    """
    if conn is not None:
        yield conn
        return
    own = connect()
    try:
        own.execute("BEGIN IMMEDIATE")
        yield own
        own.execute("COMMIT")
    except BaseException:
        try:
            own.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        own.close()


def _insert(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> int:
    """One row in, its new id out. Columns come from the keys, in order."""
    kept = {name: value for name, value in values.items() if value is not None}
    if not kept:
        raise ValueError(f"nothing to insert into {table}")
    columns = ", ".join(kept)
    holes = ", ".join("?" for _ in kept)
    cursor = conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({holes})",
                          tuple(kept.values()))
    return int(cursor.lastrowid)


def _upsert(conn: sqlite3.Connection, table: str, keys: Mapping[str, Any],
            values: Mapping[str, Any]) -> int:
    """Add the row, or update the one already there for these keys.

    Only the values actually supplied are written, so calling this at 09:30
    with the starting equity and again at 16:00 with the closing figures fills
    in both and blanks neither.
    """
    supplied = {name: value for name, value in values.items() if value is not None}
    row = {**keys, **supplied}
    columns = ", ".join(row)
    holes = ", ".join("?" for _ in row)
    conflict = ", ".join(keys)
    if supplied:
        updates = ", ".join(f"{name}=excluded.{name}" for name in supplied)
        tail = f"DO UPDATE SET {updates}"
    else:
        tail = "DO NOTHING"
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({holes}) "
        f"ON CONFLICT ({conflict}) {tail}",
        tuple(row.values()))
    where = " AND ".join(f"{name}=?" for name in keys)
    found = conn.execute(f"SELECT id FROM {table} WHERE {where}",
                         tuple(keys.values())).fetchone()
    return int(found["id"]) if found else 0


@contextmanager
def _guarded(what: str) -> Iterator[list]:
    """Run a write, and on a database problem complain rather than explode.

    The box it yields is where the result goes, so the caller can hand back
    None when something went wrong. Only sqlite3 errors and disk errors are
    caught. A TypeError from passing the wrong sort of thing is a bug in the
    caller and is left to surface.
    """
    box: list = []
    try:
        yield box
    except (sqlite3.Error, OSError) as exc:
        _warn(f"could not record {what}, the run carries on: {exc!r}")
        box.clear()


# ------------------------------------------------------------------ migrations

#: The runner's own bookkeeping table, created before any migration runs.
#: 0001_initial.sql creates it too, with IF NOT EXISTS, so that data/schema.sql
#: is a complete picture of the database. Creating it here as well means a
#: migration folder that does not happen to define it still works.
_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    filename    TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
)"""


def _applied(conn: sqlite3.Connection) -> set[str]:
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return set()
    return {row["filename"] for row in conn.execute("SELECT filename FROM schema_version")}


def migrate(path: str | Path | None = None,
            folder: str | Path | None = None) -> list[str]:
    """Bring the database up to date. Returns the migration files it ran.

    Idempotent by design: each file's name is written into schema_version once
    it has run, and a name already in there is skipped. So the second run
    returns an empty list and changes nothing.

    Each file runs inside its own transaction together with the row that
    records it, so a migration that fails halfway leaves nothing behind and can
    simply be fixed and run again.

    This one does raise, on purpose. It is a setup step run by hand or by the
    installer, and a database that is not the right shape is not something to
    carry on past.
    """
    folder = Path(folder) if folder is not None else migrations_dir()
    files = sorted(p for p in folder.glob("*.sql") if p.is_file())
    if not files:
        raise DatabaseError(f"no migrations found in {folder}")

    conn = connect(path)
    ran: list[str] = []
    try:
        conn.execute(_VERSION_TABLE)
        done = _applied(conn)
        for file in files:
            if file.name in done:
                continue
            # The BEGIN and COMMIT have to be inside the script text rather
            # than executed around it. Python's executescript() commits any
            # transaction that is already open before it starts, so a BEGIN
            # issued beforehand is thrown away and the COMMIT afterwards then
            # fails with "no transaction is active". Written this way the whole
            # migration and the row that records it are one change: either both
            # land or neither does, so a migration that dies halfway can simply
            # be fixed and run again.
            sql = file.read_text(encoding="utf-8")
            stamp = now_et().replace("'", "''")
            name = file.name.replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                f"{sql}\n"
                "INSERT OR REPLACE INTO schema_version (filename, applied_at) "
                f"VALUES ('{name}', '{stamp}');\n"
                "COMMIT;\n")
            try:
                conn.executescript(script)
            except sqlite3.Error as exc:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise DatabaseError(f"migration {file.name} failed: {exc}") from exc
            ran.append(file.name)
    finally:
        conn.close()
    return ran


# ------------------------------------------------------------------ ticks

def record_tick(ts: Any = None, book_id: str | None = None, phase: str | None = None,
                mode: str | None = None, rules_commit: str | None = None,
                duration_ms: int | None = None, outcome: str | None = None,
                notes: str | None = None,
                conn: sqlite3.Connection | None = None) -> int | None:
    """One wake up of the loop, for one book. Returns the row id.

    Write one of these every tick even when nothing happened, because the gaps
    are the point: a tick with no row is a tick that never ran, and that is the
    only place "missed ticks" can be counted from.

    phase is one of the loop's own words: idle, sweep, scan, pick, manage,
    flatten, closed. mode is the book's: dry_run, tiny or full.
    """
    with _guarded("a tick") as box:
        with transaction(conn) as db:
            box.append(_insert(db, "ticks", {
                "ts": as_ts(ts), "book_id": book_id, "phase": phase, "mode": mode,
                "rules_commit": rules_commit, "duration_ms": duration_ms,
                "outcome": outcome, "notes": notes}))
    return box[0] if box else None


# ------------------------------------------------------------------ scans

def record_scan(ts: Any = None, source: str | None = None,
                scan_codes: Any = None, stage_counts: Any = None,
                diagnostics: Any = None, market_data_type: Any = None,
                entries: Iterable[Mapping[str, Any]] | None = None,
                conn: sqlite3.Connection | None = None) -> int | None:
    """One run of a scanner and the names it produced, in one transaction.

    Either the whole thing lands or none of it does, so there is never a scan
    row in the database with its shortlist missing.

    scan_codes may be a list, in which case it is stored as a comma separated
    string, which is what a person wants to read in that column.

    Each entry is a dict. The keys it looks for are the ones the scanner
    already writes: symbol, direction (or side), score, rel_volume,
    avg_dollar_volume (or dollar_volume), flagged_by (or tags), reasons. The
    rank is the position in the list unless the entry says otherwise. Anything
    else in the dict is ignored rather than refused, so a scanner that grows a
    new field does not break this.
    """
    if isinstance(scan_codes, (list, tuple, set)):
        scan_codes = ", ".join(str(code) for code in scan_codes)
    with _guarded("a scan") as box:
        with transaction(conn) as db:
            scan_id = _insert(db, "scans", {
                "ts": as_ts(ts), "source": source, "scan_codes": scan_codes,
                "stage_counts": _json(stage_counts), "diagnostics": _json(diagnostics),
                "market_data_type": (None if market_data_type is None
                                     else str(market_data_type))})
            for position, entry in enumerate(entries or [], start=1):
                symbol = str(entry.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                _insert(db, "shortlist_entries", {
                    "scan_id": scan_id,
                    "rank": entry.get("rank", entry.get("scan_rank", position)),
                    "symbol": symbol,
                    "direction": entry.get("direction") or entry.get("side"),
                    "score": entry.get("score"),
                    "rel_volume": entry.get("rel_volume"),
                    "dollar_volume": (entry.get("dollar_volume")
                                      if entry.get("dollar_volume") is not None
                                      else entry.get("avg_dollar_volume")),
                    "tags": _json(entry.get("tags") or entry.get("flagged_by")),
                    "reasons": _json(entry.get("reasons")),
                    "traded": _flag(entry.get("traded"))})
            box.append(scan_id)
    return box[0] if box else None


def mark_shortlist_traded(scan_id: int, symbol: str,
                          conn: sqlite3.Connection | None = None) -> bool:
    """Say that a name off this scan was actually bought.

    Separate from record_scan because it is known later, once an order has been
    sent, and the answer to "did the shortlist find anything we used" is only
    worth having if it is filled in honestly rather than guessed at write time.
    """
    with _guarded("a traded shortlist entry") as box:
        with transaction(conn) as db:
            db.execute("UPDATE shortlist_entries SET traded=1 "
                       "WHERE scan_id=? AND symbol=?",
                       (int(scan_id), str(symbol).strip().upper()))
            box.append(True)
    return bool(box)


# ------------------------------------------------------------------ decisions

def record_decision(ts: Any = None, book_id: str | None = None,
                    shape: str | None = None, model: str | None = None,
                    prompt_hash: str | None = None, packet_hash: str | None = None,
                    rules_commit: str | None = None, symbol: str | None = None,
                    action: str | None = None, side: str | None = None,
                    entry: float | None = None, stop: float | None = None,
                    target: float | None = None, qty: int | None = None,
                    confidence: float | None = None, rationale: str | None = None,
                    latency_ms: int | None = None, tokens_in: int | None = None,
                    tokens_out: int | None = None, cost_usd: float | None = None,
                    rejected: Any = False, reject_reason: str | None = None,
                    conn: sqlite3.Connection | None = None) -> int | None:
    """One judgement call about one symbol. Returns the row id.

    Every choice gets a row, including every skip and every "do nothing". That
    is the strategy's own rule and it is what makes a month readable
    afterwards: the interesting question at the end is usually why a name was
    passed over, not why one was bought.

    rejected marks a call that was made and then refused, by a guardrail or by
    the parser. Put the guardrail's own id in reject_reason, for example
    max_open_positions, because that string becomes the Rule column on the
    ledger's Rules Log and is what the month end count of "which limit actually
    bit" is built from.
    """
    with _guarded("a decision") as box:
        with transaction(conn) as db:
            box.append(_insert(db, "decisions", {
                "ts": as_ts(ts), "book_id": book_id, "shape": shape, "model": model,
                "prompt_hash": prompt_hash, "packet_hash": packet_hash,
                "rules_commit": rules_commit,
                "symbol": (symbol or "").strip().upper() or None,
                "action": action, "side": side, "entry": entry, "stop": stop,
                "target": target, "qty": qty, "confidence": confidence,
                "rationale": rationale, "latency_ms": latency_ms,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": cost_usd, "rejected": _flag(rejected),
                "reject_reason": reject_reason}))
    return box[0] if box else None


def record_decision_result(result: Any, ts: Any = None,
                           rules_commit: str | None = None,
                           packet_hash: str | None = None,
                           conn: sqlite3.Connection | None = None) -> list[int]:
    """A whole DecisionResult from agent/decide.py, exploded into rows.

    One model call answers about several names at once: some picks, some skips,
    maybe some exits, maybe some rejections. The decisions table is one row per
    name, so this writes one row each and returns their ids in that order.

    WHAT HAPPENS TO THE COST, and why it matters. One call has one price, but
    it becomes several rows here. Writing the cost on every row would multiply
    the month's model spend by however many names the model happened to mention,
    which would make the whole cost comparison meaningless. So the cost, the
    token counts and the latency go on the FIRST row only, and the rest carry
    NULL. Summing the column then gives the true spend.

    A call that produced nothing at all still gets one row, with action
    "no_action", because a tick where the model was asked and said nothing is
    not the same as a tick where it was never asked.
    """
    ts = as_ts(ts)
    picks = list(getattr(result, "picks", []) or [])
    skips = list(getattr(result, "skips", []) or [])
    exits = list(getattr(result, "exits", []) or [])
    rejections = list(getattr(result, "rejections", []) or [])
    response = getattr(result, "model_response", None) or {}
    seconds = response.get("latency_s")
    if seconds is None:
        seconds = response.get("elapsed_s")
    latency_ms = None if seconds is None else int(round(float(seconds) * 1000))

    shared = {
        "ts": ts,
        "book_id": getattr(result, "book_id", None),
        "shape": getattr(result, "shape", None) or None,
        "model": getattr(result, "model", None) or None,
        "prompt_hash": getattr(result, "prompt_hash", None) or None,
        "packet_hash": packet_hash,
        "rules_commit": rules_commit,
    }

    rows: list[dict] = []
    for pick in picks:
        rows.append({**shared, "symbol": pick.get("symbol"), "action": "pick",
                     "side": pick.get("side"), "entry": pick.get("entry"),
                     "stop": pick.get("stop"), "target": pick.get("target"),
                     "qty": pick.get("qty_hint"), "confidence": pick.get("confidence"),
                     "rationale": pick.get("rationale")})
    for skip in skips:
        rows.append({**shared, "symbol": skip.get("symbol"), "action": "skip",
                     "rationale": skip.get("rationale")})
    for leave in exits:
        rows.append({**shared, "symbol": leave.get("symbol"),
                     "action": leave.get("action") or "exit",
                     "confidence": leave.get("confidence"),
                     "rationale": leave.get("rationale")})
    for refusal in rejections:
        rows.append({**shared, "symbol": refusal.get("symbol"), "action": "rejected",
                     "rejected": True,
                     "reject_reason": refusal.get("reason") or refusal.get("rationale"),
                     "rationale": refusal.get("reason") or refusal.get("rationale")})
    if not rows:
        note = "; ".join(str(n) for n in (getattr(result, "notes", None) or []))
        error = getattr(result, "error", None)
        rows.append({**shared, "action": "no_action",
                     "rationale": note or error or "nothing to do",
                     "rejected": bool(error),
                     "reject_reason": error})

    rows[0].update({"latency_ms": latency_ms,
                    "tokens_in": getattr(result, "tokens_in", None) or None,
                    "tokens_out": getattr(result, "tokens_out", None) or None,
                    "cost_usd": getattr(result, "cost_usd", None)})

    written: list[int] = []
    with _guarded("a decision result"):
        with transaction(conn) as db:
            for row in rows:
                new_id = record_decision(conn=db, **row)
                if new_id is not None:
                    written.append(new_id)
    return written


# ------------------------------------------------------------------ orders

def record_order(ts: Any = None, book_id: str | None = None,
                 order_ref: str | None = None, broker_order_id: Any = None,
                 parent_order_id: Any = None, oca_group: str | None = None,
                 symbol: str | None = None, side: str | None = None,
                 qty: int | None = None, order_type: str | None = None,
                 limit_price: float | None = None, stop_price: float | None = None,
                 tif: str | None = None, purpose: str | None = None,
                 status: str | None = None, decision_id: int | None = None,
                 conn: sqlite3.Connection | None = None) -> int | None:
    """One order sent, or that would have been sent in dry run. Returns its id.

    Write the row in dry run too. A month of "the orders we would have sent" is
    the whole of what a dry run is for, and it is worthless if it only lives in
    a log file.

    purpose is entry, stop or target. parent_order_id and oca_group are what
    hold a bracket together, so a stop and a target that cancel each other can
    be seen to be the pair they are.
    """
    with _guarded("an order") as box:
        with transaction(conn) as db:
            box.append(_insert(db, "orders", {
                "ts": as_ts(ts), "book_id": book_id, "order_ref": order_ref,
                "broker_order_id": (None if broker_order_id is None
                                    else str(broker_order_id)),
                "parent_order_id": (None if parent_order_id is None
                                    else str(parent_order_id)),
                "oca_group": oca_group,
                "symbol": (symbol or "").strip().upper() or None,
                "side": side, "qty": qty, "order_type": order_type,
                "limit_price": limit_price, "stop_price": stop_price, "tif": tif,
                "purpose": purpose, "status": status, "decision_id": decision_id}))
    return box[0] if box else None


def update_order_status(order_id: int, status: str,
                        broker_order_id: Any = None,
                        oca_group: str | None = None,
                        conn: sqlite3.Connection | None = None) -> bool:
    """Move an order on: submitted, filled, cancelled, rejected.

    An order table that can only ever say "sent" is not worth having, so this
    is the one update helper in the file. broker_order_id and oca_group are here
    too because both are the broker's own names for the order and neither exists
    until it answers. Since 2026-09-06 the loop writes the order row BEFORE it
    sends, so that the row can carry the decision that caused it, and these two
    are written in from the answer a moment later.

    A field left out is left alone rather than blanked, so moving an order from
    submitted to filled cannot lose the ids written when it was sent.
    """
    columns = ["status=?"]
    values: list[Any] = [str(status)]
    if broker_order_id is not None:
        columns.append("broker_order_id=?")
        values.append(str(broker_order_id))
    if oca_group is not None:
        columns.append("oca_group=?")
        values.append(str(oca_group))
    with _guarded("an order status") as box:
        with transaction(conn) as db:
            db.execute(f"UPDATE orders SET {', '.join(columns)} WHERE id=?",
                       (*values, int(order_id)))
            box.append(True)
    return bool(box)


# ------------------------------------------------------------------ fills

def slippage(side: Any, qty: Any, price: Any, decision_price: Any) -> tuple[Any, Any]:
    """The gap between the price we decided at and the price we got.

    Deliberately the same arithmetic as columns U and V of the Google Sheet, so
    the database and the sheet can never disagree about a number Mo is going to
    read off both:

      BUY   fill price minus decision price, times the quantity
      SELL  decision price minus fill price, times the quantity

    Either way a positive figure means money lost to the gap, which is what
    makes the column addable across a month of longs and shorts. The basis
    points figure is that same gap as a share of what the trade was worth at
    the decision price, so a five dollar slip on a thousand dollar trade and a
    fifty dollar slip on a ten thousand dollar trade both read as 50.

    Both come back as None whenever anything needed is missing, which is the
    honest answer rather than a zero that would drag the month's average down.
    """
    try:
        shares = abs(float(qty))
        got = float(price)
        decided = float(decision_price)
    except (TypeError, ValueError):
        return None, None
    direction = str(side or "").strip().upper()
    if direction.startswith("B"):
        usd = (got - decided) * shares
    elif direction.startswith("S"):
        usd = (decided - got) * shares
    else:
        return None, None
    if decided == 0 or shares == 0:
        return round(usd, 4), None
    return round(usd, 4), round(usd / (decided * shares) * 10000.0, 4)


def record_fill(ts: Any = None, order_id: int | None = None,
                exec_id: str | None = None, symbol: str | None = None,
                side: str | None = None, qty: int | None = None,
                price: float | None = None, commission: float | None = None,
                decision_price: float | None = None,
                slippage_usd: float | None = None, slippage_bps: float | None = None,
                conn: sqlite3.Connection | None = None) -> int | None:
    """One execution. Returns its row id, or the id of the one already stored.

    exec_id is IBKR's own id for the execution and is unique in the table, so
    reading the day's executions again after a restart cannot count the same
    fill twice. A repeat is not an error: the existing id comes back and
    nothing is written.

    Leave slippage_usd and slippage_bps out and they are worked out from
    decision_price by the same sums the sheet uses. Pass them and yours win.
    """
    if slippage_usd is None and slippage_bps is None and decision_price is not None:
        slippage_usd, slippage_bps = slippage(side, qty, price, decision_price)
    with _guarded("a fill") as box:
        with transaction(conn) as db:
            seen = None
            if exec_id:
                seen = db.execute("SELECT id FROM fills WHERE exec_id=?",
                                  (str(exec_id),)).fetchone()
            if seen is not None:
                box.append(int(seen["id"]))
                return box[0]
            box.append(_insert(db, "fills", {
                "ts": as_ts(ts), "order_id": order_id,
                "exec_id": (str(exec_id) if exec_id else None),
                "symbol": (symbol or "").strip().upper() or None,
                "side": side, "qty": qty, "price": price, "commission": commission,
                "decision_price": decision_price, "slippage_usd": slippage_usd,
                "slippage_bps": slippage_bps}))
    return box[0] if box else None


# ------------------------------------------------------------------ positions

def snapshot_positions(positions: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
                       ts: Any = None, book_id: str | None = None,
                       conn: sqlite3.Connection | None = None) -> int | None:
    """What one book was holding at one moment. Returns how many rows went in.

    Takes either a list of dicts or the {SYMBOL: {...}} shape that
    agent/book_state.py keeps, so a caller can hand over state.positions as it
    stands. All the rows share one timestamp, so "what did book C hold at
    10:15" is one query with no window to get wrong.

    An empty holding writes nothing and returns 0. That is correct: the
    snapshot for a flat book is the absence of rows, and the tick row is what
    proves the loop was awake at the time.
    """
    if isinstance(positions, Mapping):
        rows = []
        for symbol, body in positions.items():
            if isinstance(body, Mapping):
                rows.append({"symbol": symbol, **body})
            else:
                rows.append({"symbol": symbol, "qty": body})
    else:
        rows = [dict(row) for row in positions]

    stamp = as_ts(ts)
    with _guarded("a position snapshot") as box:
        written = 0
        with transaction(conn) as db:
            for row in rows:
                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                price = row.get("market_price")
                if price is None:
                    price = row.get("last_close")
                _insert(db, "position_snapshots", {
                    "ts": stamp, "book_id": book_id or row.get("book_id"),
                    "symbol": symbol, "qty": row.get("qty"),
                    "avg_cost": row.get("avg_cost"), "market_price": price,
                    "market_value": row.get("market_value"),
                    "unrealized_pnl": row.get("unrealized_pnl"),
                    "stop": row.get("stop"), "target": row.get("target")})
                written += 1
        box.append(written)
    return box[0] if box else None


# ------------------------------------------------------------------ alerts

def record_alert(level: str | None = None, title: str | None = None,
                 body: str | None = None, channels: Any = None,
                 ts: Any = None, conn: sqlite3.Connection | None = None) -> int | None:
    """One alert raised, and where it actually went.

    channels is the list agent/alerts.py returns: the channels that delivered,
    from imessage, slack, macos and log. An empty list is worth writing down,
    because "we tried to shout and nothing got through" is exactly the thing
    nobody finds out about otherwise.
    """
    with _guarded("an alert") as box:
        with transaction(conn) as db:
            box.append(_insert(db, "alerts", {
                "ts": as_ts(ts),
                "level": (str(level).strip().upper() if level else None),
                "title": title, "body": body, "channels": _json(channels)}))
    return box[0] if box else None


# ------------------------------------------------------------------ pre-flight

def record_preflight(check_name: str, passed: Any = None, detail: Any = None,
                     verdict: str | None = None, date: Any = None,
                     ts: Any = None,
                     conn: sqlite3.Connection | None = None) -> int | None:
    """One morning check. One row per check per day, updated if it runs again.

    verdict is the run's own word for the day as a whole, pass or fail, and it
    is stored on every check of that run so a single query answers "was the day
    allowed to trade" without joining anything.
    """
    with _guarded("a pre-flight result") as box:
        with transaction(conn) as db:
            box.append(_upsert(db, "preflight_results",
                               {"date": as_date(date), "check_name": str(check_name)},
                               {"ts": as_ts(ts),
                                "passed": (None if passed is None else _flag(passed)),
                                "detail": _json(detail), "verdict": verdict}))
    return box[0] if box else None


# ------------------------------------------------------------------ watchdog

def record_watchdog(check_name: str, ok: Any = None, detail: str | None = None,
                    action_taken: str | None = None, ts: Any = None,
                    conn: sqlite3.Connection | None = None) -> int | None:
    """One watchdog look at one thing. Every look, not just the latest.

    Unlike the pre-flight these pile up all day on purpose. The question worth
    asking of the watchdog is almost always "when did this start failing", and
    that needs the whole run of checks, not the most recent verdict.
    """
    with _guarded("a watchdog check") as box:
        with transaction(conn) as db:
            box.append(_insert(db, "watchdog_checks", {
                "ts": as_ts(ts), "check_name": str(check_name),
                "ok": (None if ok is None else _flag(ok)),
                "detail": detail, "action_taken": action_taken}))
    return box[0] if box else None


# ------------------------------------------------------------------ day trades

def record_day_trade_counter(book_id: str, count_5d: int | None = None,
                             regime: Any = None, blocked: Any = False,
                             date: Any = None, ts: Any = None,
                             conn: sqlite3.Connection | None = None) -> int | None:
    """Where a book stands against the pattern day trader limit today.

    One row per book per day, updated in place. count_5d is the day trades used
    in the rolling five business days, and regime is which rule set was in
    force, old_pdt or new_imd or unknown.

    blocked=True adds one to would_have_blocked rather than setting it, because
    a caller checking the rule knows only about the trade in front of it, not
    about the day's running total. That count is the figure that says whether
    the limit is actually costing this experiment anything.
    """
    with _guarded("a day trade counter") as box:
        with transaction(conn) as db:
            row_id = _upsert(db, "day_trade_counters",
                             {"date": as_date(date), "book_id": str(book_id)},
                             {"count_5d": count_5d, "ts": as_ts(ts),
                              "regime": (None if regime is None else str(regime))})
            if blocked and row_id:
                db.execute("UPDATE day_trade_counters "
                           "SET would_have_blocked = would_have_blocked + 1 "
                           "WHERE id=?", (row_id,))
            box.append(row_id)
    return box[0] if box else None


def record_regime(account_id: str, regime: Any = None, evidence: Any = None,
                  date: Any = None, ts: Any = None,
                  conn: sqlite3.Connection | None = None) -> int | None:
    """Which margin regime the account was in today, and what said so.

    One row per account per day. evidence is the reading's own as_dict(), so
    the tags IBKR actually returned are on the record and a regime that flips
    unexpectedly can be argued with rather than just believed.
    """
    with _guarded("a regime flag") as box:
        with transaction(conn) as db:
            box.append(_upsert(db, "regime_flags",
                               {"date": as_date(date), "account_id": str(account_id)},
                               {"regime": (None if regime is None else str(regime)),
                                "evidence": _json(evidence), "ts": as_ts(ts)}))
    return box[0] if box else None


# ------------------------------------------------------------------ daily summary

def upsert_daily_summary(date: Any, book_id: str, start_equity: float | None = None,
                         end_equity: float | None = None, pnl_usd: float | None = None,
                         pnl_pct: float | None = None, spy_close: float | None = None,
                         trades: int | None = None, commissions: float | None = None,
                         model_cost_usd: float | None = None,
                         rule_triggers: int | None = None,
                         missed_ticks: int | None = None,
                         max_drawdown_pct: float | None = None,
                         notes: str | None = None,
                         conn: sqlite3.Connection | None = None) -> int | None:
    """One book's scoreboard for one day, added or updated in place.

    Call it at the open with the starting equity and again at the close with
    the rest; leaving an argument out leaves that column alone rather than
    blanking it.

    pnl_usd and pnl_pct are worked out from the two equity figures when both
    are known and neither was passed in, because two numbers that are meant to
    agree should be worked out in one place rather than in every caller.

    This is the table the Google Sheet's Daily and Books tabs are both built
    from, and the only place each book gets its own equity curve. The sheet
    cannot do that: its Daily tab follows the one paper account all five books
    share.
    """
    keys = {"date": as_date(date), "book_id": str(book_id)}
    with _guarded("a daily summary") as box:
        with transaction(conn) as db:
            row_id = _upsert(db, "daily_book_summaries", keys,
                             {"start_equity": start_equity, "end_equity": end_equity,
                              "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                              "spy_close": spy_close, "trades": trades,
                              "commissions": commissions,
                              "model_cost_usd": model_cost_usd,
                              "rule_triggers": rule_triggers,
                              "missed_ticks": missed_ticks,
                              "max_drawdown_pct": max_drawdown_pct,
                              "notes": notes, "updated_at": now_et()})
            # The profit is worked out from whatever is in the row NOW, not from
            # what this one call happened to carry. The usual pattern is the
            # starting equity at the open and the closing equity seven hours
            # later, so at neither moment does one call hold both numbers.
            # Doing it here, after the write and inside the same transaction,
            # is what makes the split call work.
            if row_id and (pnl_usd is None or pnl_pct is None):
                stored = db.execute(
                    "SELECT start_equity, end_equity FROM daily_book_summaries "
                    "WHERE id=?", (row_id,)).fetchone()
                opened, closed = stored["start_equity"], stored["end_equity"]
                if opened is not None and closed is not None:
                    if pnl_usd is None:
                        db.execute("UPDATE daily_book_summaries SET pnl_usd=? "
                                   "WHERE id=?", (round(closed - opened, 2), row_id))
                    if pnl_pct is None and opened:
                        db.execute("UPDATE daily_book_summaries SET pnl_pct=? "
                                   "WHERE id=?", (round(closed / opened - 1.0, 6), row_id))
            box.append(row_id)
    return box[0] if box else None


# ------------------------------------------------------------------ reading back

def _rows(sql: str, args: Sequence[Any] = (),
          conn: sqlite3.Connection | None = None) -> list[dict]:
    """Run a query and hand back plain dictionaries.

    Plain dicts rather than sqlite3.Row so that nothing downstream, and in
    particular nothing in ledger/sync_sheet.py, is holding a live connection
    while it talks to Google over the network.
    """
    own = conn is None
    db = connect() if own else conn
    try:
        return [dict(row) for row in db.execute(sql, tuple(args)).fetchall()]
    except sqlite3.Error as exc:
        _warn(f"query failed: {exc!r}")
        return []
    finally:
        if own:
            db.close()


def trades_for_date(date: Any = None, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Every fill on one day, with the order and the decision behind it.

    Pass no date for every fill in the database, which is what a full rebuild
    of the ledger wants.

    Realised P&L is not in here and comes back as None. Nothing in the database
    works out the profit on a closed position yet, and an invented number in
    that column would flow straight into the Google Sheet's win rate, average
    win and average loss. A blank is the honest answer until something computes
    it properly.
    """
    where, args = ("", [])
    if date is not None:
        where = "WHERE substr(f.ts, 1, 10) = ?"
        args = [as_date(date)]
    return _rows(f"""
        SELECT f.ts                AS ts,
               substr(f.ts, 1, 10) AS date,
               f.symbol            AS symbol,
               f.side              AS side,
               f.qty               AS qty,
               f.price             AS price,
               f.commission        AS commission,
               f.decision_price    AS decision_price,
               f.slippage_usd      AS slippage_usd,
               f.slippage_bps      AS slippage_bps,
               o.order_type        AS order_type,
               o.broker_order_id   AS broker_order_id,
               o.purpose           AS purpose,
               o.book_id           AS book_id,
               d.ts                AS decision_ts,
               d.model             AS model,
               d.cost_usd          AS cost_usd,
               d.prompt_hash       AS prompt_hash,
               d.rationale         AS rationale
          FROM fills f
          LEFT JOIN orders    o ON o.id = f.order_id
          LEFT JOIN decisions d ON d.id = o.decision_id
          {where}
         ORDER BY f.ts, f.id
    """, args, conn)


def daily_summaries(date: Any = None,
                    conn: sqlite3.Connection | None = None) -> list[dict]:
    """The per book scoreboard, one row per book per day, oldest first."""
    where, args = ("", [])
    if date is not None:
        where = "WHERE date = ?"
        args = [as_date(date)]
    return _rows(f"SELECT * FROM daily_book_summaries {where} "
                 f"ORDER BY date, book_id", args, conn)


def account_days(date: Any = None,
                 conn: sqlite3.Connection | None = None) -> list[dict]:
    """One row per trading day for the whole account, all books added up.

    This is what the Google Sheet's Daily tab wants, because that tab follows
    the single paper account rather than five separate curves. Equity is summed
    across the books, and SPY's close is taken as the highest value any book
    recorded for that day, since it is one number that should be the same on
    every row.
    """
    where, args = ("", [])
    if date is not None:
        where = "WHERE date = ?"
        args = [as_date(date)]
    return _rows(f"""
        SELECT date,
               SUM(start_equity)   AS start_equity,
               SUM(end_equity)     AS end_equity,
               MAX(spy_close)      AS spy_close,
               SUM(trades)         AS trades,
               SUM(commissions)    AS commissions,
               SUM(model_cost_usd) AS model_cost_usd,
               SUM(rule_triggers)  AS rule_triggers,
               SUM(missed_ticks)   AS missed_ticks,
               COUNT(*)            AS books
          FROM daily_book_summaries
          {where}
         GROUP BY date
         ORDER BY date
    """, args, conn)


def rules_log_rows(date: Any = None,
                   conn: sqlite3.Connection | None = None) -> list[dict]:
    """The Rules Log, built from two tables and sorted into one list by time.

    Three kinds of row come out, and the "rule" field is what tells them apart,
    which matters because the ledger's Books tab counts anything that is not
    the word "decision" as a guardrail having fired:

      decision       a judgement call that stood, including every skip
      <a rule id>    a call that a guardrail refused, named by the guardrail,
                     for example max_open_positions
      alert:<LEVEL>  an alert that was raised, with no book against it, so it
                     never lands in any single book's count of rule triggers
    """
    where, args = ("", [])
    if date is not None:
        where = "WHERE substr(ts, 1, 10) = ?"
        args = [as_date(date)]

    decisions = _rows(f"""
        SELECT ts, book_id, model, cost_usd, prompt_hash, symbol, action,
               shape, rationale, rejected, reject_reason
          FROM decisions {where} ORDER BY ts, id
    """, args, conn)
    alerts = _rows(f"""
        SELECT ts, level, title, body, channels
          FROM alerts {where} ORDER BY ts, id
    """, args, conn)

    out: list[dict] = []
    for row in decisions:
        symbol = row.get("symbol") or ""
        rationale = row.get("rationale") or ""
        detail = f"{symbol}: {rationale}" if symbol else rationale
        if row.get("rejected"):
            rule = row.get("reject_reason") or "refused"
            action = f"refused: {row.get('action') or 'entry'}"
        else:
            rule = "decision"
            action = f"[{row.get('shape') or 'rules'}] {row.get('action') or ''}".strip()
        out.append({"ts": row["ts"], "rule": rule, "detail": detail,
                    "action": action, "book_id": row.get("book_id"),
                    "model": row.get("model"), "cost_usd": row.get("cost_usd"),
                    "prompt_hash": row.get("prompt_hash")})
    for row in alerts:
        channels = _loads(row.get("channels")) or []
        went = ", ".join(str(c) for c in channels) if channels else "nothing"
        out.append({"ts": row["ts"],
                    "rule": f"alert:{row.get('level') or 'INFO'}",
                    "detail": f"{row.get('title') or ''}: {row.get('body') or ''}".strip(": "),
                    "action": f"sent to {went}",
                    "book_id": None, "model": None, "cost_usd": None,
                    "prompt_hash": None})
    out.sort(key=lambda row: row["ts"])
    return out


def books_summary(conn: sqlite3.Connection | None = None) -> list[dict]:
    """The three figures the Google Sheet's Books tab cannot work out itself.

    Equity, worst drawdown and missed ticks, one row per book. Everything else
    on that tab is a live formula slicing the Trades and Rules Log tabs by
    book, and those formulas are left alone.

    Equity is the book's most recent end of day figure. Max drawdown is the
    worst single day figure recorded, kept as the negative number the sheet
    formats as a percentage. Missed ticks add up over the whole month.
    """
    return _rows("""
        SELECT s.book_id                    AS book_id,
               (SELECT end_equity
                  FROM daily_book_summaries l
                 WHERE l.book_id = s.book_id AND l.end_equity IS NOT NULL
                 ORDER BY l.date DESC LIMIT 1) AS equity,
               MIN(s.max_drawdown_pct)      AS max_drawdown_pct,
               SUM(s.missed_ticks)          AS missed_ticks,
               SUM(s.trades)                AS trades,
               SUM(s.commissions)           AS commissions,
               SUM(s.model_cost_usd)        AS model_cost_usd,
               COUNT(*)                     AS days
          FROM daily_book_summaries s
         GROUP BY s.book_id
         ORDER BY s.book_id
    """, (), conn)


def counts(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """How many rows are in each table. For a quick look, and for the tests."""
    tables = [row["name"] for row in _rows(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name", (), conn)]
    out = {}
    for table in tables:
        found = _rows(f"SELECT COUNT(*) AS n FROM {table}", (), conn)
        out[table] = int(found[0]["n"]) if found else 0
    return out


def _cli() -> int:
    """Print where the database is and what is in it. Writes nothing."""
    path = db_path()
    print(f"database: {path}")
    print(f"exists:   {path.exists()}")
    if not path.exists():
        print("\nNot built yet. Build it with:")
        print(f"  {project_root()}/venv312/bin/python "
              f"{project_root()}/scripts/migrate_db.py")
        return 1
    size = path.stat().st_size
    print(f"size:     {size / 1024:.1f} KB")
    conn = connect()
    try:
        applied = [row["filename"] for row in
                   conn.execute("SELECT filename FROM schema_version ORDER BY filename")]
        print(f"applied:  {', '.join(applied) or 'nothing'}")
        print("\nrows per table:")
        for table, number in counts(conn).items():
            print(f"  {number:>8}  {table}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - a hand check, not a code path
    raise SystemExit(_cli())
