"""The dead man's handle: if the loop stops breathing while it is holding
something, get out.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/deadman.py

THE PROBLEM IT SOLVES
---------------------
Every other guard in this project assumes something is still running. The
watchdog tells Mo the loop has stopped, which is useful at 10 in the morning and
useless at 3 in the afternoon when he is on a plane. agent/loop.py protects its
positions itself: it moves the stops, it flattens the momentum books at 15:55.
All of that stops the moment the loop stops.

So the one state nothing covers is: the loop is dead, the market is open, and
five books' worth of positions are sitting at the broker with nobody watching
them. This job is for exactly that state and no other.

WHAT IT DOES
------------
Every five minutes between 09:30 and 16:00 on a weekday it asks three questions,
in this order, and stops at the first no:

    1. Is the loop's heartbeat older than fifteen minutes?
    2. Is the market actually open right now?
    3. Does the broker hold any position, or any working order, that carries a
       BOOK_ order reference?

If all three are yes it alerts Mo and then runs agent/kill_switch.py for real,
which cancels every order and closes every position. Two messages arrive, on
purpose: the first says why, and the second, from the kill switch itself, says
what happened.

If only the first two are yes it sends one message saying the loop is dead, and
it trades nothing. That is the case where the loop has died but no book was
holding anything, and there is nothing to protect.

Question 3 is what stops it trading over nothing. The paper account holds one
share of SPY that no book bought, and a manual position like that is an ORPHAN:
it is listed in the output and named in the alert, and it never causes an order.
Only a book's own exposure counts, because only a book's exposure was being
managed by the thing that died.

Questions 1 and 2 have to be answered together. Outside market hours a fifteen
minute silence is not a fault, it is a Tuesday evening.

WHERE THE HEARTBEAT COMES FROM
------------------------------
The newest change time among these, all under output/:

    heartbeat              if this file exists at all, it wins outright and
                           nothing else is looked at. Nothing writes it today.
                           It is here so that when the loop starts touching one
                           file per tick, this reads that and stops guessing.
    loop.log               one line per book per tick, appended every tick
    tick_YYYY-MM-DD.log    everything one day's ticks printed
    state_BOOK_*_*.json    one file per book per day, rewritten every tick

Change times, not the timestamps written inside the files. That is a deliberate
difference from agent/watchdog.py, which parses the last line of loop.log and
the last_tick field inside each state file. Both are right for their job: the
watchdog is reporting to a person and should quote the loop's own words, while
this one is deciding whether to trade and should ask the filesystem, which
cannot be fooled by a loop that is still writing a stale timestamp.

FIRING ONCE PER INCIDENT
------------------------
output/deadman_state.json remembers which silence it already acted on, keyed on
the heartbeat that was stale, and what it did about it. So a loop that stays
dead all afternoon gets one kill switch at 10:15 and not seventy-eight of them.
When the loop comes back and later dies again, the heartbeat has moved, so that
is a new silence and it can act again.

The note also records whether it only spoke up or actually traded, because those
are not the same strength. A silence that was only spoken about, because no book
held anything at the time, must not go quiet if a book's position turns up ten
minutes later in the same silence.

REHEARSAL IS THE DEFAULT
------------------------
With no flags it decides, prints the decision in full, and does nothing:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/deadman.py

A dry run sends no alert, pulls no kill switch, and does not write the state
file, because consuming an incident it never acted on would leave the real run
silent. Only --really arms it, and that is what the launchd job passes.

PAPER ONLY, THE SAME AS THE KILL SWITCH
---------------------------------------
On an account that does not start with DU it alerts Mo and stops there, unless
AGENTIC_TRADING_KILL_LIVE is set to yes in the environment. Flattening a live
account because a log file looked old is not a decision a cron job gets to make
on its own.

Exit codes: 0 nothing needed, 1 it acted or would have acted, 2 it wanted to act
and could not, which today means a live account without the environment
variable. A broker it cannot read during market hours also exits 2 and sends no
alert, because agent/watchdog.py is already checking Gateway every five minutes
and would be saying the same thing louder.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402
import broker as broker_mod  # noqa: E402
import kill_switch  # noqa: E402
from paths import config_dir, output_dir, project_root  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: How long the loop may be quiet during market hours before this counts it as
#: dead. Three missed ticks at five minutes each. The watchdog shouts at two
#: missed ticks, so Mo always hears about it before anything is traded.
STALE_AFTER = timedelta(minutes=15)

#: The one file that wins outright when it exists.
HEARTBEAT_NAME = "heartbeat"

#: What is looked at when it does not, newest change time wins.
HEARTBEAT_PATTERNS = ("loop.log", "tick_*.log", "state_BOOK_*_*.json")

#: A book's orders all carry a tag starting with this. Anything else at the
#: broker was not put there by the loop and is none of this job's business.
BOOK_REF_PREFIX = "BOOK_"

#: Where the "I have already dealt with this one" note lives.
STATE_NAME = "deadman_state.json"


# --------------------------------------------------------------- the heartbeat

@dataclass(frozen=True)
class Heartbeat:
    """When the loop last touched a file, and which file that was."""

    at: datetime | None = None
    source: str = "nothing found"

    @property
    def incident(self) -> str:
        """The key that says which silence this is. Same key, same incident."""
        return self.at.isoformat() if self.at else "never"

    def age(self, now: datetime) -> timedelta | None:
        return None if self.at is None else now - self.at


def _moment(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=EASTERN)


def heartbeat(root: Path | None = None) -> Heartbeat:
    """When the loop last wrote anything down, by the file's own change time."""
    folder = (root / "output") if root is not None else output_dir()
    if not folder.exists():
        return Heartbeat()

    preferred = folder / HEARTBEAT_NAME
    if preferred.exists():
        return Heartbeat(_moment(preferred), f"output/{HEARTBEAT_NAME}")

    best: datetime | None = None
    where = "nothing found"
    for pattern in HEARTBEAT_PATTERNS:
        for path in folder.glob(pattern):
            if not path.is_file():
                continue
            when = _moment(path)
            if best is None or when > best:
                best, where = when, f"output/{path.name}"
    return Heartbeat(best, where)


# ------------------------------------------------------------- the market clock

@dataclass(frozen=True)
class Schedule:
    """When the market is open, read from config/guardrails.yaml."""

    open_at: clock_time = clock_time(9, 30)
    close_at: clock_time = clock_time(16, 0)
    holidays: tuple = ()


def load_schedule() -> Schedule:
    """Market hours and holidays from config/guardrails.yaml.

    Read with a plain YAML load rather than by importing agent/guardrails.py,
    the same way agent/watchdog.py does it, so that work in progress on the
    guardrails cannot break this. Unreadable means the defaults, which are the
    normal US session.
    """
    default = Schedule()
    try:
        import yaml
        raw = yaml.safe_load((config_dir() / "guardrails.yaml").read_text(encoding="utf-8"))
        block = (raw or {}).get("schedule") or {}
    except Exception:                                             # noqa: BLE001
        return default

    def parse(text, fallback: clock_time) -> clock_time:
        try:
            hours, _, minutes = str(text).partition(":")
            return clock_time(int(hours), int(minutes))
        except (TypeError, ValueError):
            return fallback

    return Schedule(
        open_at=parse(block.get("scan_start"), default.open_at),
        close_at=parse(block.get("market_close"), default.close_at),
        holidays=tuple(str(day) for day in (block.get("holidays") or [])),
    )


def in_market_hours(now: datetime, schedule: Schedule | None = None) -> bool:
    """Is the US market open right now? Weekdays, session hours, no holidays."""
    schedule = schedule or load_schedule()
    if now.weekday() >= 5:
        return False
    if f"{now.date():%Y-%m-%d}" in schedule.holidays:
        return False
    return schedule.open_at <= now.timetz().replace(tzinfo=None) <= schedule.close_at


# ------------------------------------------------------- whose position is that

def refs_on(row: dict) -> list[str]:
    """Every order reference on one position or order row, in any shape.

    A working order carries its own tag as orderRef. A position does not: IBKR
    reports a netted account and nothing about which order put it there. The
    replay broker adds order_refs to its position rows, which the real one
    cannot, so this reads whatever is there and book_symbols() below covers the
    real case from the book files.
    """
    found: list[str] = []
    if not isinstance(row, dict):
        return found
    for key in ("orderRef", "order_ref", "ref"):
        value = row.get(key)
        if value:
            found.append(str(value))
    for key in ("order_refs", "orderRefs"):
        for value in row.get(key) or []:
            if value:
                found.append(str(value))
    nested = row.get("order")
    if isinstance(nested, dict):
        found.extend(refs_on(nested))
    return sorted(set(found))


def book_refs_on(row: dict) -> list[str]:
    """Just the references that belong to one of the five books."""
    return [ref for ref in refs_on(row) if ref.upper().startswith(BOOK_REF_PREFIX)]


def book_symbols(root: Path | None = None) -> dict[str, str]:
    """Which symbols the books think they hold, from their own state files.

    {symbol: the book that holds it}. The newest file per book wins, today's if
    the loop got that far and the most recent earlier one if it did not. That
    fallback is not a nicety: books C and D hold for weeks, so a loop that died
    before writing today's file still has real positions belonging to it, and
    those are exactly the ones nobody is watching.
    """
    folder = (root / "output") if root is not None else output_dir(create=False)
    if not folder.exists():
        return {}

    newest: dict[str, Path] = {}
    for path in sorted(folder.glob(f"state_{BOOK_REF_PREFIX}*_*.json")):
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ref = str(stored.get("order_ref") or "").upper()
        if not ref.startswith(BOOK_REF_PREFIX):
            continue
        # Sorted by name, so the last file seen for a book is its newest day.
        newest[ref] = path

    held: dict[str, str] = {}
    for ref, path in newest.items():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for symbol, position in (stored.get("positions") or {}).items():
            try:
                quantity = float((position or {}).get("qty") or 0.0)
            except (TypeError, ValueError, AttributeError):
                continue
            if quantity:
                held[str(symbol).upper()] = ref
    return held


def sort_positions(positions: list[dict],
                   held: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Split the account's positions into the books' and everybody else's.

    A position belongs to a book when the broker tagged it, or when a book's own
    state file says that book holds that symbol. Everything else is an orphan:
    listed, reported, and never a reason to trade.
    """
    theirs: list[dict] = []
    orphans: list[dict] = []
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        refs = book_refs_on(position)
        if not refs and symbol in held:
            refs = [held[symbol]]
        if refs:
            theirs.append({**position, "book_refs": refs})
        else:
            orphans.append(position)
    return theirs, orphans


def sort_orders(orders: list[dict]) -> tuple[list[dict], list[dict]]:
    """The same split for working orders, which do carry their own tag."""
    theirs: list[dict] = []
    orphans: list[dict] = []
    for order in orders:
        refs = book_refs_on(order)
        if refs:
            theirs.append({**order, "book_refs": refs})
        else:
            orphans.append(order)
    return theirs, orphans


# ---------------------------------------------------------------- the decision

@dataclass
class Verdict:
    """Everything the dead man's handle worked out on one run."""

    now: datetime
    heartbeat: Heartbeat
    market_hours: bool
    stale: bool
    age_minutes: float | None = None
    account: str = ""
    book_positions: list = field(default_factory=list)
    book_orders: list = field(default_factory=list)
    orphan_positions: list = field(default_factory=list)
    orphan_orders: list = field(default_factory=list)
    broker_error: str = ""
    reason: str = ""
    act: bool = False
    exposed: bool = False

    @property
    def incident(self) -> str:
        return self.heartbeat.incident

    @property
    def wanted(self) -> str:
        """The strongest thing this run would do: fire, or only speak up."""
        return ACTION_FIRED if self.exposed else ACTION_NOTIFIED


def look(broker, now: datetime, root: Path | None = None,
         stale_after: timedelta = STALE_AFTER,
         schedule: Schedule | None = None) -> Verdict:
    """Work out whether the loop is dead and whether that matters. Trades nothing.

    The broker is only asked anything when the first two answers are already
    yes. A healthy loop means this job never touches IB Gateway at all, which is
    the point: seventy-eight wake ups a day should cost nothing.
    """
    beat = heartbeat(root)
    market_hours = in_market_hours(now, schedule)
    age = beat.age(now)
    stale = age is None or age > stale_after

    verdict = Verdict(
        now=now, heartbeat=beat, market_hours=market_hours, stale=stale,
        age_minutes=None if age is None else round(age.total_seconds() / 60.0, 1))

    if not market_hours:
        verdict.reason = ("the market is shut, so a quiet loop is not a fault. "
                          "Nothing was asked of the broker.")
        return verdict
    if not stale:
        verdict.reason = (f"the loop last wrote {beat.source} "
                          f"{verdict.age_minutes:g} minutes ago, which is inside "
                          f"the {stale_after.total_seconds() / 60:g} minute limit")
        return verdict

    holdings, portfolio_error = kill_switch.attempt(broker.portfolio)
    resting, orders_error = kill_switch.attempt(broker.open_orders)
    if portfolio_error or orders_error:
        verdict.broker_error = portfolio_error or orders_error
        verdict.reason = (f"the loop is quiet and the broker cannot be read "
                          f"either: {verdict.broker_error}")
        return verdict

    verdict.account = str((holdings or {}).get("account") or "")
    positions = kill_switch.open_positions(holdings or {})
    orders = kill_switch.working_orders(resting or {})
    verdict.book_positions, verdict.orphan_positions = sort_positions(
        positions, book_symbols(root))
    verdict.book_orders, verdict.orphan_orders = sort_orders(orders)

    verdict.act = True
    silence = (f"the loop has written nothing since {beat.source} "
               f"{verdict.age_minutes:g} minutes ago"
               if beat.at else "the loop has never written anything")
    if not verdict.book_positions and not verdict.book_orders:
        verdict.reason = (
            f"{silence} and the market is open, but no book is holding anything "
            f"and no book has an order working, so there is nothing to close. "
            f"{len(verdict.orphan_positions)} position(s) and "
            f"{len(verdict.orphan_orders)} order(s) at the broker belong to "
            "nobody, and those are left alone.")
        return verdict

    verdict.exposed = True
    verdict.reason = (
        f"{silence}, the market is open, and the books are exposed: "
        f"{len(verdict.book_positions)} position(s) and "
        f"{len(verdict.book_orders)} working order(s) carry a "
        f"{BOOK_REF_PREFIX} tag with nobody watching them")
    return verdict


# ---------------------------------------------------------------- the memory

#: The two things one run can do. Speaking up is not as strong as trading, so a
#: silence that was only spoken about can still be fired on later if a book's
#: position turns up in the same silence.
ACTION_NOTIFIED = "notified"
ACTION_FIRED = "fired"


def state_path(root: Path | None = None) -> Path:
    folder = (root / "output") if root is not None else output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / STATE_NAME


def read_state(root: Path | None = None) -> dict:
    """What this job did last time, or an empty dictionary."""
    try:
        stored = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def already_handled(incident: str, wanted: str, root: Path | None = None) -> bool:
    """Has this silence already been dealt with, at least this strongly?

    Two runs on the same silence do the same thing twice, which is exactly what
    the state file is for. But a silence that was only spoken about, because the
    books held nothing at the time, must not stop a kill switch when a book's
    position turns up ten minutes later in the same silence. So a note of
    "notified" blocks another notification and nothing else.
    """
    stored = read_state(root)
    if str(stored.get("incident") or "") != incident:
        return False
    if wanted == ACTION_NOTIFIED:
        return True
    return str(stored.get("action") or "") == ACTION_FIRED


def remember(verdict: Verdict, action: str, outcome: str,
             root: Path | None = None) -> Path:
    """Write down what was done about this silence, so it is not done twice."""
    path = state_path(root)
    path.write_text(json.dumps({
        "at": verdict.now.isoformat(),
        "incident": verdict.incident,
        "action": action,
        "outcome": outcome,
        "heartbeat": verdict.heartbeat.at.isoformat() if verdict.heartbeat.at else None,
        "heartbeat_source": verdict.heartbeat.source,
        "age_minutes": verdict.age_minutes,
        "account": verdict.account,
        "book_positions": [p.get("symbol") for p in verdict.book_positions],
        "book_orders": [kill_switch.order_id_of(o) for o in verdict.book_orders],
        "orphans": [p.get("symbol") for p in verdict.orphan_positions],
    }, indent=2, default=str) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------- the whole

def symbol_of(row: dict) -> str:
    """The ticker on a position or an order row.

    A position row from the MCP server carries the symbol at the top level. An
    order row carries it inside contract, which is why this exists rather than a
    plain row.get("symbol").
    """
    return str((row or {}).get("symbol")
               or ((row or {}).get("contract") or {}).get("symbol") or "?")


def describe(verdict: Verdict) -> str:
    """What is at the broker, in the words that go into the alert."""
    lines = []
    for position in verdict.book_positions:
        lines.append(f"- {position.get('symbol')} "
                     f"{float(position.get('position') or 0):g} shares, "
                     f"books {', '.join(position.get('book_refs') or [])}")
    for order in verdict.book_orders:
        lines.append(f"- working order {kill_switch.order_id_of(order)}: "
                     f"{order.get('action')} {order.get('totalQuantity')} "
                     f"{symbol_of(order)}, books "
                     f"{', '.join(order.get('book_refs') or [])}")
    for position in verdict.orphan_positions:
        lines.append(f"- LEFT ALONE: {position.get('symbol')} "
                     f"{float(position.get('position') or 0):g} shares, no book "
                     "owns this one")
    for order in verdict.orphan_orders:
        lines.append(f"- LEFT ALONE: order {kill_switch.order_id_of(order)}, "
                     f"{order.get('action')} {order.get('totalQuantity')} "
                     f"{symbol_of(order)}, no book owns this one")
    return "\n".join(lines) or "- nothing at all"


def why(verdict: Verdict) -> str:
    """The opening of every alert this job sends: what happened, and where."""
    if verdict.heartbeat.at:
        when = (f" at {verdict.heartbeat.at:%Y-%m-%d %H:%M:%S %Z}, "
                f"{verdict.age_minutes:g} minutes ago")
    else:
        when = ", which has never been written"
    return (f"The trading loop has stopped writing. Last sign of life: "
            f"{verdict.heartbeat.source}{when}.\n\n"
            f"The market is open. What account {verdict.account or 'unknown'} "
            f"is holding:\n{describe(verdict)}\n\n")


def run(broker, *, really: bool = False, now: datetime | None = None,
        root: Path | None = None, sleep=time.sleep) -> tuple[int, Verdict]:
    """One pass. Returns (exit code, what it decided).

    really   False decides and prints and stops there, sending no alert, pulling
             no kill switch and writing no state file.
    sleep    handed to the kill switch, so a test can advance a replay clock
             instead of waiting thirty real seconds.

    Exit codes: 0 nothing needed, 1 it acted, 2 it wanted to act and could not.
    """
    now = now or datetime.now(EASTERN)
    verdict = look(broker, now, root)

    heading = "DEAD MAN'S HANDLE" if really else "DEAD MAN'S HANDLE, DRY RUN"
    print(f"===== {heading} at {now:%Y-%m-%d %H:%M:%S %Z} =====")
    print(f"heartbeat: {verdict.heartbeat.source}"
          + (f" at {verdict.heartbeat.at:%H:%M:%S}, "
             f"{verdict.age_minutes:g} minutes ago" if verdict.heartbeat.at else ""))
    print(f"market open: {'yes' if verdict.market_hours else 'no'}")
    print(f"decision: {verdict.reason}")

    if not verdict.act:
        # A broker that cannot be read during market hours is agent/watchdog.py's
        # alert to send, not this one's. It checks Gateway, the port and the
        # login every five minutes and would be saying the same thing.
        return (2 if verdict.broker_error else 0), verdict

    print(f"account: {verdict.account or 'unknown'}")
    print("what is at the broker:")
    print(describe(verdict))

    if already_handled(verdict.incident, verdict.wanted, root):
        print(f"\nAlready dealt with this silence ({verdict.incident}). Doing nothing.")
        print(f"Delete {state_path(root)} to let it act again.")
        return 0, verdict

    live_account = not kill_switch.is_paper_account(verdict.account)
    live_ok = kill_switch.live_kill_allowed()
    blocked_by_live = verdict.exposed and live_account and not live_ok

    if not really:
        print("\nDRY RUN. A real run would now:")
        if not verdict.exposed:
            print("  1. tell Mo the loop is dead and no book is exposed")
            print("  2. stop there. Nothing at the broker belongs to a book.")
        elif blocked_by_live:
            print("  1. tell Mo the loop is dead and the books are exposed")
            print(f"  2. stop there, because {verdict.account} is not a paper "
                  f"account and {kill_switch.LIVE_KILL_ENV_VAR} is not set to yes")
        else:
            print("  1. tell Mo the loop is dead and the books are exposed")
            print("  2. run the kill switch for real: cancel everything, close "
                  "everything")
        print(f"  3. write {state_path(root)}, so it acts once and not every "
              "five minutes")
        print("\nNothing was sent, nothing was traded, no state file was written.")
        return 1, verdict

    # ------------------------------------------------------------ nothing of ours
    if not verdict.exposed:
        delivered = alerts_module.alert(
            "error", "The trading loop has stopped",
            why(verdict)
            + "No book is holding anything and no book has an order working, so "
              "the dead man's handle has NOT traded. Anything listed above as "
              "left alone was not put there by a book and is none of its "
              "business.\n\nThe loop is still down. Start with "
              "output/tick_YYYY-MM-DD.log and the launchd job.\n")
        print(f"\nalert delivered through: {', '.join(delivered) or 'nothing'}")
        remember(verdict, ACTION_NOTIFIED, "nothing of ours was exposed", root)
        return 1, verdict

    # --------------------------------------------------------- a live account
    if blocked_by_live:
        print(f"\nSTOPPING: {verdict.account} is not a paper account and "
              f"{kill_switch.LIVE_KILL_ENV_VAR} is not set to yes.")
        print("Alerting only. Nothing will be cancelled and nothing will be closed.")
        delivered = alerts_module.alert(
            "error", f"Loop is dead and {verdict.account} is a LIVE account",
            why(verdict)
            + "This is NOT the paper account, so the dead man's handle has "
              "alerted and stopped. It will not flatten a live account on a log "
              "file's say so.\n\nDo it yourself if that is what you want:\n"
              f"  {kill_switch.LIVE_KILL_ENV_VAR}=yes "
              f"{project_root()}/agent/kill_switch.sh --really "
              "--live-account-ok\n")
        print(f"alert delivered through: {', '.join(delivered) or 'nothing'}")
        remember(verdict, ACTION_NOTIFIED, "alert only, live account", root)
        return 2, verdict

    # ------------------------------------------------------------- pull it
    delivered = alerts_module.alert(
        "error", "Loop is dead, pulling the kill switch",
        why(verdict)
        + "The dead man's handle is now cancelling every order and closing every "
          "position. A second message follows with the result.\n")
    print(f"\nalert delivered through: {', '.join(delivered) or 'nothing'}")

    print("\nrunning the kill switch for real")
    status, result = kill_switch.pull(broker, really=True,
                                      live_account_ok=live_account,
                                      now=now, sleep=sleep)

    outcome = result.refused or ("flat" if result.flat else "not flat")
    written = remember(verdict, ACTION_FIRED, outcome, root)
    print(f"\nkill switch finished: {outcome}")
    print(f"written to: {written}")
    return (1 if status in (0, 1) else 2), verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="If the trading loop has stopped while the books are "
                    "holding something, alert Mo and pull the kill switch. A "
                    "dry run unless --really is given.")
    parser.add_argument("--really", action="store_true",
                        help="Arm it. Without this it decides, prints, and does "
                             "nothing at all.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Decide and print. Already the default; the flag is "
                             "here so the launchd job can say what it means.")
    args = parser.parse_args(argv)

    status, _ = run(broker_mod.McpBroker(), really=args.really and not args.dry_run)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
