"""Hard limits for the trading agent.

This module is the referee. It reads the numbers in config/guardrails.yaml and
checks every order the agent wants to place against them. If any limit says no,
the order is refused and the reason is written in plain English so Mo can read
the ledger later and understand exactly what happened.

Two things this file deliberately does not do:

1. It never talks to the network. No IB Gateway, no broker, no market data. It
   is pure arithmetic and clock checking, which is why it can be tested in a
   second with no account open.
2. It never guesses. A missing setting, a nonsense number or a time with no
   timezone attached raises an error instead of being quietly patched up.

Rule ids are stable strings ("max_position_pct", "kill_switch" and so on) so
other parts of the agent, and the ledger, can count how often each limit fired.

Written 2026-09-02. The numbers live in the yaml file, not here.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

__all__ = [
    "GuardrailError",
    "GuardrailConfigError",
    "GuardrailUsageError",
    "AccountConfig",
    "MoneyConfig",
    "RiskConfig",
    "UniverseConfig",
    "ScannerConfig",
    "ScheduleConfig",
    "KillSwitchConfig",
    "Guardrails",
    "PositionInfo",
    "AccountState",
    "OrderIntent",
    "Decision",
    "load_guardrails",
    "check_order",
    "daily_loss_hit",
    "entries_allowed_now",
    "must_flatten_now",
    "is_regular_hours",
    "stop_price_for",
    "max_shares_for",
]


# The environment variable that has to say "yes" before a live account loads.
LIVE_MODE_ENV_VAR = "AGENTIC_TRADING_ALLOW_LIVE"

# Purposes that mean "get us out of a trade". These are always the last thing we
# block, because refusing an exit is worse than any other mistake in here.
CLOSING_PURPOSES = ("exit", "stop", "flatten")

# What the kill switch still lets through. Note this is narrower than
# CLOSING_PURPOSES on purpose: with the stop file in place the agent may close a
# position itself, but it may not send fresh stop orders.
KILL_SWITCH_ALLOWED_PURPOSES = ("exit", "flatten")

VALID_PURPOSES = ("entry", "exit", "stop", "flatten")
VALID_SIDES = ("BUY", "SELL")

# Money is compared with half a cent of slack so that an order sitting exactly
# on a limit is allowed through rather than being blocked by a rounding wobble
# in the last decimal place of a float.
CENT_TOLERANCE = 0.005

_HHMM_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")

# Plain words for the IBKR security type codes, used in refusal messages.
_SEC_TYPE_WORDS = {
    "STK": "ordinary shares or an ETF",
    "OPT": "a stock option",
    "FUT": "a futures contract",
    "FOP": "an option on a future",
    "CASH": "a currency pair",
    "BOND": "a bond",
    "CFD": "a contract for difference",
    "WAR": "a warrant",
    "FUND": "a mutual fund",
    "CRYPTO": "a crypto coin",
}


class GuardrailError(Exception):
    """Base class so callers can catch anything this module raises."""


class GuardrailConfigError(GuardrailError):
    """The settings file is missing, unreadable or holds a bad value."""


class GuardrailUsageError(GuardrailError, ValueError):
    """The code called this module wrongly, for example a time with no timezone."""


# ---------------------------------------------------------------------------
# The settings, one dataclass per section of the yaml file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountConfig:
    """Which broker account the agent is allowed to touch."""

    mode: str
    account_id: str
    gateway_port_paper: int
    gateway_port_live: int

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    @property
    def gateway_port(self) -> int:
        """The port that matches the mode we are running in."""
        return self.gateway_port_paper if self.is_paper else self.gateway_port_live


@dataclass(frozen=True)
class MoneyConfig:
    """How much money may be at risk, and where."""

    starting_equity: float
    max_position_pct: float
    max_open_positions: int
    max_daily_loss_pct: float
    max_order_notional: float


@dataclass(frozen=True)
class RiskConfig:
    """Where the stop loss goes."""

    stop_loss_pct: float
    use_opening_range_low_if_tighter: bool


@dataclass(frozen=True)
class UniverseConfig:
    """What the agent is allowed to trade at all."""

    price_floor: float
    min_avg_volume: int
    allow_options: bool
    allow_shorts: bool
    allowed_sec_types: tuple[str, ...]
    allowed_currencies: tuple[str, ...]
    whitelist: tuple[str, ...]
    blacklist: tuple[str, ...]


@dataclass(frozen=True)
class ScannerConfig:
    """How the morning shortlist is built."""

    rel_volume_min: float
    max_candidates: int
    exclude_leveraged_etfs: bool


@dataclass(frozen=True)
class ScheduleConfig:
    """The clock. Every time here is in the timezone named below."""

    timezone: str
    scan_start: time
    pick_time: time
    entries_until: time
    flatten_at: time
    market_close: time
    loop_minutes: int
    trade_only_regular_hours: bool


@dataclass(frozen=True)
class KillSwitchConfig:
    """The file that stops the agent opening anything new."""

    file: str


@dataclass(frozen=True)
class Guardrails:
    """Every limit, loaded from one yaml file."""

    account: AccountConfig
    money: MoneyConfig
    risk: RiskConfig
    universe: UniverseConfig
    scanner: ScannerConfig
    schedule: ScheduleConfig
    kill_switch: KillSwitchConfig
    source_path: Path | None = None

    @property
    def tz(self) -> ZoneInfo:
        """The timezone object for the schedule, always America/New_York in month one."""
        return ZoneInfo(self.schedule.timezone)


# ---------------------------------------------------------------------------
# What the account looks like right now, and what we want to do
# ---------------------------------------------------------------------------


@dataclass
class PositionInfo:
    """One holding, as the broker reports it."""

    symbol: str
    qty: int
    avg_cost: float
    market_value: float

    def __post_init__(self) -> None:
        self.symbol = _clean_symbol(self.symbol, "PositionInfo.symbol")


@dataclass
class AccountState:
    """A snapshot of the account, taken just before we check an order.

    equity                 what the account is worth right now
    day_start_equity       what it was worth when the market opened today
    realized_pnl_today     money made or lost on trades already closed today
    unrealized_pnl         money made or lost on trades still open
    open_positions         holdings, keyed by symbol
    pending_order_notional dollar value of entry orders sent but not filled yet
    now                    the current time, and it must carry a timezone
    kill_switch_present    true when the stop file exists on disk
    account_id             the account the orders would actually go to
    """

    equity: float
    day_start_equity: float
    realized_pnl_today: float
    unrealized_pnl: float
    open_positions: dict[str, PositionInfo]
    pending_order_notional: float
    now: datetime
    kill_switch_present: bool
    account_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.now, datetime):
            raise GuardrailUsageError(
                "AccountState.now has to be a date and time, "
                f"but it is {type(self.now).__name__}."
            )
        _require_aware(self.now, "AccountState.now")
        if self.open_positions is None:
            self.open_positions = {}

    @property
    def total_pnl_today(self) -> float:
        """Closed and open profit or loss added together."""
        return self.realized_pnl_today + self.unrealized_pnl

    def held_qty(self, symbol: str) -> int:
        """Shares we hold in one symbol, zero when we hold none."""
        position = self.open_positions.get(_clean_symbol(symbol, "symbol"))
        return int(position.qty) if position is not None else 0

    def held_market_value(self, symbol: str) -> float:
        """Dollar value of what we hold in one symbol, zero when we hold none."""
        position = self.open_positions.get(_clean_symbol(symbol, "symbol"))
        return float(position.market_value) if position is not None else 0.0

    def open_position_count(self) -> int:
        """How many symbols we actually hold. A zero quantity does not count."""
        return sum(1 for position in self.open_positions.values() if position.qty != 0)


@dataclass
class OrderIntent:
    """One order the agent would like to place, before anyone checks it."""

    symbol: str
    side: str
    qty: int
    limit_price: float | None = None
    sec_type: str = "STK"
    currency: str = "USD"
    purpose: str = "entry"

    def __post_init__(self) -> None:
        self.symbol = _clean_symbol(self.symbol, "OrderIntent.symbol")
        self.side = str(self.side).strip().upper()
        if self.side not in VALID_SIDES:
            raise GuardrailUsageError(
                f"OrderIntent.side has to be BUY or SELL, not {self.side!r}."
            )
        self.sec_type = str(self.sec_type).strip().upper()
        self.currency = str(self.currency).strip().upper()
        self.purpose = str(self.purpose).strip().lower()
        if self.purpose not in VALID_PURPOSES:
            raise GuardrailUsageError(
                "OrderIntent.purpose has to be one of "
                f"{', '.join(VALID_PURPOSES)}, not {self.purpose!r}."
            )
        if isinstance(self.qty, bool) or not isinstance(self.qty, int):
            raise GuardrailUsageError(
                f"OrderIntent.qty has to be a whole number of shares, not {self.qty!r}."
            )
        if self.qty <= 0:
            raise GuardrailUsageError(
                "OrderIntent.qty has to be more than zero. Use side SELL to sell, "
                "never a negative quantity."
            )
        if self.limit_price is not None:
            self.limit_price = float(self.limit_price)
            if self.limit_price <= 0:
                raise GuardrailUsageError(
                    "OrderIntent.limit_price has to be more than zero when it is given."
                )

    @property
    def notional(self) -> float | None:
        """What the order would cost, or None when there is no limit price."""
        if self.limit_price is None:
            return None
        return self.qty * self.limit_price

    @property
    def is_closing(self) -> bool:
        """True when this order is getting us out of something."""
        return self.purpose in CLOSING_PURPOSES


@dataclass
class Decision:
    """The answer: may this order go, and if not, why not.

    reasons and rule_ids line up index for index, and hold every limit that was
    broken, not just the first one. daily_halt is a separate signal: it is true
    whenever the account has hit its loss limit for the day, whether or not this
    particular order was blocked.
    """

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    daily_halt: bool = False

    def add(self, rule_id: str, reason: str) -> None:
        """Record one broken limit and mark the order as refused."""
        self.rule_ids.append(rule_id)
        self.reasons.append(reason)
        self.allowed = False

    @property
    def summary(self) -> str:
        """One line for the log."""
        if self.allowed:
            return "allowed"
        return "blocked: " + "; ".join(self.reasons)


# ---------------------------------------------------------------------------
# Loading and checking the settings file
# ---------------------------------------------------------------------------


def load_guardrails(path: str | Path) -> Guardrails:
    """Read the settings file and check every value in it.

    Raises GuardrailConfigError, with a message that says what to fix, if the
    file is missing, is not valid yaml, is missing a setting, holds a value of
    the wrong kind or holds a number that makes no sense. Also refuses to load a
    live account unless the environment variable AGENTIC_TRADING_ALLOW_LIVE is
    set to yes.
    """
    config_path = Path(path).expanduser()

    if not config_path.exists():
        raise GuardrailConfigError(
            f"There is no guardrail settings file at {config_path}. "
            "Copy config/guardrails.example.yaml to config/guardrails.yaml and edit it."
        )
    if config_path.is_dir():
        raise GuardrailConfigError(
            f"{config_path} is a folder, not a settings file."
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuardrailConfigError(
            f"The guardrail settings file {config_path} could not be read: {exc}"
        ) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise GuardrailConfigError(
            f"The guardrail settings file {config_path} is not valid yaml. "
            f"The yaml reader said: {exc}"
        ) from exc

    if data is None:
        raise GuardrailConfigError(
            f"The guardrail settings file {config_path} is empty."
        )
    if not isinstance(data, dict):
        raise GuardrailConfigError(
            f"The guardrail settings file {config_path} should be a list of named "
            "sections such as account, money and schedule, but it is a "
            f"{type(data).__name__}."
        )

    where = str(config_path)
    account_raw = _section(data, "account", where)
    money_raw = _section(data, "money", where)
    risk_raw = _section(data, "risk", where)
    universe_raw = _section(data, "universe", where)
    scanner_raw = _section(data, "scanner", where)
    schedule_raw = _section(data, "schedule", where)
    kill_raw = _section(data, "kill_switch", where)

    account = _build_account(account_raw, where)
    money = _build_money(money_raw, where)
    risk = _build_risk(risk_raw, where)
    universe = _build_universe(universe_raw, where)
    scanner = _build_scanner(scanner_raw, where)
    schedule = _build_schedule(schedule_raw, where)
    kill_switch = KillSwitchConfig(
        file=_need_text(kill_raw, "kill_switch.file", where)
    )

    if account.mode == "live" and os.environ.get(LIVE_MODE_ENV_VAR) != "yes":
        raise GuardrailConfigError(
            f"The settings file {where} is set to live trading with real money "
            f"(account.mode: live), so it will not load. If that is genuinely what "
            f"you want, set the environment variable {LIVE_MODE_ENV_VAR}=yes in the "
            "same shell and try again. Otherwise change account.mode back to paper."
        )

    return Guardrails(
        account=account,
        money=money,
        risk=risk,
        universe=universe,
        scanner=scanner,
        schedule=schedule,
        kill_switch=kill_switch,
        source_path=config_path,
    )


def _build_account(raw: dict, where: str) -> AccountConfig:
    mode = _need_text(raw, "account.mode", where).lower()
    if mode not in ("paper", "live"):
        raise GuardrailConfigError(
            f"The setting account.mode in {where} has to be either paper or live, "
            f"but it says {mode!r}."
        )
    account_id = _need_text(raw, "account.account_id", where)
    if mode == "paper" and not account_id.upper().startswith("DU"):
        raise GuardrailConfigError(
            f"The setting account.mode in {where} says paper, but "
            f"account.account_id is {account_id!r} and IBKR paper account ids all "
            "start with DU. Either fix the account id or, if this really is a live "
            "account, change account.mode to live."
        )
    return AccountConfig(
        mode=mode,
        account_id=account_id,
        gateway_port_paper=_need_positive_int(raw, "account.gateway_port_paper", where),
        gateway_port_live=_need_positive_int(raw, "account.gateway_port_live", where),
    )


def _build_money(raw: dict, where: str) -> MoneyConfig:
    return MoneyConfig(
        starting_equity=_need_positive_number(raw, "money.starting_equity", where),
        max_position_pct=_need_percent(raw, "money.max_position_pct", where),
        max_open_positions=_need_positive_int(raw, "money.max_open_positions", where),
        max_daily_loss_pct=_need_percent(raw, "money.max_daily_loss_pct", where),
        max_order_notional=_need_positive_number(raw, "money.max_order_notional", where),
    )


def _build_risk(raw: dict, where: str) -> RiskConfig:
    return RiskConfig(
        stop_loss_pct=_need_percent(raw, "risk.stop_loss_pct", where),
        use_opening_range_low_if_tighter=_need_bool(
            raw, "risk.use_opening_range_low_if_tighter", where
        ),
    )


def _build_universe(raw: dict, where: str) -> UniverseConfig:
    allowed_sec_types = _need_symbol_list(raw, "universe.allowed_sec_types", where)
    if not allowed_sec_types:
        raise GuardrailConfigError(
            f"The setting universe.allowed_sec_types in {where} is empty, so the "
            "agent could not trade anything at all. For shares and ETFs use [STK]."
        )
    allowed_currencies = _need_symbol_list(raw, "universe.allowed_currencies", where)
    if not allowed_currencies:
        raise GuardrailConfigError(
            f"The setting universe.allowed_currencies in {where} is empty, so the "
            "agent could not trade anything at all. For US dollars use [USD]."
        )
    return UniverseConfig(
        price_floor=_need_number_at_least(raw, "universe.price_floor", where, 0.0),
        min_avg_volume=_need_positive_int(raw, "universe.min_avg_volume", where),
        allow_options=_need_bool(raw, "universe.allow_options", where),
        allow_shorts=_need_bool(raw, "universe.allow_shorts", where),
        allowed_sec_types=allowed_sec_types,
        allowed_currencies=allowed_currencies,
        whitelist=_need_symbol_list(raw, "universe.whitelist", where),
        blacklist=_need_symbol_list(raw, "universe.blacklist", where),
    )


def _build_scanner(raw: dict, where: str) -> ScannerConfig:
    return ScannerConfig(
        rel_volume_min=_need_positive_number(raw, "scanner.rel_volume_min", where),
        max_candidates=_need_positive_int(raw, "scanner.max_candidates", where),
        exclude_leveraged_etfs=_need_bool(
            raw, "scanner.exclude_leveraged_etfs", where
        ),
    )


def _build_schedule(raw: dict, where: str) -> ScheduleConfig:
    timezone_name = _need_text(raw, "schedule.timezone", where)
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GuardrailConfigError(
            f"The setting schedule.timezone in {where} says {timezone_name!r}, which "
            "is not a timezone this computer knows about. Use America/New_York."
        ) from exc

    schedule = ScheduleConfig(
        timezone=timezone_name,
        scan_start=_need_clock_time(raw, "schedule.scan_start", where),
        pick_time=_need_clock_time(raw, "schedule.pick_time", where),
        entries_until=_need_clock_time(raw, "schedule.entries_until", where),
        flatten_at=_need_clock_time(raw, "schedule.flatten_at", where),
        market_close=_need_clock_time(raw, "schedule.market_close", where),
        loop_minutes=_need_positive_int(raw, "schedule.loop_minutes", where),
        trade_only_regular_hours=_need_bool(
            raw, "schedule.trade_only_regular_hours", where
        ),
    )

    _check_times_in_order(
        [
            ("schedule.scan_start", schedule.scan_start),
            ("schedule.pick_time", schedule.pick_time),
            ("schedule.entries_until", schedule.entries_until),
            ("schedule.flatten_at", schedule.flatten_at),
            ("schedule.market_close", schedule.market_close),
        ],
        where,
    )
    if schedule.loop_minutes > 60:
        raise GuardrailConfigError(
            f"The setting schedule.loop_minutes in {where} is "
            f"{schedule.loop_minutes}, which is more than an hour between checks. "
            "For a day-trading strategy use something like 5."
        )
    return schedule


def _check_times_in_order(named_times: list[tuple[str, time]], where: str) -> None:
    """The trading day has to run forwards: open, pick, last entry, flatten, close."""
    for (earlier_name, earlier), (later_name, later) in zip(
        named_times, named_times[1:]
    ):
        if earlier > later:
            raise GuardrailConfigError(
                f"The times in the schedule section of {where} are out of order. "
                f"{earlier_name} is {earlier.strftime('%H:%M')} and {later_name} is "
                f"{later.strftime('%H:%M')}, but the day has to run forwards: "
                "scan_start, pick_time, entries_until, flatten_at, market_close."
            )
    _, flatten_at = named_times[-2]
    _, market_close = named_times[-1]
    if flatten_at >= market_close:
        raise GuardrailConfigError(
            f"The setting schedule.flatten_at in {where} is "
            f"{flatten_at.strftime('%H:%M')}, which is not before "
            f"schedule.market_close at {market_close.strftime('%H:%M')}. Positions "
            "have to be sold while the market is still open."
        )


# ---------------------------------------------------------------------------
# Small validators. Every message names the setting, the file and the fix.
# ---------------------------------------------------------------------------


def _section(data: dict, name: str, where: str) -> dict:
    if name not in data:
        raise GuardrailConfigError(
            f"The guardrail settings file {where} has no {name} section. "
            "Compare it with config/guardrails.example.yaml."
        )
    value = data[name]
    if not isinstance(value, dict):
        raise GuardrailConfigError(
            f"The {name} section of {where} should hold a list of settings, but it "
            f"is a {type(value).__name__}."
        )
    return value


def _need(raw: dict, dotted_name: str, where: str):
    key = dotted_name.split(".")[-1]
    if key not in raw:
        raise GuardrailConfigError(
            f"The setting {dotted_name} is missing from {where}. "
            "Compare it with config/guardrails.example.yaml."
        )
    return raw[key]


def _need_text(raw: dict, dotted_name: str, where: str) -> str:
    value = _need(raw, dotted_name, where)
    if not isinstance(value, str) or not value.strip():
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be some text, but it is "
            f"{value!r}."
        )
    return value.strip()


def _need_bool(raw: dict, dotted_name: str, where: str) -> bool:
    value = _need(raw, dotted_name, where)
    if not isinstance(value, bool):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be true or false, but it "
            f"is {value!r}."
        )
    return value


def _need_number(raw: dict, dotted_name: str, where: str) -> float:
    value = _need(raw, dotted_name, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be a number, but it is "
            f"{value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {value!r}, which is not a "
            "real number."
        )
    return number


def _need_positive_number(raw: dict, dotted_name: str, where: str) -> float:
    number = _need_number(raw, dotted_name, where)
    if number <= 0:
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {_plain_number(number)}, but "
            "it has to be more than zero."
        )
    return number


def _need_number_at_least(
    raw: dict, dotted_name: str, where: str, floor: float
) -> float:
    number = _need_number(raw, dotted_name, where)
    if number < floor:
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {_plain_number(number)}, but "
            f"it cannot be less than {_plain_number(floor)}."
        )
    return number


def _need_positive_int(raw: dict, dotted_name: str, where: str) -> int:
    value = _need(raw, dotted_name, where)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise GuardrailConfigError(
                f"The setting {dotted_name} in {where} should be a whole number, but "
                f"it is {value!r}."
            )
    if value <= 0:
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {value}, but it has to be a "
            "whole number above zero."
        )
    return int(value)


def _need_percent(raw: dict, dotted_name: str, where: str) -> float:
    number = _need_number(raw, dotted_name, where)
    if number <= 0 or number > 100:
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {_plain_number(number)}, but a "
            "percentage here has to be above 0 and no more than 100. Write 10 for "
            "ten percent, not 0.10."
        )
    return number


def _need_symbol_list(raw: dict, dotted_name: str, where: str) -> tuple[str, ...]:
    value = _need(raw, dotted_name, where)
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be a list, written like "
            f"[AAPL, MSFT] or left empty as [], but it is {value!r}."
        )
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise GuardrailConfigError(
                f"The list {dotted_name} in {where} contains {item!r}, which is not "
                "a symbol. Every entry has to be text such as AAPL."
            )
        cleaned.append(item.strip().upper())
    return tuple(cleaned)


def _need_clock_time(raw: dict, dotted_name: str, where: str) -> time:
    value = _need(raw, dotted_name, where)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be a time written as "
            f'"HH:MM" with the quotation marks, for example "09:35". Right now it '
            f"reads {value!r}. Without the quotation marks yaml turns a time into a "
            "number."
        )
    match = _HHMM_PATTERN.match(value.strip())
    if match is None:
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} is {value!r}, which is not a time "
            'this code can read. Use 24 hour "HH:MM", for example "09:35" or "15:55".'
        )
    return time(hour=int(match.group(1)), minute=int(match.group(2)))


def _clean_symbol(symbol: str, label: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise GuardrailUsageError(f"{label} has to be a symbol such as AAPL.")
    return symbol.strip().upper()


def _plain_number(value: float) -> str:
    """Print 10 rather than 10.0, but keep 1.5 as 1.5."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _round_cents(value: float) -> float:
    return float(
        Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


# ---------------------------------------------------------------------------
# Clock helpers. Naive times are refused, never guessed at.
# ---------------------------------------------------------------------------


def _require_aware(moment: datetime, label: str) -> datetime:
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise GuardrailUsageError(
            f"{label} is {moment.isoformat()}, which carries no timezone. This code "
            "will not guess whether that means New York, London or UTC. Build the "
            "time with a timezone, for example "
            'datetime(2026, 9, 2, 9, 35, tzinfo=ZoneInfo("America/New_York")).'
        )
    return moment


def _eastern(g: Guardrails, moment: datetime, label: str = "now") -> datetime:
    """Turn any timezone aware moment into the schedule's timezone."""
    if not isinstance(moment, datetime):
        raise GuardrailUsageError(
            f"{label} has to be a date and time, but it is {type(moment).__name__}."
        )
    _require_aware(moment, label)
    return moment.astimezone(g.tz)


def _is_weekday(moment: datetime) -> bool:
    """Monday to Friday. Market holidays are the calendar's job, not this file's."""
    return moment.weekday() < 5


def is_regular_hours(g: Guardrails, now: datetime) -> bool:
    """True when the US market is open: a weekday, from scan_start up to market_close.

    The start of the day is included and the close is not, so 09:30 counts as
    open and 16:00 counts as shut.
    """
    local = _eastern(g, now)
    if not _is_weekday(local):
        return False
    return g.schedule.scan_start <= local.time() < g.schedule.market_close


def entries_allowed_now(g: Guardrails, now: datetime) -> bool:
    """True when a brand new position may be opened.

    That window is pick_time up to entries_until on a weekday, 09:35 to 11:00 in
    the proposed settings. The start is included and the end is not, so 09:35 is
    fine and 11:00 is too late.
    """
    local = _eastern(g, now)
    if not _is_weekday(local):
        return False
    return g.schedule.pick_time <= local.time() < g.schedule.entries_until


def must_flatten_now(g: Guardrails, now: datetime) -> bool:
    """True when everything still open should be sold at market.

    That is from flatten_at until the close on a weekday, 15:55 to 16:00 in the
    proposed settings. After the close it goes back to false, because the orders
    could not be filled anyway.
    """
    local = _eastern(g, now)
    if not _is_weekday(local):
        return False
    return g.schedule.flatten_at <= local.time() < g.schedule.market_close


def _past_flatten_time(g: Guardrails, now: datetime) -> bool:
    """True on a trading day once the clock has reached flatten_at."""
    local = _eastern(g, now)
    return _is_weekday(local) and local.time() >= g.schedule.flatten_at


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------


def daily_loss_hit(g: Guardrails, state: AccountState) -> bool:
    """True when today's loss has reached the daily cap.

    Closed and open profit or loss are added together and compared with the cap,
    which is a percentage of what the account was worth at the open. Landing
    exactly on the cap counts as hit.
    """
    if state.day_start_equity <= 0:
        # No sensible balance to measure against, so take the safe answer and halt.
        return True
    allowed_loss = state.day_start_equity * (g.money.max_daily_loss_pct / 100.0)
    return state.total_pnl_today <= -allowed_loss + CENT_TOLERANCE


def stop_price_for(
    g: Guardrails, entry_price: float, opening_range_low: float | None
) -> float:
    """Where the stop loss goes for a long position bought at entry_price.

    Start with the percentage stop from the settings, 1.5 percent below entry.
    If the low of the opening five minutes is nearer to entry than that, and the
    settings allow it, use the opening range low instead: a nearer stop means a
    smaller loss when it is hit. The answer is always below the entry price and
    is rounded to whole cents.
    """
    if not isinstance(entry_price, (int, float)) or isinstance(entry_price, bool):
        raise GuardrailUsageError(
            f"entry_price has to be a number, but it is {entry_price!r}."
        )
    entry_price = float(entry_price)
    if entry_price <= 0 or not math.isfinite(entry_price):
        raise GuardrailUsageError(
            f"entry_price has to be more than zero, but it is {_plain_number(entry_price)}."
        )

    percent_stop = entry_price * (1.0 - g.risk.stop_loss_pct / 100.0)
    stop = percent_stop

    if opening_range_low is not None and g.risk.use_opening_range_low_if_tighter:
        low = float(opening_range_low)
        if not math.isfinite(low):
            raise GuardrailUsageError(
                f"opening_range_low has to be a number, but it is {opening_range_low!r}."
            )
        # Only useful if it is genuinely below entry. A range low at or above the
        # entry price would mean an instant stop out, so it is ignored.
        if 0 < low < entry_price:
            stop = max(percent_stop, low)

    stop = _round_cents(stop)
    if stop >= entry_price:
        # Only reachable with a sub cent entry price. Keep the promise that the
        # stop is below entry.
        stop = _round_cents(entry_price - 0.01)
    return stop


def available_cash(state: AccountState) -> float:
    """Rough spare cash: equity, less what is already in positions and unfilled orders."""
    invested = sum(
        abs(float(position.market_value)) for position in state.open_positions.values()
    )
    return max(0.0, float(state.equity) - invested - float(state.pending_order_notional))


def max_shares_for(
    g: Guardrails, state: AccountState, symbol: str, price: float
) -> int:
    """The biggest whole number of shares we may buy in one symbol right now.

    Three limits are applied and the smallest wins: the per symbol share of the
    account (max_position_pct, counting what we already hold and what is on
    order), the cap on a single order (max_order_notional), and the cash we have
    left. Returns 0 when there is no room.
    """
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        raise GuardrailUsageError(f"price has to be a number, but it is {price!r}.")
    price = float(price)
    if price <= 0 or not math.isfinite(price):
        raise GuardrailUsageError(
            f"price has to be more than zero, but it is {_plain_number(price)}."
        )

    clean_symbol = _clean_symbol(symbol, "symbol")
    position_cap = float(state.equity) * (g.money.max_position_pct / 100.0)
    position_room = (
        position_cap
        - state.held_market_value(clean_symbol)
        - float(state.pending_order_notional)
    )
    budget = min(position_room, float(g.money.max_order_notional), available_cash(state))
    if budget <= 0:
        return 0

    shares = (
        Decimal(repr(_round_cents(budget))) / Decimal(repr(price))
    ).to_integral_value(rounding=ROUND_FLOOR)
    return max(0, int(shares))


# ---------------------------------------------------------------------------
# The main check
# ---------------------------------------------------------------------------


def check_order(g: Guardrails, state: AccountState, intent: OrderIntent) -> Decision:
    """Decide whether one order may be placed, and collect every reason it may not.

    Nothing here shortcuts. Every rule runs, so the ledger shows all the limits
    an order broke rather than only the first one found.
    """
    decision = Decision(allowed=True)
    local_now = _eastern(g, state.now, "AccountState.now")
    when = f"{local_now.strftime('%H:%M')} on {local_now.strftime('%A')} New York time"

    _check_account(g, state, decision)
    _check_kill_switch(g, state, intent, decision)
    _check_instrument(g, intent, decision)
    _check_shorting(g, state, intent, decision)
    _check_clock(g, state, intent, decision, when)
    _check_daily_loss(g, state, intent, decision)
    _check_size(g, state, intent, decision)

    return decision


def _check_account(g: Guardrails, state: AccountState, decision: Decision) -> None:
    account_id = str(state.account_id).strip()

    if g.account.is_paper and not account_id.upper().startswith("DU"):
        decision.add(
            "paper_only",
            f"The settings say paper trading only, but this order would go to "
            f"account {account_id!r}, which does not start with DU. Every IBKR "
            "paper account id starts with DU, so this could be real money. "
            "Nothing was sent.",
        )

    if account_id != g.account.account_id:
        decision.add(
            "wrong_account",
            f"This order would go to account {account_id!r}, but the settings only "
            f"allow account {g.account.account_id!r}.",
        )


def _check_kill_switch(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    if not state.kill_switch_present:
        return
    if intent.purpose in KILL_SWITCH_ALLOWED_PURPOSES:
        return
    decision.add(
        "kill_switch",
        f"The stop file {g.kill_switch.file} exists, so the agent may only close "
        f"positions. This order is a {intent.purpose} order. Delete that file to "
        "let the agent trade again.",
    )


def _check_instrument(g: Guardrails, intent: OrderIntent, decision: Decision) -> None:
    allowed_types = ", ".join(g.universe.allowed_sec_types)

    if intent.sec_type not in g.universe.allowed_sec_types:
        plain = _SEC_TYPE_WORDS.get(intent.sec_type, f"a {intent.sec_type}")
        decision.add(
            "sec_type",
            f"This order is for {plain} ({intent.sec_type}) and the settings only "
            f"allow {allowed_types}.",
        )
    elif intent.sec_type in ("OPT", "FOP") and not g.universe.allow_options:
        decision.add(
            "sec_type",
            "This is an options order and universe.allow_options in the settings is "
            "false, so options are switched off.",
        )

    if intent.currency not in g.universe.allowed_currencies:
        decision.add(
            "currency",
            f"This order is priced in {intent.currency} and the settings only allow "
            f"{', '.join(g.universe.allowed_currencies)}.",
        )

    if intent.symbol in g.universe.blacklist:
        decision.add(
            "blacklist",
            f"{intent.symbol} is on the blacklist in the settings, so the agent may "
            "never trade it.",
        )

    if g.universe.whitelist and intent.symbol not in g.universe.whitelist:
        decision.add(
            "whitelist",
            f"The settings limit trading to {', '.join(g.universe.whitelist)}, and "
            f"{intent.symbol} is not on that list.",
        )


def _check_shorting(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    if g.universe.allow_shorts or intent.side != "SELL":
        return

    held = state.held_qty(intent.symbol)
    if held <= 0:
        decision.add(
            "no_shorts",
            f"This order would sell {intent.qty} shares of {intent.symbol} that we "
            "do not own, which is a short sale. Short selling is switched off in the "
            "settings.",
        )
    elif intent.qty > held:
        decision.add(
            "no_shorts",
            f"This order would sell {intent.qty} shares of {intent.symbol} but we "
            f"only hold {held}, so {intent.qty - held} of them would be a short "
            "sale. Short selling is switched off in the settings.",
        )


def _check_clock(
    g: Guardrails,
    state: AccountState,
    intent: OrderIntent,
    decision: Decision,
    when: str,
) -> None:
    if intent.purpose == "entry" and not entries_allowed_now(g, state.now):
        decision.add(
            "entry_window",
            f"New positions may only be opened between "
            f"{g.schedule.pick_time.strftime('%H:%M')} and "
            f"{g.schedule.entries_until.strftime('%H:%M')} New York time on a "
            f"weekday. It is {when}.",
        )

    if (
        g.schedule.trade_only_regular_hours
        and not intent.is_closing
        and not is_regular_hours(g, state.now)
    ):
        decision.add(
            "outside_market_hours",
            f"The market is only open {g.schedule.scan_start.strftime('%H:%M')} to "
            f"{g.schedule.market_close.strftime('%H:%M')} New York time on weekdays. "
            f"It is {when}, and this is not a closing order.",
        )

    if not intent.is_closing and _past_flatten_time(g, state.now):
        decision.add(
            "flatten_time",
            f"From {g.schedule.flatten_at.strftime('%H:%M')} New York time the agent "
            f"only closes positions. It is {when}, so this "
            f"{intent.purpose} order is too late.",
        )


def _check_daily_loss(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    if not daily_loss_hit(g, state):
        return

    # The flag describes the account, not this one order, so it is set either way.
    decision.daily_halt = True
    if intent.purpose != "entry":
        return

    allowed_loss = state.day_start_equity * (g.money.max_daily_loss_pct / 100.0)
    decision.add(
        "daily_loss_cap",
        f"The account is down {_money(abs(state.total_pnl_today))} today, which has "
        f"reached the daily limit of {_plain_number(g.money.max_daily_loss_pct)} "
        f"percent ({_money(allowed_loss)}) of the "
        f"{_money(state.day_start_equity)} it opened with. No new positions for the "
        "rest of the day. Closing orders are still allowed.",
    )


def _check_size(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """Size limits only apply to entries. An exit is never blocked for being big."""
    if intent.purpose != "entry":
        return

    notional = intent.notional
    if notional is None:
        decision.add(
            "max_order_notional",
            "This entry order has no limit price, so there is no way to work out "
            f"what it would cost or to check it against the "
            f"{_money(g.money.max_order_notional)} limit on a single order. Entries "
            "need a limit price.",
        )
    else:
        if notional > g.money.max_order_notional + CENT_TOLERANCE:
            decision.add(
                "max_order_notional",
                f"This order is worth {_money(notional)} ({intent.qty} shares at "
                f"{_money(intent.limit_price)}) and no single order may be worth "
                f"more than {_money(g.money.max_order_notional)}.",
            )

        held_value = state.held_market_value(intent.symbol)
        pending = float(state.pending_order_notional)
        would_hold = held_value + pending + notional
        position_cap = float(state.equity) * (g.money.max_position_pct / 100.0)
        if would_hold > position_cap + CENT_TOLERANCE:
            share_of_account = (
                (would_hold / float(state.equity) * 100.0) if state.equity else 0.0
            )
            decision.add(
                "max_position_pct",
                f"This order would put {_money(would_hold)} into {intent.symbol}: "
                f"{_money(held_value)} already held, {_money(pending)} on order and "
                f"{_money(notional)} from this order. That is "
                f"{share_of_account:.1f} percent of the {_money(state.equity)} "
                f"account, and the limit is "
                f"{_plain_number(g.money.max_position_pct)} percent "
                f"({_money(position_cap)}).",
            )

    already_held = state.held_qty(intent.symbol) != 0
    if not already_held:
        would_be_open = state.open_position_count() + 1
        if would_be_open > g.money.max_open_positions:
            decision.add(
                "max_open_positions",
                f"We already hold {state.open_position_count()} positions and the "
                f"limit is {g.money.max_open_positions}. {intent.symbol} would make "
                f"{would_be_open}.",
            )
