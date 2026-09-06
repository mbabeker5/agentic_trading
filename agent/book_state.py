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

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Where the project lives is agent/paths.py's job and nobody else's. These two
# names are re-exported here because callers of this module have always asked it
# where the state files go.
from paths import ROOT_ENV_VAR, output_dir, project_root  # noqa: E402,F401


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


@dataclass
class BookState:
    """Everything one book carries from one tick to the next."""

    book_id: str
    order_ref: str
    date: str
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
    halt_reason: str | None = None
    decisions: list = field(default_factory=list)
    swept_at: dict = field(default_factory=dict)
    last_manage_at: str | None = None
    triggered: dict = field(default_factory=dict)
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

    def halt(self, reason: str) -> None:
        """Stop this book opening anything else today, and say why in plain words."""
        self.halted = True
        self.halt_reason = reason if not self.halt_reason else f"{self.halt_reason}; {reason}"


# ---------------------------------------------------------- loading, saving

def state_path(order_ref: str, day: date_type, root: Path | None = None) -> Path:
    """output/state_BOOK_A_2026-09-08.json, the file for one book on one day."""
    folder = (root / "output") if root is not None else output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"state_{order_ref}_{day:%Y-%m-%d}.json"


def _known(cls, stored: dict) -> dict:
    fields = set(cls.__dataclass_fields__)
    return {k: v for k, v in stored.items() if k in fields}


def load_state(book_id: str, order_ref: str, day: date_type, capital: float = 0.0,
               root: Path | None = None) -> BookState:
    """Today's file for this book, or a fresh day built from yesterday's close.

    A brand new day starts with the book's own capital, unless there is a file
    from an earlier day, in which case what that day ended holding is carried
    forward. The insider and Congress books hold for weeks, so carrying the
    positions over is not a nicety: without it, every morning the loop would
    think those books were flat and their stops would vanish.
    """
    path = state_path(order_ref, day, root)
    if path.exists():
        try:
            stored = json.loads(path.read_text())
            return BookState(**_known(BookState, stored))
        except Exception as exc:                 # noqa: BLE001
            print(f"book_state: {path} is unreadable ({exc!r}), starting this book's "
                  "day from what came before it", file=sys.stderr)

    fresh = BookState(book_id=book_id, order_ref=order_ref, date=f"{day:%Y-%m-%d}",
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
    """
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
