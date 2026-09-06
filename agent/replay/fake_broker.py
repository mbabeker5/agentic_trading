"""A pretend broker that fills orders the way IBKR's paper simulator does.

WHY THIS EXISTS
---------------
Before any of the five books is allowed to place a real paper order, the whole
loop has to run end to end and be seen to behave: the daily loss cap has to
trip, the 3:55 flatten has to happen, a phantom position has to halt trading,
the kill switch has to bite, and the day-trade counter has to count. None of
that can be tested against the live market, because the live market will not
crash your Gateway on demand at 11:07 on a Tuesday.

So the harness replays recorded market data instead. agent/replay/fetch_history.py
fetches the past, agent/replay/record_day.py records a live day, and this file
plays it back and pretends to fill orders against it. The loop cannot tell the
difference, because this class exposes exactly the read methods that
agent/mcp_client.py does, plus the order methods that file deliberately does not
wrap.

Nothing here touches the network, IB Gateway, or a real account. It cannot, and
that is the point: an order sent to a FakeBroker moves numbers in memory and
nothing else.

HOW TIME WORKS
--------------
The clock does not run on its own. advance_to(timestamp) steps it forward, and
as it steps it walks every recorded bar that falls in between, in time order,
deciding what would have filled. The clock only ever moves forward: asking it to
go backwards raises, because a replay that can rewind is a replay that can peek
at the future by accident.

The one rule everything else hangs off: no method ever returns a bar, a quote or
a price stamped later than the current clock. That is what makes a replay honest.

HOW FILLS ARE MODELLED
----------------------
Copied from what IBKR's paper simulator actually does, which is not the same as
what the real market does. The difference is written up plainly in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/REPLAY.md, and
it matters: the simulator is optimistic, so a strategy that only just works here
does not work in real life.

  market order   fills at the next bar's open, plus half the recorded spread if
                 a quote was recorded near that moment and 0.02 if not. Buying
                 pays up, selling gets hit, so the adjustment always costs money.
  limit buy      fills when that bar's low reaches the limit or better. The fill
                 is at the limit, unless the bar opened below the limit already,
                 in which case it fills at the open, which is better than asked.
  limit sell     the mirror image: fills when the bar's high reaches the limit,
                 at the limit, or at the open when the open was already above it.
  stop           triggers on the bar that trades through the stop, then fills on
                 the NEXT bar exactly like a market order. So a stop always costs
                 at least one bar of slippage, which is the honest version.
  quantities     whole shares only.
  commission     0.005 a share, at least 1.00 an order, never more than 1 percent
                 of the order's value. That is IBKR Pro's fixed tier.

Two knobs are off by default and can be turned on to make life harder:
slippage_bps adds a fixed cost to every market fill, and partial_fill_probability
makes some orders fill in pieces so the loop has to cope with a half filled
position.

BOOKS
-----
The five books share one IBKR account, and IBKR only ever reports the netted
total. Every order carries an order_ref (BOOK_A, BOOK_B and so on) and this class
keeps a full set of books per order_ref alongside the netted account, so
reconciliation can be tested properly: the broker nets to the total, and each
book still knows its own positions, cash, and profit.

Run the tests:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest -q tests/test_replay_fake_broker.py
"""
from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

# Importable both as "python agent/replay/fake_broker.py" and as
# "from agent.replay.fake_broker import FakeBroker". The repo has no
# __init__.py files, so the project root has to be on the path either way.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.replay import common                                   # noqa: E402

EASTERN = common.EASTERN

#: The fill series. Everything the strategy does is on five minute bars, so
#: that is what orders are filled against unless a caller says otherwise.
DEFAULT_FILL_BAR_SIZE = "5 mins"

#: What a market order pays over the open when no quote was recorded anywhere
#: near it. Two cents is a fair guess for a liquid US name and is deliberately
#: not free.
DEFAULT_HALF_SPREAD = 0.02

# IBKR Pro's fixed commission tier for US stocks.
COMMISSION_PER_SHARE = 0.005
COMMISSION_MINIMUM = 1.00
COMMISSION_MAX_FRACTION = 0.01

#: The faults inject_fault() understands. A typo raises rather than silently
#: doing nothing, because a harness that quietly fails to inject a fault reports
#: a pass that never happened.
FAULT_KINDS = (
    "gateway_down",
    "delayed_data",
    "competing_session",
    "phantom_position",
    "reject_next_order",
)

#: IBKR's code for "another session is already using this connection". Worth
#: naming, because it is the one that shows up when Mo opens TWS on the laptop
#: while the loop is running.
COMPETING_SESSION_CODE = 10197
#: IBKR's code for a rejected order.
ORDER_REJECTED_CODE = 201

WORKING = "Submitted"
TRIGGERED = "Triggered"
FILLED = "Filled"
PARTIAL = "PartiallyFilled"
CANCELLED = "Cancelled"
REJECTED = "Rejected"

#: Statuses that mean the order is still able to fill.
LIVE_STATUSES = frozenset({WORKING, TRIGGERED, PARTIAL})


class FakeBrokerError(RuntimeError):
    """Something the broker refused or could not do.

    Carries IBKR's own numeric code when there is one, so a caller can tell a
    competing session (10197) from a rejected order (201) without reading the
    message text.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------- small helpers

def _as_moment(value: Any, label: str = "timestamp") -> datetime:
    """Turn whatever we were handed into an aware Eastern datetime."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date_type):
        moment = datetime(value.year, value.month, value.day, 16, 0)
    elif isinstance(value, str):
        text = value.strip()
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FakeBrokerError(
                f"cannot read {label} {value!r}. Give it a datetime or an ISO "
                "string like 2026-09-08T09:35:00-04:00."
            ) from exc
    else:
        raise FakeBrokerError(f"cannot read {label} {value!r}")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EASTERN)
    return moment.astimezone(EASTERN)


def _number(value: Any, default: float | None = None) -> float | None:
    """A float, or the default, treating None and not-a-number as missing."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _price(value: float) -> float:
    return round(float(value), 4)


def commission_for(shares: float, price: float,
                   per_share: float = COMMISSION_PER_SHARE,
                   minimum: float = COMMISSION_MINIMUM,
                   max_fraction: float = COMMISSION_MAX_FRACTION) -> float:
    """IBKR Pro's fixed commission for one US stock fill.

    Half a cent a share, but never less than a dollar an order and never more
    than one percent of what the order was worth. The cap beats the floor when
    they disagree, which is what happens on a small order in a cheap stock: 20
    shares at 2 dollars is 40 dollars of stock, so the most it can cost is 40
    cents even though the floor says a dollar.
    """
    shares = abs(float(shares))
    if shares <= 0:
        return 0.0
    value = shares * abs(float(price))
    charge = max(shares * per_share, minimum)
    ceiling = value * max_fraction
    return round(min(charge, ceiling), 4)


# ------------------------------------------------------------------ the records

@dataclass
class Fill:
    """One execution. The honest record of what actually happened."""
    exec_id: str
    order_id: int
    order_ref: str
    symbol: str
    side: str                  # BUY or SELL
    shares: int
    price: float
    time: datetime
    commission: float
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    reason: str = ""           # in words, how this price was arrived at

    def as_dict(self) -> dict:
        return {
            "execId": self.exec_id,
            "orderId": self.order_id,
            "orderRef": self.order_ref,
            "order_ref": self.order_ref,
            "symbol": self.symbol,
            "secType": self.sec_type,
            "exchange": self.exchange,
            "currency": self.currency,
            "side": self.side,
            "shares": self.shares,
            "price": _price(self.price),
            "time": self.time.isoformat(),
            "commission": round(self.commission, 4),
            "reason": self.reason,
        }


@dataclass
class Order:
    """One order sitting at the pretend broker."""
    order_id: int
    order_ref: str
    symbol: str
    action: str                       # BUY or SELL
    total_quantity: int
    order_type: str                   # MKT, LMT or STP
    limit_price: float | None = None
    stop_price: float | None = None
    tif: str = "DAY"
    placed_at: datetime | None = None
    status: str = WORKING
    filled: int = 0
    remaining: int = 0
    avg_fill_price: float | None = None
    triggered_at: datetime | None = None
    contract: dict = field(default_factory=dict)
    fills: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def is_buy(self) -> bool:
        return self.action == "BUY"

    def as_dict(self) -> dict:
        """The shape IBKR reports an order in, and the one agent/loop.py reads."""
        return {
            "orderId": self.order_id,
            "order_id": self.order_id,
            "orderRef": self.order_ref,
            "order_ref": self.order_ref,
            "symbol": self.symbol,
            "secType": self.contract.get("secType", "STK"),
            "exchange": self.contract.get("exchange", "SMART"),
            "currency": self.contract.get("currency", "USD"),
            "action": self.action,
            "side": self.action,
            "totalQuantity": self.total_quantity,
            "orderType": self.order_type,
            "lmtPrice": self.limit_price,
            "auxPrice": self.stop_price,
            "tif": self.tif,
            "status": self.status,
            "filled": self.filled,
            "remaining": self.remaining,
            "avgFillPrice": None if self.avg_fill_price is None else _price(self.avg_fill_price),
            "placedAt": None if self.placed_at is None else self.placed_at.isoformat(),
            "notes": list(self.notes),
        }


@dataclass
class BookPosition:
    """What one book holds in one symbol. Negative shares mean a short."""
    symbol: str
    qty: int = 0
    avg_cost: float = 0.0             # per share, always positive
    realized_pnl: float = 0.0         # closed trades, before commission
    commission_paid: float = 0.0


@dataclass
class Book:
    """One virtual book, keyed by the order_ref its orders carry."""
    order_ref: str
    starting_cash: float
    cash: float
    positions: dict = field(default_factory=dict)
    realized_pnl: float = 0.0
    commission_paid: float = 0.0
    day_trades: list = field(default_factory=list)


# ------------------------------------------------------------------ the broker

class FakeBroker:
    """A broker made of recorded bars and arithmetic.

    Read methods match agent/mcp_client.py one for one, so the loop can be
    pointed at this instead of the MCP server and not notice. Order methods are
    the ones agent/mcp_client.py deliberately leaves out.

    Typical use from the harness:

        broker = FakeBroker.from_recording("2026-09-08")
        broker.advance_to("2026-09-08T09:35:00-04:00")
        broker.place_order(contract, {"action": "BUY", "totalQuantity": 100,
                                      "orderType": "LMT", "lmtPrice": 12.50},
                           order_ref="BOOK_A")
        broker.advance_to("2026-09-08T09:40:00-04:00")
        broker.executions()
    """

    # ---------------------------------------------------------------- building

    def __init__(
        self,
        bars: dict | None = None,
        *,
        bar_series: dict | None = None,
        quotes: dict | None = None,
        starting_cash: float = 100_000.0,
        account_id: str = "DUREPLAY",
        default_book_capital: float = 100_000.0,
        book_capital: dict | None = None,
        fill_bar_size: str = DEFAULT_FILL_BAR_SIZE,
        slippage_bps: float = 0.0,
        partial_fill_probability: float = 0.0,
        partial_fill_fraction: float = 0.5,
        default_half_spread: float = DEFAULT_HALF_SPREAD,
        commission_per_share: float = COMMISSION_PER_SHARE,
        commission_minimum: float = COMMISSION_MINIMUM,
        commission_max_fraction: float = COMMISSION_MAX_FRACTION,
        seed: int | None = 0,
        now: Any = None,
    ) -> None:
        """
        bars                one symbol to a list of five minute bar dictionaries,
                            in the shape agent/replay/common.bar_to_dict makes.
        bar_series          the general form: bar size, then symbol, then bars.
                            Use it when you also have daily or one minute bars.
        quotes              recorded snapshots, one symbol to a time ordered
                            list of {"time","bid","ask","last",...}. Used for
                            the spread a market order pays and for snapshot().
        starting_cash       the account's cash on day one.
        book_capital        starting cash per order_ref. Anything not named here
                            gets default_book_capital.
        slippage_bps        extra cost on every market fill, in basis points.
                            Off by default. 5 means five hundredths of a percent.
        partial_fill_probability
                            chance that a fill comes in pieces instead of all at
                            once. Off by default. Deterministic given a seed.
        """
        self.account_id = str(account_id)
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.default_book_capital = float(default_book_capital)
        self._configured_book_capital = dict(book_capital or {})
        self.fill_bar_size = str(fill_bar_size)
        self.slippage_bps = float(slippage_bps)
        self.partial_fill_probability = float(partial_fill_probability)
        self.partial_fill_fraction = float(partial_fill_fraction)
        self.default_half_spread = float(default_half_spread)
        self.commission_per_share = float(commission_per_share)
        self.commission_minimum = float(commission_minimum)
        self.commission_max_fraction = float(commission_max_fraction)
        self._random = random.Random(seed)

        # bar_series[bar size][symbol] = [bar, bar, ...], sorted by time.
        self.bar_series: dict[str, dict[str, list[dict]]] = {}
        if bars:
            self._load_series(self.fill_bar_size, bars)
        for size, per_symbol in (bar_series or {}).items():
            self._load_series(size, per_symbol)

        self.quotes: dict[str, list[dict]] = {}
        for symbol, rows in (quotes or {}).items():
            self.quotes[str(symbol).upper()] = sorted(
                [dict(row) for row in rows],
                key=lambda row: _as_moment(row.get("time") or row.get("tick")))

        self.orders: dict[int, Order] = {}
        self.fills: list[Fill] = []
        self.books: dict[str, Book] = {}
        self.positions: dict[str, int] = {}       # netted, symbol to shares
        self.avg_cost: dict[str, float] = {}      # netted, symbol to cost a share
        self.realized_pnl = 0.0
        self.commission_paid = 0.0
        self.last_price: dict[str, float] = {}
        self.phantom_positions: list[dict] = []
        self._faults: dict[str, dict] = {}
        self._next_order_id = 1
        self._next_exec_id = 1

        # The clock. It starts just before the first bar we hold, so the first
        # advance_to walks the whole recording rather than skipping it.
        self.now: datetime | None = None
        if now is not None:
            self.now = _as_moment(now, "now")
        else:
            first = self._first_bar_moment()
            self.now = (first - timedelta(seconds=1)) if first else None

    def _load_series(self, bar_size: str, per_symbol: dict) -> None:
        bucket = self.bar_series.setdefault(str(bar_size), {})
        for symbol, rows in (per_symbol or {}).items():
            cleaned = [dict(row) for row in rows or []]
            cleaned = [row for row in cleaned if common.bar_moment(row) is not None]
            cleaned.sort(key=lambda row: common.bar_moment(row))
            bucket[str(symbol).upper()] = cleaned

    def _first_bar_moment(self) -> datetime | None:
        """The earliest bar in the fill series.

        The fill series and not every series, on purpose. A replay usually
        carries forty days of daily bars behind the few days it actually trades,
        and those are history the strategy is meant to be able to read on the
        first tick. Starting the clock before them would put the whole liquidity
        record in the future, where nothing can see it.
        """
        moments = []
        for rows in self._series(self.fill_bar_size).values():
            if rows:
                moments.append(common.bar_moment(rows[0]))
        moments = [m for m in moments if m is not None]
        return min(moments) if moments else None

    # ------------------------------------------------------- loading recordings

    @classmethod
    def from_recording(cls, day: Any, folder: Path | None = None, **options) -> "FakeBroker":
        """Build a broker from one day recorded by agent/replay/record_day.py.

        Reads output/recordings/<day>/bars_5m.jsonl and snapshots.jsonl.
        """
        base = Path(folder) if folder else common.day_dir(day, create=False)
        bars: dict[str, list[dict]] = {}
        seen: dict[str, set] = {}
        for record in common.read_jsonl(base / "bars_5m.jsonl"):
            symbol = str(record.get("symbol") or "").upper()
            bar = record.get("bar")
            if not symbol or not isinstance(bar, dict):
                continue
            stamp = str(bar.get("time"))
            # The recorder writes the latest bar every tick, so the same bar
            # turns up more than once. Keep one copy of each.
            if stamp in seen.setdefault(symbol, set()):
                continue
            seen[symbol].add(stamp)
            bars.setdefault(symbol, []).append(bar)

        quotes: dict[str, list[dict]] = {}
        for record in common.read_jsonl(base / "snapshots.jsonl"):
            symbol = str(record.get("symbol") or "").upper()
            if not symbol:
                continue
            row = dict(record)
            row.setdefault("time", record.get("tick") or record.get("recorded_at"))
            quotes.setdefault(symbol, []).append(row)

        return cls(bars=bars, quotes=quotes, **options)

    @classmethod
    def from_history(cls, symbols: Iterable[str] | None = None,
                     folder: Path | None = None, **options) -> "FakeBroker":
        """Build a broker from what agent/replay/fetch_history.py fetched.

        Loads every kind of bar it finds: five minute bars are what orders fill
        against, and the one minute opening range and daily bars come along so
        historical_bars() can answer for them too.
        """
        base = Path(folder) if folder else common.history_dir(create=False)
        wanted = {str(s).upper() for s in symbols} if symbols else None
        kind_to_size = {"bars_5m": "5 mins", "bars_1m_open": "1 min", "bars_1d": "1 day"}
        series: dict[str, dict[str, list[dict]]] = {}
        if base.exists():
            for path in sorted(base.glob("*.jsonl")):
                symbol = path.stem.upper()
                if wanted is not None and symbol not in wanted:
                    continue
                for record in common.read_jsonl(path):
                    size = kind_to_size.get(str(record.get("kind")))
                    bar = record.get("bar")
                    if not size or not isinstance(bar, dict):
                        continue
                    series.setdefault(size, {}).setdefault(symbol, []).append(bar)
        return cls(bars=series.get("5 mins"), bar_series=series, **options)

    # ------------------------------------------------------------------- faults

    def inject_fault(self, kind: str, **options) -> dict:
        """Break something on purpose, so the loop can be seen to cope.

            gateway_down       every broker call raises ConnectionError until
                               cleared. advance_to is deliberately exempt: the
                               market does not stop while your Gateway is down,
                               and the harness has to be able to model exactly
                               that.
            delayed_data       every snapshot reports market data type 3, the
                               way it does when the live subscription lapses.
            competing_session  every snapshot raises with IBKR's code 10197,
                               which is what happens when someone logs into TWS
                               on another machine with the same credentials.
            phantom_position   a position appears that no book placed an order
                               for, which is what reconciliation exists to
                               catch. Options: symbol (default SPY), quantity
                               (default 100), avg_cost.
            reject_next_order  the next place_order comes back rejected, then
                               the fault clears itself.
        """
        name = str(kind).strip()
        if name not in FAULT_KINDS:
            raise FakeBrokerError(
                f"there is no fault called {kind!r}. The ones this broker knows "
                f"are: {', '.join(FAULT_KINDS)}.")
        settings = dict(options)
        self._faults[name] = settings
        if name == "phantom_position":
            symbol = str(settings.get("symbol") or "SPY").upper()
            quantity = int(settings.get("quantity", 100))
            cost = _number(settings.get("avg_cost"), None)
            if cost is None:
                cost = self.last_price.get(symbol, 100.0)
            self.phantom_positions.append(
                {"symbol": symbol, "qty": quantity, "avg_cost": float(cost)})
        return {"fault": name, "options": settings}

    def clear_fault(self, kind: str) -> None:
        """Put one thing back the way it was."""
        name = str(kind).strip()
        self._faults.pop(name, None)
        if name == "phantom_position":
            self.phantom_positions.clear()

    def clear_faults(self) -> None:
        self._faults.clear()
        self.phantom_positions.clear()

    def active_faults(self) -> list[str]:
        return sorted(self._faults)

    def _fault(self, kind: str) -> dict | None:
        return self._faults.get(kind)

    def _guard_connection(self, what: str) -> None:
        """Raise if the pretend Gateway is pretending to be down."""
        if "gateway_down" in self._faults:
            raise ConnectionError(
                f"cannot {what}: IB Gateway is not answering (injected fault "
                "'gateway_down'). The loop should halt, alert, and try again "
                "next tick rather than assume it holds nothing.")

    # -------------------------------------------------------------- book keeping

    def book(self, order_ref: str) -> Book:
        """One book's state, created the first time that order_ref is seen."""
        ref = str(order_ref).strip().upper()
        if not ref:
            raise FakeBrokerError(
                "every order needs an order_ref, because a fill nobody can trace "
                "back to a book cannot be reconciled. Pass order_ref='BOOK_A'.")
        if ref not in self.books:
            capital = float(self._configured_book_capital.get(ref, self.default_book_capital))
            self.books[ref] = Book(order_ref=ref, starting_cash=capital, cash=capital)
        return self.books[ref]

    def book_position(self, order_ref: str, symbol: str) -> BookPosition:
        book = self.book(order_ref)
        key = str(symbol).upper()
        if key not in book.positions:
            book.positions[key] = BookPosition(symbol=key)
        return book.positions[key]

    def book_positions(self, order_ref: str) -> dict:
        """Every symbol one book holds, zero quantities left out."""
        book = self.book(order_ref)
        return {symbol: position for symbol, position in book.positions.items()
                if position.qty != 0}

    def book_summary(self, order_ref: str) -> dict:
        """One book's cash, positions and profit, in plain numbers."""
        book = self.book(order_ref)
        unrealized = 0.0
        holdings = []
        for symbol, position in sorted(book.positions.items()):
            if position.qty == 0:
                continue
            mark = self.last_price.get(symbol, position.avg_cost)
            open_pnl = (mark - position.avg_cost) * position.qty
            unrealized += open_pnl
            holdings.append({
                "symbol": symbol,
                "position": position.qty,
                "avgCost": _price(position.avg_cost),
                "marketPrice": _price(mark),
                "marketValue": round(mark * position.qty, 2),
                "unrealizedPnl": round(open_pnl, 2),
                "realizedPnl": round(position.realized_pnl, 2),
                "order_ref": book.order_ref,
            })
        return {
            "order_ref": book.order_ref,
            "starting_cash": round(book.starting_cash, 2),
            "cash": round(book.cash, 2),
            "positions": holdings,
            "realized_pnl": round(book.realized_pnl, 2),
            "commission_paid": round(book.commission_paid, 2),
            "realized_pnl_net": round(book.realized_pnl - book.commission_paid, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(book.cash + sum(h["marketValue"] for h in holdings), 2),
            "day_trades": len(book.day_trades),
        }

    def reconcile(self) -> dict:
        """Do the books add up to what the broker says it holds?

        This is the check the reconciliation halt is built on. It compares the
        netted account against the sum of every book, symbol by symbol, and
        names anything that does not line up. A phantom position, which is one
        that arrived without an order_ref, shows up here as a symbol the broker
        holds and no book claims.
        """
        broker_view: dict[str, int] = {}
        for row in self._netted_positions():
            broker_view[row["symbol"]] = broker_view.get(row["symbol"], 0) + int(row["position"])

        book_view: dict[str, int] = {}
        for book in self.books.values():
            for symbol, position in book.positions.items():
                if position.qty:
                    book_view[symbol] = book_view.get(symbol, 0) + int(position.qty)

        differences = []
        for symbol in sorted(set(broker_view) | set(book_view)):
            at_broker = broker_view.get(symbol, 0)
            in_books = book_view.get(symbol, 0)
            if at_broker != in_books:
                differences.append({
                    "symbol": symbol,
                    "broker_qty": at_broker,
                    "books_qty": in_books,
                    "difference": at_broker - in_books,
                    "reason": ("the broker holds shares no book placed an order for"
                               if abs(at_broker) > abs(in_books) else
                               "the books think they hold more than the broker does"),
                })
        return {"ok": not differences, "differences": differences,
                "broker": broker_view, "books": book_view}

    # ------------------------------------------------------------- reading bars

    def _series(self, bar_size: str | None = None) -> dict:
        return self.bar_series.get(str(bar_size or self.fill_bar_size), {})

    def bars_for(self, symbol: str, bar_size: str | None = None,
                 up_to: datetime | None = None) -> list[dict]:
        """Every stored bar for one symbol at or before a moment.

        Defaults to the current clock, which is the whole point: nothing in this
        class ever hands back a bar from the future.
        """
        cutoff = up_to or self.now
        rows = self._series(bar_size).get(str(symbol).upper(), [])
        if cutoff is None:
            return list(rows)
        return [row for row in rows
                if (common.bar_moment(row) or cutoff) <= cutoff]

    def _quote_near(self, symbol: str, moment: datetime | None) -> dict | None:
        """The last quote recorded at or before a moment, if there is one."""
        rows = self.quotes.get(str(symbol).upper())
        if not rows:
            return None
        cutoff = moment or self.now
        best = None
        for row in rows:
            stamp = row.get("time") or row.get("tick")
            if not stamp:
                continue
            try:
                when = _as_moment(stamp)
            except FakeBrokerError:
                continue
            if cutoff is not None and when > cutoff:
                break
            best = row
        return best

    def half_spread_for(self, symbol: str, moment: datetime | None) -> float:
        """Half the recorded bid to ask gap, or the default when none was recorded."""
        quote = self._quote_near(symbol, moment)
        if quote:
            bid = _number(quote.get("bid"))
            ask = _number(quote.get("ask"))
            if bid is not None and ask is not None and ask > bid > 0:
                return (ask - bid) / 2.0
        return self.default_half_spread

    # ------------------------------------------------------------------ the clock

    def advance_to(self, timestamp: Any) -> dict:
        """Move the clock forward, filling whatever would have filled on the way.

        Walks every recorded bar stamped after the current clock and at or
        before the target, in time order, and runs each one past the working
        orders. Returns what happened, so a harness can assert on it.

        Going backwards raises. A replay that can rewind can peek at the future
        by accident, and then every result it produces is worthless.
        """
        target = _as_moment(timestamp, "timestamp")
        started_at = self.now
        if started_at is not None and target < started_at:
            raise FakeBrokerError(
                f"cannot go back to {target.isoformat()}, the clock is already at "
                f"{started_at.isoformat()}. Replay time only moves forward.")

        pending: list[tuple[datetime, str, dict]] = []
        for symbol, rows in self._series(self.fill_bar_size).items():
            for row in rows:
                moment = common.bar_moment(row)
                if moment is None:
                    continue
                if started_at is not None and moment <= started_at:
                    continue
                if moment > target:
                    break
                pending.append((moment, symbol, row))
        pending.sort(key=lambda item: (item[0], item[1]))

        fills_before = len(self.fills)
        for moment, symbol, bar in pending:
            self.now = moment
            close = _number(bar.get("close"))
            if close is not None:
                self.last_price[symbol] = close
            self._run_bar(symbol, bar, moment)

        self.now = target
        new_fills = self.fills[fills_before:]
        return {
            "from": None if started_at is None else started_at.isoformat(),
            "to": target.isoformat(),
            "bars_processed": len(pending),
            "fills": [fill.as_dict() for fill in new_fills],
        }

    def _run_bar(self, symbol: str, bar: dict, moment: datetime) -> None:
        """Let every live order on this symbol have a go at this one bar."""
        for order in list(self.orders.values()):
            if order.symbol != symbol or order.status not in LIVE_STATUSES:
                continue
            if order.placed_at is not None and moment < order.placed_at:
                continue
            self._try_fill(order, bar, moment)

    def _try_fill(self, order: Order, bar: dict, moment: datetime) -> None:
        open_price = _number(bar.get("open"))
        high = _number(bar.get("high"))
        low = _number(bar.get("low"))
        if open_price is None or high is None or low is None:
            return

        kind = order.order_type
        # Whether a stop has been hit is read off triggered_at, not off the
        # status, because a stop that fills in pieces stops being "Triggered"
        # the moment the first piece goes through and the rest would then be
        # stranded forever.
        if kind == "STP" and order.triggered_at is None:
            # A stop is not an order until the price trades through it. Once it
            # does it becomes a market order, and market orders fill on the NEXT
            # bar, so nothing else happens on this one.
            triggered = (high >= order.stop_price) if order.is_buy else (low <= order.stop_price)
            if triggered:
                order.status = TRIGGERED
                order.triggered_at = moment
                order.notes.append(
                    f"stop {order.stop_price} was traded through at {moment.isoformat()}, "
                    f"bar range {low} to {high}")
            return

        if kind == "MKT" or order.triggered_at is not None:
            if order.triggered_at is not None and moment <= order.triggered_at:
                # A stop always costs at least one bar. It does not get to fill
                # on the same bar that set it off.
                return
            half = self.half_spread_for(order.symbol, moment)
            slip = open_price * (self.slippage_bps / 10_000.0)
            price = open_price + half + slip if order.is_buy else open_price - half - slip
            price = max(price, 0.01)
            why = (f"market fill at the next bar's open {open_price} "
                   f"{'plus' if order.is_buy else 'minus'} half the spread {round(half, 4)}")
            if self.slippage_bps:
                why += f" and {self.slippage_bps} basis points of slippage"
            if order.triggered_at is not None:
                why = f"stop triggered at {order.triggered_at.isoformat()}, then " + why
            self._execute(order, price, moment, why)
            return

        if kind == "LMT":
            limit = order.limit_price
            if limit is None:
                return
            if order.is_buy:
                if low > limit:
                    return
                price = open_price if open_price <= limit else limit
                why = (f"limit buy at {limit}, the bar's low {low} reached it"
                       + (f", and the bar opened at {open_price} which is better"
                          if open_price <= limit else ""))
            else:
                if high < limit:
                    return
                price = open_price if open_price >= limit else limit
                why = (f"limit sell at {limit}, the bar's high {high} reached it"
                       + (f", and the bar opened at {open_price} which is better"
                          if open_price >= limit else ""))
            self._execute(order, price, moment, why)

    def _execute(self, order: Order, price: float, moment: datetime, why: str) -> None:
        """Fill an order, in whole or in part, and update everything it touches."""
        shares = int(order.remaining)
        if shares <= 0:
            return
        if self.partial_fill_probability > 0 and shares > 1 \
                and self._random.random() < self.partial_fill_probability:
            piece = int(shares * self.partial_fill_fraction)
            shares = max(1, min(shares - 1, piece))
            why += f" (partial fill, {shares} of {order.remaining} shares)"

        price = _price(price)
        commission = commission_for(shares, price, self.commission_per_share,
                                    self.commission_minimum, self.commission_max_fraction)

        fill = Fill(
            exec_id=f"F{self._next_exec_id:06d}",
            order_id=order.order_id,
            order_ref=order.order_ref,
            symbol=order.symbol,
            side=order.action,
            shares=shares,
            price=price,
            time=moment,
            commission=commission,
            sec_type=order.contract.get("secType", "STK"),
            exchange=order.contract.get("exchange", "SMART"),
            currency=order.contract.get("currency", "USD"),
            reason=why,
        )
        self._next_exec_id += 1
        self.fills.append(fill)
        order.fills.append(fill.as_dict())

        already = order.filled
        order.filled += shares
        order.remaining = max(0, order.total_quantity - order.filled)
        order.avg_fill_price = ((order.avg_fill_price or 0.0) * already + price * shares) / order.filled
        order.status = FILLED if order.remaining == 0 else PARTIAL
        if order.status == PARTIAL:
            # A partly filled stop is still a market order for the rest of it.
            order.notes.append(f"{order.filled} of {order.total_quantity} shares filled so far")

        self._apply_fill(fill)

    def _apply_fill(self, fill: Fill) -> None:
        """Move the shares, the cash and the profit, at both levels."""
        signed = fill.shares if fill.side == "BUY" else -fill.shares
        cash_move = -(fill.price * fill.shares) if fill.side == "BUY" else (fill.price * fill.shares)

        # The netted account, which is all IBKR would ever show us.
        realized = self._move_position(self.positions, self.avg_cost, fill.symbol, signed, fill.price)
        self.realized_pnl += realized
        self.cash += cash_move - fill.commission
        self.commission_paid += fill.commission

        # The book that sent the order, which is the only place the fill can be
        # traced back to.
        book = self.book(fill.order_ref)
        position = self.book_position(fill.order_ref, fill.symbol)
        was = position.qty
        book_positions = {fill.symbol: position.qty}
        book_costs = {fill.symbol: position.avg_cost}
        book_realized = self._move_position(book_positions, book_costs, fill.symbol,
                                            signed, fill.price)
        position.qty = book_positions[fill.symbol]
        position.avg_cost = book_costs[fill.symbol]
        position.realized_pnl += book_realized
        position.commission_paid += fill.commission
        book.realized_pnl += book_realized
        book.commission_paid += fill.commission
        book.cash += cash_move - fill.commission

        # A day trade is a round trip in the same name on the same day. The
        # rule that matters is four in five business days, so what gets counted
        # is the closing half of a round trip.
        closed = (was > 0 and signed < 0) or (was < 0 and signed > 0)
        if closed:
            book.day_trades.append({
                "symbol": fill.symbol,
                "date": f"{fill.time.date():%Y-%m-%d}",
                "shares": min(abs(was), abs(signed)),
                "exec_id": fill.exec_id,
            })

    @staticmethod
    def _move_position(positions: dict, costs: dict, symbol: str,
                       signed_shares: int, price: float) -> float:
        """Apply one fill to one set of books. Returns the profit it closed.

        Handles all four cases: opening or adding to a long, closing part or all
        of it, the same for a short, and a fill big enough to flip a long
        straight into a short.
        """
        held = int(positions.get(symbol, 0))
        cost = float(costs.get(symbol, 0.0))
        realized = 0.0

        if held == 0 or (held > 0) == (signed_shares > 0):
            # Opening, or adding to what we already have. The average cost moves.
            total = held + signed_shares
            if total != 0:
                cost = ((abs(held) * cost) + (abs(signed_shares) * price)) / abs(total)
            held = total
        else:
            closing = min(abs(held), abs(signed_shares))
            # A long closes at a profit when the exit is above the cost. A short
            # is the other way round, which the sign of held takes care of.
            realized = (price - cost) * closing * (1 if held > 0 else -1)
            leftover = abs(signed_shares) - closing
            held = held + signed_shares
            if held == 0:
                cost = 0.0
            elif leftover > 0:
                # The fill went through flat and out the other side.
                cost = price
        positions[symbol] = held
        costs[symbol] = cost
        return realized

    # ---------------------------------------------------------- order interface

    def place_order(self, contract: Any, order: Any, order_ref: str) -> dict:
        """Send one order. Nothing fills here, fills happen on the next bar.

        contract and order are IBKR's own plain dictionaries, the same ones
        docs/MCP_SERVER.md describes:

            contract {"symbol": "SPY", "secType": "STK", "exchange": "SMART",
                      "currency": "USD"}
            order    {"action": "BUY", "totalQuantity": 100, "orderType": "LMT",
                      "lmtPrice": 700.0, "tif": "DAY"}

        order_ref is which book is sending it, and it is required. A fill that
        cannot be traced back to a book cannot be reconciled, and reconciliation
        is the whole reason this class keeps five sets of books.

        Nothing fills at the moment an order is placed, on purpose. Real fills
        arrive on the next print, and advance_to is what produces the next print
        here. That is also a real difference from IBKR's own paper account,
        where a market order sent into a live market comes back filled before
        the call returns.
        """
        self._guard_connection("place an order")

        contract_dict = self._contract_dict(contract)
        fields = self._order_dict(order)
        symbol = str(contract_dict.get("symbol") or "").upper()
        if not symbol:
            raise FakeBrokerError("the contract has no symbol on it")

        action = str(fields.get("action") or "").upper()
        if action in ("BOT", "BUY"):
            action = "BUY"
        elif action in ("SLD", "SELL"):
            action = "SELL"
        else:
            raise FakeBrokerError(f"an order's action has to be BUY or SELL, not {action!r}")

        quantity = _number(fields.get("totalQuantity") or fields.get("quantity"), 0.0) or 0.0
        shares = int(round(quantity))
        if shares <= 0:
            raise FakeBrokerError(
                f"an order needs a whole number of shares above zero, not {quantity!r}. "
                "IBKR does not trade fractions of a share on this path.")

        kind = str(fields.get("orderType") or "MKT").upper()
        if kind not in ("MKT", "LMT", "STP"):
            raise FakeBrokerError(
                f"this broker models MKT, LMT and STP orders. It was asked for {kind!r}.")
        limit = _number(fields.get("lmtPrice"))
        stop = _number(fields.get("auxPrice") or fields.get("stopPrice"))
        if kind == "LMT" and limit is None:
            raise FakeBrokerError("a limit order needs an lmtPrice")
        if kind == "STP" and stop is None:
            raise FakeBrokerError("a stop order needs an auxPrice, which is where the stop sits")

        ref = str(order_ref or "").strip().upper()
        self.book(ref)          # creates the book and rejects an empty order_ref

        new_order = Order(
            order_id=self._next_order_id,
            order_ref=ref,
            symbol=symbol,
            action=action,
            total_quantity=shares,
            order_type=kind,
            limit_price=limit,
            stop_price=stop,
            tif=str(fields.get("tif") or "DAY").upper(),
            placed_at=self.now,
            remaining=shares,
            contract=contract_dict,
        )

        if "reject_next_order" in self._faults:
            settings = self._faults.pop("reject_next_order")
            why = str(settings.get("reason")
                      or "the broker rejected this order (injected fault "
                         "'reject_next_order')")
            new_order.status = REJECTED
            new_order.remaining = 0
            new_order.notes.append(why)
            self._next_order_id += 1
            self.orders[new_order.order_id] = new_order
            answer = new_order.as_dict()
            answer.update({"rejected": True, "error_code": ORDER_REJECTED_CODE,
                           "error": why, "fills": []})
            return answer

        self._next_order_id += 1
        self.orders[new_order.order_id] = new_order
        answer = new_order.as_dict()
        answer["fills"] = []
        answer["rejected"] = False
        return answer

    def bracket_order(self, contract: Any, entry: Any, stop: Any,
                      target: Any = None, order_ref: str = "") -> dict:
        """An entry with its stop, and its target when it has one, all at once.

        The same three legs agent/broker.py sends to IBKR, placed here through
        place_order above so they fill against the recorded bars like anything
        else. Two honest differences from the real thing, both of which make
        life here harder rather than easier, which is the right direction:

          - the children are live from the moment they are placed, rather than
            waiting for the parent to fill. IBKR hangs them off the parent's id.
          - the children are not one-cancels-the-other. At IBKR a fill on the
            target pulls the stop. Here both rest until one fills and the loop
            has to notice the position is flat.

        Returns the parent's answer with a `legs` list on it, one entry per leg,
        each carrying the order id and the order_ref it went out under.
        """
        legs: list[dict] = []
        parent = self.place_order(contract, entry, order_ref)
        legs.append({"purpose": "entry", "order_id": parent.get("orderId"),
                     "order_ref": order_ref,
                     "price": self._order_dict(entry).get("lmtPrice")})

        for purpose, leg in (("target", target), ("stop", stop)):
            if leg is None:
                continue
            answer = self.place_order(contract, leg, order_ref)
            fields = self._order_dict(leg)
            legs.append({"purpose": purpose, "order_id": answer.get("orderId"),
                         "order_ref": order_ref,
                         "price": fields.get("lmtPrice") if purpose == "target"
                         else fields.get("auxPrice")})

        parent = dict(parent)
        parent["legs"] = legs
        parent["bracketed"] = any(leg["purpose"] == "stop" for leg in legs)
        return parent

    def cancel_order(self, order_id: int) -> dict:
        """Pull one order that has not filled yet."""
        self._guard_connection("cancel an order")
        order = self.orders.get(int(order_id))
        if order is None:
            raise FakeBrokerError(f"there is no order {order_id} at this broker")
        if order.status in (FILLED, CANCELLED, REJECTED):
            return {"order_id": order.order_id, "status": order.status,
                    "cancelled": False,
                    "note": f"order {order.order_id} was already {order.status}"}
        order.status = CANCELLED
        order.notes.append("cancelled")
        cancelled_shares = order.remaining
        order.remaining = 0
        return {"order_id": order.order_id, "status": CANCELLED, "cancelled": True,
                "cancelled_quantity": cancelled_shares,
                "filled_before_cancel": order.filled}

    def global_cancel(self) -> dict:
        """Pull every working order at once. What the kill switch reaches for."""
        self._guard_connection("cancel everything")
        cancelled = []
        for order in self.orders.values():
            if order.status in LIVE_STATUSES:
                order.status = CANCELLED
                order.notes.append("cancelled by a global cancel")
                order.remaining = 0
                cancelled.append(order.order_id)
        return {"cancelled": cancelled, "count": len(cancelled)}

    @staticmethod
    def _contract_dict(contract: Any) -> dict:
        if isinstance(contract, dict):
            return dict(contract)
        if isinstance(contract, str):
            return common.stock_contract_dict(contract)
        return {"symbol": getattr(contract, "symbol", ""),
                "secType": getattr(contract, "secType", "STK"),
                "exchange": getattr(contract, "exchange", "SMART"),
                "currency": getattr(contract, "currency", "USD")}

    @staticmethod
    def _order_dict(order: Any) -> dict:
        if isinstance(order, dict):
            return dict(order)
        fields = {}
        for name in ("action", "totalQuantity", "orderType", "lmtPrice", "auxPrice", "tif"):
            if hasattr(order, name):
                fields[name] = getattr(order, name)
        if not fields:
            raise FakeBrokerError(f"cannot read an order out of {order!r}")
        return fields

    # ----------------------------------------------------------- read interface

    def account_summary(self, account: str | None = None) -> dict:
        """The same shape agent/mcp_client.py returns: account plus tagged items."""
        self._guard_connection("read the account summary")
        positions = self._netted_positions()
        gross = sum(abs(row["marketValue"]) for row in positions)
        net_value = sum(row["marketValue"] for row in positions)
        unrealized = sum(row["unrealizedPnl"] for row in positions)
        equity = self.cash + net_value
        items = [
            ("NetLiquidation", equity),
            ("TotalCashValue", self.cash),
            ("SettledCash", self.cash),
            ("AvailableFunds", self.cash),
            # Deliberately unleveraged. docs/STRATEGY.md forbids margin
            # borrowing for longs, so buying power is simply the cash.
            ("BuyingPower", self.cash),
            ("GrossPositionValue", gross),
            ("RealizedPnL", self.realized_pnl - self.commission_paid),
            ("UnrealizedPnL", unrealized),
        ]
        return {
            "account": account or self.account_id,
            "items": [{"tag": tag, "value": f"{value:.2f}", "currency": "USD"}
                      for tag, value in items],
            "notes": ["these numbers come from a replay, not from IBKR"],
        }

    def account_values(self, account: str | None = None) -> dict:
        """The summary as a plain {tag: value} lookup, like the real client's."""
        summary = self.account_summary(account) or {}
        return {item["tag"]: item["value"] for item in summary.get("items", [])}

    def _netted_positions(self) -> list[dict]:
        """Every position the account holds, the way IBKR would report it.

        Netted across all five books, because one account is all IBKR sees. Any
        phantom position injected as a fault is in here too, with no order_ref
        on it, which is exactly how a real one would look.
        """
        rows = []
        for symbol in sorted(self.positions):
            quantity = int(self.positions.get(symbol, 0))
            if quantity == 0:
                continue
            cost = float(self.avg_cost.get(symbol, 0.0))
            mark = self.last_price.get(symbol, cost)
            rows.append({
                "symbol": symbol, "secType": "STK", "exchange": "SMART",
                "currency": "USD", "conId": None,
                "position": quantity,
                "avgCost": _price(cost),
                "marketPrice": _price(mark),
                "marketValue": round(mark * quantity, 2),
                "unrealizedPnl": round((mark - cost) * quantity, 2),
                "realizedPnl": 0.0,
                "order_refs": sorted({
                    ref for ref, book in self.books.items()
                    if book.positions.get(symbol) and book.positions[symbol].qty}),
            })
        for phantom in self.phantom_positions:
            symbol = phantom["symbol"]
            cost = float(phantom["avg_cost"])
            mark = self.last_price.get(symbol, cost)
            quantity = int(phantom["qty"])
            rows.append({
                "symbol": symbol, "secType": "STK", "exchange": "SMART",
                "currency": "USD", "conId": None,
                "position": quantity,
                "avgCost": _price(cost),
                "marketPrice": _price(mark),
                "marketValue": round(mark * quantity, 2),
                "unrealizedPnl": round((mark - cost) * quantity, 2),
                "realizedPnl": 0.0,
                "order_refs": [],
            })
        return rows

    def portfolio(self, account: str | None = None, include_pnl: bool = True,
                  order_ref: str | None = None) -> dict:
        """Open positions, the way agent/mcp_client.py hands them over.

        With no order_ref this is the netted account, which is all IBKR would
        ever show. Pass an order_ref and you get one book's own view instead,
        which is the half IBKR cannot give us and the reason this class exists.
        """
        self._guard_connection("read the positions")
        if order_ref:
            summary = self.book_summary(order_ref)
            positions = summary["positions"]
            return {
                "account": account or self.account_id,
                "order_ref": summary["order_ref"],
                "positions": positions,
                "totals": {
                    "marketValue": round(sum(p["marketValue"] for p in positions), 2),
                    "unrealizedPnl": summary["unrealized_pnl"],
                    "realizedPnl": summary["realized_pnl"],
                    "commission": summary["commission_paid"],
                    "cash": summary["cash"],
                    "equity": summary["equity"],
                },
                "notes": [f"one book's view, order_ref {summary['order_ref']}"],
            }

        positions = self._netted_positions()
        notes = ["netted across every book, which is all IBKR reports"]
        if self.phantom_positions:
            notes.append("a position with no order_ref is in here, which is what "
                         "the reconciliation check exists to catch")
        return {
            "account": account or self.account_id,
            "positions": positions,
            "totals": {
                "marketValue": round(sum(row["marketValue"] for row in positions), 2),
                "unrealizedPnl": round(sum(row["unrealizedPnl"] for row in positions), 2),
                "realizedPnl": round(self.realized_pnl - self.commission_paid, 2),
                "commission": round(self.commission_paid, 2),
                "cash": round(self.cash, 2),
            },
            "notes": notes,
        }

    def open_orders(self, account: str | None = None, include_all: bool = True,
                    order_ref: str | None = None) -> dict:
        """Orders that are still working, in the field names loop.py reads."""
        self._guard_connection("read the open orders")
        # include_all is here to match agent/mcp_client.py's signature. In the
        # real server it means "orders placed by other clients too", and this
        # broker is the only client there is, so it changes nothing. Use
        # all_orders() when you want the finished ones as well.
        rows = []
        for order in self.orders.values():
            if order.status not in LIVE_STATUSES:
                continue
            if order_ref and order.order_ref != str(order_ref).upper():
                continue
            rows.append(order.as_dict())
        return {"account": account or self.account_id, "orders": rows, "notes": []}

    def all_orders(self, order_ref: str | None = None) -> list[dict]:
        """Every order ever sent, finished or not. Handy in a test or a post mortem."""
        return [order.as_dict() for order in self.orders.values()
                if not order_ref or order.order_ref == str(order_ref).upper()]

    def executions(self, account: str | None = None, symbol: str | None = None,
                   sec_type: str | None = None, exchange: str | None = None,
                   side: str | None = None, time: str | None = None,
                   order_ref: str | None = None) -> dict:
        """Fills. The honest answer to "what do we actually own".

        Same filters the real client takes, plus order_ref, because with five
        books sharing one account "which fills were mine" is a question the real
        client cannot answer and this one can.
        """
        self._guard_connection("read the executions")
        wanted_side = str(side).upper() if side else None
        if wanted_side in ("BOT", "BUY"):
            wanted_side = "BUY"
        elif wanted_side in ("SLD", "SELL"):
            wanted_side = "SELL"
        after = _as_moment(time) if time else None

        rows = []
        for fill in self.fills:
            if symbol and fill.symbol != str(symbol).upper():
                continue
            if sec_type and fill.sec_type != str(sec_type).upper():
                continue
            if exchange and fill.exchange != str(exchange).upper():
                continue
            if wanted_side and fill.side != wanted_side:
                continue
            if after and fill.time < after:
                continue
            if order_ref and fill.order_ref != str(order_ref).upper():
                continue
            rows.append(fill.as_dict())
        return {"account": account or self.account_id, "executions": rows,
                "fills": rows, "notes": []}

    def snapshot(self, contracts: list, market_data_type: int = 3) -> dict:
        """One shot quotes for a list of contracts, as of the current clock.

        Uses the recorded snapshot nearest before now when there is one, and
        falls back to building a quote out of the last bar's close and the
        default spread when there is not. Never looks ahead of the clock.
        """
        self._guard_connection("read a snapshot")
        if "competing_session" in self._faults:
            raise FakeBrokerError(
                "market data is not available because another session is using "
                "this account (IBKR code 10197). Someone has logged into TWS or "
                "Gateway elsewhere with the same login.",
                code=COMPETING_SESSION_CODE)

        served = 3 if "delayed_data" in self._faults else int(market_data_type)
        rows = []
        for contract in contracts or []:
            symbol = common.symbol_of(contract)
            if not symbol:
                continue
            quote = self._quote_near(symbol, self.now) or {}
            bid = _number(quote.get("bid"))
            ask = _number(quote.get("ask"))
            last = _number(quote.get("last"))
            volume = _number(quote.get("volume"))
            bars = self.bars_for(symbol)
            close = _number(bars[-1].get("close")) if bars else None
            if last is None:
                last = close if close is not None else self.last_price.get(symbol)
            if (bid is None or ask is None) and last is not None:
                bid = last - self.default_half_spread
                ask = last + self.default_half_spread
            rows.append({
                "symbol": symbol, "secType": "STK", "exchange": "SMART",
                "currency": "USD",
                "bid": None if bid is None else _price(bid),
                "ask": None if ask is None else _price(ask),
                "last": None if last is None else _price(last),
                "close": None if close is None else _price(close),
                "volume": volume,
                "marketDataType": served,
                "market_data_type": served,
                "market_data_type_label": common.MARKET_DATA_TYPE_LABELS.get(served, "unknown"),
                "time": None if self.now is None else self.now.isoformat(),
            })
        return {
            "market_data_type": served,
            "market_data_type_label": common.MARKET_DATA_TYPE_LABELS.get(served, "unknown"),
            "snapshots": rows,
            "quotes": rows,
            "notes": ["replayed from a recording, not a live quote"],
        }

    def historical_bars(self, contract: Any, duration: str, bar_size: str,
                        what: str = "TRADES", use_rth: bool = True,
                        end_date_time: str = "") -> dict:
        """Price history for one contract, up to the clock and no further.

        duration is IBKR's own phrasing, "1 D" or "2 W". The stored series has
        to hold the bar size asked for, otherwise this comes back empty with a
        note saying so rather than quietly handing back the wrong bars.
        """
        self._guard_connection("read historical bars")
        symbol = common.symbol_of(contract)
        cutoff = _as_moment(end_date_time) if end_date_time else self.now
        if self.now is not None and cutoff is not None and cutoff > self.now:
            cutoff = self.now

        notes = []
        size = str(bar_size)
        if size not in self.bar_series:
            notes.append(f"this replay holds no {size} bars. It has: "
                         f"{', '.join(sorted(self.bar_series)) or 'nothing'}")
            return {"bars": [], "notes": notes}

        rows = self.bars_for(symbol, size, up_to=cutoff)
        rows = _trim_to_duration(rows, duration)
        return {"bars": [dict(row) for row in rows], "notes": notes}

    def bars_5m_today(self, contract: Any) -> list:
        """Today's five minute bars, regular hours only, as a list.

        Same shortcut agent/mcp_client.py offers, so the loop's calls to it work
        unchanged. "Today" is the replay's today, meaning the date the clock is
        currently sitting on.
        """
        symbol = common.symbol_of(contract)
        if self.now is None:
            return []
        today = self.now.date()
        return [dict(row) for row in self.bars_for(symbol, self.fill_bar_size)
                if (common.bar_moment(row) or self.now).date() == today]

    def is_up(self) -> bool:
        """True when the pretend Gateway is answering. Never raises."""
        return "gateway_down" not in self._faults

    # ------------------------------------------------------------------ reports

    def day_trade_count(self, order_ref: str, within_days: int = 5,
                        as_of: Any = None) -> int:
        """Round trips one book has done in the last five business days.

        The pattern day trader rule counts four in five business days, so this
        is the number the loop has to watch. See the section on it in
        /Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md.
        """
        book = self.book(order_ref)
        end = _as_moment(as_of).date() if as_of else (
            self.now.date() if self.now else datetime.now(EASTERN).date())
        days = set()
        cursor = end
        while len(days) < within_days:
            if cursor.weekday() < 5:
                days.add(f"{cursor:%Y-%m-%d}")
            cursor -= timedelta(days=1)
        return sum(1 for trade in book.day_trades if trade["date"] in days)

    def state(self) -> dict:
        """Everything at a glance. Written into the harness log after each run."""
        return {
            "now": None if self.now is None else self.now.isoformat(),
            "account_id": self.account_id,
            "cash": round(self.cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "commission_paid": round(self.commission_paid, 2),
            "positions": {s: q for s, q in self.positions.items() if q},
            "orders_placed": len(self.orders),
            "fills": len(self.fills),
            "books": {ref: self.book_summary(ref) for ref in sorted(self.books)},
            "faults": self.active_faults(),
            "reconciled": self.reconcile()["ok"],
        }


def _trim_to_duration(rows: list, duration: str) -> list:
    """Keep only the last "10 D" or "2 W" worth of bars, IBKR's way.

    IBKR counts a duration in TRADING time, not clock time. "40 D" means forty
    sessions, not the last forty days on a calendar, and the two are nowhere
    near the same thing: forty calendar days back from a Friday in September
    covers about twenty eight sessions. Reading it as calendar time is how a
    request for forty daily bars quietly comes back with thirty, and the
    strategy's thirty session dollar volume test then measures the wrong window.

    The same is true of intraday durations. A 900 second window ending at 09:40
    reaches back through the overnight gap into the previous afternoon, which is
    how the history fetcher nearly filed yesterday's close as today's opening
    range. Verified against Gateway on 2026-09-06.

    So "D" counts distinct session dates, and the rest fall back to clock time
    because a replay only holds what was recorded anyway. An unreadable duration
    means no limit, which is the safe answer for the same reason.
    """
    parts = str(duration or "").strip().split()
    if len(parts) != 2 or not rows:
        return rows
    try:
        count = int(parts[0])
    except ValueError:
        return rows
    unit = parts[1].upper()

    if unit in ("D", "W"):
        sessions = count * (5 if unit == "W" else 1)
        dates = []
        for row in rows:
            moment = common.bar_moment(row)
            if moment is None:
                continue
            day = moment.date()
            if day not in dates:
                dates.append(day)
        keep = set(dates[-sessions:])
        return [row for row in rows
                if (common.bar_moment(row) or None) is not None
                and common.bar_moment(row).date() in keep]

    per_unit = {"S": timedelta(seconds=1), "M": timedelta(days=31),
                "Y": timedelta(days=366)}
    if unit not in per_unit:
        return rows
    latest = common.bar_moment(rows[-1])
    if latest is None:
        return rows
    earliest = latest - count * per_unit[unit]
    return [row for row in rows
            if (common.bar_moment(row) or earliest) >= earliest]
