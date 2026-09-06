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

Also on 2026-09-06, three of Mo's decisions landed here. The liquidity floor
became 20 million dollars of average daily trading rather than a million shares,
which is a scanner filter rather than an order check but lives in the same
settings file. The easy to borrow rule grew from one yes or no flag into three
tests a short has to pass: IBKR's own borrowing level, what the borrow costs and
how many shares are available. And a book's mode became one of dry_run, tiny or
full, so a book can be promoted from writing orders down to actually sending
them, by hand, one book at a time.

Two things live next door rather than here. The rolling day trade count is in
agent/pdt.py, and the daily check that the books and the broker agree is in
agent/reconcile.py. Both are the same shape as this file: pure logic, no
network, plain English when they say no.

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
    "PdtConfig",
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
    "easy_to_borrow",
    "entries_allowed_now",
    "must_flatten_now",
    "is_regular_hours",
    "stop_price_for",
    "atr_stop_distance",
    "shares_for_risk",
    "weekly_loss_hit",
    "monthly_loss_hit",
    "losing_streak_hit",
    "must_flatten_at_market_now",
    "next_tick_seconds",
    "trailing_stop_price",
    "time_stop_due",
    "trading_days_between",
    "max_shares_for",
    "BOOK_MODES_ALLOWED",
    "BOOK_MODES_THAT_SEND_ORDERS",
    "HALT_ALLOWED_PURPOSES",
    "SYMBOL_TIE_BREAK",
    "DEFAULT_TINY_CAPITAL_USD",
    "DEFAULT_MIN_AVG_DOLLAR_VOLUME",
    "DEFAULT_DOLLAR_VOLUME_SESSIONS",
    "EASY_TO_BORROW_LEVEL_MIN",
    "DEFAULT_MAX_BORROW_FEE_PCT",
    "DEFAULT_BORROW_AVAILABILITY_MULTIPLE",
    "DEFAULT_MAX_DAY_TRADES_PER_5_DAYS",
    "DEFAULT_ASSUMED_LIVE_EQUITY_MIN_USD",
    "DEFAULT_ATR_DAYS",
    "DEFAULT_MIN_HISTORY_SESSIONS",
    "DEFAULT_RANK_BY",
    "DEFAULT_REL_VOLUME_WINDOW",
    "DEFAULT_REL_VOLUME_BASELINE_DAYS",
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

# What a halted or limit-state name still lets through. A trading halt is the
# same shape of problem as the kill switch, so it gets the same answer: the
# agent may still get itself out, but it may not park a fresh stop order in a
# name whose next printed price nobody knows. Added 2026-09-06 at the review
# team's request.
HALT_ALLOWED_PURPOSES = ("exit", "flatten")

# How a tie is settled when two books want the same symbol on the same tick.
# First come, first served: whoever registered the symbol first keeps it, and a
# same-tick tie goes to whichever book comes first in config/books.yaml.
#
# That resolution belongs to the trading loop, which is the only thing that sees
# all five books at once. This module only ever sees one book's order plus the
# map of what the other books already have, so the constant is here to name the
# rule and to give the loop one stable string to point at. Nothing in this file
# implements it.
SYMBOL_TIE_BREAK = "first_come_first_served"

VALID_PURPOSES = ("entry", "exit", "stop", "flatten")
VALID_SIDES = ("BUY", "SELL")

# How much rope a book has. Three settings, in order of how much can go wrong:
#
#   dry_run  the book works out the order it would have sent, writes it down,
#            and stops there. Nothing reaches the broker. Sizing still uses the
#            book's full capital, so a dry run is a full size rehearsal.
#   tiny     real orders in the paper account, but the book is only allowed to
#            risk money.tiny_capital_usd (2,000 dollars), so a bug is cheap.
#   full     real orders in the paper account against the book's full capital.
#
# Every book is on dry_run today (2026-09-06). Moving one up is a hand edit to
# config/books.yaml by Mo, never something the code does for itself, and a book
# above dry_run has to carry the date it was promoted and the git hash of the
# rules it was promoted against.
BOOK_MODES_ALLOWED = ("dry_run", "tiny", "full")

# The modes in which a book actually sends orders to the broker.
BOOK_MODES_THAT_SEND_ORDERS = ("tiny", "full")

# What a book in tiny mode is allowed to put at risk, when nothing says otherwise.
DEFAULT_TINY_CAPITAL_USD = 2000.0

# The liquidity floor Mo settled on 2026-09-06: a name has to trade at least
# 20 million dollars a day on average, over 30 completed sessions, before the
# momentum scanner will look at it. It replaced a floor of a million shares a
# day, which meant wildly different amounts of money at 6 dollars and at 600.
DEFAULT_MIN_AVG_DOLLAR_VOLUME = 20_000_000.0
DEFAULT_DOLLAR_VOLUME_SESSIONS = 30

# The easy to borrow rule, also Mo's decision of 2026-09-06. IBKR reports how
# borrowable a name is on a scale of 0 to 3, and anything above 2.5 is what the
# broker calls easy to borrow. A short only goes out when the level says easy to
# borrow, the borrow costs less than 1 percent a year, and there are at least 10
# times as many shares available to borrow as we mean to sell.
EASY_TO_BORROW_LEVEL_MIN = 2.5
IBKR_SHORTABLE_LEVEL_MAX = 3.0
DEFAULT_MAX_BORROW_FEE_PCT = 1.0
DEFAULT_BORROW_AVAILABILITY_MULTIPLE = 10.0

# How many day trades a book held to the pattern day trader rule may make in
# five business days, and the live account balance that rule assumes.
DEFAULT_MAX_DAY_TRADES_PER_5_DAYS = 3
DEFAULT_ASSUMED_LIVE_EQUITY_MIN_USD = 25_000.0

# MOMENTUM V2, approved by Mo on 2026-09-06 from the consolidated critique in
# research/momentum_spec_critique_2026-09-06.md. These are the defaults behind
# the new settings; the real numbers live in the yaml files as always.
#
# The average true range is the average size of one session's price swing over
# the last 14 sessions, counting the gap from the previous close. Fourteen
# sessions is the number the published work used and is long enough to settle
# down without going stale.
DEFAULT_ATR_DAYS = 14

# How much history a name needs before it may be traded at all. Mo considered
# and REJECTED a rule barring anything listed in the last 90 days. This does the
# same job honestly: what matters is having enough sessions to measure the
# liquidity floor and the average true range, and a name without them fails
# those tests anyway.
DEFAULT_MIN_HISTORY_SESSIONS = 30

# How the shortlist is ordered, and what the relative volume behind that order
# is measured on. The ranking by volume, rather than by the size of the gap, is
# what carried the published result.
DEFAULT_RANK_BY = "rel_volume"
DEFAULT_REL_VOLUME_WINDOW = "09:30-09:35"
DEFAULT_REL_VOLUME_BASELINE_DAYS = 14

# The orders a book may still send once one of the limits beyond the day has
# paused it. The same answer as the kill switch: get out, never in.
PAUSED_BOOK_ALLOWED_PURPOSES = ("exit", "stop", "flatten")

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

    tiny_capital_usd is what a book in tiny mode is allowed to put at risk. It
    does nothing while a book is on dry_run or full; it is written down here so
    the number lives with the other money numbers rather than in the code.

    Momentum v2, approved by Mo on 2026-09-06, added the rest:

    risk_per_trade_pct     how much of the book one trade may lose, as a
                           percentage. The share count comes from this divided
                           by the distance from entry to the stop, so every
                           position risks about the same. None on a book that
                           still sizes on max_position_pct alone, which is the
                           insider and Congress books.
    max_weekly_loss_pct    the loss limits beyond the day. Any one of these
    max_monthly_loss_pct   three pauses the book for Mo to look at it, and none
    max_consecutive_losing_days
                           of them ever blocks a closing order. None means the
                           rule is off.
    sector_gross_pct_max   how much of the book's gross exposure limit may sit
                           in one industry. None means off, which is what the
                           shared settings say, because it is a momentum rule.
    account_symbol_pct_max how much of the money all five books hold between
                           them may sit in one ticker. None means off.
    """

    starting_equity: float
    max_position_pct: float
    max_open_positions: int
    max_daily_loss_pct: float
    max_order_notional: float
    gross_exposure_pct_max: float = 100.0
    tiny_capital_usd: float = DEFAULT_TINY_CAPITAL_USD
    risk_per_trade_pct: float | None = None
    max_weekly_loss_pct: float | None = None
    max_monthly_loss_pct: float | None = None
    max_consecutive_losing_days: int | None = None
    sector_gross_pct_max: float | None = None
    account_symbol_pct_max: float | None = None


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

    Momentum v2, approved by Mo on 2026-09-06, added the volatility stop:

    atr_days       how many completed sessions the average true range covers.
                   The average true range is the average size of one session's
                   price swing, counting the gap from the previous close.
    stop_atr_pct   the stop distance, as a percentage of that average. At 10,
                   a stock whose average swing is 2 dollars stops 20 cents away.
                   None means the book has no volatility stop and falls back to
                   stop_loss_pct, which is what the insider and Congress books
                   do.
    stop_outside_opening_range
                   true when the stop may never sit inside the first five
                   minutes' range. A stop inside the range is inside the noise
                   the trade is made of, so it would be hit by the setup itself.
    use_profit_target
                   false on the momentum books, which now leave by the stop or
                   at the close and nothing else. Two independent studies found
                   a target destroys this strategy's edge.
    """

    stop_loss_pct: float
    use_opening_range_low_if_tighter: bool
    trailing_stop_pct: float | None = None
    trailing_activation_pct: float | None = None
    time_stop_trading_days: int | None = None
    atr_days: int = 14
    stop_atr_pct: float | None = None
    stop_outside_opening_range: bool = False
    use_profit_target: bool = True


@dataclass(frozen=True)
class UniverseConfig:
    """What the agent is allowed to trade at all.

    min_avg_dollar_volume is the liquidity floor Mo settled on 2026-09-06: a
    name has to trade at least this many dollars a day on average, over
    dollar_volume_sessions completed sessions, before the scanner will look at
    it. Dollars rather than shares, because 20 million dollars means the same
    thing whether the share price is 6 dollars or 600.

    min_avg_volume is the old share count floor it replaced. It is kept because
    the insider and Congress sweeps still quote a share figure in the words they
    hand the model, and because an old settings file should still load. The
    scanner no longer looks at it.

    short_price_floor is a second, higher price floor that applies to shorts
    only, because cheap stocks are the expensive ones to be short of. None means
    the book never shorts, so no separate floor is needed.

    require_shortable switches on the easy to borrow rule: before a short goes
    out, IBKR has to say the name is easy to borrow, the borrow has to cost less
    than max_borrow_fee_pct a year, and there have to be at least
    borrow_availability_multiple times as many shares available to borrow as we
    intend to sell. The loop reads all three numbers from the broker and puts
    them on the order intent.

    Momentum v2, approved by Mo on 2026-09-06, added the volatility filter and
    the hard exclusions. min_atr_usd and min_atr_pct_of_price both have to hold:
    fifty cents is a big daily swing on a 6 dollar stock and nothing at all on a
    600 dollar one. min_history_sessions is how much history a name needs before
    it may be traded at all, and it is what Mo chose INSTEAD of a rule barring
    anything listed in the last 90 days, because what actually matters is having
    enough sessions to measure the liquidity floor and the average true range.
    The five exclude flags are the promoter and binary-event traps: blank cheque
    companies, warrants, rights, preferred shares, anything traded over the
    counter or listed abroad, and anything halted right now. The scanner applies
    them; they are written here so a book's whole universe reads in one place.
    """

    price_floor: float
    allow_options: bool
    allow_shorts: bool
    allowed_sec_types: tuple[str, ...]
    allowed_currencies: tuple[str, ...]
    whitelist: tuple[str, ...]
    blacklist: tuple[str, ...]
    min_avg_dollar_volume: float = DEFAULT_MIN_AVG_DOLLAR_VOLUME
    dollar_volume_sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS
    min_avg_volume: int | None = None
    short_price_floor: float | None = None
    require_shortable: bool = False
    max_borrow_fee_pct: float = DEFAULT_MAX_BORROW_FEE_PCT
    borrow_availability_multiple: float = DEFAULT_BORROW_AVAILABILITY_MULTIPLE
    atr_days: int = DEFAULT_ATR_DAYS
    min_atr_usd: float | None = None
    min_atr_pct_of_price: float | None = None
    min_history_sessions: int = DEFAULT_MIN_HISTORY_SESSIONS
    exclude_spacs: bool = True
    exclude_warrants_and_rights: bool = True
    exclude_preferred: bool = True
    require_us_primary_listing: bool = True
    exclude_halted: bool = True


@dataclass(frozen=True)
class ScannerConfig:
    """How the morning shortlist is built.

    Momentum v2, approved by Mo on 2026-09-06, changed how the shortlist is
    ordered. rank_by is "rel_volume": the names are sorted by relative volume,
    highest first, and the top max_candidates are taken. It used to be sorted by
    the size of the gap multiplied by the volume, and the published result came
    from the volume ranking rather than the size of the move.

    rel_volume_window and rel_volume_baseline_days say what that relative volume
    is: the volume in the first five minutes, against the same five minutes on
    each of the previous 14 sessions. Both are carried here for the record and
    for agent/preopen.py, which pulls that history before the open.

    There is no Finviz setting any more. Mo decided not to buy Finviz Elite, so
    on 2026-09-06 the flag and its whole code path were deleted rather than left
    switched off (item D7).
    """

    rel_volume_min: float
    max_candidates: int
    exclude_leveraged_etfs: bool
    rank_by: str = DEFAULT_RANK_BY
    rel_volume_window: str = DEFAULT_REL_VOLUME_WINDOW
    rel_volume_baseline_days: int = DEFAULT_REL_VOLUME_BASELINE_DAYS


@dataclass(frozen=True)
class ScheduleConfig:
    """The clock. Every time here is in the timezone named below.

    entries_per_day_max is how many brand new names the book may open in one
    day. None means the only limit is max_open_positions.

    holidays is the list of days the US market is shut that are not weekends.
    It is empty in the shipped settings, and it is used by the day trade counter
    in agent/pdt.py to work out what a business day is. Nothing else in this
    file has ever known about holidays, and that has not changed.

    Momentum v2, approved by Mo on 2026-09-06, split the close in two and made
    the cadence data driven:

    flatten_at         when flattening BEGINS, with limit orders at the bid or
                       the ask, because spreads widen and depth collapses in the
                       last few minutes.
    flatten_market_at  the backstop. Anything still open at this time goes out
                       at market, because being flat matters more than the last
                       few cents. None on a book with no backstop, and then
                       flatten_at behaves exactly as it always did.
    fast_poll_seconds  how often a book looks at itself between fast_poll_from
    fast_poll_from     and fast_poll_until while it is holding something. Thirty
    fast_poll_until    seconds in the momentum books, because a stop this tight
                       needs sub-minute resolution even with the stop resting at
                       the broker. None means the book only ever uses
                       loop_minutes.
    preopen_start      when the pre-open run starts, and the two deadlines
    preopen_history_done_by
    preopen_subscribe_done_by
                       inside it. See docs/PREOPEN_FLOW.md.
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
    holidays: tuple[date, ...] = ()
    flatten_market_at: time | None = None
    fast_poll_seconds: int | None = None
    fast_poll_from: time | None = None
    fast_poll_until: time | None = None
    preopen_start: time | None = None
    preopen_history_done_by: time | None = None
    preopen_subscribe_done_by: time | None = None


@dataclass(frozen=True)
class KillSwitchConfig:
    """The file that stops the agent opening anything new."""

    file: str


@dataclass(frozen=True)
class PdtConfig:
    """The pattern day trader rule, as this project chooses to apply it.

    US regulators call anyone who makes four or more round trip day trades in
    five business days, in a margin account, a pattern day trader, and require
    that account to hold at least 25,000 dollars. The IBKR paper account is
    exempt because the money is simulated, so the code counts day trades itself
    and month one measures the cost of the rule rather than guessing at it.

    hard_limit                 true in the insider and Congress books, where a
                               day trade is a mistake, and false in the momentum
                               books, where day trading is the whole strategy.
                               A book with it false is never blocked; the loop
                               is told what would have been blocked instead.
    max_day_trades_per_5_days  three, so the fourth is the one that trips.
    assumed_live_equity_min_usd
                               25,000 dollars, the balance the rule assumes a
                               live account would have to keep. Nothing enforces
                               it on paper; it is written down so month one's
                               numbers can be read against it.

    The counting itself lives in agent/pdt.py, not here.
    """

    hard_limit: bool = False
    max_day_trades_per_5_days: int = DEFAULT_MAX_DAY_TRADES_PER_5_DAYS
    assumed_live_equity_min_usd: float = DEFAULT_ASSUMED_LIVE_EQUITY_MIN_USD


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
    tiny_capital_usd: float = DEFAULT_TINY_CAPITAL_USD


@dataclass(frozen=True)
class BookConfig:
    """One virtual book: a strategy, a pot of money and a tag on its orders.

    model is None for a book that calls no model at all.

    mode is one of dry_run, tiny or full. See BOOK_MODES_ALLOWED at the top of
    this file for what each one means.

    promoted_on and rules_commit are the paper trail behind a promotion. They
    are empty while a book is on dry_run, and they are filled in by hand on the
    day the hub approves the book: the date it was promoted, and the git hash of
    the rules it was promoted against. A book above dry_run without both of them
    refuses to load, so a book can never quietly start sending orders.
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
    tiny_capital_usd: float = DEFAULT_TINY_CAPITAL_USD
    promoted_on: date | None = None
    rules_commit: str | None = None

    @property
    def uses_a_model(self) -> bool:
        return self.model is not None

    @property
    def sends_orders(self) -> bool:
        """True when this book's orders actually reach the broker.

        False on dry_run, which is where all five books sit today.
        """
        return self.mode in BOOK_MODES_THAT_SEND_ORDERS

    def effective_capital(self) -> float:
        """How much money this book is actually working with today.

        On tiny that is the small pot, 2,000 dollars, so a bug is cheap while
        the machinery is being watched. On dry_run and on full it is the book's
        whole capital. dry_run uses the full number on purpose: a rehearsal that
        sizes its orders differently from the real thing is not a rehearsal.
        """
        if self.mode == "tiny":
            return float(self.tiny_capital_usd)
        return float(self.capital_usd)


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
    pdt: PdtConfig = field(default_factory=PdtConfig)
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
    symbols_held_elsewhere which symbols the other books have already taken,
                           written as {symbol: the book id that has it}. The
                           loop fills it by reading every book's state, because
                           only the loop sees all five books at once. Empty
                           means nothing is taken and the symbol_exclusive rule
                           has nothing to say.

    Momentum v2, approved by Mo on 2026-09-06, added six more. All six default
    to a value that means "nothing to see", so a caller written before them
    behaves exactly as it did:

    week_pnl               money made or lost this calendar week, closed and
    month_pnl              open together, and this calendar month. The loop
                           works both out by reading the book's earlier state
                           files, because only the loop can see them.
    consecutive_losing_days
                           how many trading days in a row this book has finished
                           down. Three in a row pauses it.
    sector_exposure        how much money this book has in each industry, as
                           {industry: dollars}. The loop fills it from IBKR's
                           contract details.
    account_equity         what all five books are worth added together. Used by
                           the account level per symbol cap. None means the loop
                           did not say, and then this book's own equity stands
                           in, which is the smaller and therefore safer number.
    symbol_exposure_all_books
                           how much money every book has in each ticker added
                           together, as {symbol: dollars}.
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
    symbols_held_elsewhere: dict[str, str] | None = None
    week_pnl: float = 0.0
    month_pnl: float = 0.0
    consecutive_losing_days: int = 0
    sector_exposure: dict[str, float] | None = None
    account_equity: float | None = None
    symbol_exposure_all_books: dict[str, float] | None = None

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
        self.symbols_held_elsewhere = _clean_symbol_owners(
            self.symbols_held_elsewhere
        )
        self.week_pnl = _finite_number(self.week_pnl, "AccountState.week_pnl")
        self.month_pnl = _finite_number(self.month_pnl, "AccountState.month_pnl")
        if isinstance(self.consecutive_losing_days, bool) or not isinstance(
            self.consecutive_losing_days, int
        ):
            raise GuardrailUsageError(
                "AccountState.consecutive_losing_days has to be a whole number of "
                f"days, but it is {self.consecutive_losing_days!r}."
            )
        if self.consecutive_losing_days < 0:
            raise GuardrailUsageError(
                "AccountState.consecutive_losing_days cannot be negative, but it is "
                f"{self.consecutive_losing_days}."
            )
        self.sector_exposure = _clean_money_map(
            self.sector_exposure, "AccountState.sector_exposure", upper=False
        )
        self.symbol_exposure_all_books = _clean_money_map(
            self.symbol_exposure_all_books,
            "AccountState.symbol_exposure_all_books",
            upper=True,
        )
        if self.account_equity is not None:
            self.account_equity = _finite_number(
                self.account_equity, "AccountState.account_equity"
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

    def sector_exposure_now(self, sector: str | None) -> float:
        """How much money this book already has in one industry, always positive."""
        if not sector:
            return 0.0
        return abs(float((self.sector_exposure or {}).get(str(sector).strip(), 0.0)))

    def symbol_exposure_everywhere(self, symbol: str) -> float:
        """How much every book has in one ticker added together, always positive.

        Falls back to what this book alone holds when the loop did not hand in
        the account wide map, because one book's holding is at least a floor
        under the true figure.
        """
        clean = _clean_symbol(symbol, "symbol")
        everywhere = self.symbol_exposure_all_books or {}
        if clean in everywhere:
            return abs(float(everywhere[clean]))
        return self.held_exposure(clean)

    def symbol_owner(self, symbol: str) -> str | None:
        """Which other book already has this symbol, or None when nobody has.

        "Has" covers both a position and a working entry order, because a book
        with an order sitting at the broker is as committed to the name as a
        book already holding it.
        """
        return self.symbols_held_elsewhere.get(_clean_symbol(symbol, "symbol"))

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

    The last four are what the broker says about borrowing this name, and they
    only matter to a short. The loop reads them from IBKR just before the order
    goes out and puts them here:

    shortable
             true when IBKR has said this name can be borrowed at all. It is
             false until the loop sets it, so a book that insists on a borrow
             cannot short by accident. It is the fallback when the newer
             shortable_level is not there.
    shortable_level
             IBKR's shortable indicator, on its own scale of 0 to 3. Anything
             above 2.5 is what the broker calls easy to borrow. None means the
             broker did not report one, and then the shortable flag above
             decides instead.
    borrow_fee_pct_annual
             what the borrow costs, as a percentage a year. 0.3 means three
             tenths of a percent. None means the broker did not report it, and
             an unknown borrow cost is treated as a refusal, because the shorts
             that cost 300 percent a year are exactly the ones nobody quoted.
    shares_available_to_borrow
             how many shares the broker says are available to borrow right now.
             None is treated the same way, as a refusal.

    The last two say whether the name is tradeable at all right now. The loop
    fills them from IBKR just before the order goes out, and it passes on what
    the broker actually said, unknowns included:

    halted   true when IBKR's halted tick, tick type 49, says this name is not
             trading. None means the loop asked and got no answer, and an
             unknown halt status stops an entry rather than being read as fine.
    limit_state
             true when the name is sitting in a limit-up limit-down band, which
             is the state a stock enters just before it is halted for
             volatility. None means unknown, and is treated the same way as an
             unknown halt.

    Both start as false rather than None, which is the one place this file lets
    a missing answer mean a clean one. It is a compatibility default, not a
    judgement: every check written before halts were tracked at all goes on
    behaving as it did. The loop must always pass what IBKR said, and must pass
    None when IBKR said nothing, because None is what the rule refuses on.

    sector is the industry IBKR's contract details give for this name, and it is
    what the sector cap counts against (Momentum v2, item A9, Mo 2026-09-06).
    None means the broker did not say, and on a book that has a sector cap an
    unknown industry stops an entry rather than being counted as harmless, for
    exactly the same reason an unknown halt status does.
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
    shortable_level: float | None = None
    borrow_fee_pct_annual: float | None = None
    shares_available_to_borrow: int | None = None
    halted: bool | None = False
    limit_state: bool | None = False
    sector: str | None = None

    def __post_init__(self) -> None:
        self.symbol = _clean_symbol(self.symbol, "OrderIntent.symbol")
        self.halted = _optional_flag(self.halted, "OrderIntent.halted")
        self.limit_state = _optional_flag(self.limit_state, "OrderIntent.limit_state")
        if self.sector is not None:
            self.sector = str(self.sector).strip() or None
        if self.book_id is not None:
            self.book_id = _clean_book_id(self.book_id, "OrderIntent.book_id")
        if not isinstance(self.shortable, bool):
            raise GuardrailUsageError(
                "OrderIntent.shortable has to be true or false, but it is "
                f"{self.shortable!r}."
            )
        if self.shortable_level is not None:
            self.shortable_level = _finite_number(
                self.shortable_level, "OrderIntent.shortable_level"
            )
            if not 0.0 <= self.shortable_level <= IBKR_SHORTABLE_LEVEL_MAX:
                raise GuardrailUsageError(
                    "OrderIntent.shortable_level is "
                    f"{_plain_number(self.shortable_level)}, and IBKR's shortable "
                    f"indicator only runs from 0 to "
                    f"{_plain_number(IBKR_SHORTABLE_LEVEL_MAX)}."
                )
        if self.borrow_fee_pct_annual is not None:
            self.borrow_fee_pct_annual = _finite_number(
                self.borrow_fee_pct_annual, "OrderIntent.borrow_fee_pct_annual"
            )
            if self.borrow_fee_pct_annual < 0:
                raise GuardrailUsageError(
                    "OrderIntent.borrow_fee_pct_annual cannot be negative, but it is "
                    f"{_plain_number(self.borrow_fee_pct_annual)}. Write 0.3 for three "
                    "tenths of a percent a year."
                )
        if self.shares_available_to_borrow is not None:
            if isinstance(self.shares_available_to_borrow, bool) or not isinstance(
                self.shares_available_to_borrow, (int, float)
            ):
                raise GuardrailUsageError(
                    "OrderIntent.shares_available_to_borrow has to be a number of "
                    f"shares, but it is {self.shares_available_to_borrow!r}."
                )
            self.shares_available_to_borrow = int(self.shares_available_to_borrow)
            if self.shares_available_to_borrow < 0:
                raise GuardrailUsageError(
                    "OrderIntent.shares_available_to_borrow cannot be negative, but "
                    f"it is {self.shares_available_to_borrow}."
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
    pdt = _build_pdt(_optional_section(data, "pdt", where), where)

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
        pdt=pdt,
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
        tiny_capital_usd=_optional_positive_number(
            raw, "money.tiny_capital_usd", where, default=DEFAULT_TINY_CAPITAL_USD
        ),
        risk_per_trade_pct=_optional_percent(raw, "money.risk_per_trade_pct", where),
        max_weekly_loss_pct=_optional_percent(raw, "money.max_weekly_loss_pct", where),
        max_monthly_loss_pct=_optional_percent(
            raw, "money.max_monthly_loss_pct", where
        ),
        max_consecutive_losing_days=_optional_positive_int(
            raw, "money.max_consecutive_losing_days", where
        ),
        sector_gross_pct_max=_optional_percent(
            raw, "money.sector_gross_pct_max", where
        ),
        account_symbol_pct_max=_optional_percent(
            raw, "money.account_symbol_pct_max", where
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
        atr_days=_optional_positive_int(raw, "risk.atr_days", where)
        or DEFAULT_ATR_DAYS,
        stop_atr_pct=_optional_positive_number(raw, "risk.stop_atr_pct", where),
        stop_outside_opening_range=_optional_bool(
            raw, "risk.stop_outside_opening_range", where, default=False
        ),
        use_profit_target=_optional_bool(
            raw, "risk.use_profit_target", where, default=True
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


def _build_pdt(raw: dict | None, where: str) -> PdtConfig:
    """The pattern day trader settings. A file with no pdt section gets the defaults.

    The defaults are the safe reading: no hard limit, three day trades in five
    business days, and 25,000 dollars assumed as the live account minimum.
    """
    if not raw:
        return PdtConfig()
    return PdtConfig(
        hard_limit=_optional_bool(raw, "pdt.hard_limit", where, default=False),
        max_day_trades_per_5_days=_optional_positive_int(
            raw,
            "pdt.max_day_trades_per_5_days",
            where,
            default=DEFAULT_MAX_DAY_TRADES_PER_5_DAYS,
        ),
        assumed_live_equity_min_usd=_optional_positive_number(
            raw,
            "pdt.assumed_live_equity_min_usd",
            where,
            default=DEFAULT_ASSUMED_LIVE_EQUITY_MIN_USD,
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
        allow_options=_need_bool(raw, "universe.allow_options", where),
        allow_shorts=_need_bool(raw, "universe.allow_shorts", where),
        allowed_sec_types=allowed_sec_types,
        allowed_currencies=allowed_currencies,
        whitelist=_need_symbol_list(raw, "universe.whitelist", where),
        blacklist=_need_symbol_list(raw, "universe.blacklist", where),
        min_avg_dollar_volume=_optional_positive_number(
            raw,
            "universe.min_avg_dollar_volume",
            where,
            default=DEFAULT_MIN_AVG_DOLLAR_VOLUME,
        ),
        dollar_volume_sessions=_optional_positive_int(
            raw,
            "universe.dollar_volume_sessions",
            where,
            default=DEFAULT_DOLLAR_VOLUME_SESSIONS,
        ),
        # Deprecated, and optional for that reason. Kept so an older settings
        # file still loads and so the insider and Congress sweeps can go on
        # quoting a share figure. The momentum scanner ignores it.
        min_avg_volume=_optional_positive_int(raw, "universe.min_avg_volume", where),
        short_price_floor=short_price_floor,
        require_shortable=_optional_bool(
            raw, "universe.require_shortable", where, default=False
        ),
        max_borrow_fee_pct=_optional_percent(
            raw,
            "universe.max_borrow_fee_pct",
            where,
            default=DEFAULT_MAX_BORROW_FEE_PCT,
        ),
        borrow_availability_multiple=_optional_positive_number(
            raw,
            "universe.borrow_availability_multiple",
            where,
            default=DEFAULT_BORROW_AVAILABILITY_MULTIPLE,
        ),
        atr_days=_optional_positive_int(raw, "universe.atr_days", where)
        or DEFAULT_ATR_DAYS,
        min_atr_usd=_optional_positive_number(raw, "universe.min_atr_usd", where),
        min_atr_pct_of_price=_optional_percent(
            raw, "universe.min_atr_pct_of_price", where
        ),
        min_history_sessions=_optional_positive_int(
            raw, "universe.min_history_sessions", where
        )
        or DEFAULT_MIN_HISTORY_SESSIONS,
        exclude_spacs=_optional_bool(
            raw, "universe.exclude_spacs", where, default=True
        ),
        exclude_warrants_and_rights=_optional_bool(
            raw, "universe.exclude_warrants_and_rights", where, default=True
        ),
        exclude_preferred=_optional_bool(
            raw, "universe.exclude_preferred", where, default=True
        ),
        require_us_primary_listing=_optional_bool(
            raw, "universe.require_us_primary_listing", where, default=True
        ),
        exclude_halted=_optional_bool(
            raw, "universe.exclude_halted", where, default=True
        ),
    )


def _build_scanner(raw: dict, where: str) -> ScannerConfig:
    return ScannerConfig(
        rel_volume_min=_need_positive_number(raw, "scanner.rel_volume_min", where),
        max_candidates=_need_positive_int(raw, "scanner.max_candidates", where),
        exclude_leveraged_etfs=_need_bool(
            raw, "scanner.exclude_leveraged_etfs", where
        ),
        rank_by=_optional_text(raw, "scanner.rank_by", where, default=DEFAULT_RANK_BY)
        or DEFAULT_RANK_BY,
        rel_volume_window=_optional_text(
            raw, "scanner.rel_volume_window", where, default=DEFAULT_REL_VOLUME_WINDOW
        )
        or DEFAULT_REL_VOLUME_WINDOW,
        rel_volume_baseline_days=_optional_positive_int(
            raw, "scanner.rel_volume_baseline_days", where
        )
        or DEFAULT_REL_VOLUME_BASELINE_DAYS,
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
        holidays=_optional_date_list(raw, "schedule.holidays", where),
        flatten_market_at=_optional_clock_time(
            raw, "schedule.flatten_market_at", where
        ),
        fast_poll_seconds=_optional_positive_int(
            raw, "schedule.fast_poll_seconds", where
        ),
        fast_poll_from=_optional_clock_time(raw, "schedule.fast_poll_from", where),
        fast_poll_until=_optional_clock_time(raw, "schedule.fast_poll_until", where),
        preopen_start=_optional_clock_time(raw, "schedule.preopen_start", where),
        preopen_history_done_by=_optional_clock_time(
            raw, "schedule.preopen_history_done_by", where
        ),
        preopen_subscribe_done_by=_optional_clock_time(
            raw, "schedule.preopen_subscribe_done_by", where
        ),
    )

    ordered = [
        ("schedule.scan_start", schedule.scan_start),
        ("schedule.pick_time", schedule.pick_time),
        ("schedule.entries_until", schedule.entries_until),
        ("schedule.flatten_at", schedule.flatten_at),
    ]
    # The market backstop sits between the start of the flatten and the close
    # when a book has one. A book with none is checked exactly as it always was.
    if schedule.flatten_market_at is not None:
        ordered.append(("schedule.flatten_market_at", schedule.flatten_market_at))
    ordered.append(("schedule.market_close", schedule.market_close))
    _check_times_in_order(ordered, where)

    if (schedule.fast_poll_from is None) != (schedule.fast_poll_until is None):
        raise GuardrailConfigError(
            f"The settings schedule.fast_poll_from and schedule.fast_poll_until in "
            f"{where} go together: either set both, or leave both empty for a book "
            "that only ever uses loop_minutes. Right now only one of them has a time."
        )
    if (
        schedule.fast_poll_from is not None
        and schedule.fast_poll_until is not None
        and schedule.fast_poll_from >= schedule.fast_poll_until
    ):
        raise GuardrailConfigError(
            f"The setting schedule.fast_poll_from in {where} is "
            f"{schedule.fast_poll_from.strftime('%H:%M')}, which is not before "
            f"schedule.fast_poll_until at "
            f"{schedule.fast_poll_until.strftime('%H:%M')}. The fast window has to "
            "run forwards."
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
        tiny_capital_usd=_optional_positive_number(
            shared_raw,
            "shared.tiny_capital_usd",
            where,
            default=DEFAULT_TINY_CAPITAL_USD,
        ),
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
        book = _build_book(raw_book, where, number, shared)
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


def _build_book(
    raw: dict, where: str, number: int, shared: SharedConfig | None = None
) -> BookConfig:
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

    # A hyphen and an underscore mean the same mode, so an older file that says
    # dry-run still reads as dry_run rather than failing over punctuation.
    mode = _need_text(raw, f"{label}.mode", where).lower().replace("-", "_")
    if mode not in BOOK_MODES_ALLOWED:
        raise GuardrailConfigError(
            f"The setting {label}.mode in {where} says {mode!r}, and it has to be one "
            f"of {', '.join(BOOK_MODES_ALLOWED)}. dry_run works the order out and "
            "writes it down without sending it, tiny sends real paper orders against a "
            "small pot, and full sends them against the book's whole capital."
        )

    promoted_on = _optional_date(raw, f"{label}.promoted_on", where)
    rules_commit = _optional_text(raw, f"{label}.rules_commit", where)
    if mode in BOOK_MODES_THAT_SEND_ORDERS and (
        promoted_on is None or not rules_commit
    ):
        raise GuardrailConfigError(
            f"Book {book_id} in {where} is set to {mode!r}, which sends real orders, "
            f"but {label}.promoted_on and {label}.rules_commit are not both filled in. "
            "A book only leaves dry_run when the hub approves it, and the approval is "
            "recorded here as the date it was promoted and the git hash of the rules it "
            "was promoted against. Fill both in by hand, or put the book back on "
            "dry_run."
        )

    start_date = _need_date(raw, f"{label}.start_date", where)
    end_date = _need_date(raw, f"{label}.end_date", where)
    if end_date < start_date:
        raise GuardrailConfigError(
            f"Book {book_id} in {where} ends on {end_date.isoformat()}, which is "
            f"before it starts on {start_date.isoformat()}."
        )

    default_tiny = (
        shared.tiny_capital_usd if shared is not None else DEFAULT_TINY_CAPITAL_USD
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
        tiny_capital_usd=_optional_positive_number(
            raw, f"{label}.tiny_capital_usd", where, default=default_tiny
        ),
        promoted_on=promoted_on,
        rules_commit=rules_commit,
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
    # The money a book actually works with follows its mode: a book on tiny is
    # sized against the small pot, everything else against its whole capital.
    merged["account"]["account_id"] = registry.shared.account_id
    merged["account"]["gateway_port_paper"] = registry.shared.gateway_port
    merged["schedule"]["timezone"] = registry.shared.timezone
    merged["money"]["starting_equity"] = book.effective_capital()
    merged["money"]["tiny_capital_usd"] = book.tiny_capital_usd

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


def _optional_positive_number(
    raw: dict, dotted_name: str, where: str, default: float | None = None
) -> float | None:
    if _is_unset(raw, dotted_name):
        return default
    return _need_positive_number(raw, dotted_name, where)


def _optional_text(
    raw: dict, dotted_name: str, where: str, default: str | None = None
) -> str | None:
    """A piece of text a file is allowed to write out and leave empty."""
    if _is_unset(raw, dotted_name):
        return default
    value = _need(raw, dotted_name, where)
    if isinstance(value, str) and not value.strip():
        return default
    return _need_text(raw, dotted_name, where)


def _optional_date(
    raw: dict, dotted_name: str, where: str, default: date | None = None
) -> date | None:
    """A date a file is allowed to write out and leave empty, such as promoted_on."""
    if _is_unset(raw, dotted_name):
        return default
    value = _need(raw, dotted_name, where)
    if isinstance(value, str) and not value.strip():
        return default
    return _need_date(raw, dotted_name, where)


def _optional_date_list(
    raw: dict, dotted_name: str, where: str
) -> tuple[date, ...]:
    """A list of dates, for example the market holidays. Empty is normal."""
    if _is_unset(raw, dotted_name):
        return ()
    value = _need(raw, dotted_name, where)
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise GuardrailConfigError(
            f"The setting {dotted_name} in {where} should be a list of dates, written "
            f"like [2026-11-26, 2026-12-25] or left empty as [], but it is {value!r}."
        )
    dates: list[date] = []
    for item in value:
        if isinstance(item, datetime):
            dates.append(item.date())
        elif isinstance(item, date):
            dates.append(item)
        elif isinstance(item, str):
            try:
                dates.append(date.fromisoformat(item.strip()))
            except ValueError as exc:
                raise GuardrailConfigError(
                    f"The list {dotted_name} in {where} contains {item!r}, which is "
                    "not a date this code can read. Write each one as 2026-11-26."
                ) from exc
        else:
            raise GuardrailConfigError(
                f"The list {dotted_name} in {where} contains {item!r}, which is not a "
                "date. Write each one as 2026-11-26."
            )
    return tuple(sorted(set(dates)))


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


def _optional_clock_time(raw: dict, dotted_name: str, where: str) -> time | None:
    """A time such as "15:55", or None when the setting is missing or empty."""
    if _is_unset(raw, dotted_name):
        return None
    return _need_clock_time(raw, dotted_name, where)


def _clean_symbol(symbol: str, label: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise GuardrailUsageError(f"{label} has to be a symbol such as AAPL.")
    return symbol.strip().upper()


def _optional_flag(value, label: str):
    """A yes, a no, or a plain "nobody told us". Anything else is a mistake.

    None matters here rather than being tidied away: for a halt, not knowing is
    a different answer from knowing the name is fine, and the rules treat it as
    such.
    """
    if value is None or isinstance(value, bool):
        return value
    raise GuardrailUsageError(
        f"{label} has to be true, false, or left unset when nobody knows, but it "
        f"is {value!r}."
    )


def _clean_symbol_owners(owners, label: str = "AccountState.symbols_held_elsewhere"):
    """The map of which other book has which symbol, with both ends tidied up.

    Comes in as {symbol: book id} and goes out the same shape, with the symbols
    upper-cased the way every other symbol in this file is and the book ids run
    through the same check an order's book id gets. None means an empty map.
    """
    if owners is None:
        return {}
    if not isinstance(owners, dict):
        raise GuardrailUsageError(
            f"{label} has to be a list of which book has which symbol, such as "
            '{"AAPL": "B"}, but it is a ' + f"{type(owners).__name__}."
        )
    return {
        _clean_symbol(symbol, f"a symbol in {label}"): _clean_book_id(
            book_id, f"the book id for {symbol} in {label}"
        )
        for symbol, book_id in owners.items()
    }


def _clean_money_map(value, label: str, upper: bool) -> dict[str, float]:
    """A {name: dollars} map, checked and tidied. None becomes an empty map.

    upper says whether the keys are tickers, which are always upper case, or
    industry names, which are words and are left as they were written.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise GuardrailUsageError(
            f"{label} has to be a map of names to dollar amounts, but it is "
            f"{type(value).__name__}."
        )
    out: dict[str, float] = {}
    for key, amount in value.items():
        name = str(key).strip()
        if not name:
            raise GuardrailUsageError(f"{label} has an entry with an empty name.")
        if upper:
            name = _clean_symbol(name, f"a key of {label}")
        out[name] = _finite_number(amount, f"{label}[{name!r}]")
    return out


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


def must_flatten_at_market_now(g: Guardrails, now: datetime) -> bool:
    """True once the market order backstop is due, item A11.

    Flattening starts at flatten_at with limit orders at the bid or the ask,
    because spreads widen and depth collapses in the last few minutes. Anything
    still open at flatten_market_at goes out at market instead, because being
    flat matters more than the last few cents.

    Always false for a book with no backstop time and for one that is never
    flattened at all.
    """
    backstop = g.schedule.flatten_market_at
    if backstop is None or not g.flat_by_close:
        return False
    local = _eastern(g, now)
    if not _is_weekday(local):
        return False
    return backstop <= local.time() < g.schedule.market_close


def next_tick_seconds(g: Guardrails, now: datetime, holding: bool = False) -> int:
    """How long until this book wants looking at again, in seconds. Item A14.

    Thirty seconds between fast_poll_from and fast_poll_until while the book is
    holding a position or has a working order, because a stop this tight needs
    sub-minute resolution even with the stop resting at the broker. Five minutes
    the rest of the time, and five minutes for a book with no fast window at
    all, which is the insider and Congress books.

    The loop reads this rather than deciding for itself, so the cadence is a
    number in a yaml file and not a rule buried in the code.
    """
    slow = max(1, int(g.schedule.loop_minutes)) * 60
    fast = g.schedule.fast_poll_seconds
    start = g.schedule.fast_poll_from
    end = g.schedule.fast_poll_until
    if not holding or fast is None or start is None or end is None:
        return slow
    local = _eastern(g, now)
    if not _is_weekday(local):
        return slow
    if start <= local.time() < end:
        return max(1, int(fast))
    return slow


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


def atr_stop_distance(g: Guardrails, atr: float | None) -> float | None:
    """How far the stop sits from the entry price, in dollars, off the ATR.

    Momentum v2, item A1, approved by Mo on 2026-09-06. The average true range
    is the average size of one session's price swing over the last 14 sessions,
    counting the gap from the previous close. The stop sits risk.stop_atr_pct
    percent of that away, so a stock whose average swing is 2 dollars stops 20
    cents away and a quieter one stops closer still.

    Returns None when this book has no volatility stop, which is the insider and
    Congress books, or when nobody could work out an average true range for this
    name. Then the caller falls back to the plain percentage stop.
    """
    if g.risk.stop_atr_pct is None or atr is None:
        return None
    value = _finite_number(atr, "atr")
    if value <= 0:
        return None
    distance = value * (g.risk.stop_atr_pct / 100.0)
    return distance if distance > 0 else None


def stop_price_for(
    g: Guardrails,
    entry_price: float,
    opening_range_low: float | None,
    side: str = "BUY",
    opening_range_high: float | None = None,
    atr: float | None = None,
) -> float:
    """Where the stop loss goes for a position opened at entry_price.

    THE MOMENTUM V2 STOP, item A1, when an average true range is handed in and
    the book has risk.stop_atr_pct set: the stop sits 10 percent of the 14 day
    average true range away from the entry price. On top of that, when
    risk.stop_outside_opening_range is true, it may never sit INSIDE the first
    five minutes' range, so for a long it is pushed down to at or below the
    range low and for a short up to at or above the range high. A stop inside
    the range is inside the noise the trade is made of, so the setup itself
    would hit it.

    THE FALLBACK, when there is no average true range or the book has no
    volatility stop, which is the insider and Congress books: the old rule
    exactly as it was. Start with the percentage stop from the settings, 1.5
    percent below entry on the momentum books. If the low of the opening five
    minutes is nearer to entry than that, and the settings allow it, use the
    opening range low instead, because a nearer stop means a smaller loss when
    it is hit.

    For a short, opened with a SELL, everything is the mirror image and the
    answer is always above the entry price. Pass the range high in
    opening_range_high; opening_range_low is ignored for a short.

    Either way the answer is always on the right side of entry, and is rounded
    to whole cents.
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
        return _short_stop_price(g, entry_price, opening_range_high, atr)

    distance = atr_stop_distance(g, atr)
    if distance is not None:
        stop = entry_price - distance
        if g.risk.stop_outside_opening_range and opening_range_low is not None:
            low = _finite_number(opening_range_low, "opening_range_low")
            # At or below the range low. A range low at or above entry is
            # nonsense for a long and is ignored, exactly as it is below.
            if 0 < low < entry_price:
                stop = min(stop, low)
    else:
        percent_stop = entry_price * (1.0 - g.risk.stop_loss_pct / 100.0)
        stop = percent_stop
        if opening_range_low is not None and g.risk.use_opening_range_low_if_tighter:
            low = _finite_number(opening_range_low, "opening_range_low")
            # Only useful if it is genuinely below entry. A range low at or above
            # the entry price would mean an instant stop out, so it is ignored.
            if 0 < low < entry_price:
                stop = max(percent_stop, low)

    stop = _round_cents(stop)
    if stop >= entry_price:
        # Only reachable with a sub cent entry price. Keep the promise that the
        # stop is below entry.
        stop = _round_cents(entry_price - 0.01)
    return stop


def _short_stop_price(
    g: Guardrails,
    entry_price: float,
    opening_range_high: float | None,
    atr: float | None = None,
) -> float:
    """The mirror of the long stop: above the entry price."""
    distance = atr_stop_distance(g, atr)
    if distance is not None:
        stop = entry_price + distance
        if g.risk.stop_outside_opening_range and opening_range_high is not None:
            high = _finite_number(opening_range_high, "opening_range_high")
            if high > entry_price:
                stop = max(stop, high)
    else:
        percent_stop = entry_price * (1.0 + g.risk.stop_loss_pct / 100.0)
        stop = percent_stop
        if opening_range_high is not None and g.risk.use_opening_range_low_if_tighter:
            high = _finite_number(opening_range_high, "opening_range_high")
            # A range high at or below where we sold would stop us out instantly,
            # so it is ignored, exactly as a range low above entry is for a long.
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


def shares_for_risk(
    g: Guardrails,
    state: AccountState,
    symbol: str,
    entry_price: float,
    stop_price: float,
) -> int:
    """How many shares to buy so that being wrong costs one trade's worth of risk.

    Momentum v2, item A6, approved by Mo on 2026-09-06. The book risks
    money.risk_per_trade_pct of its equity on each trade, which is 0.25 percent
    or 250 dollars on a 100,000 dollar book. The share count is that money
    divided by the distance from the entry price to the stop, so a name with a
    wide stop gets fewer shares and a name with a tight stop gets more, and
    every position loses about the same when it is wrong.

    The answer is then put through max_shares_for, so the notional caps, the
    single order cap and the cash left over are all still the ceiling. A very
    tight stop would otherwise buy an enormous position, which is exactly the
    failure this pair of rules exists to prevent.

    A book with no risk_per_trade_pct, which is the insider and Congress books,
    gets max_shares_for on its own, so nothing changes for them. So does a call
    with a stop that is not on the right side of the entry price, because there
    is no risk distance to divide by and refusing to size is worse than sizing
    the old way.
    """
    ceiling = max_shares_for(g, state, symbol, entry_price)
    risk_pct = g.money.risk_per_trade_pct
    if risk_pct is None or risk_pct <= 0:
        return ceiling

    entry = _finite_number(entry_price, "entry_price")
    stop = _finite_number(stop_price, "stop_price")
    distance = abs(entry - stop)
    if distance <= 0:
        return ceiling

    risk_dollars = float(state.equity) * (risk_pct / 100.0)
    if risk_dollars <= 0:
        return 0
    wanted = (
        Decimal(repr(_round_cents(risk_dollars))) / Decimal(repr(_round_cents(distance)))
    ).to_integral_value(rounding=ROUND_FLOOR)
    return max(0, min(int(wanted), ceiling))


def weekly_loss_hit(g: Guardrails, state: AccountState) -> bool:
    """True when this week's loss has reached the weekly cap.

    Measured against what the book was worth when the market opened today, which
    is the same base the daily cap uses, so the two numbers are read the same
    way. A book with no weekly cap always gets false.
    """
    return _beyond_the_day_hit(g.money.max_weekly_loss_pct, state, state.week_pnl)


def monthly_loss_hit(g: Guardrails, state: AccountState) -> bool:
    """True when this month's loss has reached the monthly cap."""
    return _beyond_the_day_hit(g.money.max_monthly_loss_pct, state, state.month_pnl)


def _beyond_the_day_hit(
    limit_pct: float | None, state: AccountState, pnl: float
) -> bool:
    if limit_pct is None:
        return False
    if state.day_start_equity <= 0:
        # No sensible balance to measure against, so take the safe answer.
        return True
    allowed = state.day_start_equity * (limit_pct / 100.0)
    return float(pnl) <= -allowed + CENT_TOLERANCE


def losing_streak_hit(g: Guardrails, state: AccountState) -> bool:
    """True when this book has finished down too many days in a row.

    A run of small losses is the shape a broken strategy makes, and no daily,
    weekly or monthly cap catches it on its own.
    """
    limit = g.money.max_consecutive_losing_days
    if limit is None:
        return False
    return int(state.consecutive_losing_days) >= limit


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
    _check_symbol_exclusivity(g, state, intent, decision)
    _check_halt_state(g, state, intent, decision)
    _check_instrument(g, intent, decision)
    _check_shorting(g, state, intent, decision)
    _check_short_discipline(g, state, intent, decision)
    _check_clock(g, state, intent, decision, when)
    _check_daily_loss(g, state, intent, decision)
    _check_beyond_the_day_losses(g, state, intent, decision)
    _check_size(g, state, intent, decision)
    _check_gross_exposure(g, state, intent, decision)
    _check_sector_cap(g, state, intent, decision)
    _check_account_symbol_cap(g, state, intent, decision)
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


def _opens_or_increases_position(state: AccountState, intent: OrderIntent) -> bool:
    """True when this order would leave the book with a bigger bet on the symbol.

    Buying 100 back against a 100 share short is a cover and changes nothing;
    buying 150 leaves 50 shares of brand new length. Selling 100 out of a 100
    share holding is an exit; selling 150 leaves 50 shares borrowed. Either way,
    only the part that goes past flat counts as opening something.
    """
    held = state.held_qty(intent.symbol)
    if intent.side == "BUY":
        return intent.qty > max(0, -held)
    return intent.qty > max(0, held)


def _check_symbol_exclusivity(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """Two books may never be in the same name at the same time.

    IBKR nets positions by symbol inside the one shared paper account. If book A
    is long 100 AAPL and book B buys 100 more, the broker reports one line of
    200 shares and there is no way left to say whose is whose. Reconciliation
    would be guessing, and a book that has lost track of what it holds sizes its
    next order off a number that is not true. So the second book does not get
    in. Added 2026-09-06 at the review team's request, as a blocking finding.

    Getting out is never blocked by this rule. An exit, a stop or a flatten that
    reduces this book's own position goes through untouched, because refusing
    the way out of a trade is worse than any duplication this rule prevents.
    """
    owner = state.symbol_owner(intent.symbol)
    if owner is None:
        return

    # If the map names this book itself, there is nobody to be exclusive
    # against. That happens when the loop hands in every book's holdings
    # including our own, which is an easy mistake to make and a harmless one.
    ours = {
        book_id
        for book_id in (g.book_id, state.book_id, intent.book_id)
        if book_id is not None
    }
    if owner in ours:
        return

    if intent.purpose != "entry" and not _opens_or_increases_position(state, intent):
        return

    decision.add(
        "symbol_exclusive",
        f"Book {owner} already holds {intent.symbol} or has a working order in it, "
        f"so {_pot_words(g.book_id)} may not open a position in it as well. IBKR "
        "nets positions by symbol inside the one shared paper account, so the "
        "second book's shares would disappear into the first book's line and "
        f"neither book could be reconciled afterwards. Book {owner} got there "
        "first, and first come, first served is how that is settled. Getting out "
        "of something this book already holds is never blocked by this rule.",
    )


def _halt_unknown_fields(intent: OrderIntent) -> list[str]:
    """Which of the two halt facts the loop did not manage to report."""
    missing: list[str] = []
    if intent.halted is None:
        missing.append("whether the name is halted")
    if intent.limit_state is None:
        missing.append("whether it is sitting in a limit-up limit-down band")
    return missing


def _check_halt_state(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """Is this name tradeable at all right now?

    Three refusals live under the one rule id, because they are one question
    asked three ways. A halted name takes nothing but a way out. A name in a
    limit-up limit-down band takes no new positions, because that band is the
    step immediately before a volatility halt. And a name whose halt status
    nobody could tell us takes no new positions either.

    That last one is the point of the rule (review team, 2026-09-06). Deciding
    to buy a name without knowing whether it is even trading is the failure they
    named, and reading a missing answer as "fine" is how it would happen. So an
    unknown status is refused the same way an unknown borrow cost is.
    """
    if intent.halted is True and intent.purpose not in HALT_ALLOWED_PURPOSES:
        decision.add(
            "halted",
            f"Trading in {intent.symbol} is halted, so this {intent.purpose} order "
            "cannot be sent. While a name is halted the agent may only get out of "
            f"it, which means an {' or a '.join(HALT_ALLOWED_PURPOSES)} order. "
            "Parking a fresh order in a name whose next printed price nobody knows "
            "is how a halt turns into a bad fill on the reopen.",
        )

    if intent.purpose != "entry":
        return

    if intent.limit_state is True:
        decision.add(
            "halted",
            f"{intent.symbol} is sitting in a limit-up limit-down band, which is the "
            "step immediately before a volatility halt, so no new position is opened "
            "in it. Getting out of one is still allowed.",
        )

    missing = _halt_unknown_fields(intent)
    if missing:
        decision.add(
            "halted",
            f"This order would open a position in {intent.symbol}, and the halt "
            f"status was not available: nobody told this check "
            f"{_join_with_and(missing)}. An unknown halt status is refused rather "
            "than read as a clean name, because deciding to buy something without "
            "knowing whether it is even trading is the failure this rule exists to "
            "prevent. Getting out of a position is never blocked by it.",
        )


def _join_with_and(parts: list[str]) -> str:
    """A, B and C, the way a person writes a list."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


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

    if g.universe.require_shortable:
        for reason in _borrow_failures(g, intent):
            decision.add("shortable_required", reason)


def easy_to_borrow(shortable_level: float | None, shortable: bool = False) -> bool:
    """Does IBKR call this name easy to borrow?

    IBKR reports a shortable indicator on a scale of 0 to 3, and anything above
    2.5 is the easy to borrow band. When no level was reported at all, fall back
    to the plain yes or no flag the loop used to set on its own, so an older
    caller keeps working.
    """
    if shortable_level is None:
        return bool(shortable)
    return float(shortable_level) > EASY_TO_BORROW_LEVEL_MIN


def _borrow_failures(g: Guardrails, intent: OrderIntent) -> list[str]:
    """The easy to borrow rule, in three parts, each with its own sentence.

    All three have to hold at the moment of entry (Mo, 2026-09-06): IBKR has to
    call the name easy to borrow, the borrow has to cost less than the book's
    fee limit, and there have to be enough shares available to borrow. Whichever
    part fails says so by name, because "could not short it" is not a useful
    thing to read in a ledger three weeks later.
    """
    failures: list[str] = []
    max_fee = g.universe.max_borrow_fee_pct
    multiple = g.universe.borrow_availability_multiple
    needed_shares = multiple * intent.qty

    if not easy_to_borrow(intent.shortable_level, intent.shortable):
        if intent.shortable_level is None:
            failures.append(
                f"This order would short {intent.symbol}, and the broker has not "
                "confirmed the shares can be borrowed. This book only shorts names "
                "IBKR reports as easy to borrow, so nothing was sent."
            )
        else:
            failures.append(
                f"This order would short {intent.symbol}, and IBKR rates it "
                f"{_plain_number(intent.shortable_level)} on its 0 to 3 borrowing "
                f"scale. Easy to borrow starts above "
                f"{_plain_number(EASY_TO_BORROW_LEVEL_MIN)}, so this one is harder to "
                "borrow than this book will accept."
            )

    fee = intent.borrow_fee_pct_annual
    if fee is None:
        failures.append(
            f"This order would short {intent.symbol}, and the broker did not say what "
            "borrowing the shares costs. An unknown borrow cost is refused rather than "
            f"assumed cheap, because the limit is {_plain_number(max_fee)} percent a "
            "year and the expensive borrows are the ones nobody quotes."
        )
    elif fee > max_fee + 1e-9:
        failures.append(
            f"This order would short {intent.symbol}, and borrowing the shares costs "
            f"{_plain_number(fee)} percent a year, which is above this book's limit of "
            f"{_plain_number(max_fee)} percent. An expensive borrow eats the trade "
            "before it starts."
        )

    available = intent.shares_available_to_borrow
    if available is None:
        failures.append(
            f"This order would short {intent.qty} shares of {intent.symbol}, and the "
            "broker did not say how many shares are available to borrow. Without that "
            "number there is no way to know the borrow would not be recalled, so "
            "nothing was sent."
        )
    elif available < needed_shares:
        failures.append(
            f"This order would short {intent.qty} shares of {intent.symbol}, and only "
            f"{available:,} shares are available to borrow. This book wants at least "
            f"{_plain_number(multiple)} times what it is selling, which is "
            f"{int(needed_shares):,} shares, so a thin borrow cannot be recalled out "
            "from under it."
        )

    return failures


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


def _check_beyond_the_day_losses(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """The three limits beyond the day, item A8, approved by Mo on 2026-09-06.

    A weekly cap, a monthly cap and a run of losing days. Any one of them pauses
    the book until Mo has looked at it, because without them a book could lose a
    little every day for a fortnight and no rule would ever notice.

    None of the three ever blocks a closing order. A paused book gets out of
    what it holds; it just opens nothing new.
    """
    if intent.purpose in PAUSED_BOOK_ALLOWED_PURPOSES:
        return

    base = float(state.day_start_equity)

    if weekly_loss_hit(g, state):
        allowed = base * ((g.money.max_weekly_loss_pct or 0.0) / 100.0)
        decision.add(
            "weekly_loss_cap",
            f"{_pot_words(g.book_id).capitalize()} is down "
            f"{_money(abs(state.week_pnl))} this week, which has reached its weekly "
            f"limit of {_plain_number(g.money.max_weekly_loss_pct)} percent "
            f"({_money(allowed)}). The book is paused and opens nothing new until "
            "Mo has looked at it. Closing orders are still allowed.",
        )

    if monthly_loss_hit(g, state):
        allowed = base * ((g.money.max_monthly_loss_pct or 0.0) / 100.0)
        decision.add(
            "monthly_loss_cap",
            f"{_pot_words(g.book_id).capitalize()} is down "
            f"{_money(abs(state.month_pnl))} this month, which has reached its "
            f"monthly limit of {_plain_number(g.money.max_monthly_loss_pct)} percent "
            f"({_money(allowed)}). The book is paused and opens nothing new until "
            "Mo has looked at it. Closing orders are still allowed.",
        )

    if losing_streak_hit(g, state):
        decision.add(
            "losing_streak_pause",
            f"{_pot_words(g.book_id).capitalize()} has finished down "
            f"{state.consecutive_losing_days} trading days in a row, and the limit "
            f"is {g.money.max_consecutive_losing_days}. A run of small losses is the "
            "shape a broken strategy makes, so the book is paused for Mo to look at "
            "it. Closing orders are still allowed.",
        )


def _check_sector_cap(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """No more than a quarter of the book in one industry, item A9.

    Five morning gappers move together far more than five unrelated names do, so
    ten positions in one industry is really one bet made ten times. The cap is a
    share of the book's gross exposure limit, which at a 100 percent gross cap
    is a share of the book itself.

    An industry the broker could not tell us stops the entry. That is the same
    answer an unknown halt status gets and for the same reason: a limit that
    cannot be measured is not a limit, and reading a missing answer as "fine" is
    how the rule would quietly stop working.
    """
    limit_pct = g.money.sector_gross_pct_max
    if limit_pct is None or intent.purpose != "entry":
        return

    if not intent.sector:
        decision.add(
            "sector_cap",
            f"This order would open a position in {intent.symbol}, and nobody told "
            "this check which industry it is in. The sector cap cannot be measured "
            "without it, and an unknown industry is refused rather than counted as "
            "harmless, because the whole point of the cap is that gap up names in "
            "one industry all move together. Getting out is never blocked by it.",
        )
        return

    notional = intent.notional
    if notional is None:
        # Already refused by max_order_notional, and there is nothing to add up.
        return

    equity = float(state.equity)
    if equity <= 0:
        return
    cap = equity * (g.money.gross_exposure_pct_max / 100.0) * (limit_pct / 100.0)
    held = state.sector_exposure_now(intent.sector)
    would_be = held + notional
    if would_be <= cap + CENT_TOLERANCE:
        return

    decision.add(
        "sector_cap",
        f"This order would put {_money(would_be)} of {_pot_words(g.book_id)} into "
        f"{intent.sector}: {_money(held)} already there and {_money(notional)} from "
        f"this order. The limit is {_plain_number(limit_pct)} percent of the book's "
        f"gross exposure limit, which is {_money(cap)}. Names that gapped this "
        "morning in the same industry are one bet, not several.",
    )


def _check_account_symbol_cap(
    g: Guardrails, state: AccountState, intent: OrderIntent, decision: Decision
) -> None:
    """No more than 15 percent of everything the books hold in one ticker, item A9.

    This one counts across all five books rather than inside one, which is why
    it needs the account wide figures the loop hands in. The one ticker one book
    rule already stops two books buying the same name; this is the second layer
    under it, and it also catches one book piling into a single ticker.

    When the loop did not say what all five books are worth, this book's own
    equity stands in. That is the smaller number, so the cap comes out tighter
    rather than looser, which is the safe direction to be wrong in.
    """
    limit_pct = g.money.account_symbol_pct_max
    if limit_pct is None or intent.purpose != "entry":
        return
    notional = intent.notional
    if notional is None:
        return

    base = state.account_equity
    measured_against = "everything the five books are worth"
    if base is None or base <= 0:
        base = float(state.equity)
        measured_against = (
            "what this book alone is worth, because nobody said what the five books "
            "hold between them, and the smaller figure is the safer one to measure "
            "against"
        )
    if base <= 0:
        return

    cap = base * (limit_pct / 100.0)
    held = state.symbol_exposure_everywhere(intent.symbol)
    would_be = held + notional
    if would_be <= cap + CENT_TOLERANCE:
        return

    decision.add(
        "account_symbol_cap",
        f"This order would leave {_money(would_be)} riding on {intent.symbol} across "
        f"every book: {_money(held)} already held and {_money(notional)} from this "
        f"order. The limit is {_plain_number(limit_pct)} percent of "
        f"{measured_against}, which is {_money(cap)}.",
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
