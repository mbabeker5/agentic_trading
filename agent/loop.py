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
which book it came from and which commit of the rules it ran under. What differs
between them is the clock and where the shortlist comes from:

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

    1. the book's mode in config/books.yaml is tiny or full. It is dry_run for
       all five, and a book cannot even be set to tiny or full without a
       promoted_on date and a rules_commit hash from the hub beside it.
    2. the environment variable AGENTIC_TRADING_LIVE_ORDERS is set to yes.
    3. the account id starts with DU, which is how IBKR names paper accounts.
    4. none of output/STOP, output/LOOP_DISABLED or output/NO_TRADE_TODAY exist.

Do not set that environment variable. Opening these locks is a decision for Mo
after the hub has approved a book, not a step in a script.

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

# Where the project lives is agent/paths.py's job and nobody else's. This file
# used to carry a second copy of the answer, written out as a path to Mo's
# laptop, which is a path that has to be edited on every new machine and which
# would quietly disagree with paths.py the day one of them was changed. Now it
# asks. paths.py works it out from where it sits on disk, so a plain git clone
# anywhere finds itself with nothing configured.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT_ENV_VAR, project_root  # noqa: E402,F401

PROJECT = project_root()
for _extra in (PROJECT, PROJECT / "agent", PROJECT / "ledger"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import book_state as bs                     # noqa: E402
import broker as broker_mod                 # noqa: E402
import decide as decide_mod                 # noqa: E402
import guardrails as gr                     # noqa: E402
import ledger_writer                        # noqa: E402

# Two modules another agent wrote alongside this one. The loop has to be safe
# whether or not they are there, so both are optional: a missing one degrades to
# the careful answer rather than to a crash. Both landed on 2026-09-06 and the
# real ones are used below.
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

# The pre-open run, which gathers what the 09:35 pick needs before the market is
# even open. Optional in exactly the same way as the two above: a missing one
# costs the pre-open work and nothing else, because every number it gathers has
# a slower fallback on the day. See docs/PREOPEN_FLOW.md.
try:
    import preopen as preopen_mod           # noqa: E402
    PREOPEN_ERROR: str | None = None
except Exception as exc:                    # noqa: BLE001
    preopen_mod = None                      # type: ignore[assignment]
    PREOPEN_ERROR = f"{type(exc).__name__}: {exc}"

# SQLite is the system of record and the Google Sheet is a nightly view of it,
# so every writer in this file goes to agent/db.py first and to the Sheet second.
# See docs/DATA.md. Optional in exactly the same way as the modules above,
# because a database that cannot be opened must not cost a tick: the loop is what
# holds the risk limits, and losing the record of a tick is a smaller problem
# than losing the management of a position.
try:
    import db as db_mod                       # noqa: E402
    DB_ERROR: str | None = None
except Exception as exc:                      # noqa: BLE001
    db_mod = None                             # type: ignore[assignment]
    DB_ERROR = f"{type(exc).__name__}: {exc}"

# How Mo hears about anything worth waking him for. Optional for the same
# reason: an alert that cannot be sent is a bad day, and a tick that stopped
# because an alert could not be sent is a worse one.
try:
    import alerts as alerts_mod               # noqa: E402
    ALERTS_ERROR: str | None = None
except Exception as exc:                      # noqa: BLE001
    alerts_mod = None                         # type: ignore[assignment]
    ALERTS_ERROR = f"{type(exc).__name__}: {exc}"

LIVE_ENV_VAR = "AGENTIC_TRADING_LIVE_ORDERS"
PAPER_ACCOUNT_PREFIX = "DU"
LIVE_MODES = ("tiny", "full")

# Which phase a book is in. One word each, because they end up in log lines.
IDLE, SWEEP, SCAN, PICK, MANAGE, FLATTEN, CLOSED, PREOPEN = (
    "idle", "sweep", "scan", "pick", "manage", "flatten", "closed", "preopen")

MOMENTUM, INSIDER, CONGRESS = "momentum", "insider", "congress"

# A book only wakes for a sweep inside this many minutes of the sweep time, so a
# tick at 07:03 still counts as the 07:00 sweep and one at 09:00 does not.
SWEEP_WINDOW_MINUTES = 20

# A shortlist file younger than this is used as it stands. All three momentum
# books share one scanner run, so whichever ticks first pays for it and the
# other two read the file it wrote.
SHORTLIST_FRESH_MINUTES = 10

# Only used when agent/pdt.py cannot be imported. Normally the hard limit comes
# from pdt.hard_limit in each book's own strategy.yaml, which is true for the
# insider and Congress books and false for the three momentum ones.
DAY_TRADE_HARD_LIMIT_BOOKS = ("C", "D")


# --------------------------------------------------------------- small things

def output_dir() -> Path:
    path = project_root() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------ the written record

#: Database problems already complained about in this process, so a tick that
#: writes a dozen rows does not print the same sentence a dozen times. Twelve
#: copies of one complaint is how a real message gets lost.
_DB_TROUBLE: set[str] = set()


def _db_trouble(message: str) -> None:
    """Say a database write did not happen, once per process per problem."""
    if message in _DB_TROUBLE:
        return
    _DB_TROUBLE.add(message)
    print(f"loop: {message}. The tick carries on and the Sheet still has it.",
          file=sys.stderr)


def db_call(name: str, *args, **kwargs) -> Any:
    """Call one agent/db.py writer, and never let it stop a tick.

    SQLite is the system of record since 2026-09-06 and the Google Sheet is a
    nightly view of it (docs/DATA.md), so every writer in this file comes here
    first and writes to the Sheet second. The Sheet writes stay for now, until
    the nightly sync in ledger/sync_sheet.py takes over.

    agent/db.py already turns an ordinary database error into a warning and a
    None, on purpose. This catches everything else: a module that would not
    import, a schema nobody migrated, a bad argument. Recording what happened
    must never be the thing that stops the loop, because the loop is what holds
    the risk limits.
    """
    if db_mod is None:
        _db_trouble(f"agent/db.py could not be imported ({DB_ERROR}), so nothing "
                    "is being written to the database")
        return None
    writer = getattr(db_mod, name, None)
    if writer is None:
        _db_trouble(f"agent/db.py has no {name}(), so that row is not being written")
        return None
    try:
        return writer(*args, **kwargs)
    except Exception as exc:                 # noqa: BLE001
        _db_trouble(f"db.{name}() raised {type(exc).__name__}: {exc}")
        return None


#: Touched at the end of every tick that got all the way through. The dead man's
#: handle in agent/deadman.py prefers this file over guessing at the loop's
#: pulse from log files, because a log line can be written by a tick that then
#: fell over, and this one is only written when the tick finished.
HEARTBEAT_FILE = "heartbeat"


def touch_heartbeat(when: datetime | None = None) -> Path:
    """Say the loop got all the way through a tick, by touching one file.

    agent/deadman.py reads output/heartbeat and pulls the kill switch when it is
    more than fifteen minutes old during market hours, so a loop that dies
    holding something does not sit there unwatched. It falls back to reading log
    files when this is missing, which is a guess; this file is the real answer.

    Written last, on purpose. A tick that fell over halfway must not leave a
    fresh heartbeat behind saying everything is fine.
    """
    path = output_dir() / HEARTBEAT_FILE
    stamp = (when or datetime.now(ZoneInfo("America/New_York"))).isoformat()
    path.write_text(f"{stamp}\n")
    return path


def books_yaml_path() -> Path:
    return project_root() / "config" / "books.yaml"


def rules_commit() -> str:
    """The short git hash of the rules this tick ran under.

    Every log line and every ledger row carries it, so a month later a decision
    can be read against the exact limits that were in force when it was made.
    Comes back as "unknown" outside a git checkout rather than raising, because
    not knowing the hash is no reason to skip a tick.
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


# --------------------------------------------------------- what each book does

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
    vwap_fade_closes: int = 0
    vwap_fade_acts: bool = False
    flatten_market_at: clock_time | None = None
    preopen_start: clock_time | None = None


def family_for(book: gr.BookConfig) -> str:
    """Which of the three strategies this book runs, from its folder name."""
    folder = Path(str(book.strategy_dir)).name.lower()
    if INSIDER in folder:
        return INSIDER
    if CONGRESS in folder:
        return CONGRESS
    return MOMENTUM


def _clock(text: Any) -> clock_time:
    return datetime.strptime(str(text).strip(), "%H:%M").time()


def vwap_fade_acts_for(book: gr.BookConfig) -> bool:
    """Does a VWAP fade actually close a position, or is it only written down?

    Momentum v2, item D2, approved by Mo on 2026-09-06. In month one it is
    written down and acted on never. The fade rule comes from a different
    published strategy and grafting it on as an exit was never tested, so month
    one measures the pick and records what the fade would have cost or saved.

    risk.vwap_fade_action in the book's own strategy.yaml is the switch:
    log_only, which is what the momentum books say today, or exit, which puts
    the old behaviour back in one edit.
    """
    try:
        params, _ = decide_mod.load_params(project_root() / str(book.strategy_dir))
        return str(params.get("vwap_fade_action") or "exit").strip().lower() == "exit"
    except Exception:                            # noqa: BLE001
        return True


def vwap_fade_closes_for(book: gr.BookConfig) -> int:
    """How many closes the wrong side of VWAP this book calls a fade.

    One number in one place. risk.vwap_fade_closes in the book's strategy.yaml
    is both what the code fires on and what {{vwap_fade_closes}} renders into
    the prompt, so the sentence the model reads and the rule the code applies
    cannot drift apart. A book with no such key, which is every book except the
    momentum three, gets zero and the fade rule is off for it.
    """
    try:
        params, _ = decide_mod.load_params(project_root() / str(book.strategy_dir))
        return max(0, int(params.get("vwap_fade_closes") or 0))
    except Exception:                            # noqa: BLE001
        return 0


def plan_for(book: gr.BookConfig, guard: gr.Guardrails) -> BookPlan:
    """The book's timetable, read from its own settings.

    The sweep times come from the sweep block of the strategy file, which the
    guardrails carry through untouched because they are not order limits. A book
    with no sweep block falls back to the times written in
    docs/STRATEGY_INSIDER.md and docs/STRATEGY_CONGRESS.md.
    """
    family = family_for(book)
    schedule = guard.schedule
    sweep = guard.sweep or {}

    if family == INSIDER:
        times = tuple(_clock(sweep.get(key) or fallback) for key, fallback in
                      (("morning_sweep_at", "07:00"), ("afternoon_sweep_at", "16:30")))
        script, prefix = "sweep_insider.py", "insider_shortlist"
    elif family == CONGRESS:
        times = (_clock(sweep.get("disclosure_sweep_at") or "07:30"),)
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
        vwap_fade_closes=(vwap_fade_closes_for(book) if family == MOMENTUM else 0),
        vwap_fade_acts=(vwap_fade_acts_for(book) if family == MOMENTUM else True),
        flatten_market_at=schedule.flatten_market_at,
        preopen_start=(schedule.preopen_start if family == MOMENTUM else None),
    )


def manage_due(now: datetime, last_manage_at: str | datetime | None,
               minutes: int) -> bool:
    """Is this book due for a look at its positions?

    The loop wakes every five minutes for everybody. A book on a thirty minute
    clock only looks every sixth wake up, and it works that out from when it
    last looked rather than from the minute hand, so a tick missed because the
    Mac was asleep does not push the whole day out of step.
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
    # A minute of slack, so a tick landing a few seconds early still counts.
    return (now - when).total_seconds() >= max(0, int(minutes) * 60 - 60)


def sweep_due(now: datetime, plan: BookPlan, swept_at: dict | None) -> str | None:
    """Which sweep slot this tick belongs to, or None.

    A slot is named by its time, "07:00". Once a sweep has run for that slot
    today it does not run again, however many ticks land inside the window.
    """
    for moment in plan.sweep_times:
        slot = f"{moment:%H:%M}"
        if (swept_at or {}).get(slot):
            continue
        start = datetime.combine(now.date(), moment, tzinfo=now.tzinfo)
        if start <= now < start + timedelta(minutes=SWEEP_WINDOW_MINUTES):
            return slot
    return None


def phase_for(now: datetime, plan: BookPlan, *, pick_done: bool = False,
              last_manage_at: str | datetime | None = None,
              swept_at: dict | None = None) -> tuple[str, str]:
    """Which part of the day this is for one book, and a sentence saying why.

    Deliberately takes plain values rather than a state object, so every branch
    can be tested in two lines with no files on disk.
    """
    swept_at = swept_at or {}
    moment = now.time()

    if now.weekday() >= 5:
        return CLOSED, "it is the weekend, the US market is shut"

    slot = sweep_due(now, plan, swept_at)
    if slot is not None:
        return SWEEP, f"the {slot} sweep for this book has not run yet today"

    if plan.runs_scanner and plan.preopen_start is not None \
            and plan.preopen_start <= moment < plan.scan_start:
        return PREOPEN, (f"the pre-open run works from {plan.preopen_start:%H:%M} so "
                         "the ranking is ready at the open")
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

#: Written by agent/kill_switch.py when it has flattened the account, so the
#: next tick knows the difference between "somebody pulled the handle" and "the
#: books have lost track of what they hold".
KILL_SWITCH_FLATTENED_FILE = "KILL_SWITCH_FLATTENED"


def kill_switch_flattened(root: Path | None = None) -> bool:
    """Has the kill switch flattened the account since the last tick?

    The kill switch closes everything at the broker and cannot open the five
    book files to say so, because it acts through the broker on purpose so that
    it still works when the loop is dead. So the books wake up believing they
    hold positions the account no longer has, which is exactly the shape of a
    reconciliation mismatch, and a mismatch halts a book for the day.

    Halting for the day would be the wrong answer here. Nothing has gone wrong
    and nobody has lost track of anything: somebody pulled the handle and it
    worked. So the next tick marks those positions closed by the kill switch,
    writes it down, and carries on with the books flat.
    """
    folder = (root or project_root()) / "output"
    for name in (KILL_SWITCH_FLATTENED_FILE, "STOP", "LOOP_DISABLED"):
        if (folder / name).exists():
            return name == KILL_SWITCH_FLATTENED_FILE or _stop_flattened(folder)
    return False


def _stop_flattened(folder: Path) -> bool:
    """True when the stop file itself says the account was flattened.

    agent/kill_switch.py writes a line into output/STOP saying what it did. A
    stop file somebody made by hand with `touch` holds nothing, and that is not
    a flatten, so the books are left exactly as they were.
    """
    try:
        text = (folder / "STOP").read_text().lower()
    except OSError:
        return False
    return "flatten" in text or "closed" in text


def close_positions_flattened_by_the_kill_switch(
        tick: BookTick, state: bs.BookState,
        broker_positions: dict[str, dict]) -> int:
    """Mark this book's positions closed because the kill switch closed them.

    Only ever touches a position the ACCOUNT no longer holds. A name the broker
    still reports is left alone, because that one really is a mismatch and the
    reconciliation should still halt the book over it.

    Returns how many were closed, so the caller can say so in one line.
    """
    closed = 0
    for symbol, position in list(state.all_positions().items()):
        if _number((broker_positions.get(symbol) or {}).get("position")):
            continue
        price = _number(position.last_close) or _number(position.avg_cost)
        direction = 1.0 if position.qty > 0 else -1.0
        state.realized_pnl_today = round(
            state.realized_pnl_today
            + (price - position.avg_cost) * abs(position.qty) * direction, 2)
        state.drop_position(symbol)
        state.working_orders = {
            order_id: order for order_id, order in (state.working_orders or {}).items()
            if not isinstance(order, dict)
            or str(order.get("symbol") or "").upper() != symbol}
        tick.rule("kill_switch_flattened",
                  f"{symbol}: the kill switch closed this position at the broker, "
                  f"so the book is marked flat in it at {price:.2f}",
                  "closed by the kill switch, not a reconciliation mismatch")
        tick.record(state, symbol, "closed by the kill switch",
                    "the kill switch flattened the account and this position is no "
                    "longer at the broker, so the book file was brought into line "
                    "rather than halted over the difference")
        closed += 1
    return closed


@dataclass
class ReconcileOutcome:
    """What the reconciliation said, in the shape this loop acts on."""

    available: bool
    ok: bool
    books_to_halt: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    orphans: list = field(default_factory=list)
    note: str = ""


def expected_orphans(root: Path | None = None) -> Any:
    """Positions the books already know nobody will claim.

    The paper account holds one share of SPY from the manual test on 2026-09-02
    and no book owns it. Without a list like this, every single tick would report
    it and halt all five books. Write output/expected_orphans.json as either
    ["SPY"], which forgives any quantity, or {"SPY": 1}, which forgives that
    exact quantity and complains again if it changes.
    """
    path = ((root or project_root()) / "output" / "expected_orphans.json")
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
    except Exception:                        # noqa: BLE001
        return None
    return loaded if isinstance(loaded, (list, dict)) else None


def broker_positions_for_reconcile(rows: dict[str, dict]) -> list[dict]:
    """The account's holdings in the three fields agent/reconcile.py reads."""
    return [{"symbol": symbol,
             "qty": int(round(_number(row.get("position")))),
             "avg_cost": round(_number(row.get("avgCost")), 4)}
            for symbol, row in rows.items()]


def broker_orders_for_reconcile(rows: list[dict]) -> list[dict]:
    """The account's working orders in the five fields agent/reconcile.py reads."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append({
            "orderId": row.get("orderId") or row.get("order_id"),
            "symbol": row.get("symbol"),
            "side": row.get("action") or row.get("side"),
            "qty": row.get("totalQuantity") or row.get("qty") or row.get("remaining"),
            "order_ref": row.get("orderRef") or row.get("order_ref"),
        })
    return out


def run_reconciliation(broker_positions: list, broker_open_orders: list,
                       books_state: dict, orphans: Any) -> ReconcileOutcome:
    """Ask agent/reconcile.py whether the books and the broker agree.

    Five books share one account, so the only thing saying which book owns a
    position is the tag on the order that opened it. If the book files and the
    broker disagree, nobody knows who owns what and sizing the next order would
    be guesswork, so a mismatch halts the book it belongs to.

    When that module is missing, or its answer cannot be read, every book is
    halted for the tick. A halted book still closes positions, because refusing
    to close is its own kind of risk, and it opens nothing.
    """
    if reconcile_mod is None or getattr(reconcile_mod, "reconcile", None) is None:
        return ReconcileOutcome(
            available=False, ok=False, books_to_halt=list(books_state),
            note=("reconciliation unavailable, halting all books: agent/reconcile.py "
                  f"could not be imported "
                  f"({RECONCILE_ERROR or 'it has no reconcile function'})"))

    function = reconcile_mod.reconcile
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
    halt = [str(b) for b in (getattr(report, "books_to_halt", ()) or ())]
    lines = list(getattr(report, "lines", ()) or ())
    found = list(getattr(report, "orphans", ()) or ())
    note = str(getattr(report, "summary", "")) or (
        "everything matched" if ok else "the books and the broker disagree")
    if not ok and not halt and not found:
        # It said no but named no book, so the safe reading is all of them.
        halt = list(books_state)
    return ReconcileOutcome(available=True, ok=ok, books_to_halt=halt,
                            lines=lines, orphans=found, note=note)


# ---------------------------------------------------------- the day trade count

@dataclass
class DayTradeVerdict:
    """Whether closing this position today is a day trade, and whether that stops it."""

    is_day_trade: bool
    blocked: bool
    reason: str
    used: int | None = None
    would_have_blocked: bool = False


def make_day_trade_counter(guard: gr.Guardrails):
    """The day trade counter for one book, or None when agent/pdt.py is missing."""
    if pdt_mod is None:
        return None
    try:
        return pdt_mod.counter_for(guard)
    except Exception:                        # noqa: BLE001
        return None


def day_trade_check(guard: gr.Guardrails, intent: gr.OrderIntent, today: date_type,
                    counter, opened_on: str = "") -> DayTradeVerdict:
    """Would this closing order be a day trade, and does that matter for this book?

    A day trade is buying and selling the same name on the same day. The count
    that matters is how many the book has made in the last five business days,
    and that lives in agent/pdt.py, which keeps one small file per book.

    Whether going over the line refuses the order or merely notes it is the
    pdt.hard_limit setting in each book's own strategy.yaml. It is true on the
    insider and Congress books, which hold for weeks, so a same day round trip in
    one of them is a mistake and is refused. It is false on the three momentum
    books, which day trade on purpose, so it is written down and allowed. This is
    the only check in the project that can refuse an order which closes a
    position.
    """
    book_id = guard.book_id or "?"
    if counter is not None:
        try:
            decision = counter.check(guard, intent, today)
        except Exception as exc:             # noqa: BLE001
            return DayTradeVerdict(
                False, False,
                f"the day trade counter could not answer ({type(exc).__name__}: {exc}), "
                "so this order was let through and the count is unknown")
        allowed = bool(getattr(decision, "allowed", True))
        reasons = list(getattr(decision, "reasons", []) or [])
        flagged = bool(getattr(decision, "would_have_blocked", False))
        return DayTradeVerdict(
            is_day_trade=(not allowed) or flagged or bool(reasons),
            blocked=not allowed,
            reason="; ".join(reasons) or "not a day trade",
            used=getattr(decision, "day_trades_used", None),
            would_have_blocked=flagged)

    # No counter. The book file still knows whether this position was opened
    # today, which is the day trade test; what it cannot know is how many day
    # trades came before it, which is the number the rule counts. So it is noted
    # and let through: refusing to close a position on the strength of a missing
    # counter is the more dangerous mistake.
    same_day = bool(opened_on) and str(opened_on)[:10] == f"{today:%Y-%m-%d}"
    if not same_day:
        return DayTradeVerdict(False, False,
                               "not a day trade, this position was not opened today")
    hard = bool(getattr(getattr(guard, "pdt", None), "hard_limit",
                        str(book_id).upper() in DAY_TRADE_HARD_LIMIT_BOOKS))
    return DayTradeVerdict(
        True, False,
        f"this would be a day trade in book {book_id}"
        + (", which is meant to hold for weeks" if hard
           else ", which day trades on purpose")
        + f", and agent/pdt.py is not loaded ({PDT_ERROR}), so the five day count is "
          "not known. Letting it through and writing it down.")


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
    path = project_root() / "agent" / str(script)
    python = project_root() / "venv312" / "bin" / "python"
    if not script or not path.exists():
        return False, f"{path} does not exist, so the shortlist stays as it is"
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
    if not out.get("company"):
        out["company"] = out.get("issuer_name") or out.get("asset_description") or ""
    if out.get("cluster_count") and not out.get("cluster_size"):
        out["cluster_size"] = out["cluster_count"]
    if out.get("crowd_count") and not out.get("crowding"):
        out["crowding"] = out["crowd_count"]
    return out


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


#: IBKR's halted tick is tick type 49. It comes back as a number: 0 means not
#: halted, 1 means halted, and 2 means halted with a common reason. Anything
#: else, or nothing at all, means nobody told us, and the guardrails refuse an
#: entry on an unknown halt status rather than reading it as clean.
HALTED_TICK_KEYS = ("halted", "halted_tick", "tick49", "tick_49")

#: A name sitting in a limit-up limit-down band is one step away from a
#: volatility halt. IBKR reports the band's own high and low limit prices, so
#: the tell is a last price sitting at or beyond one of them.
LIMIT_BAND_HIGH_KEYS = ("limitUpPrice", "limit_up_price", "highLimitPrice",
                        "auctionHighLimit")
LIMIT_BAND_LOW_KEYS = ("limitDownPrice", "limit_down_price", "lowLimitPrice",
                       "auctionLowLimit")


def _first_present(row: dict, keys: tuple[str, ...]):
    """The first of these keys that carries anything at all, or None."""
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def halted_from(row: dict | None) -> bool | None:
    """Is this name halted right now, from IBKR's halted tick? None means unknown.

    Tick type 49. Zero is trading, anything above zero is halted. A missing
    answer comes back as None and NOT as False, because the whole point of the
    halted rule in agent/guardrails.py is that an unknown halt status stops an
    entry rather than being read as a clean name. Handing it False would quietly
    turn that rule off.
    """
    if not isinstance(row, dict):
        return None
    raw = _first_present(row, HALTED_TICK_KEYS)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        return float(raw) > 0
    except (TypeError, ValueError):
        return None


def limit_state_from(row: dict | None) -> bool | None:
    """Is this name sitting in a limit-up limit-down band? None means unknown.

    IBKR reports the band as a pair of prices, so the test is whether the last
    price has reached one of them. A quote that carries no band at all comes
    back as None, which the guardrails refuse an entry on for the same reason as
    an unknown halt.
    """
    if not isinstance(row, dict):
        return None
    high = _first_present(row, LIMIT_BAND_HIGH_KEYS)
    low = _first_present(row, LIMIT_BAND_LOW_KEYS)
    if high is None and low is None:
        return None
    last = snapshot_price(row)
    if last is None:
        return None
    top = _number(high, 0.0)
    bottom = _number(low, 0.0)
    if top > 0 and last >= top:
        return True
    if bottom > 0 and last <= bottom:
        return True
    return False


def tradeable_now(broker: broker_mod.Broker, row: dict,
                  notes: list[str]) -> tuple[bool | None, str | None]:
    """Ask the broker whether this name is tradeable at all right now.

    Comes back as (halted, limit_state), passing on exactly what IBKR said,
    unknowns included. A quote that could not be fetched at all gives (None,
    None), which stops an entry, and that is the designed answer: deciding to
    buy a name without knowing whether it is even trading is the failure this
    rule exists to prevent.
    """
    try:
        answer = broker.snapshot([contract_for(row)]) or {}
    except Exception as exc:                     # noqa: BLE001
        notes.append(f"{row.get('symbol')}: the halt status could not be read "
                     f"({exc}), so no new position is opened in it")
        return None, None
    rows = answer.get("snapshots") or answer.get("quotes") or []
    quote = next((r for r in rows if isinstance(r, dict)), None)
    return halted_from(quote), limit_state_from(quote)


def snapshot_price(row: dict | None) -> float | None:
    """The most useful price in a snapshot: last, then the mark, then the close."""
    if not isinstance(row, dict):
        return None
    for key in ("last", "marketPrice", "close"):
        value = _number(row.get(key), -1.0)
        if value > 0:
            return round(value, 4)
    return None


# ------------------------------------------- what happened before today

@dataclass(frozen=True)
class LossHistory:
    """This book's recent record, for the limits beyond the day (item A8).

    week_pnl and month_pnl are money, not percentages: what the book has made or
    lost so far this calendar week and this calendar month, today included.
    losing_days is how many trading days IN A ROW it has finished down, counting
    backwards from the last completed day. Today is not counted, because today
    is not finished.
    """

    week_pnl: float = 0.0
    month_pnl: float = 0.0
    losing_days: int = 0


def _day_of(path: Path) -> date_type | None:
    """The date out of a state file name, or None when it does not carry one."""
    try:
        return datetime.strptime(path.stem.split("_")[-1], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def read_day_results(order_ref: str, today: date_type,
                     root: Path | None = None) -> list[tuple[date_type, float]]:
    """What this book realised on each day it has a state file for, oldest first.

    One file per book per day is the only record of a book's own money, because
    the shared account nets all five together and cannot answer "how did book A
    do". Realised profit and loss is what is read: a book that is flat at the
    close, which the momentum books always are, has nothing else left over.
    """
    folder = (root / "output") if root is not None else output_dir()
    out: list[tuple[date_type, float]] = []
    for path in sorted(folder.glob(f"state_{order_ref}_*.json")):
        day = _day_of(path)
        if day is None or day > today:
            continue
        try:
            stored = json.loads(path.read_text())
        except Exception:                        # noqa: BLE001
            continue
        if isinstance(stored, dict):
            out.append((day, _number(stored.get("realized_pnl_today"))))
    return out


def loss_history(order_ref: str, today: date_type, today_pnl: float = 0.0,
                 root: Path | None = None) -> LossHistory:
    """This week, this month, and the run of losing days behind them. Item A8.

    Momentum v2, approved by Mo on 2026-09-06. Without a rule beyond the day a
    book could lose one percent every day for a fortnight and nothing would ever
    notice, so the loop works these three numbers out from the book's own state
    files and hands them to the guardrails, which own the actual limits.

    The week runs Monday to Sunday and the month is a calendar month, because
    those are the weeks and months a person means. Today's own figure is passed
    in rather than read off disk, since the file for today is written at the end
    of the tick and would otherwise always be one tick stale.
    """
    week_start = today - timedelta(days=today.weekday())
    week = today_pnl
    month = today_pnl
    earlier = [(day, pnl) for day, pnl in read_day_results(order_ref, today, root)
               if day != today]
    for day, pnl in earlier:
        if day >= week_start:
            week += pnl
        if (day.year, day.month) == (today.year, today.month):
            month += pnl

    streak = 0
    for _, pnl in reversed(earlier):
        if pnl < 0:
            streak += 1
        else:
            break
    return LossHistory(round(week, 2), round(month, 2), streak)


# ------------------------------------------------------------------- the tick

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
        # How long until this book wants looking at again, in seconds. Thirty
        # between 09:35 and 11:00 while it is holding something, five minutes
        # otherwise (item A14, Mo 2026-09-06). run_book fills it in at the end
        # of the tick and main() writes the smallest across every book into
        # output/next_tick_seconds for the wrapper to read.
        self.next_tick_seconds = 300

    @property
    def tag(self) -> str:
        return self.book.order_ref

    @property
    def dry(self) -> bool:
        """True when this book writes down what it would do and sends nothing."""
        return str(self.book.mode).replace("-", "_").lower() not in LIVE_MODES

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
        """Write one judgement to the book's file, the database and the Sheet.

        The database first, because it is the system of record and it is a file
        on the same disk. The Sheet second, because it is a network call and it
        is a nightly view of the database rather than the truth. See
        docs/DATA.md. The Sheet write stays until ledger/sync_sheet.py takes
        that job over.
        """
        state.note_decision(self.now.isoformat(), symbol, decision, rationale,
                            phase=self.phase, rules_commit=self.rules)
        db_call("record_decision", ts=self.now, book_id=self.book.book_id,
                shape=self.phase, rules_commit=self.rules, symbol=symbol or None,
                action=decision, rationale=rationale, prompt_hash=prompt_hash or None,
                model=model if model is not None else (self.book.model or "none"),
                cost_usd=(None if cost is None else _number(cost)))
        ledger_writer.log_decision(
            self.now, symbol, decision, f"{rationale} [rules {self.rules}]",
            mode=str(self.book.mode), book_id=self.book.book_id,
            model=model if model is not None else (self.book.model or "none"),
            model_cost_usd=cost, prompt_hash=prompt_hash,
            dry_run=not self.write_ledger)

    def rule(self, rule_id: str, detail: str, action: str) -> None:
        """Write one guardrail firing to the database and to the Rules Log.

        In the database a guardrail firing is a decisions row marked rejected
        with the rule's own id in reject_reason, which is what db.rules_log_rows
        reads back out as the Rules Log and what the month end count of which
        limit actually bit is built from.
        """
        db_call("record_decision", ts=self.now, book_id=self.book.book_id,
                shape=self.phase, rules_commit=self.rules,
                symbol=_symbol_in(detail), action=action, rationale=detail,
                rejected=True, reject_reason=rule_id,
                model=self.book.model or "none")
        ledger_writer.log_rule(
            self.now, rule_id, f"{detail} [rules {self.rules}]", action,
            book_id=self.book.book_id, dry_run=not self.write_ledger)


#: Refusals that cannot turn into a yes again today for this book and this name,
#: so the pick is put down rather than worked out again on every tick.
#:
#: Deliberately short. A rule only belongs here when nothing that happens later
#: in the day could change its answer. symbol_exclusive is the case that forced
#: it: with universe.symbol_exclusive on, the name belongs to another book until
#: that book lets go of it, and re-asking every five minutes writes the same
#: sentence into the ledger forty times over and answers nothing. The first gate
#: run showed exactly that shape, with one rule refusing fifty seven orders in a
#: day, which reads as a stopped machine rather than a guardrail doing its job.
#:
#: sector_cap, max_open_positions, gross_exposure_cap and the loss caps are all
#: deliberately NOT here. Closing a position changes every one of them, and a
#: pick refused for want of room is meant to get another look once room appears.
SETTLED_FOR_THE_DAY = ("symbol_exclusive", "blacklist", "whitelist",
                       "sec_type", "currency", "no_shorts")


def settled_refusal(decision: gr.Decision) -> str | None:
    """The first refusal on this decision that will not change again today."""
    for rule_id in decision.rule_ids:
        if rule_id in SETTLED_FOR_THE_DAY:
            return rule_id
    return None


def put_the_pick_down(tick: BookTick, state: bs.BookState, symbol: str,
                      decision: gr.Decision) -> None:
    """Stop re-asking about a pick whose refusal is settled for the day."""
    settled = settled_refusal(decision)
    if not settled:
        return
    row = state.triggered.get(symbol)
    if isinstance(row, dict):
        row["skipped"] = settled
    tick.note(f"{symbol}: refused by {settled}, and that answer cannot change "
              "again today, so this pick is put down rather than worked out "
              "again on every tick")


def _symbol_in(detail: str) -> str | None:
    """The ticker a guardrail line starts with, when it starts with one.

    Every rule() call in this file writes "SYMBOL: what happened", so the name
    is there to be lifted into its own column rather than left buried in a
    sentence. A line that does not begin that way, such as a daily summary,
    gets None, which is the honest answer.
    """
    head = str(detail or "").split(":", 1)[0].strip()
    if head and 1 <= len(head) <= 6 and head.replace(".", "").isalnum() \
            and head.upper() == head:
        return head
    return None


def describe(intent: gr.OrderIntent) -> str:
    """One line describing a would be order, in words."""
    where = f"limit {intent.limit_price:.2f}" if intent.limit_price else "at market"
    return (f"{intent.side} {intent.qty} {intent.symbol} {where} "
            f"(purpose: {intent.purpose})")


def live_locks(book: gr.BookConfig, account_id: str,
               guards: Guards) -> tuple[bool, list[str]]:
    """The four locks on the live order path. All four, or nothing is sent.

    Returns whether every lock is open, and the list of the ones that are shut.
    Today every book is in dry_run mode and the environment variable is not set,
    so at least two of them are always shut.
    """
    shut: list[str] = []
    mode = str(book.mode).replace("-", "_").lower()
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
             cost: Any = None, prompt_hash: str = "", stop: float = 0.0,
             target: float = 0.0) -> gr.Decision:
    """Put one would be order through every check, and write down the answer.

    This is the only route from "this book thinks it should trade" to anything
    else happening, and in dry run it stops at the printed line, which is where
    it stops today for all five books.

    stop and target are the protective levels an entry is opened with. They are
    printed as their own lines in a dry run and sent as the bracket's children
    in the live path, so a rehearsal shows exactly the three orders the real
    thing would send.
    """
    tick.would_be_orders += 1
    decision = gr.check_order(guard, account_state, intent)
    summary = describe(intent) + (f" {extra}" if extra else "")
    verdict = ("allowed by the guardrails" if decision.allowed
               else "refused by the guardrails")
    because = ("; ".join(decision.reasons)
               or ("no limit was breached" if decision.allowed else "no reason given"))

    if decision.allowed:
        tick.approved += 1
    else:
        tick.refused += 1

    open_locks, shut = live_locks(tick.book, account_state.account_id, guards)

    if tick.dry or not open_locks or not decision.allowed:
        tick.say(f"DRY RUN {tick.tag} would place {summary}")
        if intent.purpose == "entry":
            for line in bracket_lines(intent, stop, target,
                                      guard.order_ref or tick.tag):
                tick.say(f"    leg: {line}")
        tick.say(f"  guardrails: {verdict}. {because}"
                 + (f" [rules: {', '.join(decision.rule_ids)}]"
                    if decision.rule_ids else ""))
        if decision.allowed:
            tick.say("  nothing was sent to the broker: " + "; ".join(shut))
        tick.record(state, intent.symbol, f"would place {summary}",
                    f"{verdict}. {because}", model=model, cost=cost,
                    prompt_hash=prompt_hash)
        # The order that was not sent is written down too. A month of the orders
        # a dry run would have sent is the whole of what a dry run is for, and
        # it is worthless if it only lives in a log file. See docs/DATA.md.
        record_order_row(tick, guard, intent, stop=stop,
                         status=("refused" if not decision.allowed else "dry_run"))
        for rule_id, reason in zip(decision.rule_ids, decision.reasons):
            tick.rule(rule_id, f"{intent.symbol}: {reason}", "the order was not placed")
        return decision

    # Not reachable today. All four locks would have to be open at once, and the
    # first of them needs a book promoted by hand with the hub's approval on it.
    result = submit(tick, state, intent, broker, guard, stop=stop, target=target)
    tick.record(state, intent.symbol, f"placed {summary}",
                f"{verdict}. {because}. The broker confirmed by "
                f"{result.get('confirmed_by')}",
                model=model, cost=cost, prompt_hash=prompt_hash)
    return decision


def record_order_row(tick: BookTick, guard: gr.Guardrails, intent: gr.OrderIntent,
                     stop: float = 0.0, status: str = "dry_run",
                     broker_order_id: Any = None,
                     oca_group: str | None = None) -> int | None:
    """One order into the database, sent or only worked out. Returns its row id.

    Written in dry run too, and that is the point rather than an oversight: all
    five books are on dry run, so the orders they did not send are the entire
    result so far. status says which this was, one of dry_run, refused,
    submitted, filled, cancelled or rejected.
    """
    return db_call(
        "record_order", ts=tick.now, book_id=tick.book.book_id,
        order_ref=guard.order_ref or tick.tag, broker_order_id=broker_order_id,
        oca_group=oca_group, symbol=intent.symbol, side=intent.side,
        qty=int(intent.qty),
        order_type=("LMT" if intent.limit_price else "MKT"),
        limit_price=intent.limit_price, stop_price=(_number(stop) or None),
        tif="DAY", purpose=intent.purpose, status=status)


def order_dict(intent: gr.OrderIntent) -> dict:
    """One OrderIntent as the plain IBKR order dictionary the broker takes."""
    order: dict[str, Any] = {
        "action": intent.side,
        "totalQuantity": int(intent.qty),
        "orderType": "LMT" if intent.limit_price else "MKT",
        "tif": "DAY",
    }
    if intent.limit_price:
        order["lmtPrice"] = round(float(intent.limit_price), 2)
    return order


def _other_side(side: str) -> str:
    return "SELL" if str(side).upper() == "BUY" else "BUY"


def child_orders(intent: gr.OrderIntent, stop: float,
                 target: float) -> tuple[dict | None, dict | None]:
    """The two protective legs that hang off an entry: the stop, and the target.

    Both are on the opposite side to the entry and for the same number of
    shares, because their whole job is to close what the entry opened.

    The stop leaves here as a plain STP, with the trigger price on auxPrice, and
    agent/broker.py turns it into a STP LMT on the way out: same trigger, plus a
    limit half a percent beyond it. The conversion lives there rather than here
    because it is a fact about how orders reach IBKR, not about the strategy.

    The target is a plain limit, and it is None on all three momentum books,
    which take no profit target at all since Momentum v2 (item A2, Mo
    2026-09-06). The insider and Congress books still use it.
    """
    other = _other_side(intent.side)
    stop_order = None
    if _number(stop) > 0:
        stop_order = {"action": other, "totalQuantity": int(intent.qty),
                      "orderType": "STP", "auxPrice": round(float(stop), 2),
                      "tif": "DAY"}
    target_order = None
    if _number(target) > 0:
        target_order = {"action": other, "totalQuantity": int(intent.qty),
                        "orderType": "LMT", "lmtPrice": round(float(target), 2),
                        "tif": "DAY"}
    return stop_order, target_order


def bracket_lines(intent: gr.OrderIntent, stop: float, target: float,
                  order_ref: str) -> list[str]:
    """The legs of a would-be bracket, one readable line each, for a dry run.

    Shows exactly what the live path would send, the stop-limit's own limit
    price included, so a rehearsal is a rehearsal and not a summary. A momentum
    book has no target (item A2, Mo 2026-09-06), so it shows two legs.
    """
    lines = [f"entry  {describe(intent)} tagged {order_ref} (parent, untransmitted "
             "until the stop is attached)"]
    stop_order, target_order = child_orders(intent, stop, target)
    if target_order:
        lines.append(f"target {target_order['action']} {target_order['totalQuantity']} "
                     f"{intent.symbol} limit {target_order['lmtPrice']:.2f} tagged "
                     f"{order_ref}")
    if stop_order:
        child = broker_mod.stop_limit_child(stop_order)
        lines.append(f"stop   {child['action']} {child['totalQuantity']} "
                     f"{intent.symbol} stop {child['auxPrice']:.2f} limit "
                     f"{child.get('lmtPrice', child['auxPrice']):.2f} tagged "
                     f"{order_ref} (child, one OCA group with the parent)")
    else:
        lines.append("stop   none, and an entry with no stop is refused above")
    return lines


def remember_legs(state: bs.BookState, symbol: str, result: dict, order_ref: str,
                  now: datetime) -> None:
    """Write the bracket's children into the book file so a later tick can find them.

    A stop that has to be moved has to be cancelled first, and cancelling it
    means knowing its order id. That id only exists in the broker's reply, so it
    is written down the moment it arrives.
    """
    for leg in result.get("legs") or []:
        if not isinstance(leg, dict) or leg.get("purpose") == "entry":
            continue
        order_id = leg.get("order_id")
        if order_id is None:
            continue
        state.working_orders[str(order_id)] = {
            "symbol": symbol, "purpose": str(leg.get("purpose") or "child"),
            "price": leg.get("price"), "order_ref": order_ref,
            "placed_at": now.isoformat(), "is_child": True,
        }


def resting_stop_id(state: bs.BookState, symbol: str) -> str | None:
    """The order id of the stop resting at the broker for this name, if there is one."""
    for order_id, row in (state.working_orders or {}).items():
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if str(row.get("purpose") or "").lower() == "stop":
            return str(order_id)
    return None


def submit(tick: BookTick, state: bs.BookState, intent: gr.OrderIntent,
           broker: broker_mod.Broker, guard: gr.Guardrails, stop: float = 0.0,
           target: float = 0.0) -> dict:
    """Send one order to the broker and write down what actually came back.

    An entry goes out as a bracket, so its stop rests at IBKR instead of only in
    this Mac's memory. Everything else, an exit or a flatten, is one plain
    order: there is nothing left to protect.

    Nothing reaches this today. It exists so the live path is real, visible code
    with its locks on it rather than something to be invented in a hurry later.
    """
    contract = contract_for({"symbol": intent.symbol})
    order = order_dict(intent)
    ref = guard.order_ref or tick.tag

    stop_order, target_order = child_orders(intent, stop, target)
    if intent.purpose == "entry" and stop_order is not None:
        result = broker.bracket_order(contract, order, stop_order, target_order, ref)
        remember_legs(state, intent.symbol, result, ref, tick.now)
        if not result.get("bracketed"):
            tick.note(f"{intent.symbol}: the protective legs did not go out with the "
                      "entry, so this position has no stop resting at the broker")
    else:
        result = broker.place_order(contract, order, ref)
    tick.sent += 1
    filled = _number(result.get("filled_qty"))
    price = _number(result.get("avg_fill_price"))

    # The order itself, into the database, with whatever the broker called it.
    # The row id comes back so a fill can point at the order that made it.
    row_id = record_order_row(
        tick, guard, intent, stop=stop, broker_order_id=result.get("order_id"),
        oca_group=result.get("oca_group"),
        status=("filled" if filled > 0 else
                "submitted" if result.get("working") else "rejected"))

    if filled > 0:
        tick.say(f"filled {filled:g} {intent.symbol} at {price:.4f}, confirmed by "
                 f"{result.get('confirmed_by')}")
        for message in record_fill(state, intent, filled, price, tick.now, guard):
            tick.note(f"{intent.symbol}: {message}")
        counter = make_day_trade_counter(guard)
        if counter is not None:
            try:
                counter.record_fill(intent.symbol, intent.side, int(round(filled)),
                                    tick.now,
                                    fill_id=str(result.get("order_id") or "") or None)
            except Exception as exc:         # noqa: BLE001
                tick.note(f"the day trade counter would not record the fill: {exc}")
        # Item A15: every fill carries the facts the decision was made on, so
        # slippage, risk and selection can be read back at the end of the month.
        facts = trade_facts(state, intent.symbol, guard)
        ledger_writer.log_trade(
            {"symbol": intent.symbol, "side": intent.side, "qty": filled,
             "price": price, "notional": round(filled * price, 2),
             "order_ref": guard.order_ref, "purpose": intent.purpose,
             "strategy_signal": facts.get("candle") or "",
             "notes": facts_line(facts)},
            book_id=tick.book.book_id, model=tick.book.model or "none",
            decision_price=facts.get("decision_price"),
            decision_time=facts.get("decision_time"),
            dry_run=not tick.write_ledger)
    elif result.get("working"):
        order_id = str(result.get("order_id") or f"pending-{intent.symbol}")
        state.working_orders[order_id] = {
            "symbol": intent.symbol, "side": intent.side, "qty": int(intent.qty),
            "remaining": int(intent.qty), "limit_price": intent.limit_price,
            "purpose": intent.purpose, "placed_at": tick.now.isoformat(),
            "order_ref": guard.order_ref, "db_order_id": row_id,
        }
        tick.say(f"order {order_id} is working, {intent.qty} {intent.symbol} unfilled")
    else:
        tick.note(f"the broker did not fill and is not working {intent.symbol}: "
                  f"{result.get('error') or 'no reason given'}")
    return result


def record_fill(state: bs.BookState, intent: gr.OrderIntent, filled: float,
                price: float, now: datetime,
                guard: gr.Guardrails | None = None) -> list[str]:
    """Update the book's own file after a real fill. Only the live path calls this.

    A new position is opened with its stop and its target on it, taken from the
    trigger record the pick wrote and re-clamped against the price actually
    paid. Before 2026-09-06 both were left at zero, which meant exit_reason_for
    below skipped them and neither the hard stop nor the target could ever fire.

    Returns any notes about how the levels were arrived at, so the caller can
    write them down.
    """
    symbol = intent.symbol
    signed = filled if intent.side == "BUY" else -filled
    held = state.position(symbol)

    if held is None:
        short = signed < 0
        levels = fill_levels(state, symbol, short, price, guard)
        state.put_position(bs.Position(
            symbol=symbol, qty=signed, avg_cost=price,
            opened_on=f"{now.date():%Y-%m-%d}", entry=price,
            side="short" if short else "long", trailing_high_or_low=price,
            stop=levels.stop, target=levels.target))
        state.entries_opened_today += 1
        state.cash -= signed * price
        return list(levels.notes)

    if (held.qty > 0) == (signed > 0):
        total = held.qty + signed
        held.avg_cost = ((held.avg_cost * held.qty + price * signed) / total
                         if total else price)
        held.qty = total
    else:
        closed = min(abs(signed), abs(held.qty))
        direction = 1.0 if held.qty > 0 else -1.0
        state.realized_pnl_today = round(
            state.realized_pnl_today + (price - held.avg_cost) * closed * direction, 2)
        held.qty += signed
    state.cash -= signed * price
    if abs(held.qty) < 1e-9:
        state.drop_position(symbol)
    else:
        state.put_position(held)
    return []


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
    tick.record(state, "", f"the {slot} sweep ran", f"{message}. {read_message}")


def do_preopen(tick: BookTick, state: bs.BookState,
               broker: broker_mod.Broker) -> None:
    """Hand this minute of the morning to the pre-open run.

    From 09:00 the momentum books have work to do before the market opens: a
    gap scan every few minutes, and each new name's history pulled at no more
    than four requests a minute. The pacing is the whole point. IB Gateway
    allows about 60 historical requests in any 10 minutes, so spending that
    budget between 09:00 and 09:26 means it is NOT being spent in the five
    minutes around the open, where it is scarcest and where the pick is made.

    Books A, B and E share one pre-open run exactly as they share one scanner
    run. It is idempotent within a minute: whichever ticks first does the work
    and the other two find it already done in the state file on disk.

    Everything it does is a read. It never sends an order, and there is a test
    that reads its source and fails if it ever reaches for one.

    A missing or broken agent/preopen.py costs the pre-open work and nothing
    else. The day still runs: the scanner works the same numbers out from daily
    bars at 09:35 instead, which is slower and spends the budget at the worst
    moment, which is exactly why the pre-open run exists.
    """
    if preopen_mod is None:
        tick.note(f"agent/preopen.py is not loaded ({PREOPEN_ERROR}), so nothing was "
                  "gathered before the open. The scanner works it out at 09:35 "
                  "instead, which is slower and spends the data budget at the worst "
                  "moment of the day.")
        return
    try:
        answer = preopen_mod.step(tick.now, broker) or {}
    except Exception as exc:                 # noqa: BLE001
        tick.note(f"the pre-open run raised {type(exc).__name__}: {exc}. The day "
                  "carries on and the scanner works the numbers out at 09:35.")
        tick.rule("preopen_failed",
                  f"the pre-open run raised {type(exc).__name__}: {exc}",
                  "the pre-open work was skipped, and the 09:35 scanner still runs")
        return

    phase = str(answer.get("phase") or "")
    did = str(answer.get("did") or answer.get("note") or "nothing this minute")
    candidates = answer.get("candidates")
    tick.say(f"Pre-open ({phase or 'working'}): {did}"
             + (f", {len(candidates)} candidate(s) tracked"
                if isinstance(candidates, (list, dict)) else ""))
    for message in (answer.get("notes") or []):
        tick.note(f"pre-open: {message}")
    # What the pre-open run learned lives in its own file for the day, under
    # output/preopen_state_YYYY-MM-DD.json, rather than in the book file. It is
    # shared by all three momentum books, so it does not belong to any one of
    # them. See docs/PREOPEN_FLOW.md.


def do_scan(tick: BookTick, state: bs.BookState, plan: BookPlan) -> None:
    """Run the opening scanner, or read the shortlist a sister book just wrote.

    Books A, B and E share one scanner run. Whichever of them ticks first pays
    for it and the other two read the file, because running the scanner three
    times in one minute would spend three times the data budget on three copies
    of the same answer.
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
    tick.say(f"Shortlist has {len(rows)} names. This book picks at "
             f"{plan.pick_time:%H:%M}.")


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
            # Out of the packet, not just out of the message. The scanner has no
            # news feed behind it, so a headline on a momentum row is either
            # empty or something that drifted in from elsewhere, and a packet is
            # meant to be exactly what was known at the time. Leaving an
            # unreliable field in it would make the review of a decision worse,
            # not better. See MOMENTUM_CANDIDATE_KEYS in agent/decide.py.
            for unreliable in ("headline", "news"):
                candidate.pop(unreliable, None)
            try:
                bars = broker_mod.bars_5m_today(broker, contract_for(candidate))
            except Exception as exc:         # noqa: BLE001
                bars = []
                notes.append(f"no five minute bars for {symbol}: {exc}")
            candidate["bars_5m"] = bars
            candidate["bar_count"] = len(bars)
            candidate["session_vwap"] = broker_mod.session_vwap(bars)
            if bars:
                candidate["last_close"] = bars[-1].get("close")
                if not candidate.get("opening_range_high"):
                    candidate["opening_range_high"] = bars[0].get("high")
                    candidate["opening_range_low"] = bars[0].get("low")
                    notes.append(f"{symbol}: the opening range was taken from the "
                                 "first bar, because the scanner did not supply it")
            borrow = broker_mod.borrow_terms(quote)
            candidate["shortable"] = borrow.shortable
            candidate["shortable_level"] = borrow.level
            candidate["borrow_fee_pct_annual"] = borrow.fee_pct_annual
            candidate["shares_available_to_borrow"] = borrow.shares_available
            candidate["borrow_note"] = borrow.note
        else:
            # The sweeps read filings and have no market data at all, so this is
            # where the price floor is applied.
            if price is None:
                notes.append(f"{symbol}: no price came back, so the price floor cannot "
                             "be checked and it is left out")
                continue
            if price < guard.universe.price_floor:
                notes.append(f"{symbol}: {price:.2f} is under this book's price floor "
                             f"of {guard.universe.price_floor:.2f}, so it is left out")
                continue
        enriched.append(candidate)

    packet = {
        "generated_at": tick.now.isoformat(),
        "date": f"{tick.now.date():%Y-%m-%d}",
        # The shape of this file, not the version of the code that wrote it. It
        # goes into the prompt hash, so a month of decisions made against one
        # packet shape is never silently compared with a month made against
        # another. See PACKET_SCHEMA_VERSION in agent/decide.py.
        "schema_version": decide_mod.PACKET_SCHEMA_VERSION,
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
                     "flatten_at": (f"{plan.flatten_at:%H:%M}" if plan.flat_by_close
                                    else "this book is not flattened at the close")},
        "account": bs.facts_for(state),
        "candidates": enriched,
        "positions": [_position_row(p) for p in state.all_positions().values()],
        "notes": notes,
    }
    path = (output_dir()
            / f"packet_{tick.book.order_ref}_{tick.now:%Y-%m-%d_%H%M}_pick.json")
    path.write_text(json.dumps(packet, indent=2, default=str))
    state.packet_path = str(path)
    for message in notes:
        tick.note(message)
    tick.say(f"Decision packet for {len(enriched)} candidates written to {path}")
    return packet


def record_decision_problems(tick: BookTick, state: bs.BookState, result) -> None:
    """Write down every way one decision went wrong, by name, in the ledger.

    Three different things, and they are kept apart on purpose because they mean
    different things at the end of the month:

        decision_rejected   a row the model wrote that could not be used, or a
                            whole reply that could not be read. Named, with the
                            reason. Nothing stands in for it: a tick that
                            rejects its reply opens nothing.
        model_unavailable   no usable reply arrived at all, so the book's own
                            rules answered instead. Written down so a rules
                            answer is never counted as a model answer.
        decision_failed     something else went wrong before a model was even
                            reached, such as a prompt that would not render.
    """
    for bad in getattr(result, "rejections", None) or []:
        symbol = str(bad.get("symbol") or "")
        reason = str(bad.get("reason") or "no reason given")
        detail = f"{symbol}: {reason}" if symbol else reason
        tick.say(f"  rejected: {detail}")
        tick.rule("decision_rejected", detail, "the row was thrown away")
        tick.record(state, symbol, "decision_rejected", reason,
                    model=result.model, cost=None, prompt_hash=result.prompt_hash)

    if getattr(result, "fallback", None) == "model_unavailable":
        why = next((n for n in result.notes if n.startswith("model_unavailable")),
                   "the model could not be reached")
        tick.rule("model_unavailable", why,
                  "this book's own rules answered instead of its model")
        tick.record(state, "", "model_unavailable", why, model=result.model,
                    cost=result.cost_usd, prompt_hash=result.prompt_hash)
        return

    if not result.ok:
        tick.note(f"the decision step could not answer: {result.error}")
        rule_id = "decision_rejected" if result.rejections else "decision_failed"
        tick.rule(rule_id,
                  f"the {tick.book.model or 'rules only'} answer failed: {result.error}",
                  "nothing was opened this tick and no rules answer stood in for it")


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
    record_decision_problems(tick, state, result)

    if not result.picks:
        tick.say(f"No picks. The shortlist held {len(rows)} names and none of them "
                 "cleared this book's rules.")
        tick.record(state, "", "no picks",
                    f"the shortlist held {len(rows)} candidates and none gave a usable "
                    "entry for this book", model=result.model, cost=cost,
                    prompt_hash=result.prompt_hash)
        return

    which = ("rules only" if tick.book.model in (None, "none") else tick.book.model)
    tick.say(f"Picked {len(result.picks)} names ({which}"
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

    # The stop is checked before the pick is written down as a pick, because a
    # stop on the wrong side of entry means there was never a tradeable idea
    # here, only a row that looked like one.
    if entry > 0:
        low, high = _opening_range(state, symbol)
        levels = protective_levels(guard, entry=entry, short=short, model_stop=stop,
                                   model_target=target, opening_range_low=low,
                                   opening_range_high=high)
        if levels.reject:
            tick.say(f"{symbol}: rejected. {levels.reject}")
            tick.rule("decision_rejected", f"{symbol}: {levels.reject}",
                      "the pick was thrown away and no entry order was worked out")
            tick.record(state, symbol, "decision_rejected",
                        f"{levels.reject}. The pick said: {reason}",
                        model=result.model, cost=result.cost_usd,
                        prompt_hash=result.prompt_hash)
            state.triggered[symbol] = {
                "at": tick.now.isoformat(), "price": entry, "allowed": False,
                "sent": False, "skipped": "decision_rejected",
                "side": "short" if short else "long"}
            return
        stop, target = levels.stop, levels.target
        for message in levels.notes:
            tick.note(f"{symbol}: {message}")

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
        note_late_entry(tick, state, plan, symbol, "the pick was written down and no "
                                                   "entry order was worked out")
        return
    if entry <= 0:
        tick.note(f"{symbol}: the pick carries no usable entry price, so there is "
                  "nothing to size")
        return

    quantity = size_for(tick, guard, account_state, symbol, entry, stop,
                        int(pick.get("qty_hint") or 0))
    if quantity <= 0:
        tick.say(f"  {symbol}: the money rules allow zero shares at {entry:.2f}")
        tick.record(state, symbol, "no entry order",
                    f"at {entry:.2f} this book's limits allow zero shares")
        return

    borrow = _borrow_answer(state, symbol)
    halted, limit_state = tradeable_now(broker, {"symbol": symbol}, tick.notes)
    intent = _entry_intent(symbol, short, quantity, entry, tick.book.book_id, borrow,
                           sector=sector_for(state, symbol),
                           halted=halted, limit_state=limit_state)

    # Written before the order is considered, not after, because a fill can come
    # back inside consider() and the ledger row for it reads these facts.
    state.triggered[symbol] = {
        "at": tick.now.isoformat(), "price": entry, "allowed": False,
        "sent": False, "mode": tick.book.mode, "side": "short" if short else "long",
        "stop": stop, "target": target, "qty": int(quantity), "reason": reason,
    }

    extra = f"stop {stop:.2f}"
    if target > 0:
        extra += f", target {target:.2f}"
    else:
        extra += ", no target, this book leaves on its stop or at the close"
    facts = facts_line(trade_facts(state, symbol, guard))
    if facts:
        extra += f" [{facts}]"
    if short:
        extra += f", borrow: {borrow.note}"
    decision = consider(tick, state, guard, account_state, intent, broker, guards,
                        extra=extra, model=result.model, cost=None,
                        prompt_hash=result.prompt_hash, stop=stop, target=target)
    state.triggered[symbol]["allowed"] = decision.allowed
    put_the_pick_down(tick, state, symbol, decision)
    if decision.daily_halt:
        state.halt("a guardrail asked for a halt for the rest of the day")


def trade_facts(state: bs.BookState, symbol: str,
                guard: gr.Guardrails | None = None) -> dict:
    """The eight facts item A15 asks for on every decision and every fill.

    Momentum v2, approved by Mo on 2026-09-06. Without these, luck and judgment
    cannot be told apart at the end of the month: two books can show the same
    profit while one of them was taking twice the risk for it.

        decision_price   what the pick was made at, so the ledger can work out
                         the slippage against the price actually paid. The
                         Trades tab fills the slippage in itself from this and
                         the fill price.
        atr              the 14 day average true range, which is what the stop
                         was measured from
        rel_volume       how many times its normal pace the name was trading at
        rank             its place in that morning's relative volume ranking
        candle           the first five minute candle, written as its open and
                         close, because its sign is the direction rule
        risk_usd         how much money this trade was set up to lose
        sector           the industry, which the sector cap counts against

    Everything comes off the shortlist row and the trigger record, both of which
    are written before the decision, so nothing here is worked out after the
    fact.
    """
    row = shortlist_row(state, symbol)
    raw = state.triggered.get(symbol) if isinstance(state.triggered, dict) else None
    trigger = raw if isinstance(raw, dict) else {}

    decision_price = _number(trigger.get("price")) or None
    stop = _number(trigger.get("stop"))
    quantity = _number(trigger.get("qty"))
    risk_usd = None
    if decision_price and stop > 0 and quantity > 0:
        risk_usd = round(abs(decision_price - stop) * quantity, 2)

    opened = _number(row.get("opening_range_open")) or None
    closed = _number(row.get("opening_range_close")) or None
    candle = None
    if opened is not None and closed is not None:
        way = "up" if closed > opened else ("down" if closed < opened else "flat")
        candle = f"{opened:.2f} to {closed:.2f} ({way})"

    return {
        "decision_price": decision_price,
        "decision_time": trigger.get("at") or None,
        "atr": _number(row.get("atr")) or None,
        "rel_volume": _number(row.get("rel_volume")) or None,
        "rank": row.get("rank"),
        "candle": candle,
        "risk_usd": risk_usd,
        "sector": sector_for(state, symbol),
    }


def facts_line(facts: dict) -> str:
    """The A15 facts as one short readable phrase for a Notes cell or a reason."""
    parts = []
    if facts.get("rank") is not None:
        parts.append(f"rank {facts['rank']}")
    if facts.get("rel_volume"):
        parts.append(f"relative volume {facts['rel_volume']:.2f}x")
    if facts.get("atr"):
        parts.append(f"atr {facts['atr']:.2f}")
    if facts.get("candle"):
        parts.append(f"opening candle {facts['candle']}")
    if facts.get("risk_usd"):
        parts.append(f"risking {facts['risk_usd']:,.2f} dollars")
    if facts.get("sector"):
        parts.append(f"sector {facts['sector']}")
    if facts.get("decision_price"):
        parts.append(f"decided at {facts['decision_price']:.2f}")
    return ", ".join(parts)


def size_for(tick: BookTick, guard: gr.Guardrails, account_state, symbol: str,
             entry: float, stop: float, model_hint: int = 0) -> int:
    """How many shares to buy, and a written note whenever something cut it.

    Momentum v2, item A6, approved by Mo on 2026-09-06. The book risks a fixed
    slice of itself on every trade and lets the stop decide the share count:
    0.25 percent of book equity divided by the distance from the entry price to
    the stop. So a name with a wide stop gets fewer shares and one with a tight
    stop gets more, and every position loses about the same when it is wrong.
    The notional caps are still the ceiling over the top of it, because a very
    tight stop would otherwise buy an enormous position.

    A book with no risk_per_trade_pct, which is the insider and Congress books,
    gets the old answer: whatever the notional caps allow.

    Whatever the model asked for in qty_hint is only ever a ceiling, never a
    floor. The momentum prompt no longer asks for one at all.
    """
    if _number(stop) > 0 and guard.money.risk_per_trade_pct:
        shares = gr.shares_for_risk(guard, account_state, symbol, entry, stop)
        risked = abs(entry - stop) * shares
        tick.note(f"{symbol}: {shares} shares, which risks {risked:,.2f} dollars at a "
                  f"stop {abs(entry - stop):.2f} away, being "
                  f"{_plain_pct(guard.money.risk_per_trade_pct)} percent of the book")
    else:
        shares = gr.max_shares_for(guard, account_state, symbol, entry)

    if model_hint > 0 and model_hint < shares:
        tick.note(f"{symbol}: cut from {shares} shares to {model_hint}, because the "
                  "answer asked for fewer and a smaller position is always allowed")
        shares = model_hint
    return int(max(0, shares))


def _plain_pct(value: float) -> str:
    """A percentage a person can read, so 0.25 stays 0.25 and 4.0 reads as 4."""
    return f"{value:g}"


def _borrow_answer(state: bs.BookState, symbol: str) -> broker_mod.BorrowTerms:
    """What the broker said about borrowing this name, off the shortlist row.

    Checked against the live MCP server on 2026-09-06: its snapshot carries no
    shortable level, no borrow fee and no share availability, and neither does
    ibkr_get_contract_details, so the answer today is always "the broker has not
    confirmed it". The momentum books set require_shortable, so the borrow rules
    in agent/guardrails.py refuse every short until the server can answer. That
    is the designed behaviour and not a gap.
    """
    for row in state.shortlist:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
            if "borrow_note" in row:
                return broker_mod.BorrowTerms(
                    shortable=bool(row.get("shortable")),
                    level=row.get("shortable_level"),
                    fee_pct_annual=row.get("borrow_fee_pct_annual"),
                    shares_available=row.get("shares_available_to_borrow"),
                    note=str(row.get("borrow_note") or ""))
    return broker_mod.borrow_terms(None)


def _entry_intent(symbol: str, short: bool, quantity: int, price: float,
                  book_id: str, borrow: broker_mod.BorrowTerms,
                  sector: str | None = None, halted: bool | None = None,
                  limit_state: bool | None = None) -> gr.OrderIntent:
    """One entry order, with the borrow terms on it when it is a short.

    A long carries none of them, because nothing is being borrowed. A short
    carries all four exactly as the broker reported them, unknowns included, and
    an unknown is what the guardrails refuse on.

    sector is the industry the sector cap counts against (Momentum v2, item A9).
    It is passed on exactly as the scanner reported it, None included, because
    None is what that rule refuses on for the same reason.

    halted and limit_state are what IBKR's halted tick and its limit-up
    limit-down band say about the name right now, read by tradeable_now above.
    Both are passed on exactly as the broker answered, None included. None means
    nobody could tell us, and an unknown halt status stops an entry rather than
    being read as a clean name.
    """
    return gr.OrderIntent(
        symbol=symbol, side="SELL" if short else "BUY", qty=int(quantity),
        limit_price=round(price, 2), purpose="entry", book_id=book_id,
        sector=sector, halted=halted, limit_state=limit_state,
        shortable=bool(borrow.shortable) if short else False,
        shortable_level=borrow.level if short else None,
        borrow_fee_pct_annual=borrow.fee_pct_annual if short else None,
        shares_available_to_borrow=borrow.shares_available if short else None)


@dataclass
class Levels:
    """Where one position's stop and target actually go, and why.

    reject is set when the pick cannot be traded at all. notes hold anything
    worth writing into the record: a stop that was moved, a target dropped.
    """

    stop: float = 0.0
    target: float = 0.0
    notes: list[str] = field(default_factory=list)
    reject: str | None = None


def shortlist_row(state: bs.BookState, symbol: str) -> dict:
    """One name's row off this book's shortlist, or an empty dict."""
    for row in state.shortlist:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
            return row
    return {}


def _opening_range(state: bs.BookState, symbol: str) -> tuple[float | None, float | None]:
    """The low and high of the first five minutes for one name, off the shortlist."""
    row = shortlist_row(state, symbol)
    low = _number(row.get("opening_range_low")) or None
    high = _number(row.get("opening_range_high")) or None
    return low, high


def atr_for(state: bs.BookState, symbol: str) -> float | None:
    """The 14 day average true range for one name, off the shortlist row.

    Momentum v2, item A1 (Mo, 2026-09-06). The scanner works it out from the
    daily bars it already has and writes it onto the row, so the loop never has
    to spend a data request on it. None means the scanner could not work one
    out, and then the stop falls back to the plain percentage, which is what
    stop_price_for in agent/guardrails.py does with a None.
    """
    return _number(shortlist_row(state, symbol).get("atr")) or None


def sector_for(state: bs.BookState, symbol: str) -> str | None:
    """Which industry one name is in, off the shortlist row.

    Momentum v2, item A9. The scanner reads it from IBKR's contract details
    (the industry field, falling back to category and then subcategory) and
    writes it onto the row. None means the broker did not say, and the sector
    cap in agent/guardrails.py refuses an entry rather than assuming it is
    harmless. Which is the whole point: a cap that cannot be measured is not a
    cap.
    """
    row = shortlist_row(state, symbol)
    for key in ("sector", "industry", "category"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def protective_levels(guard: gr.Guardrails, *, entry: float, short: bool,
                      model_stop: float, model_target: float,
                      opening_range_low: float | None = None,
                      opening_range_high: float | None = None,
                      atr: float | None = None) -> Levels:
    """The stop and the target a position is opened with, after the rules have had them.

    The model proposes both. It may move a stop nearer to the entry price and it
    may never move one further away, so the rule stop from
    guardrails.stop_price_for is the outer edge and the model's number is used
    only when it sits inside that edge. For a long the nearer stop is the higher
    of the two, for a short the lower, which is why one side takes the maximum
    and the other the minimum.

    A stop on the wrong side of entry is not a widening, it is nonsense: a long
    that stops out above the price it bought at would close the instant it
    opened. Those come back with reject set and the pick is thrown away.

    A target on the wrong side is dropped rather than fatal. A position with no
    target still has a stop and is still safe; it runs to the trailing stop, the
    time stop or the close instead.
    """
    notes: list[str] = []
    entry = _number(entry)
    if entry <= 0:
        return Levels(reject="there is no entry price to measure a stop from")

    side = "SELL" if short else "BUY"
    try:
        rule_stop = gr.stop_price_for(guard, entry, opening_range_low, side,
                                      opening_range_high, atr=atr)
    except gr.GuardrailError as exc:
        return Levels(reject=f"the rule stop could not be worked out: {exc}")

    stop = _number(model_stop)
    if stop <= 0:
        notes.append(f"the pick carried no stop, so the rule stop {rule_stop:.2f} is used")
        stop = rule_stop
    elif (not short and stop >= entry) or (short and stop <= entry):
        return Levels(notes=notes, reject=(
            f"the stop {stop:.2f} is on the wrong side of the entry {entry:.2f} for a "
            f"{'short' if short else 'long'}, so this pick would close itself the "
            "moment it opened"))
    else:
        clamped = min(stop, rule_stop) if short else max(stop, rule_stop)
        if abs(clamped - stop) > 0.004:
            notes.append(
                f"the stop moved from {stop:.2f} to {clamped:.2f}: the rules allow no "
                f"stop further from {entry:.2f} than {rule_stop:.2f}, and a model may "
                "tighten a stop but never widen one")
        stop = clamped

    target = _number(model_target)
    if not guard.risk.use_profit_target:
        # Momentum v2, item A2, approved by Mo on 2026-09-06. This book has no
        # profit target at all: a position leaves by its stop or at the close and
        # by nothing else. Two independent studies found that a target destroys
        # this strategy's edge, because the few trades that run a long way are
        # what pay for all the small losses. A target that arrives anyway, from a
        # model that did not read its prompt, is dropped and written down.
        if target > 0:
            notes.append(
                f"the target {target:.2f} was dropped: this book takes no profit "
                "target at all, and a position leaves on its stop or at the close")
        target = 0.0
    elif target > 0 and ((not short and target <= entry) or (short and target >= entry)):
        notes.append(
            f"the target {target:.2f} is on the wrong side of the entry {entry:.2f} for "
            f"a {'short' if short else 'long'}, so it is dropped and this position runs "
            "to its stop, its trailing stop or the close")
        target = 0.0
    return Levels(round(stop, 2), round(max(target, 0.0), 2), notes)


def fill_levels(state: bs.BookState, symbol: str, short: bool, price: float,
                guard: gr.Guardrails | None) -> Levels:
    """The stop and target to open a position with, from the pick that triggered it.

    The trigger record written at pick time holds the levels the decision was
    made with. They are re-clamped here against the price actually paid rather
    than the price that was planned, because a stop measured from a plan the
    market did not honour is not a stop.

    A fill that cannot be clamped still gets the rule stop. A filled position
    with no stop on it is the exact hole this whole change exists to close, so
    there is no path out of here that leaves stop at zero.
    """
    raw = state.triggered.get(symbol) if isinstance(state.triggered, dict) else None
    trigger = raw if isinstance(raw, dict) else {}
    model_stop = _number(trigger.get("stop"))
    model_target = _number(trigger.get("target"))

    if guard is None or price <= 0:
        return Levels(round(model_stop, 2), round(model_target, 2),
                      ["no guardrails were handed to the fill, so the pick's own "
                       "levels are used unchecked"])

    low, high = _opening_range(state, symbol)
    atr = atr_for(state, symbol)
    levels = protective_levels(guard, entry=price, short=short, model_stop=model_stop,
                               model_target=model_target, opening_range_low=low,
                               opening_range_high=high, atr=atr)
    if not levels.reject:
        return levels

    # The shares are already ours, so refusing is not on the table. Fall back to
    # the rule stop, which is always on the right side of the fill price.
    try:
        rule = gr.stop_price_for(guard, price, low, "SELL" if short else "BUY", high,
                                 atr=atr)
    except gr.GuardrailError as exc:
        return Levels(0.0, 0.0, [f"{levels.reject}, and the rule stop failed too: {exc}"])
    return Levels(rule, 0.0,
                  [f"{levels.reject}, so the rule stop {rule:.2f} is used instead"])


def count_vwap_closes(state: bs.BookState, symbol: str, position: bs.Position,
                      last_close: float | None, vwap: float | None) -> int:
    """How many five minute closes in a row have finished the wrong side of VWAP.

    Kept in the book's own file, next to the trigger record for the same name,
    because a fade is a run of bars and a run cannot be counted inside one tick.
    Any close back on the right side puts it to zero, so it is consecutive
    closes and never a total for the day. A tick with no price and no VWAP
    leaves the count where it was rather than resetting it, because nothing was
    observed.
    """
    raw = state.triggered.get(symbol) if isinstance(state.triggered, dict) else None
    row = dict(raw) if isinstance(raw, dict) else {}
    so_far = int(_number(row.get("vwap_closes_through")))
    if not vwap or not last_close:
        return so_far

    through = (last_close > vwap) if position.is_short else (last_close < vwap)
    count = so_far + 1 if through else 0
    row["vwap_closes_through"] = count
    state.triggered[symbol] = row
    return count


def exit_reason_for(position: bs.Position, plan: BookPlan, guard: gr.Guardrails,
                    today: date_type, last_close: float,
                    vwap: float | None,
                    closes_through_vwap: int = 0) -> tuple[str | None, str]:
    """Should this position be closed, and in plain words why.

    Every way out of a position, in the order the strategies put them:

        stop        the price went through the stop
        target      the price reached the target
        trailing    the price came back through the trailing stop, which follows
                    the best price the position has seen since it was opened
        time        the position has run out of trading days
        fade        momentum books only: enough five minute closes in a row have
                    finished back through the day's volume weighted average
                    price, which is the standard tell that an opening push is
                    over. How many is "enough" is risk.vwap_fade_closes in the
                    book's own strategy.yaml, carried here on the plan, and it
                    is the same number the prompt tells the model. One weak bar
                    is not a fade, which is why the count is not one.

    Kept as its own function, with no broker and no clock in it, so every rule
    can be checked on paper.

    The hard stop is the first thing checked and it is never skipped. Until
    2026-09-06 a position was opened with stop and target both left at zero, and
    a zero stop fell through the check below, so the 1.5 percent stop and the
    target could not fire at all. record_fill above now sets both. A position
    that somehow still arrives without a stop, one carried over from a state
    file written before that change, gets the rule stop measured off its entry
    rather than no stop at all.
    """
    short = position.is_short
    stop = _number(position.stop)
    target = _number(position.target)
    entry = _number(position.entry) or _number(position.avg_cost)

    if stop <= 0 and entry > 0:
        try:
            stop = gr.stop_price_for(guard, entry, None, "SELL" if short else "BUY")
        except gr.GuardrailError:
            stop = 0.0

    if stop > 0:
        if (not short and last_close <= stop) or (short and last_close >= stop):
            return "stop", f"the close {last_close:.2f} went through the stop {stop:.2f}"
    if target > 0:
        if (not short and last_close >= target) or (short and last_close <= target):
            return "target", (f"the close {last_close:.2f} reached the target "
                              f"{target:.2f}")

    best = position.trailing_high_or_low
    if best:
        trailing = None
        if entry > 0:
            trailing = gr.trailing_stop_price(
                guard, "SELL" if short else "BUY", float(best), entry)
        if trailing is not None:
            if (not short and last_close <= trailing) \
                    or (short and last_close >= trailing):
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
                            f"out of the {guard.risk.time_stop_trading_days} trading "
                            "days this book gives one")

    if plan.family == MOMENTUM and vwap and plan.vwap_fade_closes:
        if closes_through_vwap >= plan.vwap_fade_closes:
            bars = "close" if closes_through_vwap == 1 else "closes in a row"
            why = (f"momentum faded, {closes_through_vwap} five minute {bars} "
                   f"back through the day's vwap {vwap:.2f}, and this book "
                   f"calls a fade at {plan.vwap_fade_closes}")
            if plan.vwap_fade_acts:
                return "fade", why
            # Momentum v2, item D2 (Mo, 2026-09-06). In month one the fade is a
            # logged observation and closes nothing. The caller writes the line
            # and holds the position, so at the end of the month Mo can read
            # what every fade would have cost or saved.
            return "fade_observed", why
    return None, ""


def tighter_stop_for(position: bs.Position, guard: gr.Guardrails) -> float | None:
    """Where this position's stop should sit now, when that is nearer than where it is.

    Only ever returns a stop closer to the price than the one already on the
    position, never further away. A trailing stop that could loosen would give
    back the whole point of having one.
    """
    entry = _number(position.entry) or _number(position.avg_cost)
    best = position.trailing_high_or_low
    if entry <= 0 or not best:
        return None
    try:
        trailing = gr.trailing_stop_price(
            guard, "SELL" if position.is_short else "BUY", float(best), entry)
    except gr.GuardrailError:
        return None
    if trailing is None:
        return None

    current = _number(position.stop)
    if current <= 0:
        return trailing
    nearer = trailing < current if position.is_short else trailing > current
    return trailing if nearer else None


def move_resting_stop(tick: BookTick, state: bs.BookState, position: bs.Position,
                      new_stop: float, broker: broker_mod.Broker, guard: gr.Guardrails,
                      guards: Guards, account_state) -> None:
    """Move the stop that is resting at the broker, by cancelling it and placing a new one.

    IBKR has no "edit this order" on this path, so tightening a stop is two
    steps: pull the old child, place a new one for the same shares at the new
    price, tagged with the same book. The order is deliberate. Cancel first,
    place second: a moment with no stop is bad, and a moment with two stops
    would be worse, because both could fill and the book would end up short a
    position it never opened.
    """
    symbol = position.symbol
    shares = int(round(abs(position.qty)))
    side = "BUY" if position.is_short else "SELL"
    order_id = resting_stop_id(state, symbol)
    replacement = {"action": side, "totalQuantity": shares, "orderType": "STP",
                   "auxPrice": round(float(new_stop), 2), "tif": "DAY"}
    ref = guard.order_ref or tick.tag

    open_locks, shut = live_locks(tick.book, account_state.account_id, guards)
    if tick.dry or not open_locks:
        tick.say(f"DRY RUN {tick.tag} would cancel the resting stop "
                 f"{order_id or '(none recorded)'} and place "
                 f"{side} {shares} {symbol} stop {new_stop:.2f} tagged {ref}")
        tick.record(state, symbol, f"would move the stop to {new_stop:.2f}",
                    "the trailing rule tightened the stop, and nothing was sent: "
                    + ("; ".join(shut) or "this book is in dry run"))
        return

    if order_id is not None:
        answer = broker.cancel_order(order_id)
        state.working_orders.pop(str(order_id), None)
        if not answer.get("cancelled"):
            tick.note(f"{symbol}: the old stop {order_id} would not cancel "
                      f"({answer.get('error') or 'no reason given'}), so no new one was "
                      "placed and the old one is still the live stop")
            return

    placed = broker.place_order(contract_for({"symbol": symbol}), replacement, ref)
    new_id = placed.get("order_id")
    if new_id is not None:
        state.working_orders[str(new_id)] = {
            "symbol": symbol, "purpose": "stop", "price": round(float(new_stop), 2),
            "order_ref": ref, "placed_at": tick.now.isoformat(), "is_child": True}
    tick.record(state, symbol, f"moved the stop to {new_stop:.2f}",
                f"the trailing rule tightened it and order {new_id} is now resting "
                f"at the broker")


#: How long a triggered stop-limit is given to fill before the loop stops
#: waiting and gets out at market. Sixty seconds.
#:
#: The stop child is a stop-limit rather than a plain stop, so a thin gap down
#: cannot fill it at any price at all. That protects against a terrible fill.
#: The cost is the opposite risk: a price that gaps straight through the limit
#: leaves the order triggered and unfilled, and the position unprotected while
#: it keeps falling. This is the backstop for exactly that, and it is why the
#: momentum books look every 30 seconds in the morning: a minute is the most a
#: position should ever sit behind a stop that has fired and not filled.
STOP_BACKSTOP_SECONDS = 60


def stop_backstop_due(order: dict, now: datetime,
                      seconds: int = STOP_BACKSTOP_SECONDS) -> bool:
    """Has a triggered stop-limit been sitting unfilled for too long?

    True only when all three hold: the resting order is this book's stop, the
    broker says it has triggered, and the trigger was more than `seconds` ago.
    A stop that has not triggered is doing its job by waiting, so it is left
    alone, and so is one that triggered a moment ago and may yet fill.
    """
    if not isinstance(order, dict):
        return False
    if str(order.get("purpose") or "").lower() != "stop":
        return False
    when = order.get("triggered_at")
    if not when:
        return False
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when)
        except ValueError:
            return False
    if not isinstance(when, datetime):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return (now - when).total_seconds() >= max(0, int(seconds))


def note_stop_triggers(tick: BookTick, state: bs.BookState,
                       broker: broker_mod.Broker,
                       broker_orders: list | None = None) -> None:
    """Write down the moment a resting stop first shows as triggered.

    The broker reports a stop-limit as triggered before it fills. The loop has
    to know WHEN that happened to be able to say it has waited a minute, and
    nothing else on this Mac remembers between ticks, so the moment is written
    into the book file the first time it is seen.

    broker_orders is the account's working orders, already read once for the
    whole tick by main(). It is passed in rather than fetched because five books
    each asking IB Gateway the same question in the same second is how a data
    pacing violation happens, and it is what actually happened the first time
    this ran end to end: the fifth book's call timed out at 45 seconds. Left out,
    it is read here, which is what a test does.
    """
    rows = broker_orders
    if rows is None:
        try:
            rows = (broker.open_orders() or {}).get("orders") or []
        except Exception as exc:                 # noqa: BLE001
            tick.note(f"the working orders could not be read, so a triggered stop "
                      f"cannot be spotted this tick: {exc}")
            return
    triggered = {str(row.get("orderId")): row for row in rows
                 if isinstance(row, dict) and _is_triggered(row)}
    for order_id, order in (state.working_orders or {}).items():
        if not isinstance(order, dict):
            continue
        if str(order.get("purpose") or "").lower() != "stop":
            continue
        if str(order_id) in triggered and not order.get("triggered_at"):
            order["triggered_at"] = tick.now.isoformat()
            tick.note(f"{order.get('symbol')}: the stop {order_id} has triggered and "
                      f"is working its limit. If it has not filled in "
                      f"{STOP_BACKSTOP_SECONDS} seconds the position goes out at "
                      "market.")


def _is_triggered(row: dict) -> bool:
    """Does the broker say this working order has triggered but not filled yet?"""
    if row.get("triggered") is True or row.get("triggered_at"):
        return True
    status = str(row.get("status") or "").strip().lower()
    return status in ("triggered", "presubmitted_triggered")


def market_out_unfilled_stops(tick: BookTick, state: bs.BookState,
                              guard: gr.Guardrails, broker: broker_mod.Broker,
                              account_state, guards: Guards) -> None:
    """Get out at market when a stop has fired and its limit will not fill.

    The stop-limit's limit price keeps a bad fill from being catastrophic. It
    cannot keep the position from being unprotected if the price runs away
    below it, and a position sitting behind a stop that fired and did not fill
    is the worst state this book can be in. So after
    STOP_BACKSTOP_SECONDS the resting child is cancelled and the position is
    closed at market, and both halves of that are written down.
    """
    positions = state.all_positions()
    for order_id, order in list((state.working_orders or {}).items()):
        if not stop_backstop_due(order, tick.now):
            continue
        symbol = str(order.get("symbol") or "").upper()
        position = positions.get(symbol)
        if position is None or not position.qty:
            state.working_orders.pop(str(order_id), None)
            continue

        tick.say(f"  {symbol}: the stop triggered over {STOP_BACKSTOP_SECONDS} "
                 "seconds ago and has not filled, so it goes out at market")
        tick.rule("stop_backstop",
                  f"{symbol}: the stop-limit {order_id} triggered at "
                  f"{order.get('triggered_at')} and had not filled "
                  f"{STOP_BACKSTOP_SECONDS} seconds later",
                  "the resting stop was cancelled and the position was closed at "
                  "market")

        open_locks, _ = live_locks(tick.book, account_state.account_id, guards)
        if not tick.dry and open_locks:
            try:
                broker.cancel_order(order_id)
            except Exception as exc:             # noqa: BLE001
                tick.note(f"{symbol}: the triggered stop {order_id} would not "
                          f"cancel ({exc}), so the market order below may leave a "
                          "duplicate resting at the broker")
        state.working_orders.pop(str(order_id), None)

        intent = gr.OrderIntent(
            symbol=symbol, side="BUY" if position.is_short else "SELL",
            qty=int(round(abs(position.qty))), limit_price=None, purpose="stop",
            book_id=tick.book.book_id)
        consider(tick, state, guard, account_state, intent, broker, guards,
                 extra=f"market backstop, the stop-limit did not fill in "
                       f"{STOP_BACKSTOP_SECONDS} seconds")


def do_manage(tick: BookTick, state: bs.BookState, plan: BookPlan, guard: gr.Guardrails,
              broker: broker_mod.Broker, account_state, guards: Guards,
              broker_orders: list | None = None) -> None:
    """Watch what is open, and let picks that have not fired yet still fire."""
    state.last_manage_at = tick.now.isoformat()

    # First, before anything else: a stop that fired and did not fill is the
    # worst state a position can be in, so it is dealt with before the loop
    # spends a second thinking about anything else.
    note_stop_triggers(tick, state, broker, broker_orders)
    market_out_unfilled_stops(tick, state, guard, broker, account_state, guards)
    positions = state.all_positions()
    notes: list[str] = []
    today = tick.now.date()

    prices: dict[str, tuple[float | None, float | None]] = {}
    if positions:
        quotes = snapshot_by_symbol(broker, [{"symbol": s} for s in positions], notes)
        for symbol in positions:
            if plan.family == MOMENTUM:
                try:
                    bars = broker_mod.bars_5m_today(
                        broker, contract_for({"symbol": symbol}))
                except Exception as exc:     # noqa: BLE001
                    bars = []
                    notes.append(f"no five minute bars for {symbol}: {exc}")
                last = (bars[-1].get("close") if bars
                        else snapshot_price(quotes.get(symbol)))
                prices[symbol] = (_number(last, 0.0) or None,
                                  broker_mod.session_vwap(bars))
            else:
                prices[symbol] = (snapshot_price(quotes.get(symbol)), None)
    for message in notes:
        tick.note(message)

    if not positions:
        tick.say("Nothing is open.")

    # The fade count is worked out once, here, before the packet is written, so
    # the number the model is shown is the same one the code will fire on.
    vwap_closes: dict[str, int] = {}
    rows_for_packet = []
    for symbol, position in positions.items():
        last_close, vwap = prices.get(symbol, (None, None))
        vwap_closes[symbol] = count_vwap_closes(state, symbol, position, last_close,
                                                vwap)
        row = _position_row(position)
        row["last_close"] = last_close
        row["session_vwap"] = vwap
        row["closes_below_vwap"] = vwap_closes[symbol]
        rows_for_packet.append(row)

    packet = {
        "generated_at": tick.now.isoformat(), "date": f"{today:%Y-%m-%d}",
        "schema_version": decide_mod.PACKET_SCHEMA_VERSION,
        "book": tick.book.book_id, "book_id": tick.book.book_id,
        "mode": tick.book.mode, "rules_commit": tick.rules,
        "strategy_key": Path(str(tick.book.strategy_dir)).name,
        "account": bs.facts_for(state), "positions": rows_for_packet,
        "working_orders": [dict(o, orderId=k) for k, o in state.working_orders.items()
                           if isinstance(o, dict)],
    }

    result = None
    model_view: dict[str, dict] = {}
    if positions:
        strategy_dir = project_root() / str(tick.book.strategy_dir)
        result = decide_mod.decide(book_dict(tick.book), strategy_dir, "manage", packet,
                                   dry_run=tick.dry)
        cost = _number(result.cost_usd)
        state.model_cost_today = round(state.model_cost_today + cost, 6)
        tick.model_cost += cost
        for message in result.notes:
            tick.note(message)
        record_decision_problems(tick, state, result)
        model_view = {str(e.get("symbol") or "").upper(): e for e in result.exits}

    counter = make_day_trade_counter(guard)

    for symbol, position in positions.items():
        last_close, vwap = prices.get(symbol, (None, None))
        held = (f"{symbol}: holding {position.qty:g} shares ({position.side}) "
                f"bought around {position.avg_cost:.2f}")
        if last_close is None:
            tick.say(held)
            tick.note(f"{symbol}: no price came back, so it is left alone this tick")
            tick.record(state, symbol, "hold",
                        "no price came back this tick, so no rule could be checked "
                        "against it")
            continue
        tick.say(held + f", last {last_close:.2f}"
                 + (f", vwap {vwap:.2f}" if vwap else ""))

        # The best price since entry is what a trailing stop follows, so it is
        # updated before the rules are checked and it is kept in the book file.
        best = position.trailing_high_or_low
        if best is None:
            position.trailing_high_or_low = last_close
        elif position.is_short:
            position.trailing_high_or_low = min(float(best), last_close)
        else:
            position.trailing_high_or_low = max(float(best), last_close)

        # A winner's stop follows it up. The stop on the position and the stop
        # resting at the broker have to move together, or the file and the
        # account would disagree about where this trade gets out.
        nearer = tighter_stop_for(position, guard)
        if nearer is not None:
            was = _number(position.stop)
            position.stop = nearer
            tick.say(f"  {symbol}: the stop tightens from "
                     f"{was:.2f} to {nearer:.2f}, following the best price "
                     f"{float(position.trailing_high_or_low):.2f}")
            state.put_position(position)
            move_resting_stop(tick, state, position, nearer, broker, guard, guards,
                              account_state)
        state.put_position(position)

        trigger, why = exit_reason_for(position, plan, guard, today, last_close, vwap,
                                       closes_through_vwap=vwap_closes.get(symbol, 0))
        view = model_view.get(symbol) or {}
        model_says = str(view.get("action") or "").lower()
        model_reason = str(view.get("rationale") or "")

        # THE FADE IS AN OBSERVATION IN MONTH ONE, item D2 (Mo, 2026-09-06).
        # Both the rule fade and a fade the model called are written into the
        # ledger as fade_observed and close nothing at all. The fade comes from
        # a different published strategy and was never tested here, so month one
        # measures the pick and records what every fade would have cost or
        # saved. An "exit" from the model still closes the position, which is
        # what the manage prompt now says in as many words.
        #
        # Set risk.vwap_fade_action to `exit` in a book's strategy.yaml and the
        # old behaviour comes straight back, for the rule and for the model
        # together.
        if trigger is None and model_says == "exit":
            trigger = "model_exit"
            why = f"the model asked to close it now: {model_reason or 'no reason given'}"
        elif trigger is None and model_says == "fade":
            if plan.vwap_fade_acts:
                trigger = "model_fade"
                why = ("the model called the momentum gone: "
                       f"{model_reason or 'no reason given'}")
            else:
                trigger = "fade_observed"
                why = ("the model called the momentum gone: "
                       f"{model_reason or 'no reason given'}")
        elif trigger is not None and model_reason:
            why = f"{why}. The model said {model_says or 'nothing'}: {model_reason}"

        if trigger == "fade_observed":
            # Written down, acted on never. The position is held.
            tick.say(f"  {symbol}: a fade would have closed this, and in month one "
                     "it only gets written down")
            tick.rule("vwap_fade_observed", f"{symbol}: {why}",
                      "logged only, the position was held (item D2, month one)")
            tick.record(state, symbol, "fade observed, position held", why,
                        model=result.model if result else None, cost=None,
                        prompt_hash=result.prompt_hash if result else "")
            continue

        if trigger is None:
            tick.say(f"  holding {symbol}, no rule has fired")
            tick.record(state, symbol, "hold",
                        "no stop, target, trailing stop or time stop has fired"
                        + (f". The model said: {model_reason}" if model_reason else ""),
                        model=result.model if result else None, cost=None,
                        prompt_hash=result.prompt_hash if result else "")
            continue

        intent = gr.OrderIntent(
            symbol=symbol, side="BUY" if position.is_short else "SELL",
            qty=int(round(abs(position.qty))), limit_price=round(last_close, 2),
            purpose="exit", book_id=tick.book.book_id)

        verdict = day_trade_check(guard, intent, today, counter, position.opened_on)
        if verdict.blocked:
            tick.say(f"  NOT closing {symbol}: {verdict.reason}")
            tick.rule("pdt_limit", f"{symbol}: {verdict.reason}",
                      "the closing order was not placed")
            tick.record(state, symbol, "exit refused by the day trade rule",
                        verdict.reason)
            continue
        if verdict.would_have_blocked or verdict.is_day_trade:
            tick.note(f"{symbol}: {verdict.reason}")
            if verdict.would_have_blocked:
                tick.rule("pdt_limit", f"{symbol}: {verdict.reason}",
                          "allowed here, and it would have been blocked in a live "
                          "account under 25,000 dollars")

        consider(tick, state, guard, account_state, intent, broker, guards,
                 extra=f"[{trigger}] because {why}",
                 model=result.model if result else None,
                 prompt_hash=result.prompt_hash if result else "")

    _fire_waiting_entries(tick, state, plan, guard, broker, account_state, guards)


def positions_now(state: bs.BookState) -> dict:
    """What this book holds right now, keyed by symbol."""
    return state.all_positions()


def note_late_entry(tick: BookTick, state: bs.BookState, plan: BookPlan,
                    symbol: str, detail: str) -> None:
    """Write down one entry the 10:15 cutoff stopped, item D3.

    Mo moved the cutoff from 11:00 to 10:15 on 2026-09-06 because entries after
    10:15 chase moves that have already been made. Every entry it blocks is
    written into the ledger under the rule id entries_cutoff, so at the end of
    the month the cutoff can be measured rather than argued about: if the names
    it turned away all went on to run, the cutoff cost money and should move
    back.
    """
    reason = (f"{symbol}: new entries stopped at {plan.entries_until:%H:%M} New York "
              f"time and it is {tick.now:%H:%M}, so {detail}")
    tick.note(reason)
    tick.rule("entries_cutoff", reason,
              "no entry order was worked out, and this row is what measures what the "
              "cutoff cost")
    tick.record(state, symbol, "no entry, past the cutoff", reason)


def _fire_waiting_entries(tick: BookTick, state: bs.BookState, plan: BookPlan,
                          guard: gr.Guardrails, broker: broker_mod.Broker,
                          account_state, guards: Guards) -> None:
    """A pick whose entry has not been worked out yet gets another look.

    The momentum strategy enters on a break of the opening range, which may
    happen at 09:40, at 10:55, or never. A pick refused at 09:35 for want of
    room can also come back once something else has been closed.
    """
    blocked = entries_blocked_reason(guards, state)
    if blocked:
        if state.picks:
            tick.note(f"no new positions this tick: {blocked}")
        return
    if not gr.entries_allowed_now(guard, tick.now):
        for pick in state.picks:
            if not isinstance(pick, dict):
                continue
            symbol = str(pick.get("symbol") or "").upper()
            already = state.triggered.get(symbol) or {}
            if not symbol or symbol in positions_now(state) or already.get("allowed") \
                    or already.get("sent") or already.get("skipped"):
                continue
            note_late_entry(tick, state, plan, symbol,
                            "the trigger had not been broken by the cutoff")
        return

    positions = state.all_positions()
    for pick in state.picks:
        if not isinstance(pick, dict):
            continue
        symbol = str(pick.get("symbol") or "").upper()
        if not symbol or symbol in positions:
            continue
        already = state.triggered.get(symbol) or {}
        if already.get("allowed") or already.get("sent") or already.get("skipped"):
            continue

        entry = _number(pick.get("entry"))
        if entry <= 0:
            continue
        short = str(pick.get("side") or "long").lower() in ("short", "sell")

        last_close = None
        if plan.family == MOMENTUM:
            try:
                bars = broker_mod.bars_5m_today(broker, contract_for({"symbol": symbol}))
            except Exception:                # noqa: BLE001
                bars = []
            if bars:
                last_close = _number(bars[-1].get("close")) or None
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

        # The trade is entered at the price the market gave, not the one the pick
        # planned for, so the stop is re-measured from there before anything is
        # sent. Same clamp, same rejection, same reasons written down. The stop
        # comes first now, because the share count is worked out from it.
        low, high = _opening_range(state, symbol)
        levels = protective_levels(guard, entry=last_close, short=short,
                                   model_stop=_number(pick.get("stop")),
                                   model_target=target, opening_range_low=low,
                                   opening_range_high=high,
                                   atr=atr_for(state, symbol))
        if levels.reject:
            tick.say(f"  {symbol}: rejected. {levels.reject}")
            tick.rule("decision_rejected", f"{symbol}: {levels.reject}",
                      "the entry was not worked out")
            tick.record(state, symbol, "decision_rejected", levels.reject)
            state.triggered[symbol] = {
                "at": tick.now.isoformat(), "price": last_close, "allowed": False,
                "sent": False, "skipped": "decision_rejected"}
            continue
        for message in levels.notes:
            tick.note(f"{symbol}: {message}")

        # Size on the price we would actually pay, not the price we planned for.
        quantity = size_for(tick, guard, account_state, symbol, last_close, levels.stop)
        if quantity <= 0:
            tick.record(state, symbol, "no entry",
                        f"at {last_close:.2f} this book's limits allow zero shares")
            continue

        borrow = _borrow_answer(state, symbol)
        halted, limit_state = tradeable_now(broker, {"symbol": symbol}, tick.notes)
        intent = _entry_intent(symbol, short, quantity, last_close,
                               tick.book.book_id, borrow,
                               sector=sector_for(state, symbol),
                               halted=halted, limit_state=limit_state)
        tick.say(f"  {symbol} broke its {entry:.2f} trigger, now {last_close:.2f}")

        # Same order as the pick path: the trigger record first, because a fill
        # can arrive inside consider() and its ledger row reads these facts.
        state.triggered[symbol] = {
            "at": tick.now.isoformat(), "price": last_close,
            "allowed": False, "sent": False, "mode": tick.book.mode,
            "side": "short" if short else "long", "stop": levels.stop,
            "target": levels.target, "qty": int(quantity)}
        extra = f"stop {levels.stop:.2f}"
        if levels.target > 0:
            extra += f", target {levels.target:.2f}"
        facts = facts_line(trade_facts(state, symbol, guard))
        if facts:
            extra += f" [{facts}]"
        if short:
            extra += f", borrow: {borrow.note}"
        decision = consider(tick, state, guard, account_state, intent, broker, guards,
                            extra=extra, stop=levels.stop, target=levels.target)
        state.triggered[symbol]["allowed"] = decision.allowed
        put_the_pick_down(tick, state, symbol, decision)
        if decision.daily_halt:
            state.halt("a guardrail asked for a halt for the rest of the day")


def flatten_price(quote: dict | None, short: bool) -> float | None:
    """The price a limit flatten goes out at: the bid to sell, the ask to buy.

    Momentum v2, item A11 (Mo, 2026-09-06). From 15:45 the book gets out with
    limit orders sitting on the other side's price, because spreads widen and
    depth collapses in the last few minutes and a market order into that pays
    for the hurry. Closing a long means selling, so it takes the bid. Closing a
    short means buying, so it takes the ask.

    None when the quote carries neither, and then the caller sends a market
    order and says so, because being flat matters more than the last few cents.
    """
    if not isinstance(quote, dict):
        return None
    wanted = "ask" if short else "bid"
    price = _number(quote.get(wanted), -1.0)
    if price > 0:
        return round(price, 2)
    return snapshot_price(quote)


def do_flatten(tick: BookTick, state: bs.BookState, plan: BookPlan,
               guard: gr.Guardrails, broker: broker_mod.Broker, account_state,
               guards: Guards) -> None:
    """Close everything, in the two stages Momentum v2 asks for (item A11).

    From flatten_at, 15:45, every position goes out as a LIMIT order at the bid
    for a long and the ask for a short. Spreads widen and depth collapses in the
    last few minutes of the day, so a market order into that pays for the hurry.

    From flatten_market_at, 15:55, anything still open goes out at MARKET. That
    is the backstop, and it exists because being flat matters more than the last
    few cents. A book with no flatten_market_at in its settings behaves exactly
    as it always did and sends market orders throughout.
    """
    positions = state.all_positions()
    if not positions:
        tick.say(f"Nothing is open at {plan.flatten_at:%H:%M}, so there is nothing "
                 "to close.")
        return

    at_market = plan.flatten_market_at is None or gr.must_flatten_at_market_now(
        guard, tick.now)
    if at_market:
        tick.say(f"It is past {(plan.flatten_market_at or plan.flatten_at):%H:%M}. "
                 f"Closing all {len(positions)} open positions at market, which is "
                 "the backstop.")
    else:
        tick.say(f"It is past {plan.flatten_at:%H:%M}. Closing all {len(positions)} "
                 "open positions with limit orders at the bid or the ask. Anything "
                 f"still open at {plan.flatten_market_at:%H:%M} goes out at market.")

    quotes = snapshot_by_symbol(broker, [{"symbol": s} for s in positions], [])
    counter = make_day_trade_counter(guard)
    today = tick.now.date()
    for symbol, position in positions.items():
        price = snapshot_price(quotes.get(symbol))
        limit = None
        if not at_market:
            limit = flatten_price(quotes.get(symbol), position.is_short)
            if limit is None:
                tick.note(f"{symbol}: no bid or ask came back, so this one goes out "
                          "at market rather than waiting for a price that may not "
                          "arrive before the close")
        intent = gr.OrderIntent(
            symbol=symbol, side="BUY" if position.is_short else "SELL",
            qty=int(round(abs(position.qty))), limit_price=limit, purpose="flatten",
            book_id=tick.book.book_id)
        verdict = day_trade_check(guard, intent, today, counter, position.opened_on)
        if verdict.blocked:
            tick.say(f"  NOT closing {symbol}: {verdict.reason}")
            tick.rule("pdt_limit", f"{symbol}: {verdict.reason}",
                      "the closing order was not placed")
            tick.record(state, symbol, "flatten refused by the day trade rule",
                        verdict.reason)
            continue
        how = ("at market" if intent.limit_price is None
               else f"limit {intent.limit_price:.2f} on the "
                    f"{'ask' if position.is_short else 'bid'}")
        consider(tick, state, guard, account_state, intent, broker, guards,
                 extra=(f"end of day close out {how}, last price {price:.2f}" if price
                        else f"end of day close out {how}"))


def write_daily(tick: BookTick, state: bs.BookState) -> None:
    """This book's own end of day line, written once, at or after the close.

    A note on the Daily tab in the ledger: it has no book column, on purpose,
    because it tracks the one paper account all five books share. So the per book
    figures go to the Rules Log, which does have a book column and which the
    Books tab slices on, and the one account level line is written in main() once
    every book has had its turn.
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


# ------------------------------------------------------------------- one book

def book_claims(state: bs.BookState) -> dict[str, float]:
    """Every name one book holds or has a working entry order in, and what it is worth.

    A working entry order counts exactly as much as a position here. A book with
    an order resting at the broker is as committed to that name as one already
    holding it, and pretending otherwise is how two books end up in the same
    ticker in the gap between sending an order and it filling.
    """
    claims: dict[str, float] = {}
    for symbol, position in state.all_positions().items():
        claims[symbol] = round(
            claims.get(symbol, 0.0) + abs(_number(position.market_value)), 2)
    for order in (state.working_orders or {}).values():
        if not isinstance(order, dict):
            continue
        if str(order.get("purpose") or "entry") != "entry":
            continue
        symbol = str(order.get("symbol") or "").upper()
        if not symbol:
            continue
        remaining = _number(order.get("remaining"), _number(order.get("qty")))
        price = _number(order.get("limit_price")) or _number(order.get("price"))
        claims[symbol] = round(
            claims.get(symbol, 0.0) + (remaining * price if remaining > 0
                                       and price > 0 else 0.0), 2)
    return claims


@dataclass
class AccountWide:
    """What all five books hold between them, which no single book can see.

    order      the book ids in register order, which is what settles a tie.
    claims     {book id: {symbol: dollars}} for every name each book holds or
               has a working entry order in.
    equities   {book id: dollars} what each book is worth.

    owners, exposure and equity are worked out from those three rather than
    stored, because absorb() below rewrites one book's row part way through a
    tick and three separately maintained copies of the same fact would drift.

    WHY absorb() EXISTS. This used to be read once at the top of the tick and
    then left alone while all five books took their turns. That made one ticker,
    one book a rule about yesterday: book A could open AAPL at 09:35 and book B,
    running four lines later in the SAME tick, would still be told nobody was in
    it, because the map it was handed had been built before A moved. So the
    exclusivity rule refused nothing on the only tick where it mattered. Now
    main() folds each book's own state back in the moment that book finishes,
    and the book after it sees the truth.
    """

    order: list[str] = field(default_factory=list)
    claims: dict[str, dict[str, float]] = field(default_factory=dict)
    equities: dict[str, float] = field(default_factory=dict)

    @property
    def owners(self) -> dict[str, str]:
        """{symbol: book id}, first come first served in register order."""
        found: dict[str, str] = {}
        for book_id in self.order:
            for symbol in self.claims.get(book_id) or {}:
                found.setdefault(symbol, book_id)
        return found

    @property
    def exposure(self) -> dict[str, float]:
        """{symbol: dollars} added up across every book, for item A9's cap."""
        total: dict[str, float] = {}
        for book_id in self.order:
            for symbol, money in (self.claims.get(book_id) or {}).items():
                total[symbol] = round(total.get(symbol, 0.0) + money, 2)
        return total

    @property
    def equity(self) -> float:
        """What the five books are worth added together."""
        return round(sum(self.equities.values()), 2)

    def without(self, book_id: str) -> dict[str, str]:
        """The owners map as one book sees it, with its own names taken out."""
        return {symbol: owner for symbol, owner in self.owners.items()
                if owner != book_id}

    def absorb(self, book_id: str, state: bs.BookState) -> None:
        """Replace one book's row with what that book believes right now.

        Called after each book's turn, so the next book in the register sees
        what this one just did rather than what it had before the tick started.
        A replacement rather than an addition, because the book's earlier row is
        already in here and adding to it would count the same position twice.
        """
        book_id = str(book_id)
        if book_id not in self.order:
            self.order.append(book_id)
        self.claims[book_id] = book_claims(state)
        self.equities[book_id] = bs.book_equity(state)


def read_account_wide(books, now: datetime,
                      broker_positions: dict[str, dict] | None = None) -> AccountWide:
    """Read every book's file once, and add up what the five of them hold.

    The shared IBKR account nets positions by symbol, so it can say the account
    holds 400 shares of AAPL and it cannot say which book owns which hundred.
    Only the book files can. This is the one place that reads all five, and it
    runs once a tick rather than once a book, which is also why the order checks
    take these numbers rather than working them out for themselves.

    Ties go first come, first served, resolved by the order the books appear in
    config/books.yaml, which is the rule named as SYMBOL_TIE_BREAK in
    agent/guardrails.py.
    """
    wide = AccountWide()
    for book in books:
        state = bs.load_state(book.book_id, book.order_ref, now.date(),
                              capital=book.capital_usd)
        if broker_positions:
            bs.mark_positions(state, broker_positions)
        wide.absorb(book.book_id, state)
    return wide


def sector_exposure_for(state: bs.BookState) -> dict[str, float]:
    """How much money this book has in each industry, as {industry: dollars}.

    The industry comes off the shortlist row the position was opened from, which
    is where the scanner wrote what IBKR's contract details said. A position
    whose industry nobody knows is counted under the empty string, which no
    sector cap ever matches, so it never quietly makes room for another name in
    a sector it might belong to.
    """
    out: dict[str, float] = {}
    for symbol, position in state.all_positions().items():
        sector = sector_for(state, symbol) or ""
        out[sector] = round(out.get(sector, 0.0) + abs(_number(position.market_value)), 2)
    return out


def fill_v2_state(account_state, state: bs.BookState, book: gr.BookConfig,
                  now: datetime, account_wide: "AccountWide | None" = None) -> None:
    """Put the Momentum v2 facts on the snapshot the guardrails check against.

    Three of the new rules need facts only the loop can see (Mo, 2026-09-06):

        week_pnl, month_pnl, consecutive_losing_days
                          item A8, read out of this book's earlier state files
        sector_exposure   item A9, this book's money by industry

    The rest come off account_wide, which main() reads once for the whole tick
    because only main() sees all five books at once:

        symbols_held_elsewhere    which names the other books already have
        symbol_exposure_all_books item A9's account level per symbol cap
        account_equity            what the five books are worth together

    Called with account_wide left out, all three stay empty and the account
    level cap falls back to this book's own equity, which is the smaller and
    therefore tighter number.
    """
    history = loss_history(book.order_ref, now.date(),
                           _number(state.realized_pnl_today))
    account_state.week_pnl = history.week_pnl
    account_state.month_pnl = history.month_pnl
    account_state.consecutive_losing_days = history.losing_days
    account_state.sector_exposure = sector_exposure_for(state)

    if account_wide is not None:
        account_state.symbols_held_elsewhere = account_wide.without(book.book_id)
        account_state.symbol_exposure_all_books = dict(account_wide.exposure)
        account_state.account_equity = account_wide.equity or None


def run_book(book: gr.BookConfig, guard: gr.Guardrails, now: datetime, guards: Guards,
             broker: broker_mod.Broker, account_id: str, broker_positions: dict,
             rules: str, write_ledger: bool, halt_reason: str | None = None,
             quiet: bool = False,
             account_wide: "AccountWide | None" = None,
             broker_orders: list | None = None) -> tuple[BookTick, bs.BookState]:
    """One book's whole turn: work out the phase, do it, write the file."""
    tick = BookTick(book, now, rules, write_ledger, quiet=quiet)
    plan = plan_for(book, guard)
    day = now.date()
    state = bs.load_state(book.book_id, book.order_ref, day, capital=book.capital_usd)
    state.account_id = account_id

    # A kill switch flatten is not a mismatch. It is the handle working. So the
    # books are brought into line with the account and told why, rather than
    # being halted for the day over a difference somebody made on purpose.
    if kill_switch_flattened():
        closed = close_positions_flattened_by_the_kill_switch(
            tick, state, broker_positions)
        if closed:
            tick.say(f"The kill switch flattened {closed} position(s) in this book. "
                     "They are marked closed rather than treated as a mismatch.")
            halt_reason = None

    if halt_reason:
        state.halt(halt_reason)

    bs.mark_positions(state, broker_positions)
    if not state.day_start_equity:
        state.day_start_equity = bs.book_equity(state) or float(book.capital_usd)

    account_state = bs.account_state_for(
        state, gr, now, account_id, guards.stop_present, broker_positions)
    fill_v2_state(account_state, state, book, now, account_wide)

    phase, why = phase_for(now, plan, pick_done=state.picked_at is not None,
                           last_manage_at=state.last_manage_at, swept_at=state.swept_at)
    tick.phase = phase

    if not quiet:
        facts = bs.facts_for(state)
        print(f"\n[{book.order_ref}] {book.name}")
        print(f"  mode {book.mode} | model {book.model or 'none'} | "
              f"strategy {plan.family} | phase {phase} ({why})")
        print(f"  worth {facts['equity']:,.2f} of {facts['capital']:,.2f} capital | "
              f"{facts['open_positions']} open | {facts['entries_opened_today']} "
              f"entries today | rules {rules}")
        if state.halted:
            print(f"  HALTED: {state.halt_reason}")

    try:
        if phase == PREOPEN:
            do_preopen(tick, state, broker)
        elif phase == SWEEP:
            do_sweep(tick, state, plan, sweep_due(now, plan, state.swept_at) or "")
        elif phase == SCAN:
            do_scan(tick, state, plan)
        elif phase == PICK:
            do_pick(tick, state, plan, guard, broker, account_state, guards)
        elif phase == MANAGE:
            do_manage(tick, state, plan, guard, broker, account_state, guards,
                      broker_orders)
        elif phase == FLATTEN:
            do_flatten(tick, state, plan, guard, broker, account_state, guards)
        elif phase == CLOSED:
            if now.weekday() < 5 and now.time() >= plan.market_close \
                    and not state.daily_written:
                write_daily(tick, state)
            else:
                tick.say("Nothing to do. " + why)
        else:
            tick.say("Nothing to do yet. " + why)
    except Exception as exc:                 # noqa: BLE001
        # One book falling over must not cost the other four their tick.
        tick.note(f"this book's {phase} raised {type(exc).__name__}: {exc}")
        tick.rule("book_failed", f"the {phase} phase of book {book.book_id} raised "
                  f"{type(exc).__name__}: {exc}", "this book was skipped this tick")

    # Item A9 asks for the count of positions pointing the same way at once to
    # be written down every tick, because five morning gappers all long is one
    # bet made five times and the ledger should say so.
    held = state.all_positions().values()
    longs = sum(1 for position in held if not position.is_short)
    shorts = len(held) - longs
    if held:
        tick.rule("same_direction_count",
                  f"book {book.book_id} holds {longs} long and {shorts} short at "
                  f"{now:%H:%M}, in "
                  f"{len({sector_for(state, s) or 'unknown' for s in state.all_positions()})} "
                  "industries", "written down, nothing was blocked")

    tick.next_tick_seconds = gr.next_tick_seconds(
        guard, now, holding=bool(state.all_positions() or state.working_orders))

    state.tick_count += 1
    state.last_tick = now.isoformat()
    state.last_phase = phase

    # The attendance register, and the picture of what this book held while it
    # was awake. Both go to the database, which is the system of record: a tick
    # with no row is a tick that never ran, and that is the only place a missed
    # tick can be counted from.
    db_call("record_tick", ts=now, book_id=book.book_id, phase=phase,
            mode=str(book.mode), rules_commit=rules,
            outcome=("halted" if state.halted else "ok"),
            notes="; ".join(tick.notes[:5]) or None)
    snapshot_book_positions(tick, state)

    path = bs.save_state(state)
    if not quiet:
        print(f"  {tick.would_be_orders} would be orders, {tick.approved} allowed, "
              f"{tick.refused} refused, {tick.sent} sent | state {path}")
    return tick, state


def snapshot_book_positions(tick: BookTick, state: bs.BookState) -> None:
    """What this book was holding at this moment, into the database.

    Every tick, so a day can be replayed afterwards rather than guessed at from
    the fills. The stop and the target go in with it, which is what would make a
    stop that quietly went missing visible in the history instead of invisible.

    A flat book writes nothing and that is correct: the snapshot for a book
    holding nothing is the absence of rows, and the tick row above is what
    proves the loop was awake at the time.
    """
    rows = []
    for symbol, position in state.all_positions().items():
        rows.append({
            "symbol": symbol,
            "qty": int(round(position.qty)),
            "avg_cost": round(_number(position.avg_cost), 4),
            "market_price": position.last_close,
            "market_value": round(_number(position.market_value), 2),
            "unrealized_pnl": (
                round((_number(position.last_close) - _number(position.avg_cost))
                      * position.qty, 2) if position.last_close else None),
            "stop": _number(position.stop) or None,
            "target": _number(position.target) or None,
        })
    if rows:
        db_call("snapshot_positions", rows, ts=tick.now, book_id=tick.book.book_id)


# ----------------------------------------------------------------- the driver

def tick_log_line(now: datetime, rules: str, book: gr.BookConfig, tick: BookTick,
                  state: bs.BookState) -> str:
    facts = bs.facts_for(state)
    return (f"{now:%Y-%m-%d %H:%M:%S} {now.tzname()} | book={book.book_id} | "
            f"rules={rules} | mode={book.mode} | phase={tick.phase} | "
            f"equity={facts['equity']:.2f} | positions={facts['open_positions']} | "
            f"picks={len(state.picks)} | would_be_orders={tick.would_be_orders} | "
            f"approved={tick.approved} | refused={tick.refused} | sent={tick.sent} | "
            f"halted={'yes' if state.halted else 'no'} | "
            f"model_cost={tick.model_cost:.4f} | notes={len(tick.notes)} | "
            f"next_tick={tick.next_tick_seconds}s")


#: Where the loop writes how soon it wants waking again, in whole seconds.
#: agent/run_tick.sh reads it after every tick. See docs/LOOP.md.
NEXT_TICK_FILE = "next_tick_seconds"


def write_next_tick(seconds: int) -> Path:
    """Say how soon this loop wants waking again, in one small file. Item A14.

    launchd wakes the loop on a fixed timetable and cannot be told to speed up
    mid morning, so the cadence is written here instead and the wrapper honours
    it: agent/run_tick.sh reads this file after a tick and, when it says less
    than a minute, runs a short in-process sub-loop of its own until the next
    launchd wake up is due. That way the 30 second cadence between 09:35 and
    11:00 costs no change to the launchd job at all.

    The number written is the SMALLEST any book asked for, because the loop
    ticks every book together and the busiest one sets the pace.
    """
    path = output_dir() / NEXT_TICK_FILE
    path.write_text(f"{max(1, int(seconds))}\n")
    return path


def write_tick_log(lines: list[str]) -> Path:
    path = output_dir() / "loop.log"
    with path.open("a") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


#: The keys a broker row might carry the account number under. IBKR's own
#: portfolio rows use "account"; the MCP server has been seen using the other
#: two, so all three are read rather than one being guessed at.
ACCOUNT_KEYS = ("account", "acctId", "accountId", "account_id")


def position_account(row: dict, fallback: str = "") -> str:
    """Which account one broker position row belongs to."""
    for key in ACCOUNT_KEYS:
        value = str(row.get(key) or "").strip()
        if value:
            return value.upper()
    return str(fallback or "").strip().upper()


def position_key(row: dict, fallback_account: str = "") -> tuple[str, str]:
    """(symbol, account), which is what actually identifies a broker holding.

    Keyed by symbol alone, a second row for the same name overwrites the first
    and its shares vanish out of every sum the loop makes. That is not a
    hypothetical: an account can report more than one row for one ticker, and
    the replay gate's phantom position fault produces exactly that shape.
    """
    return (str(row.get("symbol") or "").strip().upper(),
            position_account(row, fallback_account))


def add_position_rows(first: dict, second: dict) -> dict:
    """Two broker rows for the same name and account, added into one.

    The share counts and the market values add. The average cost is weighted by
    the share count, which is what an average cost means, and a row with no
    shares cannot move it. Everything else on the row is taken from the first
    one seen, because the two describe the same holding.
    """
    out = dict(first)
    left = _number(first.get("position"))
    right = _number(second.get("position"))
    total = left + right
    out["position"] = total

    left_cost = _number(first.get("avgCost"))
    right_cost = _number(second.get("avgCost"))
    if total:
        out["avgCost"] = round(
            (left_cost * abs(left) + right_cost * abs(right))
            / (abs(left) + abs(right) or 1.0), 4)
    for key in ("marketValue", "unrealizedPnl", "realizedPnl"):
        if first.get(key) is not None or second.get(key) is not None:
            out[key] = round(_number(first.get(key)) + _number(second.get(key)), 2)
    refs = list(first.get("order_refs") or []) + list(second.get("order_refs") or [])
    if refs:
        out["order_refs"] = sorted(set(refs))
    return out


def positions_by_key(holdings: dict,
                     fallback_account: str = "") -> dict[tuple[str, str], dict]:
    """The account's holdings keyed by (symbol, account), nothing dropped.

    Two rows that land on the same key are added rather than one replacing the
    other, so a name reported twice for one account keeps both halves of itself.
    """
    out: dict[tuple[str, str], dict] = {}
    for row in (holdings.get("positions") or []):
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        key = position_key(row, fallback_account)
        out[key] = add_position_rows(out[key], row) if key in out else dict(row)
    return {key: row for key, row in out.items() if _number(row.get("position"))}


def net_by_symbol(rows: dict[tuple[str, str], dict]) -> dict[str, dict]:
    """The same holdings netted per symbol, which is the one line IBKR shows.

    Everything downstream of this, the reconciliation and each book's marks,
    wants the netted answer, because a book holds a NAME and not a name in an
    account. The per key view above is what stops a row being lost on the way.
    """
    out: dict[str, dict] = {}
    for (symbol, _account), row in rows.items():
        out[symbol] = add_position_rows(out[symbol], row) if symbol in out else dict(row)
    return {symbol: row for symbol, row in out.items() if _number(row.get("position"))}


@dataclass
class BrokerFacts:
    """One read of the shared account, in the shapes the rest of the tick wants.

    positions is netted per symbol, which is what the reconciliation and each
    book's marks read. rows is the same holdings keyed by (symbol, account),
    which is what stops a second row for one name being lost, and it is what
    goes into the position snapshot so the history keeps what the account
    actually said.
    """

    values: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    orders: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def read_broker_facts(broker: broker_mod.Broker,
                      wanted_account: str | None) -> BrokerFacts:
    """One read of the shared account, used by all five books.

    Read once per tick rather than once per book, because five books asking IB
    Gateway the same three questions in the same second is how a data pacing
    violation happens.
    """
    facts = BrokerFacts()
    holdings: dict = {}
    try:
        facts.values = broker_mod.account_values(broker, wanted_account)
    except Exception as exc:                 # noqa: BLE001
        facts.problems.append(f"could not read the account summary: {exc}")
    try:
        holdings = broker.portfolio(wanted_account) or {}
    except Exception as exc:                 # noqa: BLE001
        facts.problems.append(f"could not read the positions: {exc}")
    try:
        facts.orders = (broker.open_orders(wanted_account) or {}).get("orders", []) or []
    except Exception as exc:                 # noqa: BLE001
        facts.problems.append(f"could not read the open orders: {exc}")

    facts.rows = positions_by_key(holdings, str(wanted_account or ""))
    facts.positions = net_by_symbol(facts.rows)
    return facts


def main(argv: list[str] | None = None, broker: broker_mod.Broker | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One tick of the trading loop, across all five books. Dry run "
                    "only today: the mode comes from config/books.yaml and every "
                    "book in it is dry_run.")
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
                        help="accepted and ignored. Every book is already dry_run, "
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

    books = list(registry.enabled_books())
    if args.book:
        wanted = str(args.book).strip().upper()
        books = [b for b in books if b.book_id == wanted]
        if not books:
            print(f"loop: there is no enabled book {wanted} in {args.books_file}. The "
                  "enabled ones are "
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

    facts = read_broker_facts(broker, account_wanted)
    values = facts.values
    broker_positions = facts.positions
    broker_orders = facts.orders
    account_id = str(account_wanted or "").strip()
    equity = _number(values.get("NetLiquidation"))

    for problem in facts.problems:
        print(f"  note: {problem}")
    print(f"\nAccount {account_id}: worth {equity:,.2f}, {len(broker_positions)} "
          f"positions and {len(broker_orders)} working orders across all five books")

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
    # agree about who owns what, sizing the next order would be guesswork.
    books_state: dict[str, dict] = {}
    for book in books:
        state = bs.load_state(book.book_id, book.order_ref, now.date(),
                              capital=book.capital_usd)
        books_state[book.book_id] = {
            "positions": {symbol: int(round(p.qty))
                          for symbol, p in state.all_positions().items()},
            "working_orders": dict(state.working_orders)}

    # Read once for the whole tick, because it opens all five book files and
    # five books each opening all five would be twenty five reads a tick.
    account_wide = read_account_wide(books, now, broker_positions)

    outcome = run_reconciliation(broker_positions_for_reconcile(broker_positions),
                                 broker_orders_for_reconcile(broker_orders),
                                 books_state, expected_orphans())
    print(f"\nReconciliation: {outcome.note}")
    for line in outcome.lines[:10]:
        print(f"  {line}")
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
    totals = {"would_be": 0, "approved": 0, "refused": 0, "sent": 0, "cost": 0.0,
              "next_tick": 300}
    any_daily = False

    for book in books:
        try:
            guard = gr.load_book_guardrails(args.books_file, book.book_id)
        except gr.GuardrailError as exc:
            print(f"\n[{book.order_ref}] cannot load this book's limits, so it is "
                  f"skipped this tick: {exc}")
            ledger_writer.log_rule(now, "book_settings_broken",
                                   f"book {book.book_id}: {exc} [rules {rules}]",
                                   "this book was skipped this tick",
                                   book_id=book.book_id, dry_run=not args.write_ledger)
            continue

        tick, state = run_book(book, guard, now, guards, broker, account_id,
                               broker_positions, rules, args.write_ledger,
                               halt_reason=halts.get(book.book_id),
                               account_wide=account_wide,
                               broker_orders=broker_orders)
        # Fold this book's own answer back in before the next one takes its
        # turn, so one ticker, one book is a rule about right now rather than a
        # rule about how the day started. Without this, book B is told nobody is
        # in a name that book A opened four lines ago.
        account_wide.absorb(book.book_id, state)
        lines.append(tick_log_line(now, rules, book, tick, state))
        totals["would_be"] += tick.would_be_orders
        totals["approved"] += tick.approved
        totals["refused"] += tick.refused
        totals["sent"] += tick.sent
        totals["cost"] += tick.model_cost
        totals["next_tick"] = min(totals["next_tick"], tick.next_tick_seconds)
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
    cadence = write_next_tick(int(totals["next_tick"]))
    # Written last, because a tick that fell over halfway must not leave a fresh
    # heartbeat behind saying everything is fine.
    beat = touch_heartbeat(now)
    print("\n" + "=" * 78)
    for line in lines:
        print(line)
    print(f"Totals: {totals['would_be']} would be orders, {totals['approved']} allowed, "
          f"{totals['refused']} refused, {totals['sent']} sent, "
          f"{totals['cost']:.4f} dollars of model spend")
    print(f"Tick log {path}")
    print(f"Next tick wanted in {int(totals['next_tick'])} seconds ({cadence})")
    print(f"Heartbeat {beat}")
    if RECONCILE_ERROR:
        print(f"agent/reconcile.py could not be imported ({RECONCILE_ERROR}), so every "
              "book was halted this tick.")
    if PDT_ERROR:
        print(f"agent/pdt.py could not be imported ({PDT_ERROR}), so day trades were "
              "read from the book files and the five day count is unknown.")
    if PREOPEN_ERROR:
        print(f"agent/preopen.py could not be imported ({PREOPEN_ERROR}), so nothing "
              "was gathered before the open and the scanner works it out at 09:35.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
