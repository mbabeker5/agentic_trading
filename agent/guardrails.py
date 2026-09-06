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

Since 2026-09-06 the same code also referees five virtual books that share one
IBKR paper account. config/books.yaml is the register of books. Each book names
a folder under strategies/ whose strategy.yaml holds that book's own numbers.
load_book_guardrails() lays the book's numbers over the shared ones in
config/guardrails.yaml and hands back the same Guardrails object every function
in here already takes, so the rest of the agent never has to learn a second
shape. A book's orders carry its book id, and an order tagged for the wrong book
is refused like any other broken limit.

Written 2026-09-02, extended for the five books on 2026-09-06. The numbers live
in the yaml files, not here.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
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
    "StrategyConfig",
    "SharedConfig",
    "BookConfig",
    "BookRegistry",
    "Guardrails",
    "PositionInfo",
    "AccountState",
    "OrderIntent",
    "Decision",
    "load_guardrails",
    "load_books",
    "load_book",
    "load_book_guardrails",
    "check_order",
    "daily_loss_hit",
    "entries_allowed_now",
    "must_flatten_now",
    "is_regular_hours",
    "stop_price_for",
    "trailing_stop_price",
    "time_stop_due",
    "trading_days_between",
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

# How much rope a book has. Only dry-run loads today: the book writes down the
# order it would have sent and stops there. Nothing else is allowed until Mo
# signs the strategy numbers off, and that approval is a change to this line.
BOOK_MODES_ALLOWED = ("dry-run",)

# Who makes the call inside a book. "hybrid" means a model picks the names
# inside the rules; "rules_only" means no model is called at all.
VALID_DISCRETION = ("hybrid", "rules_only")

# A strategy's numbers are provisional until Mo approves them. The word is kept
# in the file so nothing can quietly graduate itself.
VALID_STRATEGY_STATUS = ("provisional", "approved")

# A book id is short and loud so it reads well in the ledger: A, B, C and so on.
_BOOK_ID_PATTERN = re.compile(r"^[A-Z0-9_]{1,8}$")

# Every order carries this prefix plus the book id as its IBKR order reference,
# which is how fills in one shared paper account get attributed to one book.
ORDER_REF_PREFIX = "BOOK_"

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
    """How much money may be at risk, and where.

    gross_exposure_pct_max is the backstop: longs and shorts added together,
    ignoring which way they point, may never be worth more than this percentage
    of the book. 100 means the book never borrows to buy.
    """

    starting_equity: float
    max_position_pct: float
    max_open_positions: int
    max_daily_loss_pct: float
    max_order_notional: float
    gross_exposure_pct_max: float = 100.0


@dataclass(frozen=True)
class RiskConfig:
    """Where the stop loss goes, and when a position runs out of time.

    trailing_stop_pct and trailing_activation_pct are a pair: the trailing stop
    sits that percentage away from the best price the position has seen, and it
    only switches on once the position is up by the activation percentage. Both
    are None on a book that has no trailing rule, and then there is no trailing
    stop at all.

    time_stop_trading_days is how many trading days a position may live before
    it is closed whatever the price. None means no clock.
    """

    stop_loss_pct: float
    use_opening_range_low_if_tighter: bool
    trailing_stop_pct: float | None = None
    trailing_activation_pct: float | None = None
    time_stop_trading_days: int | None = None


@dataclass(frozen=True)
class UniverseConfig:
    """What the agent is allowed to trade at all.

    short_price_floor is a second, higher price floor that applies to shorts
    only, because cheap stocks are the expensive ones to be short of. None means
    the book never shorts, so no separate floor is needed.

    require_shortable says the broker has to have confirmed the name is
    borrowable before a short goes out. The loop reads that flag from IBKR and
    puts it on the order intent.
    """

    price_floor: float
    min_avg_volume: int
    allow_options: bool
    allow_shorts: bool
    allowed_sec_types: tuple[str, ...]
    allowed_currencies: tuple[str, ...]
    whitelist: tuple[str, ...]
    blacklist: tuple[str, ...]
    short_price_floor: float | None = None
    require_shortable: bool = False


@dataclass(frozen=True)
class ScannerConfig:
    """How the morning shortlist is built."""

    rel_volume_min: float
    max_candidates: int
    exclude_leveraged_etfs: bool


@dataclass(frozen=True)
class ScheduleConfig:
    """The clock. Every time here is in the timezone named below.

    entries_per_day_max is how many brand new names the book may open in one
    day. None means the only limit is max_open_positions.
    """

    timezone: str
    scan_start: time
    pick_time: time
    entries_until: time
    flatten_at: time
    market_close: time
    loop_minutes: int
    trade_only_regular_hours: bool
    entries_per_day_max: int | None = None


@dataclass(frozen=True)
class KillSwitchConfig:
    """The file that stops the agent opening anything new."""

    file: str


@dataclass(frozen=True)
class StrategyConfig:
    """What kind of book this is, as opposed to what its numbers are.

    status          provisional until Mo signs the numbers off
    name            the book's strategy in a few words
    spec            the document those numbers came from
    discretion      hybrid (a model picks inside the rules) or rules_only
    holds_overnight true when positions may live past the close
    flat_by_close   true when everything is sold at flatten_at every day
    """

    status: str
    name: str
    spec: str
    discretion: str
    holds_overnight: bool
    flat_by_close: bool


@dataclass(frozen=True)
class SharedConfig:
    """The things all five books have in common, from the top of books.yaml."""

    account_id: str
    gateway_port: int
    ledger_config_path: str
    timezone: str
    guardrails_path: str


@dataclass(frozen=True)
class BookConfig:
    """One virtual book: a strategy, a pot of money and a tag on its orders.

    model is None for a book that calls no model at all.
    """

    book_id: str
    name: str
    strategy_dir: str
    order_ref: str
    capital_usd: float
    model: str | None
    enabled: bool
    mode: str
    start_date: date
    end_date: date
    notes: str

    @property
    def uses_a_model(self) -> bool:
        return self.model is not None


@dataclass(frozen=True)
class BookRegistry:
    """Everything in config/books.yaml, checked and ready to use."""

    shared: SharedConfig
    books: tuple[BookConfig, ...]
    source_path: Path | None = None

    @property
    def book_ids(self) -> tuple[str, ...]:
        return tuple(book.book_id for book in self.books)

    def get(self, book_id: str) -> BookConfig:
        """One book by its id, or a message naming the ones that do exist."""
        wanted = str(book_id).strip().upper()
        for book in self.books:
            if book.book_id == wanted:
                return book
        raise GuardrailConfigError(
            f"There is no book {book_id!r} in {self.source_path}. The books in "
            f"that file are {', '.join(self.book_ids)}."
        )

    def enabled_books(self) -> tuple[BookConfig, ...]:
        return tuple(book for book in self.books if book.enabled)


@dataclass(frozen=True)
class Guardrails:
    """Every limit, loaded from one yaml file, or from a book's two.

    book and strategy are None for the shared settings in
    config/guardrails.yaml, and filled in when the limits were built for one
    book by load_book_guardrails().
    """

    account: AccountConfig
    money: MoneyConfig
    risk: RiskConfig
    universe: UniverseConfig
    scanner: ScannerConfig
    schedule: ScheduleConfig
    kill_switch: KillSwitchConfig
    source_path: Path | None = None
    strategy: StrategyConfig | None = None
    book: BookConfig | None = None
    sweep: dict | None = None
    strategy_path: Path | None = None

    @property
    def tz(self) -> ZoneInfo:
        """The timezone object for the schedule, always America/New_York in month one."""
        return ZoneInfo(self.schedule.timezone)

    @property
    def book_id(self) -> str | None:
        """Which book these limits belong to, or None for the shared settings."""
        return self.book.book_id if self.book is not None else None

    @property
    def order_ref(self) -> str | None:
        """The tag every order from this book carries, so fills can be told apart."""
        return self.book.order_ref if self.book is not None else None

    @property
    def flat_by_close(self) -> bool:
        """True when everything open is sold before the close every day.

        The shared settings, which have no strategy section, say true. That
        keeps the original day-trading behaviour for anything that has not been
        told it is a book.
        """
        return True if self.strategy is None else self.strategy.flat_by_close

    @property
    def holds_overnight(self) -> bool:
        return False if self.strategy is None else self.strategy.holds_overnight

    @property
    def discretion(self) -> str:
        return "hybrid" if self.strategy is None else self.strategy.discretion


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
    book_id                which virtual book this snapshot is of, or None
    gross_exposure         every position in the book added up, ignoring which
                           way it points. Left as None it is worked out from
                           open_positions instead.
    entries_opened_today   how many brand new names the book has opened today
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
    book_id: str | None = None
    gross_exposure: float | None = None
    entries_opened_today: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.now, datetime):
            raise GuardrailUsageError(
                "AccountState.now has to be a date and time, "
                f"but it is {type(self.now).__name__}."
            )
        _require_aware(self.now, "AccountState.now")
        if self.open_positions is None:
            self.open_positions = {}
        if self.book_id is not None:
            self.book_id = _clean_book_id(self.book_id, "AccountState.book_id")
        if isinstance(self.entries_opened_today, bool) or not isinstance(
            self.entries_opened_today, int
        ):
            raise GuardrailUsageError(
                "AccountState.entries_opened_today has to be a whole number of "
                f"positions, but it is {self.entries_opened_today!r}."
            )
        if self.entries_opened_today < 0:
            raise GuardrailUsageError(
                "AccountState.entries_opened_today cannot be negative, but it is "
                f"{self.entries_opened_today}."
            )

    @property
    def total_pnl_today(self) -> float:
        """Closed and open profit or loss added together."""
        return self.realized_pnl_today + self.unrealized_pnl

    def held_qty(self, symbol: str) -> int:
        """Shares we hold in one symbol, zero when we hold none."""
        position = self.open_positions.get(_clean_symbol(symbol, "symbol"))
        return int(position.qty) if position is not None else 0

    def held_market_value(self, symbol: str) -> float:
        """Dollar value of what we hold in one symbol, as the broker reports it.

        Zero when we hold none, and negative for a short position.
        """
        position = self.open_positions.get(_clean_symbol(symbol, "symbol"))
        return float(position.market_value) if position is not None else 0.0

    def held_exposure(self, symbol: str) -> float:
        """How much money is riding on one symbol, short or long, always positive.

        A short position shows up at the broker as a negative market value, and
        a limit that subtracted a negative number would quietly hand out more
        room rather than less, so the size checks use this instead.
        """
        return abs(self.held_market_value(symbol))

    def open_position_count(self) -> int:
        """How many symbols we actually hold. A zero quantity does not count."""
        return sum(1 for position in self.open_positions.values() if position.qty != 0)

    def position_direction(self, symbol: str) -> str:
        """Which way one holding points: long, short or flat.

        A short shows up at the broker as a negative number of shares, so that
        is the whole test.
        """
        held = self.held_qty(symbol)
        if held > 0:
            return "long"
        if held < 0:
            return "short"
        return "flat"

    def is_short(self, symbol: str) -> bool:
        return self.position_direction(symbol) == "short"

    def gross_exposure_now(self) -> float:
        """Every position added up, ignoring which way it points.

        A book long 30,000 dollars and short 20,000 has 50,000 of gross
        exposure, not 10,000, because both sides can lose money at once. The
        figure handed in on gross_exposure wins if it is there, because the loop
        knows which positions belong to which book and this snapshot may not.
        """
        if self.gross_exposure is not None:
            return abs(float(self.gross_exposure))
        return sum(
            abs(float(position.market_value))
            for position in self.open_positions.values()
        )


@dataclass
class OrderIntent:
    """One order the agent would like to place, before anyone checks it.

    book_id  which virtual book is sending it. None means the shared settings,
             the way the agent worked before there were books.
    shortable
             true when IBKR has said this name can actually be borrowed. The
             loop sets it from the broker's own flag; it is false until then,
             so a book that insists on it cannot short by accident.
    """

    symbol: str
    side: str
    qty: int
    limit_price: float | None = None
    sec_type: str = "STK"
    currency: str = "USD"
    purpose: str = "entry"
    book_id: str | None = None
    shortable: bool = False

    def __post_init__(self) -> None:
        self.symbol = _clean_symbol(self.symbol, "OrderIntent.symbol")
        if self.book_id is not None:
            self.book_id = _clean_book_id(self.book_id, "OrderIntent.book_id")
        if not isinstance(self.shortable, bool):
            raise GuardrailUsageError(
                "OrderIntent.shortable has to be true or false, but it is "
                f"{self.shortable!r}."
            )
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
    data = _read_settings_file(config_path)
    return _guardrails_from_mapping(data, str(config_path), source_path=config_path)


def _read_settings_file(config_path: Path) -> dict:
    """Read one yaml settings file and hand back its named sections."""
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
    return data


def _guardrails_from_mapping(
    data: dict,
    where: str,
    source_path: Path | None = None,
    book: BookConfig | None = None,
    strategy_path: Path | None = None,
) -> Guardrails:
    """Turn already read settings into a checked Guardrails object.

    load_guardrails() hands in one file. load_book_guardrails() hands in the
    shared file with a book's strategy.yaml laid over it, which is why this step
    is separate: the checking is identical either way.
    """
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

    strategy_raw = _optional_section(data, "strategy", where)
    strategy = _build_strategy(strategy_raw, where) if strategy_raw else None
    sweep = _optional_section(data, "sweep", where)

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
        source_path=source_path,
        strategy=strategy,
        book=book,
        sweep=dict(sweep) if sweep else None,
        strategy_path=strategy_path,
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
        gross_exposure_pct_max=_optional_percent(
            raw, "money.gross_exposure_pct_max", where, default=100.0
        ),
    )


def _build_risk(raw: dict, where: str) -> RiskConfig:
    trailing_stop_pct = _optional_percent(raw, "risk.trailing_stop_pct", where)
    trailing_activation_pct = _optional_percent(
        raw, "risk.trailing_activation_pct", where
    )
    if (trailing_stop_pct is None) != (trailing_activation_pct is None):
        raise GuardrailConfigError(
            f"The settings risk.trailing_stop_pct and risk.trailing_activation_pct "
            f"in {where} go together: either set both, or leave both empty for a "
            "book with no trailing stop. Right now only one of them has a number."
        )
    return RiskConfig(
        stop_loss_pct=_need_percent(raw, "risk.stop_loss_pct", where),
        use_opening_range_low_if_tighter=_need_bool(
            raw, "risk.use_opening_range_low_if_tighter", where
        ),
        trailing_stop_pct=trailing_stop_pct,
        trailing_activation_pct=trailing_activation_pct,
        time_stop_trading_days=_optional_positive_int(
            raw, "risk.time_stop_trading_days", where
        ),
    )


def _build_strategy(raw: dict, where: str) -> StrategyConfig:
    status = _need_text(raw, "strategy.status", where).lower()
    if status not in VALID_STRATEGY_STATUS:
        raise GuardrailConfigError(
            f"The setting strategy.status in {where} says {status!r}, and it has "
            f"to be one of {', '.join(VALID_STRATEGY_STATUS)}. Every strategy stays "
            "provisional until Mo approves its numbers."
        )
    discretion = _need_text(raw, "strategy.discretion", where).lower().replace("-", "_")
    if discretion not in VALID_DISCRETION:
        raise GuardrailConfigError(
            f"The setting strategy.discretion in {where} says {discretion!r}, and it "
            f"has to be one of {', '.join(VALID_DISCRETION)}. Use hybrid when a model "
            "picks the names inside the rules, rules_only when no model is called."
        )
    return StrategyConfig(
        status=status,
        name=_need_text(raw, "strategy.name", where),
        spec=_need_text(raw, "strategy.spec", where),
        discretion=discretion,
        holds_overnight=_need_bool(raw, "strategy.holds_overnight", where),
        flat_by_close=_need_bool(raw, "strategy.flat_by_close", where),
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
    price_floor = _need_number_at_least(raw, "universe.price_floor", where, 0.0)
    short_price_floor = _optional_number_at_least(
        raw, "universe.short_price_floor", where, 0.0
    )
    if short_price_floor is not None and short_price_floor < price_floor:
        raise GuardrailConfigError(
            f"The setting universe.short_price_floor in {where} is "
            f"{_plain_number(short_price_floor)}, which is below the ordinary "
            f"universe.price_floor of {_plain_number(price_floor)}. The floor for "
            "shorts is meant to be the higher of the two, because a cheap stock is "
            "the expensive one to be short of."
        )
    return UniverseConfig(
        price_floor=price_floor,
        min_avg_volume=_need_positive_int(raw, "universe.min_avg_volume", where),
        allow_options=_need_bool(raw, "universe.allow_options", where),
        allow_shorts=_need_bool(raw, "universe.allow_shorts", where),
        allowed_sec_types=allowed_sec_types,
        allowed_currencies=allowed_currencies,
        whitelist=_need_symbol_list(raw, "universe.whitelist", where),
        blacklist=_need_symbol_list(raw, "universe.blacklist", where),
        short_price_floor=short_price_floor,
        require_shortable=_optional_bool(
            raw, "universe.require_shortable", where, default=False
        ),
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
        entries_per_day_max=_optional_positive_int(
            raw, "schedule.entries_per_day_max", where
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
# The five books
# ---------------------------------------------------------------------------


def load_books(path: str | Path) -> BookRegistry:
    """Read config/books.yaml, the register of virtual books.

    Checks that every book has an id nobody else uses, an order reference that
    matches that id, a pot of money, a strategy folder and a run window whose
    end is not before its start. Refuses any mode other than dry-run, because
    nothing in this project is allowed to send a real order until Mo approves
    the strategy numbers.

    Raises GuardrailConfigError with a message naming the file and the fix.
    """
    books_path = Path(path).expanduser()
    data = _read_settings_file(books_path)
    where = str(books_path)

    shared_raw = _section(data, "shared", where)
    shared = SharedConfig(
        account_id=_need_text(shared_raw, "shared.account_id", where),
        gateway_port=_need_positive_int(shared_raw, "shared.gateway_port", where),
        ledger_config_path=_need_text(shared_raw, "shared.ledger_config", where),
        timezone=_need_text(shared_raw, "shared.timezone", where),
        guardrails_path=_need_text(shared_raw, "shared.guardrails", where),
    )
    try:
        ZoneInfo(shared.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GuardrailConfigError(
            f"The setting shared.timezone in {where} says {shared.timezone!r}, which "
            "is not a timezone this computer knows about. Use America/New_York."
        ) from exc

    raw_books = data.get("books")
    if not isinstance(raw_books, list) or not raw_books:
        raise GuardrailConfigError(
            f"The books section of {where} should be a list of books, each with a "
            f"book_id, and right now it is {type(raw_books).__name__}."
        )

    books: list[BookConfig] = []
    seen_ids: set[str] = set()
    seen_refs: set[str] = set()
    for number, raw_book in enumerate(raw_books, start=1):
        if not isinstance(raw_book, dict):
            raise GuardrailConfigError(
                f"Book number {number} in {where} should be a list of settings such "
                f"as book_id and capital_usd, but it is a {type(raw_book).__name__}."
            )
        book = _build_book(raw_book, where, number)
        if book.book_id in seen_ids:
            raise GuardrailConfigError(
                f"Two books in {where} both call themselves {book.book_id!r}. Every "
                "book needs its own id, because that is how fills are told apart."
            )
        if book.order_ref in seen_refs:
            raise GuardrailConfigError(
                f"Two books in {where} both use the order reference "
                f"{book.order_ref!r}. Every book needs its own, because IBKR reports "
                "fills by that tag and the ledger splits the books on it."
            )
        seen_ids.add(book.book_id)
        seen_refs.add(book.order_ref)
        books.append(book)

    return BookRegistry(
        shared=shared, books=tuple(books), source_path=books_path
    )


def _build_book(raw: dict, where: str, number: int) -> BookConfig:
    label = f"books[{number}]"
    raw_id = _need_text(raw, f"{label}.book_id", where)
    try:
        book_id = _clean_book_id(raw_id, f"{label}.book_id")
    except GuardrailUsageError as exc:
        raise GuardrailConfigError(f"In {where}: {exc}") from exc

    order_ref = _need_text(raw, f"{label}.order_ref", where)
    expected_ref = f"{ORDER_REF_PREFIX}{book_id}"
    if order_ref != expected_ref:
        raise GuardrailConfigError(
            f"The setting {label}.order_ref in {where} is {order_ref!r}, but book "
            f"{book_id} has to tag its orders {expected_ref!r}. The tag is the book "
            "id with the prefix on the front, and nothing else, so that a fill can "
            "always be traced back to one book."
        )

    mode = _need_text(raw, f"{label}.mode", where).lower()
    if mode not in BOOK_MODES_ALLOWED:
        raise GuardrailConfigError(
            f"The setting {label}.mode in {where} says {mode!r}, and the only mode "
            f"allowed today is {', '.join(BOOK_MODES_ALLOWED)}. Every strategy number "
            "in this project is still provisional, so a book may write down the order "
            "it would have sent and nothing more. Changing that is a decision for Mo, "
            "not an edit to this file."
        )

    start_date = _need_date(raw, f"{label}.start_date", where)
    end_date = _need_date(raw, f"{label}.end_date", where)
    if end_date < start_date:
        raise GuardrailConfigError(
            f"Book {book_id} in {where} ends on {end_date.isoformat()}, which is "
            f"before it starts on {start_date.isoformat()}."
        )

    return BookConfig(
        book_id=book_id,
        name=_need_text(raw, f"{label}.name", where),
        strategy_dir=_need_text(raw, f"{label}.strategy_dir", where),
        order_ref=order_ref,
        capital_usd=_need_positive_number(raw, f"{label}.capital_usd", where),
        model=_read_model(raw, f"{label}.model", where),
        enabled=_need_bool(raw, f"{label}.enabled", where),
        mode=mode,
        start_date=start_date,
        end_date=end_date,
        notes=_need_text(raw, f"{label}.notes", where),
    )


def _read_model(raw: dict, dotted_name: str, where: str) -> str | None:
    """The model id, or None for a book that calls no model at all.

    Both an empty setting and the word none mean no model, because yaml reads
    a bare none as the word rather than as nothing.
    """
    if _is_unset(raw, dotted_name):
        return None
    text = _need_text(raw, dotted_name, where)
    if text.lower() in ("none", "no", "off"):
        return None
    return text


def _need_date(raw: dict, dotted_name: str, where: str) -> date:
    value = _need(raw, dotted_name, where)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise GuardrailConfigError(
                f"The setting {dotted_name} in {where} is {value!r}, which is not a "
                "date this code can read. Write it as 2026-09-08."
            ) from exc
    raise GuardrailConfigError(
        f"The setting {dotted_name} in {where} should be a date written as "
        f"2026-09-08, but it is {value!r}."
    )


def load_book(books_yaml_path: str | Path, book_id: str) -> BookConfig:
    """One book's entry in the register, by its id."""
    return load_books(books_yaml_path).get(book_id)


def load_book_guardrails(books_yaml_path: str | Path, book_id: str) -> Guardrails:
    """The limits for one book: the shared settings with the book's laid over them.

    Three files go in. config/books.yaml says which account, which port and
    which strategy folder. config/guardrails.yaml holds the settings every book
    shares. The book's own strategies/<folder>/strategy.yaml wins wherever it
    names a setting, which is how the insider book gets an 8 percent stop while
    the momentum book keeps 1.5 percent.

    What comes back is an ordinary Guardrails object, so check_order,
    max_shares_for, stop_price_for and the rest work on a book exactly as they
    worked before books existed.
    """
    books_path = Path(books_yaml_path).expanduser()
    registry = load_books(books_path)
    book = registry.get(book_id)

    # Paths inside books.yaml are written from the project folder, the one that
    # holds config/ and strategies/.
    project_root = books_path.resolve().parent.parent
    shared_path = _resolve_under(project_root, registry.shared.guardrails_path)
    strategy_path = _resolve_under(project_root, book.strategy_dir) / "strategy.yaml"

    if not strategy_path.exists():
        raise GuardrailConfigError(
            f"Book {book.book_id} in {books_path} points at the strategy folder "
            f"{book.strategy_dir}, but there is no strategy.yaml in it. Expected "
            f"{strategy_path}."
        )

    shared_settings = _read_settings_file(shared_path)
    strategy_settings = _read_settings_file(strategy_path)
    merged = _merge_settings(shared_settings, strategy_settings)

    # The register has the last word on the things all five books share, so one
    # book cannot quietly point itself at a different account or a different port.
    merged["account"]["account_id"] = registry.shared.account_id
    merged["account"]["gateway_port_paper"] = registry.shared.gateway_port
    merged["schedule"]["timezone"] = registry.shared.timezone
    merged["money"]["starting_equity"] = book.capital_usd

    where = f"{shared_path} merged with {strategy_path}"
    return _guardrails_from_mapping(
        merged,
        where,
        source_path=shared_path,
        book=book,
        strategy_path=strategy_path,
    )


def _resolve_under(project_root: Path, relative_or_absolute: str) -> Path:
    path = Path(relative_or_absolute).expanduser()
    return path if path.is_absolute() else (project_root / path)


def _merge_settings(base: dict, overlay: dict) -> dict:
    """The base settings with the overlay's on top, one section at a time.

    Only the two levels the settings files actually use are merged: a section,
    then the settings in it. A section the overlay does not mention is inherited
    whole, which is why a strategy file only has to write down what it changes.
    """
    merged: dict = {
        name: (dict(value) if isinstance(value, dict) else value)
        for name, value in base.items()
    }
    for name, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(name), dict):
            merged[name] = {**merged[name], **value}
        else:
            merged[name] = value
    return merged


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


def _optional_section(data: dict, name: str, where: str) -> dict | None:
    """A section that a plain settings file is allowed not to have at all."""
    if name not in data or data[name] is None:
        return None
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


def _is_unset(raw: dict, dotted_name: str) -> bool:
    """True when a setting is absent, or written out but left empty."""
    key = dotted_name.split(".")[-1]
    return key not in raw or raw[key] is None


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


def _optional_percent(
    raw: dict, dotted_name: str, where: str, default: float | None = None
) -> float | None:
    """A percentage a book may leave out, for example a trailing stop it has none of."""
    if _is_unset(raw, dotted_name):
        return default
    return _need_percent(raw, dotted_name, where)


def _optional_positive_int(
    raw: dict, dotted_name: str, where: str, default: int | None = None
) -> int | None:
    if _is_unset(raw, dotted_name):
        return default
    return _need_positive_int(raw, dotted_name, where)


def _optional_number_at_least(
    raw: dict, dotted_name: str, where: str, floor: float, default: float | None = None
) -> float | None:
    if _is_unset(raw, dotted_name):
        return default
    return _need_number_at_least(raw, dotted_name, where, floor)


def _optional_bool(
    raw: dict, dotted_name: str, where: str, default: bool = False
) -> bool:
    if _is_unset(raw, dotted_name):
        return default
    return _need_bool(raw, dotted_name, where)


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


def _clean_book_id(book_id: str, label: str) -> str:
    """Book ids are short and upper case, so A and " a " mean the same book."""
    if not isinstance(book_id, str) or not book_id.strip():
        raise GuardrailUsageError(f"{label} has to be a book id such as A.")
    cleaned = book_id.strip().upper()
    if not _BOOK_ID_PATTERN.match(cleaned):
        raise GuardrailUsageError(
            f"{label} is {book_id!r}, which is not a book id. Use a short one such "
            "as A, B or C."
        )
    return cleaned


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

    A book whose strategy says flat_by_close is false is never flattened, so
    this is always false for it. The insider and Congress books hold for weeks;
    selling them every afternoon would be the opposite of the strategy. They are
    still barred from opening anything new after their entry window shuts, which
    is the entry_window and flatten_time rules in check_order, not this one.
    """
    local = _eastern(g, now)
    if not g.flat_by_close:
        return False
    if not _is_weekday(local):
        return False
    return g.schedule.flatten_at <= local.time() < g.schedule.market_close


def trading_days_between(opened_on: date, today: date) -> int:
    """How many trading days a position has been alive.

    Counts the weekdays after the day it was opened, up to and including today,
    so a position opened on Friday is one trading day old on Monday. Holidays
    are not known about here, exactly as they are not known about anywhere else
    in this file.
    """
    start = _as_plain_date(opened_on, "opened_on")
    end = _as_plain_date(today, "today")
    if end <= start:
        return 0
    days = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def time_stop_due(g: Guardrails, opened_on: date, today: date) -> bool:
    """True when a position has run out of time and should be closed.

    The insider book gives a position 30 trading days and the Congress book 60,
    whatever the price is doing, because the edge behind the trade goes stale.
    A book with no time stop in its settings always gets false.
    """
    limit = g.risk.time_stop_trading_days
    if limit is None:
        return False
    return trading_days_between(opened_on, today) >= limit


def _as_plain_date(value, label: str) -> date:
    """A calendar date.

    A full date and time is accepted and read in whatever timezone it carries,
    so hand in New York moments. One with no timezone is refused rather than
    guessed at, the same as everywhere else in this file.
    """
    if isinstance(value, datetime):
        _require_aware(value, label)
        return value.date()
    if isinstance(value, date):
        return value
    raise GuardrailUsageError(
        f"{label} has to be a date such as date(2026, 9, 8), but it is "
        f"{type(value).__name__}."
    )


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
    g: Guardrails,
    entry_price: float,
    opening_range_low: float | None,
    side: str = "BUY",
    opening_range_high: float | None = None,
) -> float:
    """Where the stop loss goes for a position opened at entry_price.

    For a long, bought with a BUY: start with the percentage stop from the
    settings, 1.5 percent below entry. If the low of the opening five minutes is
    nearer to entry than that, and the settings allow it, use the opening range
    low instead, because a nearer stop means a smaller loss when it is hit. The
    answer is always below the entry price.

    For a short, opened with a SELL, everything is the mirror image: the stop
    sits 1.5 percent above entry, or on the high of the opening five minutes if
    that is nearer, and the answer is always above the entry price. Pass the
    range high in opening_range_high; opening_range_low is ignored for a short.

    Either way the answer is rounded to whole cents.
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
    side = _clean_side(side, "side")

    if side == "SELL":
        return _short_stop_price(g, entry_price, opening_range_high)

    percent_stop = entry_price * (1.0 - g.risk.stop_loss_pct / 100.0)
    stop = percent_stop

    if opening_range_low is not None and g.risk.use_opening_range_low_if_tighter:
        low = _finite_number(opening_range_low, "opening_range_low")
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


def _short_stop_price(
    g: Guardrails, entry_price: float, opening_range_high: float | None
) -> float:
    """The mirror of the long stop: above the entry price, and the nearer wins."""
    percent_stop = entry_price * (1.0 + g.risk.stop_loss_pct / 100.0)
    stop = percent_stop

    if opening_range_high is not None and g.risk.use_opening_range_low_if_tighter:
        high = _finite_number(opening_range_high, "opening_range_high")
        # A range high at or below where we sold would stop us out instantly, so
        # it is ignored, exactly as a range low above entry is for a long.
        if high > entry_price:
            stop = min(percent_stop, high)

    stop = _round_cents(stop)
    if stop <= entry_price:
        stop = _round_cents(entry_price + 0.01)
    return stop


def trailing_stop_price(
    g: Guardrails,
    side: str,
    highest_close_since_entry_or_lowest_for_short: float,
    entry_price: float,
) -> float | None:
    """Where a trailing stop sits today, or None while it is not switched on yet.

    A trailing stop follows the position's best price rather than its entry
    price, so a winner keeps some of what it made. It does nothing until the
    position is up by risk.trailing_activation_pct, and from then on it sits
    risk.trailing_stop_pct away from the best price seen so far.

    For a long, hand in the highest close since entry. For a short, hand in the
    lowest, because down is the good direction. Books with no trailing rule in
    their settings always get None back.
    """
    trail = g.risk.trailing_stop_pct
    activation = g.risk.trailing_activation_pct
    if trail is None or activation is None:
        return None

    side = _clean_side(side, "side")
    best = _finite_number(
        highest_close_since_entry_or_lowest_for_short,
        "highest_close_since_entry_or_lowest_for_short",
    )
    entry = _finite_number(entry_price, "entry_price")
    if entry <= 0 or best <= 0:
        raise GuardrailUsageError(
            "entry_price and the best price since entry both have to be more than "
            f"zero, but they are {_plain_number(entry)} and {_plain_number(best)}."
        )

    if side == "BUY":
        gain_pct = (best / entry - 1.0) * 100.0
        if gain_pct + 1e-9 < activation:
            return None
        return _round_cents(best * (1.0 - trail / 100.0))

    gain_pct = (1.0 - best / entry) * 100.0
    if gain_pct + 1e-9 < activation:
        return None
    return _round_cents(best * (1.0 + trail / 100.0))


def _clean_side(side: str, label: str) -> str:
    cleaned = str(side).strip().upper()
    if cleaned not in VALID_SIDES:
        raise GuardrailUsageError(
            f"{label} has to be BUY for a long or SELL for a short, not {side!r}."
        )
    return cleaned


def _finite_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardrailUsageError(f"{label} has to be a number, but it is {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        raise GuardrailUsageError(f"{label} has to be a number, but it is {value!r}.")
    return number


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
        - state.held_exposure(clean_symbol)
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
    _check_book(g, state, intent, decision)
    _check_kill_switch(g, state, intent, decision)
    _check_instrument(g, intent, decision)
    _check_shorting(g, state, intent, decision)
    _check_short_discipline(g, state, intent, decision)
    _check_clock(g, state, intent, decision, when)
    _check_daily_loss(g, state, intent, decision)
    _check_size(g, state, intent, decision)
    _check_gross_exposure(g, state, intent, decision)
    _check_entries_per_day(g, state, intent, decision)

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


def _book_words(book_id: str | None) -> str:
    """How a book is named when the message is about which book an order is for."""
    if book_id is None:
        return "the shared settings, which belong to no book"
    return f"book {book_id}"


def _pot_words(book_id: str | None) -> str:
    """How a book is named when the message is about its money."""
    return "the account" if book_id is None else f"book {book_id}"


def _check_book(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """Five books share one paper account, so every order has to say which it is.

    This one blocks a closing order as well as an entry, which nothing else in
    here does. An exit tagged for the wrong book would sell a position that
    belongs to a different strategy, and that is worse than a missed exit.
    """
    expected = g.book_id
    if intent.book_id != expected:
        decision.add(
            "wrong_book",
            f"This order is tagged for {_book_words(intent.book_id)}, but these "
            f"limits belong to {_book_words(expected)}. Five books share one paper "
            "account, so an order carrying the wrong book would spend the wrong "
            "money and land in the wrong row of the ledger.",
        )
    elif state.book_id is not None and state.book_id != expected:
        decision.add(
            "wrong_book",
            f"This account snapshot was taken for {_book_words(state.book_id)}, but "
            f"these limits belong to {_book_words(expected)}. Checking one book's "
            "order against another book's positions would give the wrong answer.",
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


def _opens_or_increases_short(state: AccountState, intent: OrderIntent) -> bool:
    """True when this sell order would leave us owing shares we do not own.

    Selling 100 of a 100 share holding is an exit. Selling 150 of it leaves 50
    borrowed, and so does any sell at all when the holding is already short or
    empty.
    """
    if intent.side != "SELL":
        return False
    held = state.held_qty(intent.symbol)
    return intent.qty > max(0, held)


def _check_short_discipline(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """The two extra hurdles a short has to clear on the way out of the door.

    Only new shorts are checked. Buying a short back is a closing order and is
    never blocked by anything in here.
    """
    if intent.purpose != "entry" or not _opens_or_increases_short(state, intent):
        return

    floor = g.universe.short_price_floor
    price = intent.limit_price
    if floor is not None and price is not None and price < floor - CENT_TOLERANCE:
        decision.add(
            "short_price_floor",
            f"This order would short {intent.symbol} at {_money(price)}, and this "
            f"book only shorts shares priced at {_money(floor)} or more. Cheap "
            "shares are the expensive ones to be short of: they are harder to "
            "borrow and they can double in a morning.",
        )

    if g.universe.require_shortable and not intent.shortable:
        decision.add(
            "shortable_required",
            f"This order would short {intent.symbol}, and the broker has not "
            "confirmed the shares can be borrowed. This book only shorts names IBKR "
            "reports as shortable, so nothing was sent.",
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

        held_value = state.held_exposure(intent.symbol)
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


def _check_gross_exposure(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """Longs and shorts added together may not outgrow the book.

    Both sides can lose money on the same morning, so they add up rather than
    cancelling out. At 100 percent the book never borrows to buy. With five
    positions capped at 15 percent each the natural ceiling is 75 percent, so
    this is the backstop behind the per position limit rather than the thing
    that usually bites.
    """
    if intent.purpose != "entry":
        return
    notional = intent.notional
    if notional is None:
        # Already refused by max_order_notional, and there is nothing to add up.
        return

    equity = float(state.equity)
    if equity <= 0:
        # The daily loss cap owns the case of a book with nothing left in it.
        return

    cap = equity * (g.money.gross_exposure_pct_max / 100.0)
    held = state.gross_exposure_now()
    pending = float(state.pending_order_notional)
    would_be = held + pending + notional
    if would_be <= cap + CENT_TOLERANCE:
        return

    share = would_be / equity * 100.0
    decision.add(
        "gross_exposure_cap",
        f"This order would put {_money(would_be)} to work in "
        f"{_pot_words(g.book_id)}: {_money(held)} already in positions, "
        f"{_money(pending)} on order and {_money(notional)} from this order. Longs "
        f"and shorts count the same way, so that is {share:.1f} percent of the "
        f"{_money(equity)} the book is worth, and the limit is "
        f"{_plain_number(g.money.gross_exposure_pct_max)} percent ({_money(cap)}).",
    )


def _check_entries_per_day(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """How many brand new names a book may open in one day.

    Adding to something the book already holds does not count, because that is
    the same idea getting bigger rather than a new one.
    """
    if intent.purpose != "entry":
        return
    limit = g.schedule.entries_per_day_max
    if limit is None:
        return
    if state.held_qty(intent.symbol) != 0:
        return
    opened = int(state.entries_opened_today)
    if opened < limit:
        return

    decision.add(
        "entries_per_day",
        f"This order would open a new position in {_pot_words(g.book_id)}, which "
        f"has already opened {opened} new positions today, and the limit is {limit} "
        f"a day. {intent.symbol} waits for tomorrow. Adding to something already "
        "held is still allowed, and so is getting out of anything.",
    )
