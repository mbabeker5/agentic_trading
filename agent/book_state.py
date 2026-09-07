"""What one book remembers between ticks.

There is no long running process in this project. launchd wakes agent/loop.py,
the loop does the one thing that belongs to that minute, and exits. Everything a
book has to carry from one tick to the next lives in one file per book per day:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/state_BOOK_A_2026-09-08.json

Five books, five files a day. Delete one and that book starts the day over,
which is exactly what you want after a bad morning and exactly what you must not
do while it is holding something.

What is in it, and why each piece has to survive a restart:

    capital                what the book was given to trade with
    cash                   what it has not spent
    day_start_equity       what it was worth at the open. The daily loss cap is
                           a percentage of this, so it is written down once and
                           never recalculated during the day
    positions              what it holds, by symbol, each with the entry, the
                           stop, the target, the side, the day it was opened and
                           the best price seen since, which is what a trailing
                           stop follows
    working_orders         orders sent and not yet filled, by broker order id
    fills_seen             the execution ids already applied, so reading the
                           day's fills again cannot count one twice
    shortlist              the names the scanner or the sweep found this morning
    picks                  what the model or the rules chose from that shortlist
    entries_opened_today   how many brand new names it has opened today, which
                           is a limit in every strategy file
    realized_pnl_today     money made or lost on trades already closed today
    halted / halt_reason   whether this book is stopped, and why, in words
    decisions              every judgement this book made today, with the reason

The important detail: this is per book, not per account. Five books share one
IBKR paper account, so the account's own position list is the five books added
together and cannot answer "what does book C hold". Only these files can. That
is also why a mismatch between them and the broker is a halt rather than a
warning: if they disagree, nobody knows who owns what.

Nothing here talks to a broker or a network. It reads and writes JSON and does
arithmetic, which is why the tests for it run in a second.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Where the project lives is agent/paths.py's job and nobody else's. These two
# names are re-exported here because callers of this module have always asked it
# where the state files go.
from paths import ROOT_ENV_VAR, output_dir, project_root  # noqa: E402,F401

#: Every clock in this project is New York, and created_at below is the one
#: field that must be the REAL clock rather than the tick's, so it gets its own
#: timezone here rather than borrowing the caller's.
NEW_YORK = ZoneInfo("America/New_York")

#: Where a state file that cannot be describing the day it claims is put.
STALE_FOLDER = "stale"

#: Every file moved there by this process, newest last. The loop reads it after
#: it has loaded its books and sends one alert naming all of them.
#:
#: A list here rather than a callback passed in, because load_state is called
#: from a dozen places across the loop, the dead man's handle and the tests, and
#: none of them should have to remember to pass an alerter for a thing that
#: happens once a year. There is no long running process in this project, so it
#: lives exactly as long as one tick.
STALE_ARCHIVED: list[dict] = []


# ---------------------------------------------------------------- the shapes

@dataclass
class Position:
    """One holding in one book, with the plan it was opened under.

    side is "long" or "short". trailing_high_or_low is the best price the
    position has seen since it was opened: the highest close for a long, the
    lowest for a short, because down is the good direction when you are short.
    That one number is what a trailing stop is measured from, and losing it on a
    restart would quietly reset every trailing stop to nothing.
    """

    symbol: str
    qty: float = 0.0
    avg_cost: float = 0.0
    opened_on: str = ""
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    trailing_high_or_low: float | None = None
    side: str = "long"
    market_value: float = 0.0
    last_close: float | None = None
    entry_reason: str = ""

    @property
    def is_short(self) -> bool:
        return self.side == "short" or self.qty < 0


#: Why a book is halted. The cause matters because it decides what clears it,
#: and until 2026-09-06 nothing cleared anything at all.
#:
#:   reconciliation  the books and the broker disagreed. Clears itself the
#:                   moment they agree again, because the thing that was wrong
#:                   is no longer wrong.
#:   loss_cap        the book is down to a limit. Clears at the next trading
#:                   day, which is what the limits are measured over.
#:   kill_switch     somebody pulled the handle, or the dead man's handle did.
#:                   Clears only once output/LOOP_DISABLED is gone, which means
#:                   a person ran agent/reenable.sh, AND reconciliation is
#:                   clean. Two conditions, because the handle is pulled for a
#:                   reason and the account was emptied under the books' feet.
#:   other           anything else, including a guardrail asking for one.
#:                   Clears at the next trading day.
#:   market_data     the quotes are not good enough to open a position on: a
#:                   competing session has taken the data line, or what came
#:                   back is delayed. Clears the moment a live quote arrives,
#:                   because the thing that was wrong is no longer wrong.
HALT_RECONCILIATION = "reconciliation"
HALT_LOSS_CAP = "loss_cap"
HALT_KILL_SWITCH = "kill_switch"
HALT_MARKET_DATA = "market_data"
HALT_OTHER = "other"

#: How many halt reasons are kept. The five most recent, oldest dropped.
#:
#: This used to be an ever growing string. halt() appended to it and
#: reconciliation calls it on every tick, so the same sentence ended up stored
#: eighty times over in the book file and quoted in full in every log line that
#: mentioned it. The first replay gate run found one reason 2,276 characters
#: long, on a day when exactly one thing had gone wrong.
MAX_HALT_REASONS = 5

#: And how long any one of them may be. A reason nobody can read is not a reason.
HALT_REASON_MAX_CHARS = 200


@dataclass
class BookState:
    """Everything one book carries from one tick to the next."""

    book_id: str
    order_ref: str
    date: str
    #: When this file was first written, on the REAL clock, in New York.
    #:
    #: Never the tick's own time. A tick can be told to pretend it is another
    #: day with --now, and its pretend time goes into last_tick and into every
    #: decision, which is right: those describe the day being rehearsed. This
    #: one field describes the FILE, and it is what tells a file written on
    #: Saturday for Tuesday apart from one written on Tuesday for Tuesday. See
    #: is_stale() below and docs/BACKLOG.md item 18.
    created_at: str = ""
    capital: float = 0.0
    cash: float = 0.0
    day_start_equity: float = 0.0
    positions: dict = field(default_factory=dict)
    working_orders: dict = field(default_factory=dict)
    shortlist: list = field(default_factory=list)
    shortlist_path: str | None = None
    shortlist_read_at: str | None = None
    picks: list = field(default_factory=list)
    picked_at: str | None = None
    packet_path: str | None = None
    entries_opened_today: int = 0
    realized_pnl_today: float = 0.0
    halted: bool = False
    #: One readable sentence: the most recent reason, plus how many earlier ones
    #: there were. Bounded, because everything that quotes a halt quotes this.
    halt_reason: str | None = None
    #: The five most recent reasons, newest last, each with the time it happened
    #: and what kind of halt it is. This is what decides whether a halt clears.
    halt_reasons: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    swept_at: dict = field(default_factory=dict)
    last_manage_at: str | None = None
    triggered: dict = field(default_factory=dict)
    #: IBKR's own execution ids for every fill already applied to this book
    #: today. Reading the day's executions again after a restart must not count
    #: the same fill twice, and the exec id is the only thing that can say so.
    fills_seen: list = field(default_factory=list)
    tick_count: int = 0
    last_tick: str | None = None
    last_phase: str | None = None
    daily_written: bool = False
    model_cost_today: float = 0.0
    account_id: str | None = None

    # ------------------------------------------------------------ positions

    def position(self, symbol: str) -> Position | None:
        raw = self.positions.get(str(symbol).upper())
        if raw is None:
            return None
        return raw if isinstance(raw, Position) else Position(**_known(Position, raw))

    def all_positions(self) -> dict[str, Position]:
        """Every holding as a Position object, keyed by symbol, zero sizes dropped."""
        out: dict[str, Position] = {}
        for symbol in list(self.positions):
            found = self.position(symbol)
            if found is not None and found.qty:
                out[str(symbol).upper()] = found
        return out

    def put_position(self, position: Position) -> None:
        self.positions[position.symbol.upper()] = asdict(position)

    def drop_position(self, symbol: str) -> None:
        self.positions.pop(str(symbol).upper(), None)

    # ----------------------------------------------------------- the record

    def note_decision(self, when: Any, symbol: str, decision: str, rationale: str,
                      phase: str = "", rules_commit: str = "") -> None:
        """Add one judgement to the day's record. Kept even when nothing was sent."""
        self.decisions.append({
            "at": str(when), "symbol": str(symbol or ""), "phase": phase,
            "decision": str(decision), "rationale": str(rationale),
            "rules_commit": rules_commit,
        })

    def halt(self, reason: str, cause: str = HALT_OTHER, at: Any = None) -> None:
        """Stop this book opening anything else, and say why in plain words.

        The same reason twice in a row is not written down twice. Reconciliation
        calls this on every tick while a disagreement stands, so without that
        one mismatch would fill the list in half an hour and push out every
        other reason the book had.
        """
        reason = str(reason or "").strip()[:HALT_REASON_MAX_CHARS] or "no reason given"
        cause = str(cause or HALT_OTHER)
        when = str(at) if at is not None else datetime.now().astimezone().isoformat()

        self.halted = True
        rows = [row for row in self.halt_reasons if isinstance(row, dict)]
        if not (rows and rows[-1].get("reason") == reason
                and rows[-1].get("cause") == cause):
            rows.append({"at": when, "cause": cause, "reason": reason})
        self.halt_reasons = rows[-MAX_HALT_REASONS:]
        self.halt_reason = self._halt_sentence()

    def clear_halt(self, cause: str | None = None) -> list[dict]:
        """Lift the halts of one cause, or all of them. Returns what was lifted.

        A book halted for two different reasons stays halted until both are
        gone, which is the point of keeping the cause on each one rather than a
        single flag and a growing sentence.
        """
        rows = [row for row in self.halt_reasons if isinstance(row, dict)]
        if cause is None:
            lifted, kept = rows, []
        else:
            lifted = [row for row in rows if row.get("cause") == cause]
            kept = [row for row in rows if row.get("cause") != cause]
        self.halt_reasons = kept
        self.halted = bool(kept)
        self.halt_reason = self._halt_sentence() if kept else None
        return lifted

    def halt_causes(self) -> set:
        """Which kinds of halt are holding this book right now."""
        return {str(row.get("cause")) for row in self.halt_reasons
                if isinstance(row, dict)}

    def _halt_sentence(self) -> str:
        """The most recent reason and a count, short enough to quote anywhere."""
        rows = [row for row in self.halt_reasons if isinstance(row, dict)]
        if not rows:
            return ""
        latest = rows[-1]
        clock = str(latest.get("at") or "")[11:16] or "an unknown time"
        line = (f"{latest.get('reason')} "
                f"(at {clock}, {latest.get('cause', HALT_OTHER)})")
        if len(rows) > 1:
            line += (f", and {len(rows) - 1} earlier reason(s) today, the last "
                     f"{MAX_HALT_REASONS} kept in halt_reasons in this file")
        return line


# ---------------------------------------------------------- loading, saving

def state_path(order_ref: str, day: date_type, root: Path | None = None) -> Path:
    """output/state_BOOK_A_2026-09-08.json, the file for one book on one day."""
    folder = (root / "output") if root is not None else output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"state_{order_ref}_{day:%Y-%m-%d}.json"


def _known(cls, stored: dict) -> dict:
    fields = set(cls.__dataclass_fields__)
    return {k: v for k, v in stored.items() if k in fields}


def written_at(path: Path, stored: dict) -> datetime | None:
    """When this state file was really written, or None when nobody can tell.

    created_at is the answer when the file has one. When it does not, which is
    every file written before 2026-09-07, the file's own modification time is
    the next best thing and it is a real clock too: a rehearsal on Saturday
    leaves a Saturday mtime whatever date it wrote into the name.
    """
    raw = str(stored.get("created_at") or "").strip()
    if raw:
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            moment = None
        if moment is not None:
            return moment if moment.tzinfo else moment.replace(tzinfo=NEW_YORK)
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=NEW_YORK)
    except OSError:
        return None


def is_stale(path: Path, day: date_type, stored: dict,
             real_today: date_type | None = None) -> bool:
    """Was this file written before the day it claims to describe had begun?

    THE BUG THIS CLOSES. On Saturday 2026-09-06 at 13:22 a rehearsal wrote
    state_BOOK_A_2026-09-08.json through E into the real output folder, each one
    saying the pick had already been made. load_state loads a file by the date
    in its name, and the loop reads a set picked_at as the pick already made, so
    on Tuesday 2026-09-08, the first trading day of the experiment, all five
    books would have loaded Saturday's rehearsal and skipped their first real
    pick. Nothing in any log would have looked wrong.

    Two conditions, and both are needed:

        the file was written before the day it names, AND
        that day has actually arrived

    The second is what keeps a rehearsal honest while it is still a rehearsal. A
    file written today for tomorrow is not wrong yet, it is just early, and a
    replay of a day in the past is not wrong at all. Only when the day it claims
    has really started does a file written before that day become a file that
    cannot possibly be describing it.
    """
    today = real_today or datetime.now(NEW_YORK).date()
    if day > today:
        return False                         # the day it names has not arrived
    moment = written_at(path, stored)
    return moment is not None and moment.date() < day


def archive_stale_state(path: Path, day: date_type, stored: dict,
                        real_today: date_type | None = None) -> Path | None:
    """Move a file that cannot be describing today into output/stale/. Where it went.

    None when the file is fine, which is every ordinary morning.

    Moved rather than deleted, because the thing to do with a file nobody can
    explain is keep it and look at it. The day starts fresh from what came
    before, exactly as it would have if the file had never been there. What was
    moved is written into STALE_ARCHIVED so the loop can tell Mo.
    """
    if not is_stale(path, day, stored, real_today):
        return None
    folder = path.parent / STALE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(NEW_YORK).strftime("%Y%m%dT%H%M%S")
    target = folder / f"{path.stem}.moved-{stamp}{path.suffix}"
    moment = written_at(path, stored)
    try:
        path.replace(target)
    except OSError as exc:
        print(f"book_state: {path} was written on "
              f"{moment:%Y-%m-%d} for {day:%Y-%m-%d} and cannot be right, but it "
              f"could not be moved out of the way ({exc}). This book is NOT "
              "starting the day fresh.", file=sys.stderr)
        return None
    print(f"book_state: {path.name} says it is {day:%Y-%m-%d} but it was written on "
          f"{moment:%Y-%m-%d}, before that day began, so it cannot be describing "
          f"it. Moved to {target} and this book starts the day fresh.",
          file=sys.stderr)
    STALE_ARCHIVED.append({
        "order_ref": path.stem.replace("state_", "").rsplit("_", 1)[0],
        "date": f"{day:%Y-%m-%d}",
        "written_at": (f"{moment:%Y-%m-%d %H:%M}" if moment else "unknown"),
        "was": str(path),
        "moved_to": str(target),
    })
    return target


def load_state(book_id: str, order_ref: str, day: date_type, capital: float = 0.0,
               root: Path | None = None) -> BookState:
    """Today's file for this book, or a fresh day built from yesterday's close.

    A brand new day starts with the book's own capital, unless there is a file
    from an earlier day, in which case what that day ended holding is carried
    forward. The insider and Congress books hold for weeks, so carrying the
    positions over is not a nicety: without it, every morning the loop would
    think those books were flat and their stops would vanish.

    A file for today that was written before today began is not used at all. It
    is moved to output/stale/ and the day starts fresh, because a file like that
    is a rehearsal that leaked into the real folder and following it would mean
    skipping the day's first real pick. See archive_stale_state().
    """
    path = state_path(order_ref, day, root)
    if path.exists():
        stored: dict | None = None
        try:
            stored = json.loads(path.read_text())
        except Exception as exc:                 # noqa: BLE001
            print(f"book_state: {path} is unreadable ({exc!r}), starting this book's "
                  "day from what came before it", file=sys.stderr)
        if isinstance(stored, dict) and archive_stale_state(path, day, stored) is None:
            return BookState(**_known(BookState, stored))

    fresh = BookState(book_id=book_id, order_ref=order_ref, date=f"{day:%Y-%m-%d}",
                      created_at=datetime.now(NEW_YORK).isoformat(),
                      capital=float(capital), cash=float(capital),
                      day_start_equity=float(capital))
    previous = load_previous_state(order_ref, day, root)
    if previous is not None:
        fresh.capital = previous.capital or fresh.capital
        fresh.cash = previous.cash
        fresh.positions = dict(previous.positions)
        fresh.working_orders = dict(previous.working_orders)
        fresh.halted = False           # a new day, a new chance
        fresh.halt_reason = None
        fresh.halt_reasons = []        # which is what clears a loss cap halt
        fresh.day_start_equity = 0.0   # filled in by the first tick from the marks
        fresh.account_id = previous.account_id
    return fresh


def load_previous_state(order_ref: str, day: date_type,
                        root: Path | None = None) -> BookState | None:
    """The most recent state file for this book from before today, if there is one."""
    folder = (root / "output") if root is not None else output_dir(create=False)
    if not folder.exists():
        return None
    today_name = f"state_{order_ref}_{day:%Y-%m-%d}.json"
    earlier = sorted(p for p in folder.glob(f"state_{order_ref}_*.json")
                     if p.name < today_name)
    for path in reversed(earlier):
        try:
            return BookState(**_known(BookState, json.loads(path.read_text())))
        except Exception:                        # noqa: BLE001
            continue
    return None


def save_state(state: BookState, root: Path | None = None) -> Path:
    """Write the file, whole or not at all.

    Written to a temporary name and moved into place, so a tick killed halfway
    through leaves the last good file rather than half a new one.

    A state built by hand rather than by load_state gets its created_at here, on
    the real clock, so that every file on disk carries one and nothing has to
    fall back to reading the file's modification time.
    """
    if not str(state.created_at or "").strip():
        state.created_at = datetime.now(NEW_YORK).isoformat()
    day = datetime.strptime(state.date, "%Y-%m-%d").date()
    path = state_path(state.order_ref, day, root)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2, default=str))
    temporary.replace(path)
    return path


# ------------------------------------------------ what the guardrails check

def _number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default        # a NaN is not a number


def mark_positions(state: BookState, broker_positions: dict[str, dict]) -> None:
    """Put today's prices on this book's holdings.

    broker_positions is the account's own list, keyed by symbol. Five books share
    that account, so a symbol two books both hold shows up once with the total.
    The share price is what is taken from it, never the quantity, because the
    quantity belongs to the book file and not to the account.
    """
    for symbol, position in state.all_positions().items():
        row = broker_positions.get(symbol) or {}
        price = _number(row.get("marketPrice"))
        if price <= 0:
            held = _number(row.get("position"))
            value = _number(row.get("marketValue"))
            price = abs(value / held) if held else 0.0
        if price > 0:
            position.last_close = round(price, 4)
            position.market_value = round(price * position.qty, 2)
        elif not position.market_value:
            position.market_value = round(position.avg_cost * position.qty, 2)
        state.put_position(position)


def unrealized_pnl(state: BookState) -> float:
    """Money made or lost on what this book still holds, at today's marks."""
    total = 0.0
    for position in state.all_positions().values():
        if not position.last_close:
            continue
        total += (position.last_close - position.avg_cost) * position.qty
    return round(total, 2)


def gross_exposure(state: BookState) -> float:
    """Everything the book holds added up, ignoring which way it points.

    Long 30,000 and short 20,000 is 50,000 of exposure, not 10,000, because both
    sides can lose money on the same morning.
    """
    return round(sum(abs(_number(p.market_value))
                     for p in state.all_positions().values()), 2)


def pending_notional(state: BookState) -> float:
    """Dollars of entry orders sent and not filled yet."""
    total = 0.0
    for order in state.working_orders.values():
        if not isinstance(order, dict):
            continue
        if str(order.get("purpose") or "entry") != "entry":
            continue
        remaining = _number(order.get("remaining"), _number(order.get("qty")))
        price = _number(order.get("limit_price")) or _number(order.get("price"))
        if remaining > 0 and price > 0:
            total += remaining * price
    return round(total, 2)


def book_equity(state: BookState) -> float:
    """What this book is worth right now.

    The account's net liquidation figure is the five books added together plus
    whatever else is in the account, so it cannot answer this. A book is worth
    what it started the day with, plus what it has made or lost since, closed and
    open together.
    """
    start = _number(state.day_start_equity) or _number(state.capital)
    return round(start + _number(state.realized_pnl_today) + unrealized_pnl(state), 2)


def account_state_for(state: BookState, guardrails_module, now: datetime,
                      account_id: str, kill_switch_present: bool,
                      broker_positions: dict[str, dict] | None = None):
    """The AccountState the guardrails check this book's orders against.

    Two sources go in and one object comes out. The book file says what this book
    holds, what it paid and how many names it has opened today, because the
    account cannot know that. The broker says what those holdings are worth right
    now. Mixing them the other way round is the classic bug: sizing book A
    against all five books' positions would let every book fill the same limit
    five times over.
    """
    if broker_positions:
        mark_positions(state, broker_positions)

    positions = {}
    for symbol, position in state.all_positions().items():
        positions[symbol] = guardrails_module.PositionInfo(
            symbol=symbol,
            qty=int(round(position.qty)),
            avg_cost=round(_number(position.avg_cost), 4),
            market_value=round(_number(position.market_value), 2),
        )

    equity = book_equity(state)
    day_start = _number(state.day_start_equity) or _number(state.capital) or equity
    return guardrails_module.AccountState(
        equity=equity,
        day_start_equity=day_start,
        realized_pnl_today=round(_number(state.realized_pnl_today), 2),
        unrealized_pnl=unrealized_pnl(state),
        open_positions=positions,
        pending_order_notional=pending_notional(state),
        now=now,
        kill_switch_present=kill_switch_present,
        account_id=account_id,
        book_id=state.book_id,
        gross_exposure=gross_exposure(state),
        entries_opened_today=int(state.entries_opened_today),
    )


def facts_for(state: BookState) -> dict:
    """The book's numbers as plain data, for the decision packet and the log."""
    equity = book_equity(state)
    day_start = _number(state.day_start_equity) or _number(state.capital) or equity
    facts = {
        "book": state.book_id,
        "capital": round(_number(state.capital), 2),
        "equity": equity,
        "day_start_equity": round(day_start, 2),
        "cash": round(_number(state.cash), 2),
        "realized_pnl_today": round(_number(state.realized_pnl_today), 2),
        "unrealized_pnl": unrealized_pnl(state),
        "gross_exposure": gross_exposure(state),
        "open_positions": len(state.all_positions()),
        "entries_opened_today": int(state.entries_opened_today),
        "pending_order_notional": pending_notional(state),
    }
    if day_start > 0:
        facts["day_pnl_pct"] = round((equity / day_start - 1.0) * 100.0, 3)
    return facts
