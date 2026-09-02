"""The five minute trading loop. One run of this file is one tick.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py --dry-run

    # pretend it is 9:36 in the morning, to test a phase after hours
    ... /agent/loop.py --dry-run --now "2026-09-03 09:36"

There is no while loop in here on purpose. launchd wakes this script every five
minutes during market hours (see config/launchd/com.mtalib.agentic-trading.tick.plist
and docs/LAUNCHD.md), the script looks at the clock, does the one thing that
belongs to that moment, writes down what it saw, and exits. Everything it needs
to remember between ticks lives in output/state_YYYY-MM-DD.json. So a tick that
crashes, or a Mac that was asleep, costs one tick and not the day.

What happens when, all New York time, all read from config/guardrails.yaml:

    before 09:30   nothing to do yet
    09:30 to 09:35 the scanner runs and writes a shortlist
    09:35          the decision packet is built and the picks are made
    09:35 to 15:55 positions are watched against stop, target and the VWAP fade
                   rule; new entries are allowed only until 11:00
    15:55 to 16:00 everything open would be closed
    after 16:00    the day is written up

NOTHING IS ORDERED TODAY. Not on paper, not through a preview or a dry run flag
on the broker's own tools. Every order this file works out is printed as
"DRY RUN would place ..." and written to the ledger as a decision, and that is
where it stops. The live path exists below in submit_order() and is shut behind
three separate locks that all have to be open at once:

    1. the --live flag on the command line, and
    2. the environment variable AGENTIC_TRADING_LIVE_ORDERS set to yes, and
    3. an account id that starts with DU, which is how IBKR names paper accounts.

Even with all three open it stops short of the broker, because agent/mcp_client.py
deliberately does not wrap the order tools. Wiring that last inch is a separate
job that waits on Mo reading the strategy numbers in docs/STRATEGY.md and saying
yes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date as date_type, datetime, time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
for extra in (PROJECT / "agent", PROJECT / "ledger"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import ledger_writer                       # noqa: E402
import mcp_client as mcp                   # noqa: E402

# agent/guardrails.py is written by another agent. If it is not there yet, or it
# is half written, this file still has to run in dry run and say so plainly
# rather than dying on an import.
try:
    import guardrails as gr                # noqa: E402
    GUARDRAILS_IMPORT_ERROR: str | None = None
except Exception as exc:                   # noqa: BLE001
    gr = None                              # type: ignore[assignment]
    GUARDRAILS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

CONFIG_PATH = PROJECT / "config" / "guardrails.yaml"
EXAMPLE_CONFIG_PATH = PROJECT / "config" / "guardrails.example.yaml"
OUTPUT = PROJECT / "output"
TICK_LOG = OUTPUT / "loop.log"
SCANNER = PROJECT / "agent" / "scanner.py"
VENV_PYTHON = PROJECT / "venv312" / "bin" / "python"

LIVE_ENV_VAR = "AGENTIC_TRADING_LIVE_ORDERS"
PAPER_ACCOUNT_PREFIX = "DU"

BEFORE_SCAN, SCAN, PICK, MANAGE, FLATTEN, CLOSED = (
    "before-scan", "scan", "pick", "manage", "flatten", "closed")

# Every time a documented guardrails helper is missing and this file had to fall
# back to its own copy of the rule. Reported in the tick summary so a silent
# fallback can never look like a passing test.
FALLBACKS_USED: list[str] = []


# --------------------------------------------------------------- the schedule

@dataclass
class Schedule:
    """The clock, straight out of the schedule block of config/guardrails.yaml."""
    timezone: str
    scan_start: clock_time
    pick_time: clock_time
    entries_until: clock_time
    flatten_at: clock_time
    market_close: clock_time
    loop_minutes: int

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _parse_clock(text: Any, fallback: str) -> clock_time:
    raw = str(text or fallback).strip()
    for shape in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, shape).time()
        except ValueError:
            continue
    raise SystemExit(f"loop: cannot read the time {raw!r} in {CONFIG_PATH}")


def load_config() -> tuple[dict, Path]:
    """Read the guardrails file as plain data.

    The phase logic below reads the clock from this dictionary rather than from
    the guardrails object, so that a change to the shape of that object cannot
    stop the loop knowing what time it is.
    """
    import yaml

    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    if not path.exists():
        raise SystemExit(
            f"loop: no guardrails file. Expected {CONFIG_PATH}. "
            f"Copy the example: cp {EXAMPLE_CONFIG_PATH} {CONFIG_PATH}")
    return yaml.safe_load(path.read_text()) or {}, path


def schedule_from(config: dict) -> Schedule:
    block = config.get("schedule") or {}
    return Schedule(
        timezone=str(block.get("timezone") or "America/New_York"),
        scan_start=_parse_clock(block.get("scan_start"), "09:30"),
        pick_time=_parse_clock(block.get("pick_time"), "09:35"),
        entries_until=_parse_clock(block.get("entries_until"), "11:00"),
        flatten_at=_parse_clock(block.get("flatten_at"), "15:55"),
        market_close=_parse_clock(block.get("market_close"), "16:00"),
        loop_minutes=int(block.get("loop_minutes") or 5),
    )


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
            today = datetime.now(zone).date()
            return datetime.combine(today, wanted, tzinfo=zone)
        except ValueError:
            continue
    raise SystemExit(f'loop: cannot read --now {text!r}. Try --now "2026-09-03 09:36"')


def phase_for(now: datetime, schedule: Schedule, pick_done: bool) -> tuple[str, str]:
    """Which part of the day is this, and one sentence saying why."""
    if now.weekday() >= 5:
        return CLOSED, "it is the weekend, the US market is shut"

    moment = now.time()
    if moment < schedule.scan_start:
        return BEFORE_SCAN, f"the market opens at {schedule.scan_start:%H:%M}"
    if moment < schedule.pick_time:
        return SCAN, (f"the first five minutes, {schedule.scan_start:%H:%M} to "
                      f"{schedule.pick_time:%H:%M}, is when the scanner runs")
    if moment < schedule.flatten_at:
        if not pick_done and moment < schedule.entries_until:
            return PICK, f"the {schedule.pick_time:%H:%M} pick has not been made yet today"
        if not pick_done:
            return MANAGE, (f"no pick was made today and it is past "
                            f"{schedule.entries_until:%H:%M}, so no new position may be opened")
        return MANAGE, "the pick is made, so watch what came out of it"
    if moment < schedule.market_close:
        return FLATTEN, f"{schedule.flatten_at:%H:%M} has passed, everything open gets closed"
    return CLOSED, f"the market closed at {schedule.market_close:%H:%M}"


# ---------------------------------------- stand ins for the guardrails module
#
# The real versions of these live in agent/guardrails.py. The copies below are
# only used when that file cannot be imported, so that this loop can still be
# tested in dry run. They are deliberately the simplest reading of the numbers
# in docs/STRATEGY.md. Nothing in here is allowed to approve an order: a
# fallback check always answers no.

@dataclass
class _PositionInfo:
    symbol: str
    qty: float
    avg_cost: float
    market_value: float


@dataclass
class _AccountState:
    equity: float
    day_start_equity: float
    realized_pnl_today: float
    unrealized_pnl: float
    open_positions: dict
    pending_order_notional: float
    now: datetime
    kill_switch_present: bool
    account_id: str


@dataclass
class _OrderIntent:
    symbol: str
    side: str
    qty: float
    limit_price: float | None
    sec_type: str = "STK"
    currency: str = "USD"
    purpose: str = "entry"


@dataclass
class _Decision:
    allowed: bool
    reasons: list
    rule_ids: list
    daily_halt: bool = False


def _note_fallback(what: str) -> None:
    if what not in FALLBACKS_USED:
        FALLBACKS_USED.append(what)


def _build(real_name: str, fallback_class, kwargs: dict):
    """Make one of the guardrails dataclasses, or our stand in.

    If the real class exists but its field names turn out to be different from
    what we were told, that is worth knowing loudly rather than crashing, so we
    record it and carry on with the stand in.
    """
    real = getattr(gr, real_name, None) if gr else None
    if real is not None:
        try:
            return real(**kwargs)
        except Exception as exc:            # noqa: BLE001
            _note_fallback(f"guardrails.{real_name} would not take our fields "
                           f"({type(exc).__name__}: {exc})")
    elif gr is not None:
        _note_fallback(f"guardrails has no {real_name}")
    return fallback_class(**kwargs)


def make_position(symbol: str, qty: float, avg_cost: float, market_value: float):
    return _build("PositionInfo", _PositionInfo, dict(
        symbol=symbol, qty=qty, avg_cost=avg_cost, market_value=market_value))


def make_order_intent(symbol: str, side: str, qty: float, limit_price: float | None,
                      purpose: str, sec_type: str = "STK", currency: str = "USD"):
    """One would be order.

    qty is forced to a whole number of shares. IBKR reports a holding of one
    share as 1.0, and the guardrail layer rightly refuses a fractional share
    count on a stock order, so the rounding belongs here rather than in six
    call sites.
    """
    return _build("OrderIntent", _OrderIntent, dict(
        symbol=symbol, side=side, qty=int(round(float(qty))), limit_price=limit_price,
        sec_type=sec_type, currency=currency, purpose=purpose))


def load_guardrails_object(path: Path):
    """The guardrails object the check functions want, or None if unavailable."""
    if gr is None:
        _note_fallback(f"agent/guardrails.py could not be imported ({GUARDRAILS_IMPORT_ERROR})")
        return None
    loader = getattr(gr, "load_guardrails", None)
    if loader is None:
        _note_fallback("guardrails has no load_guardrails")
        return None
    try:
        return loader(str(path))
    except Exception as exc:                # noqa: BLE001
        _note_fallback(f"guardrails.load_guardrails({path.name}) failed: {type(exc).__name__}: {exc}")
        return None


def _call_guardrail(name: str, fallback, *args):
    """Use the real rule when it is there, our own reading of it when it is not."""
    function = getattr(gr, name, None) if gr else None
    if function is not None:
        try:
            return function(*args)
        except Exception as exc:            # noqa: BLE001
            _note_fallback(f"guardrails.{name} raised {type(exc).__name__}: {exc}")
    elif gr is not None:
        _note_fallback(f"guardrails has no {name}")
    return fallback(*args)


def check_order(guard, state, intent) -> Any:
    """Would the guardrail layer allow this order?

    With no guardrail layer loaded the answer is always no. That is the whole
    point of a guardrail: if the thing that says no is missing, the answer is
    no. In dry run the would be order is still printed, marked as unchecked, so
    the loop can be tested without pretending it was approved.
    """
    def refuse(_guard, _state, _intent):
        return _Decision(
            allowed=False,
            reasons=["the guardrail layer is not loaded, so no order may be approved"],
            rule_ids=["guardrails_unavailable"],
            daily_halt=False)

    if guard is None:
        return refuse(guard, state, intent)
    return _call_guardrail("check_order", refuse, guard, state, intent)


def entries_allowed_now(guard, now: datetime, schedule: Schedule) -> bool:
    def by_the_clock(_guard, moment):
        return schedule.pick_time <= moment.time() < schedule.entries_until

    if guard is None:
        return by_the_clock(guard, now)
    return bool(_call_guardrail("entries_allowed_now", by_the_clock, guard, now))


def must_flatten_now(guard, now: datetime, schedule: Schedule) -> bool:
    def by_the_clock(_guard, moment):
        return schedule.flatten_at <= moment.time() < schedule.market_close

    if guard is None:
        return by_the_clock(guard, now)
    return bool(_call_guardrail("must_flatten_now", by_the_clock, guard, now))


def is_regular_hours(guard, now: datetime, schedule: Schedule) -> bool:
    def by_the_clock(_guard, moment):
        return (moment.weekday() < 5
                and schedule.scan_start <= moment.time() < schedule.market_close)

    if guard is None:
        return by_the_clock(guard, now)
    return bool(_call_guardrail("is_regular_hours", by_the_clock, guard, now))


def stop_price_for(guard, entry_price: float, opening_range_low: float | None,
                   config: dict) -> float:
    """Where the stop goes under a long position.

    The strategy says: this many percent below the entry, or the low of the
    first five minutes if that is nearer. Nearer, for something we are long,
    means higher, because it is the shorter fall and the smaller loss.
    """
    def own_reading(_guard, price, range_low):
        percent = float(((config.get("risk") or {}).get("stop_loss_pct")) or 1.5)
        percent_stop = price * (1.0 - percent / 100.0)
        if range_low and 0 < range_low < price:
            return round(max(percent_stop, float(range_low)), 2)
        return round(percent_stop, 2)

    if guard is None:
        return float(own_reading(guard, entry_price, opening_range_low))
    return float(_call_guardrail("stop_price_for", own_reading, guard,
                                 entry_price, opening_range_low))


def max_shares_for(guard, state, symbol: str, price: float, config: dict) -> int:
    """The most shares the money rules allow in one name at this price."""
    def own_reading(_guard, account, _symbol, share_price):
        money = config.get("money") or {}
        equity = float(getattr(account, "equity", 0.0) or 0.0)
        by_percent = equity * float(money.get("max_position_pct") or 10) / 100.0
        by_notional = float(money.get("max_order_notional") or 10000)
        budget = min(by_percent, by_notional)
        if share_price <= 0:
            return 0
        return int(math.floor(budget / share_price))

    if guard is None:
        return int(own_reading(guard, state, symbol, price))
    return int(_call_guardrail("max_shares_for", own_reading, guard, state, symbol, price))


def decision_fields(decision) -> tuple[bool, list, list, bool]:
    """Read a Decision without caring which class it came from."""
    allowed = bool(getattr(decision, "allowed", False))
    reasons = list(getattr(decision, "reasons", []) or [])
    rule_ids = list(getattr(decision, "rule_ids", []) or [])
    halt = bool(getattr(decision, "daily_halt", False))
    return allowed, reasons, rule_ids, halt


# ----------------------------------------------------- what the day remembers

@dataclass
class DayState:
    """Everything the loop has to carry from one tick to the next.

    Saved to output/state_YYYY-MM-DD.json after every tick. Delete that file and
    the day starts over.
    """
    date: str
    account_id: str | None = None
    day_start_equity: float | None = None
    scanner_ran_at: str | None = None
    shortlist_path: str | None = None
    picks: list = field(default_factory=list)
    picked_at: str | None = None
    packet_path: str | None = None
    triggered: dict = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None
    tick_count: int = 0
    last_tick: str | None = None
    last_phase: str | None = None
    daily_started_logged: bool = False
    daily_closed_logged: bool = False


def state_path(day: date_type) -> Path:
    return OUTPUT / f"state_{day:%Y-%m-%d}.json"


def load_state(day: date_type) -> DayState:
    path = state_path(day)
    if not path.exists():
        return DayState(date=f"{day:%Y-%m-%d}")
    try:
        stored = json.loads(path.read_text())
    except Exception as exc:                # noqa: BLE001
        print(f"loop: {path} is unreadable ({exc!r}), starting the day fresh", file=sys.stderr)
        return DayState(date=f"{day:%Y-%m-%d}")
    known = {f for f in DayState.__dataclass_fields__}
    return DayState(**{k: v for k, v in stored.items() if k in known})


def save_state(state: DayState) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = state_path(datetime.strptime(state.date, "%Y-%m-%d").date())
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2, default=str))
    temporary.replace(path)


# --------------------------------------------------- reading the account state

def _number(text: Any, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def pending_buy_notional(orders: list[dict]) -> float:
    """Roughly how many dollars of buy orders are already working.

    Best effort by design: it uses the limit price when there is one and the
    average fill price otherwise, and skips an order it cannot price. The
    guardrail layer treats it as a floor, not gospel.
    """
    total = 0.0
    for order in orders:
        side = str(order.get("action") or order.get("side") or "").upper()
        if side not in ("BUY", "BOT"):
            continue
        quantity = _number(order.get("totalQuantity") or order.get("quantity"))
        filled = _number(order.get("filled"))
        remaining = _number(order.get("remaining"), quantity - filled) or (quantity - filled)
        price = _number(order.get("lmtPrice") or order.get("limitPrice")
                        or order.get("avgFillPrice") or order.get("auxPrice"))
        if remaining > 0 and price > 0:
            total += remaining * price
    return round(total, 2)


def read_account(client: mcp.McpClient, now: datetime, state: DayState,
                 kill_switch_present: bool, account_id_wanted: str | None):
    """Build the AccountState the guardrail layer checks orders against.

    Returns the state object, a plain dictionary of the same facts for the log,
    and a list of anything that went wrong while reading.
    """
    problems: list[str] = []
    values: dict[str, str] = {}
    holdings: dict = {}
    orders: list[dict] = []

    try:
        values = client.account_values(account_id_wanted)
    except mcp.McpError as exc:
        problems.append(f"could not read the account summary: {exc}")
    try:
        holdings = client.portfolio(account_id_wanted) or {}
    except mcp.McpError as exc:
        problems.append(f"could not read the positions: {exc}")
    try:
        orders = (client.open_orders(account_id_wanted) or {}).get("orders", []) or []
    except mcp.McpError as exc:
        problems.append(f"could not read the open orders: {exc}")

    equity = _number(values.get("NetLiquidation"))
    totals = holdings.get("totals") or {}
    account_id = str(holdings.get("account") or account_id_wanted or "")

    positions: dict[str, Any] = {}
    for row in holdings.get("positions", []) or []:
        quantity = _number(row.get("position"))
        if quantity == 0:
            continue
        symbol = str(row.get("symbol") or "")
        positions[symbol] = make_position(
            symbol=symbol, qty=quantity,
            avg_cost=_number(row.get("avgCost")),
            market_value=_number(row.get("marketValue")))

    # The first tick of the day sets the line everything is measured from. The
    # daily loss cap is a percent of this number, so it is written down once and
    # never recalculated.
    if state.day_start_equity is None and equity > 0:
        state.day_start_equity = equity
    day_start = state.day_start_equity if state.day_start_equity is not None else equity

    account_state = _build("AccountState", _AccountState, dict(
        equity=equity,
        day_start_equity=day_start,
        realized_pnl_today=_number(totals.get("realizedPnl")),
        unrealized_pnl=_number(totals.get("unrealizedPnl")),
        open_positions=positions,
        pending_order_notional=pending_buy_notional(orders),
        now=now,
        kill_switch_present=kill_switch_present,
        account_id=account_id,
    ))

    facts = {
        "account_id": account_id,
        "equity": equity,
        "day_start_equity": day_start,
        "cash": _number(values.get("TotalCashValue")),
        "buying_power": _number(values.get("BuyingPower")),
        "realized_pnl_today": _number(totals.get("realizedPnl")),
        "unrealized_pnl": _number(totals.get("unrealizedPnl")),
        "open_positions": len(positions),
        "pending_buy_notional": pending_buy_notional(orders),
        "open_orders": len(orders),
    }
    if equity > 0 and day_start > 0:
        facts["day_pnl_pct"] = round((equity / day_start - 1.0) * 100.0, 3)
    return account_state, facts, positions, problems


# ---------------------------------------------------------------- the scanner

def kill_switch_path(config: dict) -> Path:
    configured = str((config.get("kill_switch") or {}).get("file") or "output/STOP")
    path = Path(configured)
    return path if path.is_absolute() else PROJECT / path


def run_scanner(out_path: Path) -> tuple[bool, str]:
    """Run agent/scanner.py as its own process and let it write the shortlist.

    Its own process on purpose: the scanner talks to IBKR's scanner and can hang
    or fall over, and neither should be able to take the loop with it.
    """
    if not SCANNER.exists():
        return False, f"{SCANNER} does not exist yet, carrying on with an empty shortlist"
    if not VENV_PYTHON.exists():
        return False, f"{VENV_PYTHON} does not exist"
    command = [str(VENV_PYTHON), str(SCANNER), "--out", str(out_path)]
    try:
        finished = subprocess.run(command, cwd=str(PROJECT), capture_output=True,
                                  text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return False, "the scanner ran for more than four minutes and was stopped"
    except Exception as exc:                # noqa: BLE001
        return False, f"the scanner would not start: {exc!r}"
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return False, (f"the scanner exited with code {finished.returncode}: "
                       f"{tail[-1] if tail else 'no message'}")
    return True, f"the scanner finished and wrote {out_path}"


def shortlist_path(day: date_type) -> Path:
    return OUTPUT / f"shortlist_{day:%Y-%m-%d}.json"


def read_shortlist(path: Path) -> tuple[list[dict], str]:
    """Read the scanner's shortlist, forgiving how it wrapped the list."""
    if not path.exists():
        return [], f"no shortlist at {path}, carrying on with nothing to pick from"
    try:
        loaded = json.loads(path.read_text())
    except Exception as exc:                # noqa: BLE001
        return [], f"{path} is not readable JSON ({exc!r}), carrying on with an empty shortlist"
    if isinstance(loaded, list):
        candidates = loaded
    elif isinstance(loaded, dict):
        candidates = None
        for key in ("candidates", "shortlist", "symbols", "results", "rows"):
            if isinstance(loaded.get(key), list):
                candidates = loaded[key]
                break
        if candidates is None:
            first_list = next((v for v in loaded.values() if isinstance(v, list)), None)
            candidates = first_list or []
    else:
        return [], f"{path} holds a {type(loaded).__name__}, not a list of candidates"
    clean = [c for c in candidates if isinstance(c, dict) and c.get("symbol")]
    return clean, f"read {len(clean)} candidates from {path}"


def contract_for(candidate: dict) -> dict:
    """An IBKR contract object for one shortlist row."""
    contract: dict[str, Any] = {"symbol": str(candidate.get("symbol")),
                                "secType": "STK", "exchange": "SMART", "currency": "USD"}
    if candidate.get("conId"):
        contract["conId"] = candidate["conId"]
    if candidate.get("primaryExchange"):
        contract["primaryExchange"] = candidate["primaryExchange"]
    return contract


# ------------------------------------------------------------- the pick itself

@dataclass
class Pick:
    """One name the loop would trade today, with its levels worked out."""
    symbol: str
    conId: Any = None
    primaryExchange: str | None = None
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    qty: int = 0
    score: float = 0.0
    reason: str = ""


def candidate_score(candidate: dict) -> float:
    """How interesting a candidate looks, on the two numbers the strategy names.

    Percentage gain on the day times how heavily it is trading against its own
    normal pace. Both matter and neither is enough alone: a big gain on thin
    volume is noise, and heavy volume going nowhere is not a trend.
    """
    gain = _number(candidate.get("gain_pct"))
    relative_volume = _number(candidate.get("rel_volume"), 1.0) or 1.0
    return round(gain * relative_volume, 4)


def build_decision_packet(client: mcp.McpClient, candidates: list[dict], now: datetime,
                          facts: dict, schedule: Schedule, mode: str) -> tuple[dict, list[str]]:
    """Everything a decision needs, in one file, so the decision is reviewable.

    Written to disk before anything is decided. If a pick later looks wrong, the
    packet is exactly what was known at the time, which is the difference
    between reviewing a decision and guessing at it.
    """
    notes: list[str] = []
    enriched: list[dict] = []
    for candidate in sorted(candidates, key=candidate_score, reverse=True):
        row = dict(candidate)
        row["score"] = candidate_score(candidate)
        try:
            bars = client.bars_5m_today(contract_for(candidate))
        except mcp.McpError as exc:
            bars = []
            notes.append(f"no five minute bars for {candidate.get('symbol')}: {exc}")
        row["bars_5m"] = bars
        row["bar_count"] = len(bars)
        row["session_vwap"] = mcp.session_vwap(bars)
        row["last_close"] = bars[-1]["close"] if bars else None
        if bars and not row.get("opening_range_high"):
            # The scanner normally supplies these. If it did not, the first bar
            # of the day is the opening range by definition.
            row["opening_range_high"] = bars[0].get("high")
            row["opening_range_low"] = bars[0].get("low")
            notes.append(f"{candidate.get('symbol')}: opening range taken from the first bar, "
                         "the scanner did not supply it")
        enriched.append(row)

    packet = {
        "generated_at": now.isoformat(),
        "date": f"{now.date():%Y-%m-%d}",
        "mode": mode,
        "strategy": "opening momentum, month one, see docs/STRATEGY.md",
        "guardrails_loaded": gr is not None and GUARDRAILS_IMPORT_ERROR is None,
        "schedule": {"scan_start": f"{schedule.scan_start:%H:%M}",
                     "pick_time": f"{schedule.pick_time:%H:%M}",
                     "entries_until": f"{schedule.entries_until:%H:%M}",
                     "flatten_at": f"{schedule.flatten_at:%H:%M}"},
        "account": facts,
        "candidates": enriched,
        "notes": notes,
    }
    return packet, notes


def decide(packet: dict, guard, account_state, config: dict,
           max_picks: int = 3) -> list[Pick]:
    """Choose today's names from the decision packet.

    TODO: THIS IS WHERE CLAUDE GOES.
    ---------------------------------------------------------------------------
    The strategy in docs/STRATEGY.md gives this job to Claude: read the
    shortlist, the five minute bars and any headline, pick up to five names, and
    write down one line of reasoning for each. That call is not made yet. When it
    is, it belongs right here: hand the packet to the model, get back the same
    list of Pick objects this function already returns, and keep the placeholder
    below as the answer to fall back on when the model is slow or unreachable.

    Two things must stay true when that lands. First, whatever the model says
    still goes through check_order afterwards, so a persuasive answer cannot
    talk its way past a limit. Second, every pick keeps its written reason,
    because a decision with no reason cannot be reviewed at the end of the month.
    ---------------------------------------------------------------------------

    Until then this is a deterministic placeholder: the three highest scoring
    candidates, entering on a break above the opening range high, stopping where
    the risk rules say, and aiming for twice the distance from entry to stop.
    Deterministic on purpose, so the same packet always gives the same picks and
    a test that changes behaviour has really changed something.
    """
    picks: list[Pick] = []
    for candidate in packet.get("candidates", [])[:max_picks]:
        symbol = str(candidate.get("symbol"))
        entry = _number(candidate.get("opening_range_high"))
        if entry <= 0:
            continue
        range_low = _number(candidate.get("opening_range_low")) or None
        stop = stop_price_for(guard, entry, range_low, config)
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            continue
        target = round(entry + 2.0 * risk_per_share, 2)
        quantity = max_shares_for(guard, account_state, symbol, entry, config)
        picks.append(Pick(
            symbol=symbol,
            conId=candidate.get("conId"),
            primaryExchange=candidate.get("primaryExchange"),
            entry=round(entry, 2),
            stop=stop,
            target=target,
            qty=int(quantity),
            score=_number(candidate.get("score")),
            reason=(f"placeholder pick, ranked {candidate.get('score')} on gain "
                    f"{candidate.get('gain_pct')} percent at {candidate.get('rel_volume')} "
                    f"times normal volume; flagged by {candidate.get('flagged_by')}"),
        ))
    return picks


# ------------------------------------------------------------ the order gate

def live_orders_allowed(want_live: bool, account_id: str) -> tuple[bool, list[str]]:
    """The three locks on the live path. All three, or nothing happens.

    Returns whether every lock is open, and the list of the ones that are shut.
    """
    shut: list[str] = []
    if not want_live:
        shut.append("the --live flag was not passed")
    if os.environ.get(LIVE_ENV_VAR) != "yes":
        shut.append(f"{LIVE_ENV_VAR} is not set to yes")
    if not str(account_id).startswith(PAPER_ACCOUNT_PREFIX):
        shut.append(f"the account id {account_id or 'unknown'} does not start with "
                    f"{PAPER_ACCOUNT_PREFIX}, so it is not a paper account")
    return (not shut), shut


def submit_order(intent, account_id: str, want_live: bool):
    """The one and only door to the broker. It is shut.

    Nothing calls this today. It exists so that the live path is a real, visible
    piece of code with its locks on it, instead of something to be invented in a
    hurry later.
    """
    open_locks, shut = live_orders_allowed(want_live, account_id)
    if not open_locks:
        raise RuntimeError("refusing to send an order: " + "; ".join(shut))
    raise RuntimeError(
        "the live order path is not wired up. All three safety locks are open, but "
        "agent/mcp_client.py deliberately does not wrap the broker's order tools, so "
        "there is nothing here to call. Wiring it is a separate job that waits on Mo "
        "approving the numbers in docs/STRATEGY.md. When it happens: add the wrapper "
        "to agent/mcp_client.py, call it from here, then confirm the result against "
        "executions() and open_orders(), because the server reports an instant market "
        "fill as an error even though it filled.")


def describe(intent) -> str:
    """One line describing a would be order, in words."""
    price = getattr(intent, "limit_price", None)
    where = f"limit {price:.2f}" if price else "at market"
    return (f"{getattr(intent, 'side', '?')} {getattr(intent, 'qty', '?')} "
            f"{getattr(intent, 'symbol', '?')} {where} "
            f"(purpose: {getattr(intent, 'purpose', '?')})")


class Tick:
    """One run of the loop. Holds what happened so the summary can be honest."""

    def __init__(self, now: datetime, mode: str, dry_run: bool, write_ledger: bool):
        self.now = now
        self.mode = mode
        self.dry_run = dry_run
        self.write_ledger = write_ledger
        self.would_be_orders = 0
        self.approved = 0
        self.refused = 0
        self.notes: list[str] = []

    def say(self, message: str) -> None:
        print(message)

    def note(self, message: str) -> None:
        self.notes.append(message)
        print(f"  note: {message}")

    def record_decision(self, symbol: str, decision: str, rationale: str) -> None:
        """Write one judgement to the Rules Log. In dry run it is printed."""
        ledger_writer.log_decision(
            self.now, symbol, decision, rationale, mode=self.mode,
            dry_run=self.dry_run and not self.write_ledger)

    def consider(self, guard, account_state, intent, extra: str = "") -> Any:
        """Put one would be order through the guardrails and write down the answer.

        This is the only route from "the loop thinks it should trade" to anything
        else happening, and in dry run it stops at the printed line.
        """
        self.would_be_orders += 1
        decision = check_order(guard, account_state, intent)
        allowed, reasons, rule_ids, halt = decision_fields(decision)
        summary = describe(intent) + (f" {extra}" if extra else "")
        verdict = "allowed by the guardrails" if allowed else "refused by the guardrails"
        because = ("; ".join(str(r) for r in reasons)
                   or ("no limit was breached" if allowed else "no reason given"))

        if allowed:
            self.approved += 1
        else:
            self.refused += 1

        if self.dry_run:
            self.say(f"  DRY RUN would place {summary}")
            self.say(f"    guardrails: {verdict}. {because}"
                     + (f" [rules: {', '.join(str(r) for r in rule_ids)}]" if rule_ids else ""))
            self.say("    nothing was sent to the broker, this is dry run")
        else:
            # Not reachable today: main() refuses to run without --dry-run.
            self.say(f"  LIVE path reached for {summary}, {verdict}")

        self.record_decision(
            getattr(intent, "symbol", "?"),
            f"would place {summary}" if self.dry_run else f"place {summary}",
            f"{verdict}. {because}")
        return decision


# ------------------------------------------------------------------ the phases

def do_scan(tick: Tick, day: date_type) -> tuple[list[dict], Path]:
    path = shortlist_path(day)
    tick.say(f"Running the scanner, writing to {path}")
    ok, message = run_scanner(path)
    tick.note(message)
    candidates, read_message = read_shortlist(path)
    tick.note(read_message)
    return candidates, path


def do_pick(tick: Tick, client: mcp.McpClient, day: date_type, guard, account_state,
            facts: dict, schedule: Schedule, config: dict, state: DayState) -> list[Pick]:
    path = shortlist_path(day)
    candidates, message = read_shortlist(path)
    tick.note(message)
    state.shortlist_path = str(path)

    packet, packet_notes = build_decision_packet(
        client, candidates, tick.now, facts, schedule, tick.mode)
    for message in packet_notes:
        tick.note(message)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    packet_path = OUTPUT / f"decision_packet_{tick.now:%Y-%m-%d_%H%M}.json"
    packet_path.write_text(json.dumps(packet, indent=2, default=str))
    state.packet_path = str(packet_path)
    tick.say(f"Decision packet for {len(candidates)} candidates written to {packet_path}")

    picks = decide(packet, guard, account_state, config)
    state.picks = [asdict(p) for p in picks]
    state.picked_at = tick.now.isoformat()

    if not picks:
        tick.say("No picks today. Nothing on the shortlist cleared the rules.")
        tick.record_decision(
            "", "no picks",
            f"the shortlist held {len(candidates)} candidates and none gave a usable "
            "entry above its opening range high")
        return picks

    tick.say(f"Picked {len(picks)} names:")
    for pick in picks:
        tick.say(f"  {pick.symbol}: enter above {pick.entry:.2f}, stop {pick.stop:.2f}, "
                 f"target {pick.target:.2f}, size {pick.qty} shares (score {pick.score})")
        tick.record_decision(pick.symbol, f"picked, entry {pick.entry:.2f} "
                             f"stop {pick.stop:.2f} target {pick.target:.2f}", pick.reason)

    if not entries_allowed_now(guard, tick.now, schedule):
        tick.note(f"it is past {schedule.entries_until:%H:%M}, so these picks are recorded "
                  "but no entry order would be worked out for them")
        return picks

    # An entry only fires when price actually breaks the opening range high, so
    # at the moment of picking we work out the order and let the guardrails rule
    # on it, which is what gets written down.
    for pick in picks:
        if pick.qty <= 0:
            tick.note(f"{pick.symbol}: the money rules allow zero shares at "
                      f"{pick.entry:.2f}, so there is nothing to buy")
            continue
        intent = make_order_intent(pick.symbol, "BUY", pick.qty, pick.entry, "entry")
        tick.consider(guard, account_state, intent,
                      extra=f"stop {pick.stop:.2f}, target {pick.target:.2f}")
    return picks


def latest_prices(client: mcp.McpClient, symbol: str,
                  candidate: dict | None = None) -> tuple[float | None, float | None, int]:
    """The last five minute close and the day's VWAP for one symbol."""
    contract = contract_for(candidate or {"symbol": symbol})
    try:
        bars = client.bars_5m_today(contract)
    except mcp.McpError:
        return None, None, 0
    if not bars:
        return None, None, 0
    return bars[-1].get("close"), mcp.session_vwap(bars), len(bars)


def exit_reason(last_close: float, vwap: float | None, stop: float,
                target: float) -> tuple[str | None, str]:
    """Should this position be closed, and in plain words why.

    The three ways out of a long, all from docs/STRATEGY.md:

      the stop was hit      the five minute close is at or below the stop
      the target was hit    the five minute close reached the target
      momentum faded        the five minute close is back below the day's
                            volume weighted average price, which is the
                            standard tell that an opening push is over

    Returns which of the three fired and the reason, or (None, "") to keep
    holding. Kept as its own function with no broker and no clock in it so the
    rule can be checked on paper.

    Note that all three lead to the same kind of order, one with the purpose
    "exit", including the one the stop triggered. In agent/guardrails.py the
    purpose "stop" means a resting stop order parked at the broker, and the kill
    switch deliberately blocks those while still letting a position be closed.
    A sell because the price broke our stop is us getting out now, so it is an
    exit. Which of the three fired is kept here and written into the reason, so
    nothing is lost from the ledger.
    """
    if stop and last_close <= stop:
        return "stop", (f"the five minute close {last_close:.2f} is at or below "
                        f"the stop {stop:.2f}")
    if target and last_close >= target:
        return "target", (f"the five minute close {last_close:.2f} reached the "
                          f"target {target:.2f}")
    if vwap and last_close < vwap:
        return "fade", (f"momentum faded, the five minute close {last_close:.2f} is back "
                        f"below the day's vwap {vwap:.2f}")
    return None, ""


def do_manage(tick: Tick, client: mcp.McpClient, guard, account_state, positions: dict,
              schedule: Schedule, state: DayState, config: dict) -> None:
    """Watch what is open, and let picks that have not fired yet still fire.

    Three ways out of a position, all from docs/STRATEGY.md: the stop is hit, the
    target is hit, or momentum faded, which the strategy defines as a five minute
    close back below the day's volume weighted average price.
    """
    picks_by_symbol = {p.get("symbol"): p for p in state.picks if isinstance(p, dict)}

    if not positions:
        tick.say("Nothing is open.")
    for symbol, position in positions.items():
        quantity = float(getattr(position, "qty", 0.0))
        last_close, vwap, bar_count = latest_prices(client, symbol)
        plan = picks_by_symbol.get(symbol)
        held = (f"{symbol}: holding {quantity:g} shares bought around "
                f"{getattr(position, 'avg_cost', 0.0):.2f}, worth "
                f"{getattr(position, 'market_value', 0.0):.2f}")
        if last_close is None:
            tick.say(held)
            tick.note(f"{symbol}: no five minute bars came back, leaving it alone this tick")
            continue
        tick.say(held + f", last five minute close {last_close:.2f}"
                 + (f", day vwap {vwap:.2f}" if vwap else ""))

        if plan is None:
            tick.note(f"{symbol}: this loop did not open it, so it has no stop or target on "
                      "file. It will be closed with everything else at "
                      f"{schedule.flatten_at:%H:%M}.")
            tick.record_decision(symbol, "hold, not opened by this loop",
                                 "no entry, stop or target recorded for this position in "
                                 f"{state_path(tick.now.date())}")
            continue

        stop = _number(plan.get("stop"))
        target = _number(plan.get("target"))
        trigger, reason = exit_reason(last_close, vwap, stop, target)

        if trigger is None:
            tick.say(f"  holding {symbol}, above its stop {stop:.2f} and its vwap, "
                     f"still short of its target {target:.2f}")
            tick.record_decision(symbol, "hold", "stop not hit, target not reached, "
                                 "and the price is still above the day's vwap")
            continue

        intent = make_order_intent(symbol, "SELL", abs(quantity), last_close, "exit")
        tick.consider(guard, account_state, intent,
                      extra=f"[{trigger}] because {reason}")

    if state.halted:
        tick.note(f"new entries are off for the rest of today: {state.halt_reason}")
        return
    if not entries_allowed_now(guard, tick.now, schedule):
        if picks_by_symbol:
            tick.note(f"new entries closed at {schedule.entries_until:%H:%M}, so any pick that "
                      "has not fired by now is left alone")
        return

    for symbol, plan in picks_by_symbol.items():
        if symbol in positions or symbol in state.triggered:
            continue
        entry = _number(plan.get("entry"))
        quantity = int(_number(plan.get("qty")))
        if entry <= 0 or quantity <= 0:
            continue
        last_close, _vwap, _count = latest_prices(client, symbol)
        if last_close is None:
            tick.note(f"{symbol}: no price came back, so its entry cannot be judged this tick")
            continue
        if last_close <= entry:
            tick.say(f"  {symbol} is at {last_close:.2f}, still under its "
                     f"{entry:.2f} trigger, waiting")
            tick.record_decision(symbol, "wait",
                                 f"last close {last_close:.2f} has not broken the opening "
                                 f"range high {entry:.2f}")
            continue

        target = _number(plan.get("target"))
        if target and last_close >= target:
            # The move already went where we were hoping it would go. Buying now
            # means paying for the whole move and keeping only the risk.
            tick.say(f"  {symbol} is at {last_close:.2f}, already past its "
                     f"{target:.2f} target, so the entry is skipped")
            tick.record_decision(symbol, "no entry, the move already ran",
                                 f"last close {last_close:.2f} is at or above the target "
                                 f"{target:.2f}, so there is no reward left to pay for the risk")
            state.triggered[symbol] = {"at": tick.now.isoformat(), "price": last_close,
                                       "allowed": False, "sent": False,
                                       "mode": tick.mode, "skipped": "past target"}
            continue

        tick.say(f"  {symbol} broke its {entry:.2f} trigger, now {last_close:.2f}")
        # Size on the price we would actually pay, not on the price we planned
        # for at 9:35. The trigger fires above the planned entry by definition,
        # so keeping the old share count would quietly push the order through
        # the dollar cap.
        priced_quantity = max_shares_for(guard, account_state, symbol, last_close, config)
        if priced_quantity < quantity:
            tick.note(f"{symbol}: cut from {quantity} shares to {priced_quantity} because the "
                      f"price moved from {entry:.2f} to {last_close:.2f} before the trigger fired")
            quantity = priced_quantity
        if quantity <= 0:
            tick.record_decision(symbol, "no entry",
                                 f"at {last_close:.2f} the money rules allow zero shares")
            continue
        intent = make_order_intent(symbol, "BUY", quantity, last_close, "entry")
        decision = tick.consider(guard, account_state, intent,
                                 extra=f"stop {_number(plan.get('stop')):.2f}, "
                                       f"target {_number(plan.get('target')):.2f}")
        allowed, _reasons, _ids, halt = decision_fields(decision)
        # In dry run nothing was bought, but the trigger is remembered so the
        # next tick does not report the same break over and over.
        state.triggered[symbol] = {
            "at": tick.now.isoformat(), "price": last_close,
            "allowed": allowed, "sent": False, "mode": tick.mode,
        }
        if halt:
            state.halted = True
            state.halt_reason = "a guardrail asked for a halt for the rest of the day"


def do_flatten(tick: Tick, client: mcp.McpClient, guard, account_state, positions: dict,
               schedule: Schedule) -> None:
    """Close everything. No position is carried overnight, ever."""
    if not positions:
        tick.say(f"Nothing is open at {schedule.flatten_at:%H:%M}, so there is nothing to close.")
        return
    tick.say(f"It is past {schedule.flatten_at:%H:%M}. Closing all "
             f"{len(positions)} open positions.")
    for symbol, position in positions.items():
        quantity = abs(float(getattr(position, "qty", 0.0)))
        last_close, _vwap, _count = latest_prices(client, symbol)
        intent = make_order_intent(symbol, "SELL", quantity, None, "flatten")
        tick.consider(guard, account_state, intent,
                      extra=(f"end of day close out, last price "
                             f"{last_close:.2f}" if last_close else "end of day close out"))


# ------------------------------------------------------------------ the driver

def write_tick_log(line: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TICK_LOG.open("a") as handle:
        handle.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One tick of the five minute trading loop. Dry run only today.")
    parser.add_argument("--dry-run", action="store_true",
                        help="work everything out and send nothing. The only mode "
                             "that runs today.")
    parser.add_argument("--live", action="store_true",
                        help="ask for the live order path. Also needs "
                             f"{LIVE_ENV_VAR}=yes and a DU paper account, and even "
                             "then the broker call is not wired up yet.")
    parser.add_argument("--now", metavar="WHEN",
                        help='pretend it is this time, New York time, for example '
                             '"2026-09-03 09:36". Lets a phase be tested after hours.')
    parser.add_argument("--write-ledger", action="store_true",
                        help="in dry run, still write the decisions to the real Google "
                             "Sheet instead of printing them")
    parser.add_argument("--config", default=str(CONFIG_PATH),
                        help="which guardrails file to read")
    args = parser.parse_args(argv)

    if not args.dry_run:
        print("loop: refusing to run. Pass --dry-run.\n"
              "      Dry run is the only mode that works today, by design. The live path "
              "is shut behind\n"
              f"      the --live flag, the environment variable {LIVE_ENV_VAR}=yes and a "
              "paper account id\n"
              "      starting with DU, and the broker call behind those is deliberately "
              "not wired up.\n"
              "      See the note at the top of this file.", file=sys.stderr)
        return 2

    config, config_used = load_config()
    schedule = schedule_from(config)
    zone = schedule.zone
    now = parse_now(args.now, zone)
    day = now.date()

    mode = "dry-run"
    tick = Tick(now, mode, dry_run=True, write_ledger=args.write_ledger)

    print("=" * 78)
    print(f"Tick at {now:%Y-%m-%d %H:%M:%S} {now.tzname()}"
          + ("  (pretend time from --now)" if args.now else "")
          + f"   mode: {mode}")
    print(f"Rules from {config_used}")
    print("=" * 78)

    state = load_state(day)
    guard = load_guardrails_object(Path(args.config))
    if guard is None:
        print("The guardrail layer is NOT loaded, so this tick can approve nothing.")
        print(f"  why: {FALLBACKS_USED[0] if FALLBACKS_USED else 'unknown'}")
        print("  the loop still runs, works out every would be order and writes it down,")
        print("  and every one of them is refused. That is the safe way round.")

    switch = kill_switch_path(config)
    kill_switch_present = switch.exists()
    if kill_switch_present:
        print(f"KILL SWITCH is on: the file {switch} exists.")
        print("  Nothing will be opened. Positions may still be closed.")
        print(f"  Remove it to resume: rm {switch}")
        ledger_writer.log_rule(now, "kill_switch", f"the file {switch} exists",
                               "no new positions, closing only",
                               dry_run=not args.write_ledger)

    client = mcp.McpClient(account=(config.get("account") or {}).get("account_id"))
    account_state, facts, positions, problems = read_account(
        client, now, state, kill_switch_present,
        (config.get("account") or {}).get("account_id"))
    for problem in problems:
        tick.note(problem)

    state.account_id = facts["account_id"] or state.account_id
    if facts["account_id"] and not facts["account_id"].startswith(PAPER_ACCOUNT_PREFIX):
        print(f"STOP: the account is {facts['account_id']}, which does not start with "
              f"{PAPER_ACCOUNT_PREFIX}. Paper accounts do. Refusing to go further.")
        ledger_writer.log_rule(now, "paper_account_only",
                               f"account {facts['account_id']} is not a paper account",
                               "the tick stopped", dry_run=not args.write_ledger)
        return 3

    if facts["equity"]:
        print(f"Account {facts['account_id']}: worth {facts['equity']:,.2f}, started the day at "
              f"{facts['day_start_equity']:,.2f} "
              f"({facts.get('day_pnl_pct', 0.0):+.3f} percent), "
              f"{facts['open_positions']} positions open, {facts['open_orders']} orders working")
    else:
        print("Could not read the account. Every would be order will be refused this tick.")

    open_locks, shut_locks = live_orders_allowed(args.live, facts["account_id"])
    print("Live orders: " + ("ALL THREE LOCKS OPEN, and the broker call is still not wired up"
                             if open_locks else "off. " + "; ".join(shut_locks)))

    # Once the pick has been attempted today, every later tick manages. Based on
    # whether it was attempted rather than on whether it found anything, so an
    # empty shortlist does not send the loop back to picking on every tick.
    phase, why = phase_for(now, schedule, state.picked_at is not None)
    regular_hours = is_regular_hours(guard, now, schedule)
    print(f"\nPhase: {phase}  ({why})")
    print(f"Regular market hours: {'yes' if regular_hours else 'no'}\n")

    if state.day_start_equity is not None and not state.daily_started_logged:
        ledger_writer.upsert_daily(f"{day:%Y-%m-%d}",
                                   starting_equity=round(state.day_start_equity, 2),
                                   dry_run=not args.write_ledger)
        state.daily_started_logged = True

    if phase == BEFORE_SCAN:
        print(f"Nothing to do yet. The scanner runs at {schedule.scan_start:%H:%M}.")
    elif phase == SCAN:
        candidates, path = do_scan(tick, day)
        if candidates:
            state.shortlist_path = str(path)
            state.scanner_ran_at = now.isoformat()
            print(f"Shortlist has {len(candidates)} names. "
                  f"Claude picks from it at {schedule.pick_time:%H:%M}.")
        else:
            print("Shortlist is empty. Nothing will be picked unless the next scan finds "
                  "something.")
    elif phase == PICK:
        do_pick(tick, client, day, guard, account_state, facts, schedule, config, state)
    elif phase == MANAGE:
        do_manage(tick, client, guard, account_state, positions, schedule, state, config)
    elif phase == FLATTEN:
        do_flatten(tick, client, guard, account_state, positions, schedule)
    elif phase == CLOSED:
        print("The market is shut. Nothing to do.")
        if positions and now.time() >= schedule.market_close:
            tick.note(f"{len(positions)} positions are still open after the close. "
                      "That should not happen, the flatten phase is meant to clear them.")
        if not state.daily_closed_logged and facts["equity"] and now.weekday() < 5 \
                and now.time() >= schedule.market_close:
            ledger_writer.upsert_daily(
                f"{day:%Y-%m-%d}", ending_equity=round(facts["equity"], 2),
                rules_triggered=("; ".join(FALLBACKS_USED) or "none"),
                notes=f"dry run, {tick.would_be_orders} would be orders this tick",
                dry_run=not args.write_ledger)
            state.daily_closed_logged = True

    if FALLBACKS_USED:
        print("\nThings that were not there and had to be worked around:")
        for item in FALLBACKS_USED:
            print(f"  - {item}")

    state.tick_count += 1
    state.last_tick = now.isoformat()
    state.last_phase = phase
    save_state(state)

    summary = (f"{now:%Y-%m-%d %H:%M:%S} {now.tzname()} | mode={mode} | phase={phase} | "
               f"account={facts['account_id'] or 'unknown'} | "
               f"equity={facts['equity']:.2f} | positions={facts['open_positions']} | "
               f"picks={len(state.picks)} | would_be_orders={tick.would_be_orders} | "
               f"approved={tick.approved} | refused={tick.refused} | "
               f"guardrails={'loaded' if guard is not None else 'MISSING'} | "
               f"kill_switch={'ON' if kill_switch_present else 'off'} | "
               f"notes={len(tick.notes)}")
    write_tick_log(summary)
    print(f"\n{summary}")
    print(f"State saved to {state_path(day)}")
    print(f"Tick log      {TICK_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
