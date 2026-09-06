"""One tick of the trading loop, across all five books.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py

    # one book only
    ... /agent/loop.py --book C

    # pretend it is Tuesday morning, to see a phase after hours
    ... /agent/loop.py --now "2026-09-08 09:36"

There is no while loop in here on purpose. launchd wakes this script (see
config/launchd/com.mtalib.agentic-trading.tick.plist and docs/LAUNCHD.md), it
looks at the clock, does the one thing that belongs to that minute for every
enabled book in config/books.yaml, writes down what it saw, and exits. What each
book has to remember between ticks lives in its own file, one per book per day,
handled by agent/book_state.py. So a tick that crashes, or a Mac that was
asleep, costs one tick and not the day.

Five books, one account, three strategies
-----------------------------------------
Books A, B and E run the opening momentum strategy on a five minute clock. Book
C buys insider filings and book D buys Congress filings, both on a thirty minute
clock, and neither is sold off at the close. Every book has its own money, its
own limits and its own tag on its orders, and every log line and ledger row says
which book it came from. What differs is only the clock and where the shortlist
comes from:

    momentum   scanner 09:30 to 09:35, pick 09:35, manage every 5 minutes,
               entries until 11:00, everything sold at 15:55
    insider    sweep 07:00 and 16:30, pick 09:45, manage every 30 minutes,
               nothing is sold at the close
    congress   sweep 07:30, pick 09:45, manage every 30 minutes, nothing is
               sold at the close

NOTHING IS ORDERED TODAY
------------------------
Not on paper, not through a preview, not through the dry_run flag on the
broker's own order tools. Every order this file works out is printed as
"DRY RUN BOOK_A would place ..." and written to the ledger as a decision, and
that is where it stops. The live path exists below, in submit(), and it is shut
behind four separate locks that all have to be open at once:

    1. the book's mode in config/books.yaml is tiny or full. It is dry-run for
       all five, and agent/guardrails.py refuses to load any other value today.
    2. the environment variable AGENTIC_TRADING_LIVE_ORDERS is set to yes.
    3. the account id starts with DU, which is how IBKR names paper accounts.
    4. none of output/STOP, output/LOOP_DISABLED or output/NO_TRADE_TODAY exist.

Do not set that environment variable. Opening these locks is a decision for Mo
after he has read the numbers in docs/STRATEGY.md, not a step in a script.

The three files that stop it
----------------------------
    output/LOOP_DISABLED   the loop does nothing at all and says so
    output/STOP            positions may be closed, nothing may be opened
    output/NO_TRADE_TODAY  no book opens anything today, exits still work

See docs/LOOP.md for the whole of it in plain words.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_ROOT = Path("/Users/mtalib/workspace_repos/personal_repo/agentic_trading")
ROOT_ENV_VAR = "AGENTIC_TRADING_ROOT"


def project_root() -> Path:
    """The project folder, from AGENTIC_TRADING_ROOT or the default above."""
    raw = (os.environ.get(ROOT_ENV_VAR) or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_ROOT


PROJECT = project_root()
for _extra in (PROJECT, PROJECT / "agent", PROJECT / "ledger"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import book_state as bs                     # noqa: E402
import broker as broker_mod                 # noqa: E402
import decide as decide_mod                 # noqa: E402
import guardrails as gr                     # noqa: E402
import ledger_writer                        # noqa: E402
import mcp_client as mcp                    # noqa: E402

# Two modules another agent is writing at the same time as this one. The loop
# has to be safe whether or not they have landed, so both are optional and a
# missing one degrades to the careful answer rather than to a crash.
try:
    import reconcile as reconcile_mod       # noqa: E402
    RECONCILE_ERROR: str | None = None
except Exception as exc:                    # noqa: BLE001
    reconcile_mod = None                    # type: ignore[assignment]
    RECONCILE_ERROR = f"{type(exc).__name__}: {exc}"

try:
    import pdt as pdt_mod                   # noqa: E402
    PDT_ERROR: str | None = None
except Exception as exc:                    # noqa: BLE001
    pdt_mod = None                          # type: ignore[assignment]
    PDT_ERROR = f"{type(exc).__name__}: {exc}"

LIVE_ENV_VAR = "AGENTIC_TRADING_LIVE_ORDERS"
PAPER_ACCOUNT_PREFIX = "DU"
LIVE_MODES = ("tiny", "full")

# Which phase a book is in. One word each, because they end up in log lines.
IDLE, SWEEP, SCAN, PICK, MANAGE, FLATTEN, CLOSED = (
    "idle", "sweep", "scan", "pick", "manage", "flatten", "closed")

MOMENTUM, INSIDER, CONGRESS = "momentum", "insider", "congress"

# A book only wakes for a sweep inside this many minutes of the sweep time, so a
# tick at 07:03 still counts as the 07:00 sweep and one at 09:00 does not.
SWEEP_WINDOW_MINUTES = 20

# A shortlist file this old is stale and the scanner or sweep is run again. All
# three momentum books share one scanner run, so whichever ticks first pays for
# it and the other two read the file.
SHORTLIST_FRESH_MINUTES = 10

# The classic pattern day trader line: a fourth day trade inside five business
# days is what the rule is about.
DAY_TRADE_LIMIT = 3

# Books C and D hold for weeks, so a same day round trip in one of them is a
# bug rather than a strategy, and it is refused. Books A, B and E are day
# trading books on purpose, so a day trade there is written down and allowed.
DAY_TRADE_HARD_LIMIT_BOOKS = ("C", "D")


# --------------------------------------------------------------- small things

def output_dir() -> Path:
    path = project_root() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def books_yaml_path() -> Path:
    return project_root() / "config" / "books.yaml"


def rules_commit() -> str:
    """The short git hash of the rules this tick ran under.

    Every log line and every ledger row carries it, so a month later a decision
    can be read against the exact limits that were in force when it was made.
    Comes back as "unknown" outside a git checkout rather than raising, because
    not knowing the hash is not a reason to skip a tick.
    """
    try:
        finished = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(project_root()),
            capture_output=True, text=True, timeout=10)
    except Exception:                        # noqa: BLE001
        return "unknown"
    if finished.returncode != 0:
        return "unknown"
    return finished.stdout.strip() or "unknown"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def parse_now(text: str | None, zone: ZoneInfo) -> datetime:
    """The current time, or the pretend time from --now, in New York."""
    if not text:
        return datetime.now(zone)
    raw = text.strip()
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                  "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw, shape).replace(tzinfo=zone)
        except ValueError:
            continue
    for shape in ("%H:%M:%S", "%H:%M"):
        try:
            wanted = datetime.strptime(raw, shape).time()
            return datetime.combine(datetime.now(zone).date(), wanted, tzinfo=zone)
        except ValueError:
            continue
    raise SystemExit(f'loop: cannot read --now {text!r}. Try --now "2026-09-08 09:36"')


# ------------------------------------------------------------- the guard files

@dataclass(frozen=True)
class Guards:
    """The three files that stop the loop, and whether each of them is there."""

    loop_disabled: Path
    stop: Path
    no_trade_today: Path

    @property
    def loop_disabled_present(self) -> bool:
        return self.loop_disabled.exists()

    @property
    def stop_present(self) -> bool:
        return self.stop.exists()

    @property
    def no_trade_present(self) -> bool:
        return self.no_trade_today.exists()

    @property
    def any_present(self) -> bool:
        return self.loop_disabled_present or self.stop_present or self.no_trade_present


def read_guards(root: Path | None = None) -> Guards:
    folder = (root or project_root()) / "output"
    return Guards(loop_disabled=folder / "LOOP_DISABLED",
                  stop=folder / "STOP",
                  no_trade_today=folder / "NO_TRADE_TODAY")


def entries_blocked_reason(guards: Guards, state: bs.BookState) -> str | None:
    """Why this book may not open anything right now, or None when it may."""
    if guards.stop_present:
        return (f"the stop file {guards.stop} exists, so this tick may close "
                "positions and open nothing")
    if guards.no_trade_present:
        return (f"the file {guards.no_trade_today} exists, so no book opens "
                "anything today. Closing orders still work.")
    if state.halted:
        return f"book {state.book_id} is halted today: {state.halt_reason}"
    return None


# ------------------------------------------------------------- what each book does

@dataclass(frozen=True)
class BookPlan:
    """When one book does what, and where its shortlist comes from.

    Built from the book's own strategy.yaml through agent/guardrails.py, so
    changing a time in that file changes the loop and nothing has to be edited
    here.
    """

    family: str
    scan_start: clock_time
    pick_time: clock_time
    entries_until: clock_time
    flatten_at: clock_time
    market_close: clock_time
    manage_minutes: int
    flat_by_close: bool
    sweep_times: tuple[clock_time, ...] = ()
    sweep_script: str | None = None
    shortlist_prefix: str = "shortlist"
    runs_scanner: bool = False


def family_for(book: gr.BookConfig) -> str:
    """Which of the three strategies this book runs, from its folder name."""
    folder = Path(str(book.strategy_dir)).name.lower()
    if INSIDER in folder:
        return INSIDER
    if CONGRESS in folder:
        return CONGRESS
    return MOMENTUM


def _clock(text: str) -> clock_time:
    return datetime.strptime(text, "%H:%M").time()


def plan_for(book: gr.BookConfig, guard: gr.Guardrails) -> BookPlan:
    """The book's timetable, read from its own settings.

    The sweep times come from the sweep block of the strategy file, which the
    guardrails carry through untouched because they are not order limits. If a
    book has no sweep block the times below are the ones written in
    docs/STRATEGY_INSIDER.md and docs/STRATEGY_CONGRESS.md.
    """
    family = family_for(book)
    schedule = guard.schedule
    sweep = guard.sweep or {}

    if family == INSIDER:
        times = tuple(_clock(str(sweep.get(key) or fallback)) for key, fallback in
                      (("morning_sweep_at", "07:00"), ("afternoon_sweep_at", "16:30")))
        script, prefix = "sweep_insider.py", "insider_shortlist"
    elif family == CONGRESS:
        times = (_clock(str(sweep.get("disclosure_sweep_at") or "07:30")),)
        script, prefix = "sweep_congress.py", "congress_shortlist"
    else:
        times, script, prefix = (), None, "shortlist"

    return BookPlan(
        family=family,
        scan_start=schedule.scan_start,
        pick_time=schedule.pick_time,
        entries_until=schedule.entries_until,
        flatten_at=schedule.flatten_at,
        market_close=schedule.market_close,
        manage_minutes=int(schedule.loop_minutes or 5),
        flat_by_close=bool(guard.flat_by_close),
        sweep_times=times,
        sweep_script=script,
        shortlist_prefix=prefix,
        runs_scanner=(family == MOMENTUM),
    )


def manage_due(now: datetime, last_manage_at: str | datetime | None,
               minutes: int) -> bool:
    """Is this book due for a look at its positions?

    The loop wakes every five minutes for everybody. A book on a thirty minute
    clock only looks every sixth wake up, and it works that out from when it
    last looked rather than from the minute hand, so a tick that was missed
    because the Mac was asleep does not push the whole day out of step.
    """
    if last_manage_at is None:
        return True
    when = last_manage_at
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when)
        except ValueError:
            return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    # One minute of slack, so a tick that lands a few seconds early still counts.
    return (now - when).total_seconds() >= max(0, int(minutes) * 60 - 60)


def sweep_due(now: datetime, plan: BookPlan, swept_at: dict) -> str | None:
    """Which sweep slot this tick belongs to, or None.

    A slot is named by its time, "07:00", and once a sweep has run for that slot
    today it does not run again, however many ticks land inside the window.
    """
    for moment in plan.sweep_times:
        slot = f"{moment:%H:%M}"
        if swept_at.get(slot):
            continue
        start = datetime.combine(now.date(), moment, tzinfo=now.tzinfo)
        if start <= now < start + timedelta(minutes=SWEEP_WINDOW_MINUTES):
            return slot
    return None


def phase_for(now: datetime, plan: BookPlan, *, pick_done: bool = False,
              last_manage_at: str | datetime | None = None,
              swept_at: dict | None = None) -> tuple[str, str]:
    """Which part of the day this is for one book, and one sentence saying why.

    Deliberately takes plain values rather than a state object, so every branch
    can be tested with two lines and no files on disk.
    """
    swept_at = swept_at or {}
    moment = now.time()

    if now.weekday() >= 5:
        return CLOSED, "it is the weekend, the US market is shut"

    slot = sweep_due(now, plan, swept_at)
    if slot is not None:
        return SWEEP, f"the {slot} sweep for this book has not run yet today"

    if plan.runs_scanner and moment < plan.scan_start:
        return IDLE, f"the market opens at {plan.scan_start:%H:%M}"
    if plan.runs_scanner and moment < plan.pick_time:
        return SCAN, (f"the first minutes, {plan.scan_start:%H:%M} to "
                      f"{plan.pick_time:%H:%M}, are when the scanner runs")
    if not plan.runs_scanner and moment < plan.pick_time:
        return IDLE, f"this book picks at {plan.pick_time:%H:%M}"

    if plan.flat_by_close and plan.flatten_at <= moment < plan.market_close:
        return FLATTEN, (f"{plan.flatten_at:%H:%M} has passed and this book is flat "
                         "by the close, so everything open gets sold")

    if moment >= plan.market_close:
        return CLOSED, f"the market closed at {plan.market_close:%H:%M}"

    if not pick_done and moment < plan.entries_until:
        return PICK, f"the {plan.pick_time:%H:%M} pick has not been made yet today"

    if manage_due(now, last_manage_at, plan.manage_minutes):
        if pick_done:
            return MANAGE, "the pick is made, so watch what came out of it"
        return MANAGE, (f"no pick was made today and it is past "
                        f"{plan.entries_until:%H:%M}, so nothing new may be opened")
    return IDLE, (f"this book looks at its positions every {plan.manage_minutes} "
                  "minutes and it is not due yet")


# --------------------------------------------------------------- reconciliation

@dataclass
class ReconcileOutcome:
    """What the reconciliation said, in a shape this loop can act on."""

    available: bool
    ok: bool
    books_to_halt: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)
    orphans: list = field(default_factory=list)
    note: str = ""


def expected_orphans(root: Path | None = None) -> list:
    """Positions and orders that belong to no book and are known about.

    The paper account already holds one share of SPY from the manual test on
    2026-09-02, and nothing in books.yaml owns it. Without a list like this,
    every single tick would report it as a mismatch and halt all five books.
    Add a symbol to output/expected_orphans.json to forgive it.
    """
    path = ((root or project_root()) / "output" / "expected_orphans.json")
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text())
    except Exception:                        # noqa: BLE001
        return []
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        return list(loaded.get("symbols") or loaded.get("orphans") or [])
    return []


def run_reconciliation(broker_positions: list, broker_open_orders: list,
                       books_state: dict, orphans: list) -> ReconcileOutcome:
    """Ask agent/reconcile.py whether the books and the broker agree.

    Five books share one account, so the only thing that says which book owns a
    position is the tag on the order that opened it. If the book files and the
    broker disagree, nobody knows who owns what, and sizing the next order would
    be guesswork. So a mismatch halts the book it belongs to.

    That module is being written at the same time as this one. When it is not
    there, or its answer cannot be read, every book is halted for the tick. A
    halted book still closes positions, because refusing to close is its own
    risk, and it opens nothing.
    """
    if reconcile_mod is None:
        return ReconcileOutcome(
            available=False, ok=False, books_to_halt=list(books_state),
            note=("reconciliation unavailable, halting all books: agent/reconcile.py "
                  f"could not be imported ({RECONCILE_ERROR})"))

    function = getattr(reconcile_mod, "reconcile", None)
    if function is None:
        return ReconcileOutcome(
            available=False, ok=False, books_to_halt=list(books_state),
            note="reconciliation unavailable, halting all books: agent/reconcile.py "
                 "has no reconcile function")

    report = None
    try:
        report = function(broker_positions, broker_open_orders, books_state,
                          expected_orphans=orphans)
    except TypeError:
        try:
            report = function(broker_positions, broker_open_orders, books_state)
        except Exception as exc:             # noqa: BLE001
            return ReconcileOutcome(
                available=False, ok=False, books_to_halt=list(books_state),
                note="reconciliation unavailable, halting all books: reconcile() "
                     f"would not take the arguments this loop has ({exc})")
    except Exception as exc:                 # noqa: BLE001
        return ReconcileOutcome(
            available=False, ok=False, books_to_halt=list(books_state),
            note=f"reconciliation unavailable, halting all books: reconcile() raised "
                 f"{type(exc).__name__}: {exc}")

    ok = bool(getattr(report, "ok", False))
    halt = list(getattr(report, "books_to_halt", []) or [])
    mismatches = list(getattr(report, "mismatches", []) or [])
    found_orphans = list(getattr(report, "orphans", []) or [])
    if not ok and not halt:
        # It said no but did not say which book, so the safe reading is all of them.
        halt = list(books_state)
    note = ("the books and the broker agree" if ok else
            f"{len(mismatches)} mismatch(es) between the books and the broker")
    return ReconcileOutcome(available=True, ok=ok, books_to_halt=halt,
                            mismatches=mismatches, orphans=found_orphans, note=note)


# ---------------------------------------------------------- the day trade count

@dataclass
class DayTradeVerdict:
    """Whether closing this position today is a day trade, and whether that stops it."""

    is_day_trade: bool
    count: int | None
    blocked: bool
    reason: str


def make_day_trade_counter(book_id: str):
    """A DayTradeCounter from agent/pdt.py, or None when that module is not there."""
    if pdt_mod is None:
        return None
    maker = getattr(pdt_mod, "DayTradeCounter", None)
    if maker is None:
        return None
    store = output_dir() / f"day_trades_{book_id}.json"
    try:
        return maker(book_id, str(store))
    except Exception:                        # noqa: BLE001
        try:
            return maker(book_id=book_id, store_path=str(store))
        except Exception:                    # noqa: BLE001
            return None


def _try(obj, name: str, *argument_sets):
    """Call one method with the first set of arguments it will accept."""
    function = getattr(obj, name, None)
    if function is None:
        return None
    for args, kwargs in argument_sets:
        try:
            return function(*args, **kwargs)
        except TypeError:
            continue
        except Exception:                    # noqa: BLE001
            return None
    return None


def day_trade_verdict(book_id: str, symbol: str, opened_on: str, today: date_type,
                      counter=None) -> DayTradeVerdict:
    """Would closing this position today count as a day trade, and does it matter here?

    A day trade is buying and selling the same name on the same day. The book
    file records the day each position was opened, so the loop can answer that
    on its own even with agent/pdt.py missing. What it cannot answer on its own
    is how many day trades the book has already done in the last five business
    days, which is what the pattern day trader rule counts, so that number comes
    from pdt.py when it is there and is None when it is not.

    Books C and D hold for weeks. A same day round trip in one of them means
    something has gone wrong, so it is refused. Books A, B and E day trade on
    purpose, so it is written down and allowed through.
    """
    same_day = bool(opened_on) and str(opened_on)[:10] == f"{today:%Y-%m-%d}"
    if counter is not None:
        answer = _try(counter, "would_be_day_trade",
                      ((symbol,), {}), ((), {"symbol": symbol}),
                      ((symbol, today), {}), ((), {}))
        if isinstance(answer, bool):
            same_day = answer

    count = None
    if counter is not None:
        answer = _try(counter, "count_last_5_business_days",
                      ((), {}), ((today,), {}), ((), {"today": today}))
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            count = int(answer)

    hard = str(book_id).upper() in DAY_TRADE_HARD_LIMIT_BOOKS
    if not same_day:
        return DayTradeVerdict(False, count, False,
                               "not a day trade, this position was not opened today")

    where = f"book {book_id}"
    if count is None:
        counted = ("how many day trades this book has already made is not known, "
                   f"because agent/pdt.py is not loaded ({PDT_ERROR})")
    else:
        counted = f"{where} has made {count} day trade(s) in the last five business days"

    if hard and count is not None and count >= DAY_TRADE_LIMIT:
        return DayTradeVerdict(
            True, count, True,
            f"this would be day trade number {count + 1} for {where}, and the limit is "
            f"{DAY_TRADE_LIMIT} in five business days. {where.capitalize()} holds for "
            "weeks, so a same day round trip in it is a mistake rather than a strategy "
            "and it is refused.")
    if hard and count is None:
        return DayTradeVerdict(
            True, None, False,
            f"this would be a day trade in {where}, which holds for weeks, and "
            f"{counted}. Letting it through, because refusing to close a position on "
            "the strength of a missing counter is the more dangerous mistake.")
    return DayTradeVerdict(
        True, count, False,
        f"this is a day trade in {where}, which day trades on purpose, so it is "
        f"written down and allowed. {counted}.")


# ------------------------------------------------------- shortlists and packets

def shortlist_path(plan: BookPlan, day: date_type) -> Path:
    return output_dir() / f"{plan.shortlist_prefix}_{day:%Y-%m-%d}.json"


def _fresh_enough(path: Path, now: datetime, minutes: int) -> bool:
    if not path.exists():
        return False
    age = now.timestamp() - path.stat().st_mtime
    return 0 <= age <= minutes * 60


def run_helper(script: str, out_path: Path, timeout: int = 300) -> tuple[bool, str]:
    """Run the scanner or a sweep as its own process and let it write the shortlist.

    Its own process on purpose. Both talk to the outside world, IBKR in one case
    and the SEC in the other, and either can hang or fall over. Neither should be
    able to take the loop down with it.
    """
    path = project_root() / "agent" / script
    python = project_root() / "venv312" / "bin" / "python"
    if not path.exists():
        return False, f"{path} does not exist yet, carrying on with an empty shortlist"
    if not python.exists():
        return False, f"{python} does not exist, so the helper cannot be run"
    try:
        finished = subprocess.run(
            [str(python), str(path), "--out", str(out_path)],
            cwd=str(project_root()), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{script} ran for more than {timeout} seconds and was stopped"
    except Exception as exc:                 # noqa: BLE001
        return False, f"{script} would not start: {exc!r}"
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return False, (f"{script} exited with code {finished.returncode}: "
                       f"{tail[-1] if tail else 'no message'}")
    return True, f"{script} finished and wrote {out_path}"


def read_shortlist(path: Path) -> tuple[list[dict], str]:
    """Read a shortlist file, forgiving how the scanner or sweep wrapped the list."""
    if not path.exists():
        return [], f"no shortlist at {path}, so there is nothing to pick from"
    try:
        loaded = json.loads(path.read_text())
    except Exception as exc:                 # noqa: BLE001
        return [], f"{path} is not readable JSON ({exc!r}), carrying on with nothing"
    if isinstance(loaded, list):
        rows = loaded
    elif isinstance(loaded, dict):
        rows = None
        for key in ("candidates", "shortlist", "symbols", "results", "rows"):
            if isinstance(loaded.get(key), list):
                rows = loaded[key]
                break
        if rows is None:
            rows = next((v for v in loaded.values() if isinstance(v, list)), [])
    else:
        return [], f"{path} holds a {type(loaded).__name__}, not a list of candidates"
    clean = [normalise_candidate(r) for r in rows
             if isinstance(r, dict) and (r.get("symbol") or r.get("ticker"))]
    return clean, f"read {len(clean)} candidates from {path}"


def normalise_candidate(row: dict) -> dict:
    """One shortlist row with a symbol on it, whatever the source called it.

    The scanner writes "symbol". Both sweeps write "ticker", because that is the
    word the SEC and the House Clerk use. Everything downstream, the guardrails
    included, wants "symbol", so the translation happens once, here.
    """
    out = dict(row)
    if not out.get("symbol") and out.get("ticker"):
        out["symbol"] = out["ticker"]
    out["symbol"] = str(out.get("symbol") or "").strip().upper()
    if not out.get("company") and out.get("issuer_name"):
        out["company"] = out["issuer_name"]
    if not out.get("company") and out.get("asset_description"):
        out["company"] = out["asset_description"]
    if out.get("cluster_count") and not out.get("cluster_size"):
        out["cluster_size"] = out["cluster_count"]
    if out.get("crowd_count") and not out.get("crowding"):
        out["crowding"] = out["crowd_count"]
    return out


def contract_for(row: dict) -> dict:
    """An IBKR contract for one shortlist row or one holding."""
    contract: dict[str, Any] = {
        "symbol": str(row.get("symbol") or row.get("ticker") or "").upper(),
        "secType": "STK", "exchange": "SMART", "currency": "USD"}
    if row.get("conId"):
        contract["conId"] = row["conId"]
    if row.get("primaryExchange"):
        contract["primaryExchange"] = row["primaryExchange"]
    return contract


def snapshot_by_symbol(broker: broker_mod.Broker, rows: list[dict],
                       notes: list[str]) -> dict[str, dict]:
    """One quote each for a list of names, in a single call, keyed by symbol."""
    contracts = [contract_for(row) for row in rows if row.get("symbol")]
    if not contracts:
        return {}
    try:
        answer = broker.snapshot(contracts) or {}
    except Exception as exc:                 # noqa: BLE001
        notes.append(f"no quotes came back for {len(contracts)} names: {exc}")
        return {}
    out: dict[str, dict] = {}
    for row in (answer.get("snapshots") or answer.get("quotes") or []):
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def snapshot_price(row: dict | None) -> float | None:
    """The most useful price in a snapshot: last, then the mark, then the close."""
    if not isinstance(row, dict):
        return None
    for key in ("last", "marketPrice", "close"):
        value = _number(row.get(key), -1.0)
        if value > 0:
            return round(value, 4)
    return None


# ------------------------------------------------------------------ the tick

class BookTick:
    """One book's turn in one tick. Holds what happened so the summary is honest."""

    def __init__(self, book: gr.BookConfig, now: datetime, rules: str,
                 write_ledger: bool, quiet: bool = False):
        self.book = book
        self.now = now
        self.rules = rules
        self.write_ledger = write_ledger
        self.quiet = quiet
        self.would_be_orders = 0
        self.approved = 0
        self.refused = 0
        self.sent = 0
        self.notes: list[str] = []
        self.model_cost = 0.0
        self.phase = IDLE

    @property
    def tag(self) -> str:
        return self.book.order_ref

    @property
    def dry(self) -> bool:
        """True when this book writes down what it would do and sends nothing."""
        return str(self.book.mode).replace("_", "-").lower() not in LIVE_MODES

    def say(self, message: str) -> None:
        if not self.quiet:
            print(f"  [{self.tag}] {message}")

    def note(self, message: str) -> None:
        self.notes.append(message)
        if not self.quiet:
            print(f"  [{self.tag}] note: {message}")

    def record(self, state: bs.BookState, symbol: str, decision: str, rationale: str,
               model: str | None = None, cost: Any = None,
               prompt_hash: str = "") -> None:
        """Write one judgement to the book's file and to the Rules Log."""
        state.note_decision(self.now.isoformat(), symbol, decision, rationale,
                            phase=self.phase, rules_commit=self.rules)
        ledger_writer.log_decision(
            self.now, symbol, decision, f"{rationale} [rules {self.rules}]",
            mode=str(self.book.mode), book_id=self.book.book_id,
            model=model if model is not None else (self.book.model or "none"),
            model_cost_usd=cost, prompt_hash=prompt_hash,
            dry_run=not self.write_ledger)

    def rule(self, rule_id: str, detail: str, action: str) -> None:
        """Write one guardrail firing to the Rules Log, tagged with the book."""
        ledger_writer.log_rule(
            self.now, rule_id, f"{detail} [rules {self.rules}]", action,
            book_id=self.book.book_id, dry_run=not self.write_ledger)


def describe(intent: gr.OrderIntent) -> str:
    """One line describing a would be order, in words."""
    where = f"limit {intent.limit_price:.2f}" if intent.limit_price else "at market"
    return (f"{intent.side} {intent.qty} {intent.symbol} {where} "
            f"(purpose: {intent.purpose})")


def live_locks(book: gr.BookConfig, account_id: str,
               guards: Guards) -> tuple[bool, list[str]]:
    """The four locks on the live order path. All four, or nothing is sent.

    Returns whether every lock is open, and the list of the ones that are shut.
    Today every book is in dry-run mode and the environment variable is not set,
    so at least two of them are always shut.
    """
    shut: list[str] = []
    mode = str(book.mode).replace("_", "-").lower()
    if mode not in LIVE_MODES:
        shut.append(f"book {book.book_id} is in {mode} mode, and only "
                    f"{' or '.join(LIVE_MODES)} may send an order")
    if os.environ.get(LIVE_ENV_VAR) != "yes":
        shut.append(f"{LIVE_ENV_VAR} is not set to yes")
    if not str(account_id).upper().startswith(PAPER_ACCOUNT_PREFIX):
        shut.append(f"the account id {account_id or 'unknown'} does not start with "
                    f"{PAPER_ACCOUNT_PREFIX}, so it is not a paper account")
    if guards.loop_disabled_present:
        shut.append(f"{guards.loop_disabled} exists")
    if guards.stop_present:
        shut.append(f"{guards.stop} exists")
    if guards.no_trade_present:
        shut.append(f"{guards.no_trade_today} exists")
    return (not shut), shut


def consider(tick: BookTick, state: bs.BookState, guard: gr.Guardrails,
             account_state, intent: gr.OrderIntent, broker: broker_mod.Broker,
             guards: Guards, extra: str = "", model: str | None = None,
             cost: Any = None, prompt_hash: str = "") -> gr.Decision:
    """Put one would be order through every check, and write down the answer.

    This is the only route from "this book thinks it should trade" to anything
    else happening. In dry run it stops at the printed line, which is where it
    stops today for all five books.
    """
    tick.would_be_orders += 1
    decision = gr.check_order(guard, account_state, intent)
    summary = describe(intent) + (f" {extra}" if extra else "")
    verdict = "allowed by the guardrails" if decision.allowed else "refused by the guardrails"
    because = ("; ".join(decision.reasons)
               or ("no limit was breached" if decision.allowed else "no reason given"))

    if decision.allowed:
        tick.approved += 1
    else:
        tick.refused += 1

    open_locks, shut = live_locks(tick.book, account_state.account_id, guards)

    if tick.dry or not open_locks or not decision.allowed:
        tick.say(f"DRY RUN {tick.tag} would place {summary}")
        tick.say(f"  guardrails: {verdict}. {because}"
                 + (f" [rules: {', '.join(decision.rule_ids)}]" if decision.rule_ids else ""))
        if decision.allowed:
            tick.say("  nothing was sent to the broker: " + "; ".join(shut))
        tick.record(state, intent.symbol, f"would place {summary}",
                    f"{verdict}. {because}", model=model, cost=cost,
                    prompt_hash=prompt_hash)
        for rule_id, reason in zip(decision.rule_ids, decision.reasons):
            tick.rule(rule_id, f"{intent.symbol}: {reason}", "the order was not placed")
        return decision

    # Not reachable today. All four locks would have to be open at once, and the
    # first of them is a mode agent/guardrails.py refuses to load.
    result = submit(tick, state, intent, broker, guard)
    tick.record(state, intent.symbol, f"placed {summary}",
                f"{verdict}. {because}. Broker said: {result.get('confirmed_by')}",
                model=model, cost=cost, prompt_hash=prompt_hash)
    return decision


def submit(tick: BookTick, state: bs.BookState, intent: gr.OrderIntent,
           broker: broker_mod.Broker, guard: gr.Guardrails) -> dict:
    """Send one order to the broker and write down what actually came back.

    Nothing reaches this today. It exists so the live path is real, visible code
    with its locks on it rather than something to be invented in a hurry later.
    """
    contract = contract_for({"symbol": intent.symbol})
    order: dict[str, Any] = {
        "action": intent.side,
        "totalQuantity": int(intent.qty),
        "orderType": "LMT" if intent.limit_price else "MKT",
        "tif": "DAY",
    }
    if intent.limit_price:
        order["lmtPrice"] = round(float(intent.limit_price), 2)

    result = broker.place_order(contract, order, guard.order_ref or tick.tag)
    tick.sent += 1
    filled = _number(result.get("filled_qty"))
    price = _number(result.get("avg_fill_price"))

    if filled > 0:
        tick.say(f"filled {filled:g} {intent.symbol} at {price:.4f} "
                 f"(confirmed by {result.get('confirmed_by')})")
        record_fill(state, intent, filled, price, tick.now)
        ledger_writer.log_trade(
            {"symbol": intent.symbol, "side": intent.side, "qty": filled,
             "price": price, "notional": round(filled * price, 2),
             "order_ref": guard.order_ref, "purpose": intent.purpose},
            book_id=tick.book.book_id, model=tick.book.model or "none",
            dry_run=not tick.write_ledger)
    elif result.get("working"):
        order_id = str(result.get("order_id") or f"pending-{intent.symbol}")
        state.working_orders[order_id] = {
            "symbol": intent.symbol, "side": intent.side, "qty": int(intent.qty),
            "remaining": int(intent.qty), "limit_price": intent.limit_price,
            "purpose": intent.purpose, "placed_at": tick.now.isoformat(),
            "order_ref": guard.order_ref,
        }
        tick.say(f"order {order_id} is working, {intent.qty} {intent.symbol} unfilled")
    else:
        tick.note(f"the broker did not fill and is not working {intent.symbol}: "
                  f"{result.get('error') or 'no reason given'}")
    return result


def record_fill(state: bs.BookState, intent: gr.OrderIntent, filled: float,
                price: float, now: datetime) -> None:
    """Update the book's own file after a real fill. Only the live path calls this."""
    symbol = intent.symbol
    signed = filled if intent.side == "BUY" else -filled
    held = state.position(symbol)

    if held is None:
        state.put_position(bs.Position(
            symbol=symbol, qty=signed, avg_cost=price, opened_on=f"{now.date():%Y-%m-%d}",
            entry=price, side="short" if signed < 0 else "long",
            trailing_high_or_low=price))
        state.entries_opened_today += 1
        state.cash -= signed * price
        return

    if (held.qty > 0) == (signed > 0):
        total = held.qty + signed
        held.avg_cost = (held.avg_cost * held.qty + price * signed) / total if total else price
        held.qty = total
    else:
        closed = min(abs(signed), abs(held.qty))
        direction = 1.0 if held.qty > 0 else -1.0
        state.realized_pnl_today += round((price - held.avg_cost) * closed * direction, 2)
        held.qty += signed
    state.cash -= signed * price
    if abs(held.qty) < 1e-9:
        state.drop_position(symbol)
    else:
        state.put_position(held)


# ------------------------------------------------------------------ the phases

def do_sweep(tick: BookTick, state: bs.BookState, plan: BookPlan, slot: str) -> None:
    """Run this book's filing sweep for one slot of the day."""
    path = shortlist_path(plan, tick.now.date())
    tick.say(f"Running the {slot} sweep, writing to {path}")
    ok, message = run_helper(plan.sweep_script or "", path)
    tick.note(message)
    state.swept_at[slot] = tick.now.isoformat()
    rows, read_message = read_shortlist(path)
    tick.note(read_message)
    if ok:
        state.shortlist = rows
        state.shortlist_path = str(path)
        state.shortlist_read_at = tick.now.isoformat()
    tick.record(state, "", f"{slot} sweep ran",
                f"{message}. {read_message}")


def do_scan(tick: BookTick, state: bs.BookState, plan: BookPlan) -> None:
    """Run the opening scanner, or read the shortlist a sister book just wrote.

    Books A, B and E share one scanner run. Whichever of them ticks first pays
    for it and the other two read the file, because running the scanner three
    times in the same minute would spend three times the data budget on three
    copies of the same answer.
    """
    path = shortlist_path(plan, tick.now.date())
    if _fresh_enough(path, tick.now, SHORTLIST_FRESH_MINUTES):
        rows, message = read_shortlist(path)
        tick.note(f"{message} (written in the last {SHORTLIST_FRESH_MINUTES} minutes "
                  "by another momentum book's tick, so the scanner was not run again)")
    else:
        tick.say(f"Running the scanner, writing to {path}")
        ok, message = run_helper("scanner.py", path, timeout=240)
        tick.note(message)
        rows, read_message = read_shortlist(path)
        tick.note(read_message)
    state.shortlist = rows
    state.shortlist_path = str(path)
    state.shortlist_read_at = tick.now.isoformat()
    tick.say(f"Shortlist has {len(rows)} names. This book picks at {plan.pick_time:%H:%M}.")


def build_pick_packet(tick: BookTick, state: bs.BookState, plan: BookPlan,
                      guard: gr.Guardrails, broker: broker_mod.Broker,
                      rows: list[dict]) -> dict:
    """Everything the pick needs, in one file, so the decision can be reviewed.

    Written to disk before anything is decided. If a pick later looks wrong, the
    packet is exactly what was known at the time, which is the difference
    between reviewing a decision and guessing at it.
    """
    notes: list[str] = []
    quotes = snapshot_by_symbol(broker, rows, notes)
    enriched: list[dict] = []

    for row in rows:
        candidate = dict(row)
        symbol = candidate["symbol"]
        quote = quotes.get(symbol)
        price = snapshot_price(quote)
        if price is not None:
            candidate.setdefault("last", price)
            candidate["last_close"] = price

        if plan.family == MOMENTUM:
            try:
                bars = broker_mod.bars_5m_today(broker, contract_for(candidate))
            except Exception as exc:         # noqa: BLE001
                bars, _ = [], notes.append(f"no five minute bars for {symbol}: {exc}")
            candidate["bars_5m"] = bars
            candidate["bar_count"] = len(bars)
            candidate["session_vwap"] = broker_mod.session_vwap(bars)
            if bars:
                candidate["last_close"] = bars[-1].get("close")
                if not candidate.get("opening_range_high"):
                    candidate["opening_range_high"] = bars[0].get("high")
                    candidate["opening_range_low"] = bars[0].get("low")
                    notes.append(f"{symbol}: the opening range was taken from the first "
                                 "bar, because the scanner did not supply it")
            shortable, why = broker_mod.shortable_from_snapshot(quote)
            candidate["shortable"] = shortable
            candidate["borrow_note"] = why
        else:
            # The sweeps read filings and have no market data at all, so the
            # price floor and the liquidity floor are applied here.
            if price is None:
                notes.append(f"{symbol}: no price came back, so the price floor and the "
                             "liquidity floor cannot be checked and it is left out")
                continue
            if price < guard.universe.price_floor:
                notes.append(f"{symbol}: {price:.2f} is under this book's price floor of "
                             f"{guard.universe.price_floor:.2f}, so it is left out")
                continue
        enriched.append(candidate)

    packet = {
        "generated_at": tick.now.isoformat(),
        "date": f"{tick.now.date():%Y-%m-%d}",
        "book": tick.book.book_id,
        "book_id": tick.book.book_id,
        "order_ref": tick.book.order_ref,
        "mode": tick.book.mode,
        "model": tick.book.model or "none",
        "rules_commit": tick.rules,
        "strategy_key": Path(str(tick.book.strategy_dir)).name,
        "strategy": guard.strategy.name if guard.strategy else "shared settings",
        "schedule": {"pick_time": f"{plan.pick_time:%H:%M}",
                     "entries_until": f"{plan.entries_until:%H:%M}",
                     "flatten_at": f"{plan.flatten_at:%H:%M}" if plan.flat_by_close
                     else "this book is not flattened at the close"},
        "account": bs.facts_for(state),
        "candidates": enriched,
        "positions": [_position_row(p) for p in state.all_positions().values()],
        "notes": notes,
    }
    folder = output_dir()
    path = folder / f"packet_{tick.book.order_ref}_{tick.now:%Y-%m-%d_%H%M}_pick.json"
    path.write_text(json.dumps(packet, indent=2, default=str))
    state.packet_path = str(path)
    for message in notes:
        tick.note(message)
    tick.say(f"Decision packet for {len(enriched)} candidates written to {path}")
    return packet


def _position_row(position: bs.Position) -> dict:
    return {
        "symbol": position.symbol, "side": position.side, "qty": position.qty,
        "avg_cost": position.avg_cost, "entry": position.entry,
        "stop": position.stop, "target": position.target,
        "entry_date": position.opened_on, "entry_reason": position.entry_reason,
        "last_close": position.last_close,
        "high_close_since_entry": position.trailing_high_or_low,
    }


def book_dict(book: gr.BookConfig) -> dict:
    """The book in the shape agent/decide.py wants it."""
    return {"id": book.book_id, "book": book.book_id, "book_id": book.book_id,
            "model": book.model or "none", "order_ref": book.order_ref,
            "mode": book.mode, "name": book.name}


def do_pick(tick: BookTick, state: bs.BookState, plan: BookPlan, guard: gr.Guardrails,
            broker: broker_mod.Broker, account_state, guards: Guards) -> None:
    """Choose today's names and work out what buying them would look like."""
    path = shortlist_path(plan, tick.now.date())
    rows, message = read_shortlist(path)
    tick.note(message)
    if rows:
        state.shortlist = rows
        state.shortlist_path = str(path)

    packet = build_pick_packet(tick, state, plan, guard, broker, rows)
    strategy_dir = project_root() / str(tick.book.strategy_dir)
    result = decide_mod.decide(book_dict(tick.book), strategy_dir, "pick", packet,
                               dry_run=tick.dry)
    state.picked_at = tick.now.isoformat()
    state.picks = list(result.picks)
    cost = _number(result.cost_usd)
    state.model_cost_today = round(state.model_cost_today + cost, 6)
    tick.model_cost += cost

    for message in result.notes:
        tick.note(message)
    if not result.ok:
        tick.note(f"the decision step could not answer: {result.error}")
        tick.rule("decision_failed", f"the {tick.book.model or 'rules only'} decision "
                  f"failed: {result.error}", "no picks were made this tick")

    if not result.picks:
        tick.say(f"No picks. The shortlist held {len(rows)} names and none of them "
                 "cleared this book's rules.")
        tick.record(state, "", "no picks",
                    f"the shortlist held {len(rows)} candidates and none gave a usable "
                    "entry for this book", model=result.model, cost=cost,
                    prompt_hash=result.prompt_hash)
        return

    tick.say(f"Picked {len(result.picks)} names "
             f"({'rules only' if tick.book.model in (None, 'none') else tick.book.model}"
             f"{', dry run so no model was called' if tick.dry else ''}):")
    for skip in result.skips:
        tick.record(state, str(skip.get("symbol") or ""), "skipped",
                    str(skip.get("rationale") or "no reason given"),
                    model=result.model, cost=None, prompt_hash=result.prompt_hash)

    blocked = entries_blocked_reason(guards, state)
    for pick in result.picks:
        _consider_pick(tick, state, plan, guard, broker, account_state, guards,
                       pick, result, blocked)


def _consider_pick(tick: BookTick, state: bs.BookState, plan: BookPlan,
                   guard: gr.Guardrails, broker: broker_mod.Broker, account_state,
                   guards: Guards, pick: dict, result, blocked: str | None) -> None:
    """Turn one pick into a would be order and put it through every check."""
    symbol = str(pick.get("symbol") or "").upper()
    if not symbol:
        return
    short = str(pick.get("side") or "long").lower() in ("short", "sell")
    entry = _number(pick.get("entry"))
    stop = _number(pick.get("stop"))
    target = _number(pick.get("target"))
    reason = str(pick.get("rationale") or "no reason given")

    tick.say(f"{symbol}: {'short' if short else 'long'} from {entry:.2f}, "
             f"stop {stop:.2f}, target {target:.2f}")
    tick.record(state, symbol,
                f"picked, {'short' if short else 'long'} entry {entry:.2f} "
                f"stop {stop:.2f} target {target:.2f}", reason,
                model=result.model, cost=result.cost_usd,
                prompt_hash=result.prompt_hash)

    if blocked:
        tick.say(f"  no entry order for {symbol}: {blocked}")
        tick.record(state, symbol, "no entry order", blocked)
        return
    if not gr.entries_allowed_now(guard, tick.now):
        tick.note(f"{symbol}: it is outside {plan.pick_time:%H:%M} to "
                  f"{plan.entries_until:%H:%M}, so the pick is written down and no "
                  "entry order is worked out")
        return
    if entry <= 0:
        tick.note(f"{symbol}: the pick carries no usable entry price, so there is "
                  "nothing to size")
        return

    quantity = int(pick.get("qty_hint") or 0)
    allowed_shares = gr.max_shares_for(guard, account_state, symbol, entry)
    if allowed_shares < quantity or quantity <= 0:
        if quantity > allowed_shares:
            tick.note(f"{symbol}: cut from {quantity} shares to {allowed_shares}, "
                      "because the money rules say so and the model does not")
        quantity = allowed_shares
    if quantity <= 0:
        tick.say(f"  {symbol}: the money rules allow zero shares at {entry:.2f}")
        tick.record(state, symbol, "no entry order",
                    f"at {entry:.2f} this book's limits allow zero shares")
        return

    shortable, borrow_note = _borrow_answer(state, symbol)
    intent = gr.OrderIntent(
        symbol=symbol, side="SELL" if short else "BUY", qty=int(quantity),
        limit_price=round(entry, 2), purpose="entry", book_id=tick.book.book_id,
        shortable=shortable if short else False)
    extra = f"stop {stop:.2f}, target {target:.2f}"
    if short:
        extra += f", borrow: {borrow_note}"
    decision = consider(tick, state, guard, account_state, intent, broker, guards,
                        extra=extra, model=result.model, cost=None,
                        prompt_hash=result.prompt_hash)
    state.triggered[symbol] = {
        "at": tick.now.isoformat(), "price": entry, "allowed": decision.allowed,
        "sent": False, "mode": tick.book.mode, "side": "short" if short else "long",
        "stop": stop, "target": target, "qty": int(quantity), "reason": reason,
    }
    if decision.daily_halt:
        state.halt("a guardrail asked for a halt for the rest of the day")


def _borrow_answer(state: bs.BookState, symbol: str) -> tuple[bool, str]:
    """What the broker said about borrowing this name, from the shortlist row."""
    for row in state.shortlist:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
            if "shortable" in row:
                return bool(row.get("shortable")), str(row.get("borrow_note") or "")
    return broker_mod.shortable_from_snapshot(None)


def exit_reason_for(position: bs.Position, plan: BookPlan, guard: gr.Guardrails,
                    today: date_type, last_close: float,
                    vwap: float | None) -> tuple[str | None, str]:
    """Should this position be closed, and in plain words why.

    Every way out of a position, in the order the strategies put them:

        stop        the price went through the stop
        target      the price reached the target
        trailing    the price came back through the trailing stop, which follows
                    the best price the position has seen since it was opened
        time        the position has run out of trading days
        fade        momentum books only: the five minute close is back below the
                    day's volume weighted average price, which is the standard
                    tell that an opening push is over

    Kept as its own function, with no broker and no clock in it, so every rule
    can be checked on paper.
    """
    short = position.is_short
    stop = _number(position.stop)
    target = _number(position.target)

    if stop:
        if (not short and last_close <= stop) or (short and last_close >= stop):
            return "stop", (f"the close {last_close:.2f} went through the stop "
                            f"{stop:.2f}")
    if target:
        if (not short and last_close >= target) or (short and last_close <= target):
            return "target", (f"the close {last_close:.2f} reached the target "
                              f"{target:.2f}")

    best = position.trailing_high_or_low
    if best:
        trailing = gr.trailing_stop_price(
            guard, "SELL" if short else "BUY", float(best), _number(position.entry)
            or _number(position.avg_cost))
        if trailing is not None:
            if (not short and last_close <= trailing) or (short and last_close >= trailing):
                return "trailing", (f"the close {last_close:.2f} came back through the "
                                    f"trailing stop {trailing:.2f}, which was following "
                                    f"the best price of {float(best):.2f}")

    if position.opened_on:
        try:
            opened = datetime.strptime(str(position.opened_on)[:10], "%Y-%m-%d").date()
        except ValueError:
            opened = None
        if opened is not None and gr.time_stop_due(guard, opened, today):
            return "time", (f"this position was opened on {opened:%Y-%m-%d} and has run "
                            f"out of the {guard.risk.time_stop_trading_days} trading days "
                            "this book gives one")

    if plan.family == MOMENTUM and vwap:
        if (not short and last_close < vwap) or (short and last_close > vwap):
            return "fade", (f"momentum faded, the five minute close {last_close:.2f} is "
                            f"back through the day's vwap {vwap:.2f}")
    return None, ""


def do_manage(tick: BookTick, state: bs.BookState, plan: BookPlan, guard: gr.Guardrails,
              broker: broker_mod.Broker, account_state, guards: Guards) -> None:
    """Watch what is open, and let picks that have not fired yet still fire."""
    state.last_manage_at = tick.now.isoformat()
    positions = state.all_positions()
    notes: list[str] = []
    today = tick.now.date()

    prices: dict[str, tuple[float | None, float | None]] = {}
    if positions:
        rows = [{"symbol": s} for s in positions]
        quotes = snapshot_by_symbol(broker, rows, notes)
        for symbol in positions:
            if plan.family == MOMENTUM:
                try:
                    bars = broker_mod.bars_5m_today(broker, contract_for({"symbol": symbol}))
                except Exception as exc:     # noqa: BLE001
                    bars = []
                    notes.append(f"no five minute bars for {symbol}: {exc}")
                last = bars[-1].get("close") if bars else snapshot_price(quotes.get(symbol))
                prices[symbol] = (_number(last, 0.0) or None, broker_mod.session_vwap(bars))
            else:
                prices[symbol] = (snapshot_price(quotes.get(symbol)), None)
    for message in notes:
        tick.note(message)

    if not positions:
        tick.say("Nothing is open.")

    rows_for_packet = []
    for symbol, position in positions.items():
        last_close, vwap = prices.get(symbol, (None, None))
        row = _position_row(position)
        row["last_close"] = last_close
        row["session_vwap"] = vwap
        rows_for_packet.append(row)

    packet = {
        "generated_at": tick.now.isoformat(), "date": f"{today:%Y-%m-%d}",
        "book": tick.book.book_id, "book_id": tick.book.book_id,
        "mode": tick.book.mode, "rules_commit": tick.rules,
        "strategy_key": Path(str(tick.book.strategy_dir)).name,
        "account": bs.facts_for(state), "positions": rows_for_packet,
        "working_orders": [dict(o, orderId=k) for k, o in state.working_orders.items()
                           if isinstance(o, dict)],
    }
    model_view: dict[str, dict] = {}
    if positions:
        strategy_dir = project_root() / str(tick.book.strategy_dir)
        result = decide_mod.decide(book_dict(tick.book), strategy_dir, "manage", packet,
                                   dry_run=tick.dry)
        cost = _number(result.cost_usd)
        state.model_cost_today = round(state.model_cost_today + cost, 6)
        tick.model_cost += cost
        if not result.ok:
            tick.note(f"the manage decision could not answer: {result.error}")
        model_view = {str(e.get("symbol") or "").upper(): e for e in result.exits}
    else:
        result = None

    counter = make_day_trade_counter(tick.book.book_id)

    for symbol, position in positions.items():
        last_close, vwap = prices.get(symbol, (None, None))
        held = (f"{symbol}: holding {position.qty:g} shares "
                f"({position.side}) bought around {position.avg_cost:.2f}")
        if last_close is None:
            tick.say(held)
            tick.note(f"{symbol}: no price came back, so it is left alone this tick")
            tick.record(state, symbol, "hold", "no price came back this tick, so no "
                        "rule could be checked against it")
            continue
        tick.say(held + f", last {last_close:.2f}" + (f", vwap {vwap:.2f}" if vwap else ""))

        # The best price since entry is what a trailing stop follows, so it is
        # updated before the rules are checked and it is kept in the book file.
        best = position.trailing_high_or_low
        if best is None:
            position.trailing_high_or_low = last_close
        elif position.is_short:
            position.trailing_high_or_low = min(float(best), last_close)
        else:
            position.trailing_high_or_low = max(float(best), last_close)
        state.put_position(position)

        trigger, why = exit_reason_for(position, plan, guard, today, last_close, vwap)
        view = model_view.get(symbol) or {}
        model_says = str(view.get("action") or "").lower()
        model_reason = str(view.get("rationale") or "")

        if trigger is None and model_says == "exit":
            trigger = "model"
            why = f"the model asked to close it: {model_reason}"
        elif trigger is not None and model_reason:
            why = f"{why}. The model said: {model_says or 'nothing'}, {model_reason}"

        if trigger is None:
            tick.say(f"  holding {symbol}, no rule has fired")
            tick.record(state, symbol, "hold",
                        f"no stop, target, trailing stop or time stop has fired"
                        + (f". The model said: {model_reason}" if model_reason else ""),
                        model=result.model if result else None,
                        cost=None, prompt_hash=result.prompt_hash if result else "")
            continue

        verdict = day_trade_verdict(tick.book.book_id, symbol, position.opened_on,
                                    today, counter)
        if verdict.blocked:
            tick.say(f"  NOT closing {symbol}: {verdict.reason}")
            tick.rule("day_trade_limit", f"{symbol}: {verdict.reason}",
                      "the closing order was not placed")
            tick.record(state, symbol, "exit refused by the day trade rule", verdict.reason)
            continue
        if verdict.is_day_trade:
            tick.note(f"{symbol}: {verdict.reason}")

        intent = gr.OrderIntent(
            symbol=symbol, side="BUY" if position.is_short else "SELL",
            qty=int(round(abs(position.qty))), limit_price=round(last_close, 2),
            purpose="exit", book_id=tick.book.book_id)
        consider(tick, state, guard, account_state, intent, broker, guards,
                 extra=f"[{trigger}] because {why}",
                 model=result.model if result else None,
                 prompt_hash=result.prompt_hash if result else "")

    _fire_waiting_entries(tick, state, plan, guard, broker, account_state, guards)


def _fire_waiting_entries(tick: BookTick, state: bs.BookState, plan: BookPlan,
                          guard: gr.Guardrails, broker: broker_mod.Broker,
                          account_state, guards: Guards) -> None:
    """A pick whose entry has not been worked out yet gets another look.

    The momentum strategy enters on a break of the opening range, which may
    happen at 09:40 or at 10:55 or never. A pick that was refused at 09:35 for
    want of room can also come back once something else has been closed.
    """
    blocked = entries_blocked_reason(guards, state)
    if blocked:
        tick.note(f"no new positions this tick: {blocked}")
        return
    if not gr.entries_allowed_now(guard, tick.now):
        if state.picks:
            tick.note(f"new entries closed at {plan.entries_until:%H:%M}, so a pick that "
                      "has not fired by now is left alone")
        return

    positions = state.all_positions()
    for pick in state.picks:
        if not isinstance(pick, dict):
            continue
        symbol = str(pick.get("symbol") or "").upper()
        if not symbol or symbol in positions:
            continue
        already = state.triggered.get(symbol) or {}
        if already.get("allowed") or already.get("sent"):
            continue

        entry = _number(pick.get("entry"))
        if entry <= 0:
            continue
        short = str(pick.get("side") or "long").lower() in ("short", "sell")
        try:
            bars = broker_mod.bars_5m_today(broker, contract_for({"symbol": symbol})) \
                if plan.family == MOMENTUM else []
        except Exception:                    # noqa: BLE001
            bars = []
        last_close = _number(bars[-1].get("close")) if bars else None
        if last_close is None:
            quotes = snapshot_by_symbol(broker, [{"symbol": symbol}], [])
            last_close = snapshot_price(quotes.get(symbol))
        if not last_close:
            tick.note(f"{symbol}: no price came back, so its entry cannot be judged "
                      "this tick")
            continue

        broken = last_close < entry if short else last_close > entry
        if not broken:
            tick.say(f"  {symbol} is at {last_close:.2f}, still the wrong side of its "
                     f"{entry:.2f} trigger, waiting")
            tick.record(state, symbol, "wait",
                        f"the last close {last_close:.2f} has not broken the "
                        f"{entry:.2f} trigger")
            continue

        target = _number(pick.get("target"))
        ran = (last_close <= target) if short else (last_close >= target)
        if target and ran:
            tick.say(f"  {symbol} is at {last_close:.2f}, already past its {target:.2f} "
                     "target, so the entry is skipped")
            tick.record(state, symbol, "no entry, the move already ran",
                        f"the last close {last_close:.2f} is already at the target "
                        f"{target:.2f}, so there is no reward left to pay for the risk")
            state.triggered[symbol] = {"at": tick.now.isoformat(), "price": last_close,
                                       "allowed": False, "sent": False,
                                       "skipped": "past target"}
            continue

        # Size on the price we would actually pay, not the price we planned for.
        quantity = gr.max_shares_for(guard, account_state, symbol, last_close)
        if quantity <= 0:
            tick.record(state, symbol, "no entry",
                        f"at {last_close:.2f} this book's limits allow zero shares")
            continue
        shortable, borrow_note = _borrow_answer(state, symbol)
        intent = gr.OrderIntent(
            symbol=symbol, side="SELL" if short else "BUY", qty=int(quantity),
            limit_price=round(last_close, 2), purpose="entry",
            book_id=tick.book.book_id, shortable=shortable if short else False)
        tick.say(f"  {symbol} broke its {entry:.2f} trigger, now {last_close:.2f}")
        decision = consider(tick, state, guard, account_state, intent, broker, guards,
                            extra=f"stop {_number(pick.get('stop')):.2f}"
                                  + (f", borrow: {borrow_note}" if short else ""))
        state.triggered[symbol] = {
            "at": tick.now.isoformat(), "price": last_close,
            "allowed": decision.allowed, "sent": False, "mode": tick.book.mode}
        if decision.daily_halt:
            state.halt("a guardrail asked for a halt for the rest of the day")


def do_flatten(tick: BookTick, state: bs.BookState, plan: BookPlan, guard: gr.Guardrails,
               broker: broker_mod.Broker, account_state, guards: Guards) -> None:
    """Close everything. The momentum books carry nothing overnight, ever."""
    positions = state.all_positions()
    if not positions:
        tick.say(f"Nothing is open at {plan.flatten_at:%H:%M}, so there is nothing "
                 "to close.")
        return
    tick.say(f"It is past {plan.flatten_at:%H:%M}. Closing all {len(positions)} "
             "open positions.")
    quotes = snapshot_by_symbol(broker, [{"symbol": s} for s in positions], [])
    for symbol, position in positions.items():
        price = snapshot_price(quotes.get(symbol))
        intent = gr.OrderIntent(
            symbol=symbol, side="BUY" if position.is_short else "SELL",
            qty=int(round(abs(position.qty))), limit_price=None, purpose="flatten",
            book_id=tick.book.book_id)
        consider(tick, state, guard, account_state, intent, broker, guards,
                 extra=(f"end of day close out, last price {price:.2f}" if price
                        else "end of day close out"))


def write_daily(tick: BookTick, state: bs.BookState, guard: gr.Guardrails) -> None:
    """The book's own end of day line, written once, at or after the close.

    A note on the Daily tab: it has no book column, on purpose, because it
    tracks the one paper account all five books share. So the per book figures
    go to the Rules Log, which does have a book column and which the Books tab
    slices on. The account level line is written once by whichever book is
    handled last, in main().
    """
    facts = bs.facts_for(state)
    summary = (f"end of day: worth {facts['equity']:,.2f} against "
               f"{facts['day_start_equity']:,.2f} at the open "
               f"({facts.get('day_pnl_pct', 0.0):+.3f} percent), "
               f"{facts['open_positions']} positions still open, "
               f"{facts['entries_opened_today']} opened today, "
               f"realised {facts['realized_pnl_today']:,.2f}, "
               f"model spend {state.model_cost_today:.4f} dollars")
    tick.say(summary)
    tick.record(state, "", "daily summary", summary,
                cost=state.model_cost_today or None)
    tick.rule("daily_summary", f"book {tick.book.book_id}: {summary}",
              "written at the close")
    state.daily_written = True


# ------------------------------------------------------------------ one book

def run_book(book: gr.BookConfig, guard: gr.Guardrails, now: datetime, guards: Guards,
             broker: broker_mod.Broker, account_id: str, broker_positions: dict,
             rules: str, write_ledger: bool, halt_reason: str | None = None,
             quiet: bool = False) -> tuple[BookTick, bs.BookState]:
    """One book's whole turn: work out the phase, do it, write the file."""
    tick = BookTick(book, now, rules, write_ledger, quiet=quiet)
    plan = plan_for(book, guard)
    day = now.date()
    state = bs.load_state(book.book_id, book.order_ref, day, capital=book.capital_usd)
    state.account_id = account_id

    if halt_reason:
        state.halt(halt_reason)

    bs.mark_positions(state, broker_positions)
    if not state.day_start_equity:
        state.day_start_equity = bs.book_equity(state) or float(book.capital_usd)

    account_state = bs.account_state_for(
        state, gr, now, account_id, guards.stop_present, broker_positions)

    phase, why = phase_for(now, plan, pick_done=state.picked_at is not None,
                           last_manage_at=state.last_manage_at, swept_at=state.swept_at)
    tick.phase = phase

    if not quiet:
        print(f"\n[{book.order_ref}] {book.name}")
        print(f"  mode {book.mode} | model {book.model or 'none'} | "
              f"strategy {plan.family} | phase {phase} ({why})")
        facts = bs.facts_for(state)
        print(f"  worth {facts['equity']:,.2f} of {facts['capital']:,.2f} capital | "
              f"{facts['open_positions']} open | {facts['entries_opened_today']} "
              f"entries today | rules {rules}")
        if state.halted:
            print(f"  HALTED: {state.halt_reason}")

    try:
        if phase == SWEEP:
            slot = sweep_due(now, plan, state.swept_at) or ""
            do_sweep(tick, state, plan, slot)
        elif phase == SCAN:
            do_scan(tick, state, plan)
        elif phase == PICK:
            do_pick(tick, state, plan, guard, broker, account_state, guards)
        elif phase == MANAGE:
            do_manage(tick, state, plan, guard, broker, account_state, guards)
        elif phase == FLATTEN:
            do_flatten(tick, state, plan, guard, broker, account_state, guards)
        elif phase == CLOSED:
            if now.weekday() < 5 and now.time() >= plan.market_close \
                    and not state.daily_written:
                write_daily(tick, state, guard)
            else:
                tick.say("Nothing to do. " + why)
        else:
            tick.say("Nothing to do yet. " + why)
    except Exception as exc:                 # noqa: BLE001
        # One book falling over must not cost the other four their tick.
        tick.note(f"this book's {phase} raised {type(exc).__name__}: {exc}")
        tick.rule("book_failed", f"the {phase} phase of book {book.book_id} raised "
                  f"{type(exc).__name__}: {exc}", "this book was skipped for this tick")

    state.tick_count += 1
    state.last_tick = now.isoformat()
    state.last_phase = phase
    path = bs.save_state(state)
    if not quiet:
        print(f"  {tick.would_be_orders} would be orders, {tick.approved} allowed, "
              f"{tick.refused} refused, {tick.sent} sent | state {path}")
    return tick, state


# ------------------------------------------------------------------ the driver

def tick_log_line(now: datetime, rules: str, book: gr.BookConfig, tick: BookTick,
                  state: bs.BookState) -> str:
    facts = bs.facts_for(state)
    return (f"{now:%Y-%m-%d %H:%M:%S} {now.tzname()} | book={book.book_id} | "
            f"rules={rules} | mode={book.mode} | phase={tick.phase} | "
            f"equity={facts['equity']:.2f} | positions={facts['open_positions']} | "
            f"picks={len(state.picks)} | would_be_orders={tick.would_be_orders} | "
            f"approved={tick.approved} | refused={tick.refused} | sent={tick.sent} | "
            f"halted={'yes' if state.halted else 'no'} | "
            f"model_cost={tick.model_cost:.4f} | notes={len(tick.notes)}")


def write_tick_log(lines: list[str]) -> Path:
    path = output_dir() / "loop.log"
    with path.open("a") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


def read_broker_facts(broker: broker_mod.Broker, wanted_account: str | None,
                      problems: list[str]) -> tuple[dict, dict, list, list]:
    """One read of the shared account, used by all five books.

    Read once per tick rather than once per book, because five books asking IB
    Gateway the same three questions in the same second is how a data pacing
    violation happens.
    """
    values: dict = {}
    holdings: dict = {}
    orders: list = []
    try:
        values = broker_mod.account_values(broker, wanted_account)
    except Exception as exc:                 # noqa: BLE001
        problems.append(f"could not read the account summary: {exc}")
    try:
        holdings = broker.portfolio(wanted_account) or {}
    except Exception as exc:                 # noqa: BLE001
        problems.append(f"could not read the positions: {exc}")
    try:
        orders = (broker.open_orders(wanted_account) or {}).get("orders", []) or []
    except Exception as exc:                 # noqa: BLE001
        problems.append(f"could not read the open orders: {exc}")

    positions = {}
    for row in (holdings.get("positions") or []):
        if isinstance(row, dict) and row.get("symbol"):
            positions[str(row["symbol"]).upper()] = row
    return values, positions, orders, problems


def main(argv: list[str] | None = None, broker: broker_mod.Broker | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One tick of the trading loop, across all five books. Dry run "
                    "only today: the mode comes from config/books.yaml and every "
                    "book in it is dry-run.")
    parser.add_argument("--now", metavar="WHEN",
                        help='pretend it is this time, New York time, for example '
                             '"2026-09-08 09:36". Lets a phase be tested after hours.')
    parser.add_argument("--book", metavar="ID",
                        help="run one book only, by its id, for example C")
    parser.add_argument("--write-ledger", action="store_true",
                        help="write the decisions to the real Google Sheet instead "
                             "of printing them")
    parser.add_argument("--books-file", default=str(books_yaml_path()),
                        help="which register of books to read")
    parser.add_argument("--dry-run", action="store_true",
                        help="accepted and ignored. Every book is already dry-run, "
                             "because that is what its mode in books.yaml says.")
    args = parser.parse_args(argv)

    guards = read_guards()
    if guards.loop_disabled_present:
        print(f"loop: {guards.loop_disabled} exists, so this tick does nothing at all.")
        print(f"      Remove it to start again: rm {guards.loop_disabled}")
        return 0

    try:
        registry = gr.load_books(args.books_file)
    except gr.GuardrailError as exc:
        print(f"loop: cannot read the register of books.\n{exc}", file=sys.stderr)
        return 2

    zone = ZoneInfo(registry.shared.timezone)
    now = parse_now(args.now, zone)
    rules = rules_commit()
    account_wanted = registry.shared.account_id

    books = [b for b in registry.enabled_books()]
    if args.book:
        wanted = str(args.book).strip().upper()
        books = [b for b in books if b.book_id == wanted]
        if not books:
            print(f"loop: there is no enabled book {wanted} in {args.books_file}. "
                  f"The enabled ones are "
                  f"{', '.join(b.book_id for b in registry.enabled_books())}.",
                  file=sys.stderr)
            return 2

    print("=" * 78)
    print(f"Tick at {now:%Y-%m-%d %H:%M:%S} {now.tzname()}"
          + ("  (pretend time from --now)" if args.now else ""))
    print(f"Rules {rules} | register {args.books_file} | "
          f"{len(books)} enabled book(s): {', '.join(b.book_id for b in books)}")
    print("=" * 78)

    if guards.stop_present:
        print(f"\nKILL SWITCH: {guards.stop} exists. Every book may close positions "
              "and none may open one.")
        print(f"  Remove it to resume: rm {guards.stop}")
    if guards.no_trade_present:
        print(f"\nNO TRADE TODAY: {guards.no_trade_today} exists. No book opens "
              "anything today. Closing orders still work.")

    if broker is None:
        broker = broker_mod.McpBroker(account=account_wanted)

    problems: list[str] = []
    values, broker_positions, broker_orders, problems = read_broker_facts(
        broker, account_wanted, problems)
    account_id = str((values.get("AccountOrGroup") or account_wanted or "")).strip() \
        or str(account_wanted or "")
    equity = _number(values.get("NetLiquidation"))

    for problem in problems:
        print(f"  note: {problem}")
    print(f"\nAccount {account_id}: worth {equity:,.2f}, "
          f"{len(broker_positions)} positions and {len(broker_orders)} working orders "
          "across all five books")

    if account_id and not account_id.upper().startswith(PAPER_ACCOUNT_PREFIX):
        print(f"STOP: the account is {account_id}, which does not start with "
              f"{PAPER_ACCOUNT_PREFIX}. Paper accounts do. Refusing to go further.",
              file=sys.stderr)
        ledger_writer.log_rule(now, "paper_account_only",
                               f"account {account_id} is not a paper account "
                               f"[rules {rules}]", "the whole tick stopped",
                               dry_run=not args.write_ledger)
        return 3

    # Reconciliation before anything else. If the books and the broker do not
    # agree about who owns what, sizing the next order is guesswork.
    books_state = {}
    for book in books:
        state = bs.load_state(book.book_id, book.order_ref, now.date(),
                              capital=book.capital_usd)
        books_state[book.book_id] = {
            "book_id": book.book_id, "order_ref": book.order_ref,
            "positions": state.positions, "working_orders": state.working_orders}

    outcome = run_reconciliation(list(broker_positions.values()), broker_orders,
                                 books_state, expected_orphans())
    print(f"\nReconciliation: {outcome.note}")
    if outcome.orphans:
        print(f"  {len(outcome.orphans)} position(s) or order(s) belong to no book: "
              f"{outcome.orphans}")
    halts: dict[str, str] = {}
    for book_id in outcome.books_to_halt:
        halts[str(book_id).upper()] = outcome.note
        ledger_writer.log_rule(
            now, "reconciliation", f"book {book_id}: {outcome.note} [rules {rules}]",
            "this book opens nothing until it is sorted out, and may still close "
            "positions", book_id=str(book_id), dry_run=not args.write_ledger)
    if halts:
        print(f"  halted this tick: {', '.join(sorted(halts))}")

    lines: list[str] = []
    totals = {"would_be": 0, "approved": 0, "refused": 0, "sent": 0, "cost": 0.0}
    any_daily = False

    for book in books:
        try:
            guard = gr.load_book_guardrails(args.books_file, book.book_id)
        except gr.GuardrailError as exc:
            print(f"\n[{book.order_ref}] cannot load this book's limits, so it is "
                  f"skipped this tick: {exc}")
            ledger_writer.log_rule(now, "book_settings_broken",
                                   f"book {book.book_id}: {exc} [rules {rules}]",
                                   "this book was skipped for this tick",
                                   book_id=book.book_id, dry_run=not args.write_ledger)
            continue

        tick, state = run_book(book, guard, now, guards, broker, account_id,
                               broker_positions, rules, args.write_ledger,
                               halt_reason=halts.get(book.book_id))
        lines.append(tick_log_line(now, rules, book, tick, state))
        totals["would_be"] += tick.would_be_orders
        totals["approved"] += tick.approved
        totals["refused"] += tick.refused
        totals["sent"] += tick.sent
        totals["cost"] += tick.model_cost
        any_daily = any_daily or state.daily_written

    if any_daily and equity > 0:
        # One line for the account, because the Daily tab has no book column.
        ledger_writer.upsert_daily(
            f"{now.date():%Y-%m-%d}", ending_equity=round(equity, 2),
            rules_triggered=(outcome.note if not outcome.ok else "none"),
            notes=(f"rules {rules}, {len(books)} books, {totals['would_be']} would be "
                   f"orders, {totals['sent']} sent"),
            model_cost_usd=round(totals["cost"], 4) or None,
            dry_run=not args.write_ledger)

    path = write_tick_log(lines)
    print("\n" + "=" * 78)
    for line in lines:
        print(line)
    print(f"Totals: {totals['would_be']} would be orders, {totals['approved']} allowed, "
          f"{totals['refused']} refused, {totals['sent']} sent, "
          f"{totals['cost']:.4f} dollars of model spend")
    print(f"Tick log {path}")
    if RECONCILE_ERROR:
        print(f"agent/reconcile.py is not there yet ({RECONCILE_ERROR}), so every book "
              "was halted this tick.")
    if PDT_ERROR:
        print(f"agent/pdt.py is not there yet ({PDT_ERROR}), so day trades are counted "
              "from the book files and the five day count is unknown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
