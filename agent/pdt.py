"""The pattern day trader rule, counted here because the paper account will not.

US regulators call anyone who makes four or more round trip day trades in five
business days, in a margin account, a pattern day trader, and they require that
account to hold at least 25,000 dollars. Fall below it and the broker stops the
account day trading for 90 days.

The IBKR paper account this project runs on is exempt, because the money in it
is simulated and IBKR does not apply the rule there. That is convenient and
useless at the same time: month one would sail past a rule a live account would
run straight into, and nobody would learn anything from it. So this file counts
day trades itself.

Mo's decision, 2026-09-06:

1. Assume 25,000 dollars of live equity as the safe minimum.
2. Every book keeps its own rolling five business day day trade counter.
3. The insider book (C) and the Congress book (D) are held to a hard limit of
   three day trades in five business days. Those two books are meant to hold
   positions for weeks, so a day trade in one of them is a mistake, and the
   fourth one is refused.
4. The momentum books (A, B and E) are never blocked, because day trading is
   their whole strategy. Instead every order the rule would have blocked is
   written down, so the live money cost of the rule is measured at the end of
   the month rather than guessed at.

A day trade is a buy and a sell (or a short and a cover) of the same symbol, in
the same book, on the same trading day.

Which rulebook applies, added 2026-09-06
----------------------------------------

Everything above describes the old rulebook, and FINRA retired it with effect
from 2026-06-04 (Regulatory Notice 26-10, phase-in to 2027-10-20). A migrated
account has no 25,000 dollar floor and nothing counts to four. In its place come
the intraday margin deficit rules, where the thing that gets an account in
trouble is an order it cannot pay for, not an order it counted wrong.

Which of the two an account is under is a fact about that account, and IBKR will
say if asked. agent/margin_regime.py does the asking and the reading, the 9 AM
pre-flight writes the answer into pdt.regime in config/guardrails.yaml, and this
file behaves differently depending on what it says:

    old_pdt   everything above. The hard limit refuses the fourth day trade on
              the books that have one, and the momentum books get a note.
    new_imd   the counter still records every fill, because the ledger still
              wants the month's count, but it never blocks and never sets
              would_have_blocked, because there is no longer a rule to block
              for. Instead every entry goes through the intraday margin deficit
              check in agent/margin_regime.py: gross exposure at or under 100
              percent of book equity and cash never below zero.
    unknown   nobody has asked the account yet. pdt.treat_unknown_as decides,
              and it ships as old_pdt, so an unasked account behaves as though
              the strict old rule still binds. That is the safe direction: the
              cost of counting an account that need not count is a note in a
              log, and the cost of not counting one that must is a 90 day ban.

A counter built without a regime is unknown, which means old_pdt, which means
every piece of behaviour described above this section is exactly what happens.
Nothing changed for anyone who does not pass one.

How the counting works
----------------------

One symbol, one trading day, fills walked in the order they happened. The only
thing being tracked is shares that were opened that same day. A fill that moves
the day's position away from zero is an opening fill. A fill that moves it back
towards zero consumes shares opened today and counts as one day trade, one per
closing fill rather than one per share. A fill that crosses straight through
zero counts one day trade and leaves the remainder open as a new position.

Two things follow from that, and both are deliberate:

* Selling a position that was carried in from a previous day is not a day
  trade, because no shares were opened today for it to close.
* This file sees fills and nothing else. It does not know what the book was
  holding when the day started, so the first fill of the day in a symbol always
  reads as an opening fill. If the book sells something it held overnight and
  then buys it back the same afternoon, that buy back is counted as a day
  trade even though a broker might not count it. That errs towards counting
  one too many, which is the safe direction for a limit.

What this file deliberately does not do
---------------------------------------

It never talks to the network, and it never guesses. A time with no timezone,
a nonsense quantity or a broken store file raises a plain ValueError with a
sentence saying what to fix, rather than being quietly patched up.

The file on disk
----------------

Each book keeps its own small JSON file, by default
output/pdt_BOOK_<book id>.json, so book A writes to output/pdt_BOOK_A.json. It
holds "book_id", "version" and "fills", and each fill is written out as
{"symbol", "side", "qty", "ts", "trade_date", "fill_id"}. It is meant to be
readable: open it in any text editor and the day's trading is right there.

Every fill is saved the moment it is recorded, by writing a temporary file in
the same folder and then replacing the real one, so a crash halfway through can
never leave half a file behind. To stop the file growing forever, saving drops
any fill older than 60 calendar days before the newest fill it holds, which is
far more history than a five business day window needs.

The time written into "ts" carries a timezone and is always converted to New
York first, because that is the market's clock and it is what decides which
trading day a fill belongs to. "trade_date" is written for a human to read;
the code works it out again from "ts" when it loads the file, so the two can
never drift apart.

Written 2026-09-06. The settings live in the yaml files, not here.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from margin_regime import (  # noqa: E402
    RULE_ID_IMD,
    Regime,
    as_regime,
    imd_check,
    read_regime_setting,
)
from paths import config_dir, output_dir  # noqa: E402

__all__ = [
    "RULE_ID_PDT_LIMIT",
    "RULE_ID_IMD",
    "PDT_EQUITY_MINIMUM_USD",
    "DEFAULT_MAX_DAY_TRADES_PER_5_DAYS",
    "DEFAULT_TREAT_UNKNOWN_AS",
    "WINDOW_BUSINESS_DAYS",
    "KEEP_FILL_DAYS",
    "STORE_VERSION",
    "NEW_YORK",
    "Regime",
    "PdtDecision",
    "DayTradeCounter",
    "business_days_back",
    "counter_for",
    "settings_regime",
    "store_path_for",
]


# The rule id written in the ledger whenever this limit fires, so the ledger can
# count how often it did.
RULE_ID_PDT_LIMIT = "pdt_limit"

# What a live margin account has to hold before it may day trade freely.
PDT_EQUITY_MINIMUM_USD = 25000.0

# How many day trades a book gets in five business days when its settings say
# nothing. Three, so that the fourth one is the one that would trip the rule.
DEFAULT_MAX_DAY_TRADES_PER_5_DAYS = 3

# What an unknown regime is treated as when nothing says otherwise. The strict
# old rule, because being counted when you need not be costs a line in a log and
# not being counted when you must costs 90 days of not trading.
DEFAULT_TREAT_UNKNOWN_AS = Regime.OLD_PDT

# How many business days the rolling window covers, today included.
WINDOW_BUSINESS_DAYS = 5

# Fills older than this many calendar days before the newest one are dropped
# when the file is saved.
KEEP_FILL_DAYS = 60

# The shape of the file on disk, so a later change to it can be spotted.
STORE_VERSION = 1

# The market's clock. A fill's trading day is decided here and nowhere else.
NEW_YORK = ZoneInfo("America/New_York")

# The two sides a fill can have. Read case insensitively.
VALID_SIDES = ("BUY", "SELL")

# A book id is short and loud so it reads well in the ledger and in a filename.
_BOOK_ID_PATTERN = re.compile(r"^[A-Z0-9_]{1,8}$")


# ---------------------------------------------------------------------------
# The answer this module hands back
# ---------------------------------------------------------------------------


@dataclass
class PdtDecision:
    """The answer: may this order go, and what the day trade counter knows.

    The first three fields are the same as agent.guardrails.Decision, so the
    trading loop can read a refusal from here exactly the way it reads a refusal
    from the guardrails. reasons and rule_ids line up index for index.

    would_have_blocked is the extra one, and it is the whole point of the file
    for the momentum books. It is true when the rule would have stopped this
    order in a live account under 25,000 dollars, on a book that is not held to
    the hard limit. In that case allowed stays true, the order goes out, and the
    reason is written down so the cost of the rule can be added up later. Only a
    real refusal puts anything in rule_ids.

    day_trades_used is how many day trades the book has already made in the five
    business days ending today, limit is how many it is allowed, hard_limit says
    whether going over is refused or merely noted, and symbol is the name the
    order was for.

    regime is which rulebook this answer was worked out under, and it is written
    into the ledger so a month of decisions can be read back knowing which rules
    were in force. Under new_imd, would_have_blocked is always false and the day
    trade count is kept for the record only.

    note is for anything worth writing down that is not a refusal: why the
    deficit check could not run, or that it ran and found room. It is kept out
    of reasons on purpose, because the loop reads a non-empty reasons list as
    "this order is a day trade" when it writes the tick log.
    """

    allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    would_have_blocked: bool = False
    day_trades_used: int = 0
    limit: int = DEFAULT_MAX_DAY_TRADES_PER_5_DAYS
    hard_limit: bool = False
    symbol: str | None = None
    regime: Regime = DEFAULT_TREAT_UNKNOWN_AS
    note: str = ""

    @property
    def summary(self) -> str:
        """One line for the log."""
        if not self.allowed:
            return "blocked: " + "; ".join(self.reasons)
        if self.would_have_blocked:
            return "allowed, but a live account would have been blocked: " + "; ".join(
                self.reasons
            )
        return "allowed"


@dataclass(frozen=True)
class _Fill:
    """One fill, as this file remembers it.

    ts always carries a timezone and is always in New York time. trade_date is
    the New York date of that moment, which is the day the fill belongs to.
    """

    symbol: str
    side: str
    qty: int
    ts: datetime
    trade_date: date
    fill_id: str | None = None


# ---------------------------------------------------------------------------
# Business days
# ---------------------------------------------------------------------------


def business_days_back(
    today: date, count: int, holidays: Iterable[date] | None = ()
) -> list[date]:
    """The `count` business days ending on today inclusive, oldest first.

    Business days are Monday to Friday, less any date in holidays. Ask for five
    business days ending on Thursday 2026-09-10 and you get the Friday before
    the weekend back as well: 2026-09-04, 2026-09-07, 2026-09-08, 2026-09-09,
    2026-09-10.

    If today is itself a weekend or a holiday it is not counted, so asking on a
    Saturday gives the five business days ending on the Friday before it.
    """
    end = _as_plain_date(today, "today")
    wanted = _whole_number_above_zero(count, "count")
    closed = _clean_holidays(holidays)

    days: list[date] = []
    cursor = end
    while len(days) < wanted:
        if _is_business_day(cursor, closed):
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    return days


def store_path_for(book_id: str, store_dir: str | Path | None = None) -> Path:
    """Where one book's day trade file lives, output/pdt_BOOK_A.json for book A."""
    clean = _clean_book_id(book_id, "book_id")
    folder = Path(store_dir).expanduser() if store_dir is not None else output_dir()
    return folder / f"pdt_BOOK_{clean}.json"


def settings_regime(config_path: str | Path | None = None) -> tuple[Regime, Regime]:
    """The regime and its unknown fallback, out of the shared settings file.

    Comes back as (regime, treat_unknown_as), read from the pdt block of
    config/guardrails.yaml. That file is the right place for it because the
    regime is a fact about the account rather than about one strategy, and
    because the 9 AM pre-flight writes it there once a day.

    A missing or broken file gives (unknown, old_pdt), which is the reading that
    keeps the strict old behaviour.
    """
    path = (
        Path(config_path)
        if config_path is not None
        else config_dir() / "guardrails.yaml"
    )
    return read_regime_setting(path)


def counter_for(book_config, store_dir: str | Path | None = None) -> DayTradeCounter:
    """Build the day trade counter for the book these settings belong to.

    book_config is whatever agent.guardrails.load_book_guardrails() hands back,
    and everything is read off it with getattr, so a small stand in object with
    the same shape works just as well. Two things are read: book_id, which says
    which book and so which file, and schedule.holidays when the settings have
    one, which is the list of days the market is shut.

    The regime comes off pdt.regime when the settings carry one, and out of the
    pdt block of config/guardrails.yaml when they do not. Both roads lead to the
    same place; the second one exists because the settings loader in
    agent/guardrails.py does not carry the field yet, and the pre-flight writes
    its answer into that yaml file either way.

    store_dir is only for tests and one off runs. Left alone, the counter writes
    into the project's output folder.
    """
    book_id = getattr(book_config, "book_id", None)
    if book_id is None:
        raise ValueError(
            "counter_for needs settings that belong to one book, and the ones "
            "handed in have no book_id. Load them with "
            "agent.guardrails.load_book_guardrails() so they carry one, or build "
            "the counter directly with DayTradeCounter(book_id=...)."
        )
    schedule = getattr(book_config, "schedule", None)
    holidays = getattr(schedule, "holidays", None)
    store_path = store_path_for(book_id, store_dir) if store_dir is not None else None

    regime, treat_unknown_as = settings_regime()
    section = getattr(book_config, "pdt", None)
    declared = getattr(section, "regime", None)
    if declared is not None:
        regime = as_regime(declared, "pdt.regime")
    declared_fallback = getattr(section, "treat_unknown_as", None)
    if declared_fallback is not None:
        treat_unknown_as = as_regime(declared_fallback, "pdt.treat_unknown_as")

    return DayTradeCounter(
        book_id=book_id,
        store_path=store_path,
        holidays=holidays,
        regime=regime,
        treat_unknown_as=treat_unknown_as,
    )


# ---------------------------------------------------------------------------
# The counter itself
# ---------------------------------------------------------------------------


class DayTradeCounter:
    """One book's rolling count of day trades, kept in a small file on disk.

    Build one per book. It loads whatever is already in the file, records every
    fill the loop reports, and answers the two questions the loop needs: how
    many day trades this book has made in the last five business days, and
    whether the order it is about to send would make another one.
    """

    def __init__(
        self,
        book_id: str,
        store_path: str | Path | None = None,
        holidays: Iterable[date] | None = None,
        regime=None,
        treat_unknown_as=None,
    ) -> None:
        """Start counting for one book, reading anything already on disk.

        book_id is the short id such as "A". store_path defaults to
        output/pdt_BOOK_<book id>.json, and a path handed in is used exactly as
        given. holidays is the list of days the market is shut, which the five
        business day window skips over.

        regime is which day trading rulebook the account is under, and it is
        only a default: settings handed to check() win over it. Left alone it is
        unknown, which treat_unknown_as turns into old_pdt, so a counter built
        the way every counter was built before 2026-09-06 behaves exactly as it
        did. Nothing here reads a file or asks a broker to find out; use
        counter_for() for that, or settings_regime().

        A missing file is not a problem: the count simply starts from nothing. A
        file that cannot be read, or that does not hold what this code expects,
        raises a ValueError naming the file and saying what to do about it.
        """
        self.book_id = _clean_book_id(book_id, "book_id")
        self.store_path = (
            Path(store_path).expanduser()
            if store_path is not None
            else store_path_for(self.book_id)
        )
        self.holidays = _clean_holidays(holidays)
        self.regime = as_regime(regime, "regime")
        self.treat_unknown_as = (
            DEFAULT_TREAT_UNKNOWN_AS
            if treat_unknown_as is None
            else as_regime(treat_unknown_as, "treat_unknown_as")
        )
        if self.treat_unknown_as is Regime.UNKNOWN:
            self.treat_unknown_as = DEFAULT_TREAT_UNKNOWN_AS
        self._fills: list[_Fill] = []
        self._fill_ids: set[str] = set()
        self._load()

    # -- recording ---------------------------------------------------------

    def record_fill(
        self,
        symbol: str,
        side: str,
        qty: int,
        ts: datetime,
        fill_id: str | None = None,
    ) -> None:
        """Write down one fill, and save the file straight away.

        side is BUY or SELL and is read whatever case it is typed in. qty is a
        whole number of shares above zero: to sell, use side SELL, never a
        negative quantity. ts has to carry a timezone, because which trading day
        a fill belongs to depends on it, and it is converted to New York time
        before the day is taken.

        fill_id is optional and is the broker's own id for the fill. When it is
        given, recording the same id a second time does nothing at all, so a
        loop that restarts and replays the fills it already saw cannot count
        them twice.
        """
        clean_symbol = _clean_symbol(symbol, "symbol")
        clean_side = _clean_side(side, "side")
        clean_qty = _whole_number_above_zero(qty, "qty")
        moment = _require_aware(ts, "ts").astimezone(NEW_YORK)
        clean_fill_id = _clean_fill_id(fill_id)

        if clean_fill_id is not None and clean_fill_id in self._fill_ids:
            return

        self._fills.append(
            _Fill(
                symbol=clean_symbol,
                side=clean_side,
                qty=clean_qty,
                ts=moment,
                trade_date=moment.date(),
                fill_id=clean_fill_id,
            )
        )
        if clean_fill_id is not None:
            self._fill_ids.add(clean_fill_id)
        self._save()

    # -- counting ----------------------------------------------------------

    def count_last_5_business_days(self, today: date) -> int:
        """How many day trades this book has made in the window ending today.

        The window is the five business days ending on today inclusive, so today
        plus the four business days before it. Weekends and any holiday handed
        to the constructor are skipped over, which is why day trades made on a
        Friday still count on the Thursday after.
        """
        day = _as_plain_date(today, "today")
        window = business_days_back(day, WINDOW_BUSINESS_DAYS, self.holidays)
        return sum(self._day_trades_on(one_day) for one_day in window)

    def would_be_day_trade(self, symbol: str, side: str, today: date) -> bool:
        """True when a fill on this side today would close something opened today.

        If the day's fills leave the book holding 100 shares of AAPL it opened
        this morning, then a SELL is true and another BUY is false. If nothing in
        that symbol was opened today, both sides are false, because there is
        nothing a fill today could close.
        """
        clean_symbol = _clean_symbol(symbol, "symbol")
        clean_side = _clean_side(side, "side")
        day = _as_plain_date(today, "today")

        opened = self._opened_today(clean_symbol, day)
        if opened == 0:
            return False
        return _points_the_other_way(opened, 1 if clean_side == "BUY" else -1)

    # -- the check the loop calls -----------------------------------------

    def effective_regime(self, book_config=None) -> Regime:
        """Which rulebook this counter is answering under, with unknown resolved.

        pdt.regime on the settings wins when they carry one, the counter's own
        regime is next, and unknown becomes pdt.treat_unknown_as, which ships as
        old_pdt. So a counter and settings that say nothing at all give old_pdt,
        which is how this file behaved before the two regimes existed.
        """
        section = getattr(book_config, "pdt", None)
        declared = getattr(section, "regime", None)
        regime = (
            as_regime(declared, "pdt.regime")
            if declared is not None
            else self.regime
        )

        if regime is not Regime.UNKNOWN:
            return regime

        fallback = getattr(section, "treat_unknown_as", None)
        if fallback is not None:
            resolved = as_regime(fallback, "pdt.treat_unknown_as")
        else:
            resolved = self.treat_unknown_as
        return DEFAULT_TREAT_UNKNOWN_AS if resolved is Regime.UNKNOWN else resolved

    def check(self, book_config, intent, today: date, state=None) -> PdtDecision:
        """Decide whether one order may go, as far as the day trader rule cares.

        book_config is what agent.guardrails.load_book_guardrails() hands back
        for this book, and intent is an agent.guardrails.OrderIntent. Both are
        read with getattr and nothing is imported from guardrails here, so a
        plain stand in object with the same shape works just as well. Three
        settings are read: pdt.hard_limit, pdt.max_day_trades_per_5_days and
        book_id. A book with no pdt section at all is treated as having no hard
        limit and an allowance of three, which is the safe reading.

        The logic is short. If the order would not be a day trade, it is allowed
        and nothing is flagged. If it would be, and the book has already used up
        its allowance in the five business days ending today, then this order
        would be the fourth day trade (or later) in five business days. On a book
        with the hard limit set, it is refused. On a book without, it is allowed
        and the note is written down instead.

        One thing worth knowing: this is the only check in the project that can
        refuse an order that closes a position. That is deliberate, because on
        the insider and Congress books the closing order is the day trade, and
        those two books are not meant to be closing anything the same day they
        opened it.

        All of that is the old rulebook, and it only runs when the regime is
        old_pdt. Under new_imd the count is still worked out and still put on
        the answer, because the ledger wants it, but nothing is refused for it
        and would_have_blocked stays false: FINRA retired the rule those
        refusals were protecting against. What runs in its place is
        imd_check() from agent/margin_regime.py, which refuses an entry that
        could leave the account short of margin during the day.

        state is the account snapshot, the same agent.guardrails.AccountState
        the other checks get, and it is only needed under new_imd. Left out, the
        deficit check says so in note and refuses nothing, because the gross
        exposure cap in agent/guardrails.py runs on every order anyway.
        """
        hard_limit, limit = _pdt_settings(book_config)
        book_id = getattr(book_config, "book_id", None) or self.book_id
        symbol = _clean_symbol(getattr(intent, "symbol", None), "intent.symbol")
        side = _clean_side(getattr(intent, "side", None), "intent.side")
        day = _as_plain_date(today, "today")
        regime = self.effective_regime(book_config)

        decision = PdtDecision(
            allowed=True,
            day_trades_used=self.count_last_5_business_days(day),
            limit=limit,
            hard_limit=hard_limit,
            symbol=symbol,
            regime=regime,
        )

        if regime is Regime.NEW_IMD:
            return self._check_new_imd(decision, book_config, intent, state)

        if not self.would_be_day_trade(symbol, side, day):
            return decision
        if decision.day_trades_used < limit:
            return decision

        used = decision.day_trades_used
        if hard_limit:
            decision.allowed = False
            decision.rule_ids.append(RULE_ID_PDT_LIMIT)
            decision.reasons.append(_refusal_sentence(book_id, symbol, side, used))
        else:
            decision.would_have_blocked = True
            decision.reasons.append(_note_sentence(book_id, symbol, side, used))
        return decision

    def _check_new_imd(
        self, decision: PdtDecision, book_config, intent, state
    ) -> PdtDecision:
        """The new rulebook: count for the record, refuse only a margin deficit.

        The count already on the decision stays there and goes to the ledger, so
        the month can still be read against what the old rule would have cost.
        It just does not decide anything any more.
        """
        verdict = imd_check(book_config, state, intent)
        decision.note = verdict.note
        if verdict.allowed:
            return decision
        decision.allowed = False
        decision.rule_ids.extend(verdict.rule_ids)
        decision.reasons.extend(verdict.reasons)
        return decision

    # -- the working out ---------------------------------------------------

    def _fills_on(self, day: date, symbol: str | None = None) -> list[_Fill]:
        """One day's fills, oldest first, for one symbol or for all of them."""
        chosen = [
            fill
            for fill in self._fills
            if fill.trade_date == day and (symbol is None or fill.symbol == symbol)
        ]
        return sorted(chosen, key=lambda fill: fill.ts)

    def _day_trades_on(self, day: date) -> int:
        """How many day trades this book made on one trading day, across all names."""
        fills_today = self._fills_on(day)
        if not fills_today:
            return 0
        symbols = sorted({fill.symbol for fill in fills_today})
        return sum(
            _count_symbol_day([fill for fill in fills_today if fill.symbol == symbol])
            for symbol in symbols
        )

    def _opened_today(self, symbol: str, day: date) -> int:
        """Shares of one symbol opened today and still open, as a signed number.

        Positive means the book bought them today and still holds them. Negative
        means it shorted them today and has not covered. Zero means today's
        fills in that name have cancelled out, or there were none.
        """
        opened = 0
        for fill in self._fills_on(day, symbol):
            opened += fill.qty if fill.side == "BUY" else -fill.qty
        return opened

    # -- the file on disk --------------------------------------------------

    def _load(self) -> None:
        """Read the file if it is there, and complain clearly if it is broken."""
        if not self.store_path.exists():
            return
        if self.store_path.is_dir():
            raise ValueError(
                f"The day trade file {self.store_path} is a folder, not a file. "
                "Move it out of the way and try again."
            )

        try:
            raw_text = self.store_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"The day trade file {self.store_path} could not be read: {exc}. "
                "Fix the permissions on it, or delete it and the count starts "
                "again from nothing."
            ) from exc

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"The day trade file {self.store_path} is not valid JSON. The "
                f"reader said: {exc}. Fix the file by hand, or delete it and the "
                "count starts again from nothing, which loses this book's day "
                "trade history."
            ) from exc

        self._fills = []
        self._fill_ids = set()
        for fill in _fills_from_data(data, self.store_path, self.book_id):
            self._fills.append(fill)
            if fill.fill_id is not None:
                self._fill_ids.add(fill.fill_id)

    def _save(self) -> None:
        """Write the file safely: a temporary file first, then swap it in.

        Old fills are dropped on the way out, so the file stays small enough to
        read. Writing a temporary file in the same folder and then replacing the
        real one means a crash halfway through leaves the old file untouched
        rather than half a new one.
        """
        self._prune()
        payload = {
            "book_id": self.book_id,
            "version": STORE_VERSION,
            "fills": [_fill_to_json(fill) for fill in self._fills],
        }

        folder = self.store_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=folder,
            prefix=self.store_path.name + ".",
            suffix=".tmp",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.store_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _prune(self) -> None:
        """Forget fills older than 60 calendar days before the newest one."""
        if not self._fills:
            return
        newest = max(fill.trade_date for fill in self._fills)
        oldest_kept = newest - timedelta(days=KEEP_FILL_DAYS)
        kept = [fill for fill in self._fills if fill.trade_date >= oldest_kept]
        if len(kept) == len(self._fills):
            return
        self._fills = kept
        self._fill_ids = {
            fill.fill_id for fill in kept if fill.fill_id is not None
        }


# ---------------------------------------------------------------------------
# The counting rule, on its own so it can be read in one sitting
# ---------------------------------------------------------------------------


def _count_symbol_day(fills: list[_Fill]) -> int:
    """How many day trades one symbol's fills add up to on one trading day.

    Walk the fills in the order they happened, tracking only the shares opened
    that same day. A fill that moves that number away from zero is opening
    something. A fill that moves it back towards zero is closing something the
    book opened today, and that is one day trade, whether it closes ten shares
    or a thousand. A fill big enough to cross straight through zero counts as
    the one day trade and leaves the rest of itself open as a new position.
    """
    day_trades = 0
    opened = 0
    for fill in fills:
        signed = fill.qty if fill.side == "BUY" else -fill.qty
        if opened != 0 and _points_the_other_way(opened, signed):
            day_trades += 1
        opened += signed
    return day_trades


def _points_the_other_way(opened: int, signed: int) -> bool:
    """True when a fill points against what the book opened today.

    Neither number is ever zero when this is asked, so comparing which side of
    zero each one sits on is the whole test.
    """
    return (opened > 0) != (signed > 0)


def _pdt_settings(book_config) -> tuple[bool, int]:
    """Read the two pdt settings off whatever object we were handed.

    Read with getattr rather than by importing anything, so a plain stand in
    object with a pdt section works exactly like the real thing. A book with no
    pdt section is treated as having no hard limit and an allowance of three,
    which is the reading that neither blocks a momentum book nor lets a
    hold-for-weeks book day trade freely by accident.
    """
    section = getattr(book_config, "pdt", None)
    if section is None:
        return False, DEFAULT_MAX_DAY_TRADES_PER_5_DAYS

    hard_limit = getattr(section, "hard_limit", False)
    if hard_limit is None:
        hard_limit = False
    if not isinstance(hard_limit, bool):
        raise ValueError(
            f"The setting pdt.hard_limit is {hard_limit!r}, and it has to be true "
            "or false. True means this book refuses a day trade over the limit, "
            "false means it makes a note of it and carries on."
        )

    limit = getattr(section, "max_day_trades_per_5_days", None)
    if limit is None:
        return bool(hard_limit), DEFAULT_MAX_DAY_TRADES_PER_5_DAYS
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError(
            f"The setting pdt.max_day_trades_per_5_days is {limit!r}, and it has "
            "to be a whole number of day trades, zero or more. Three is the "
            "number in the shipped settings."
        )
    return bool(hard_limit), int(limit)


def _refusal_sentence(book_id: str, symbol: str, side: str, used: int) -> str:
    """Why a hold-for-weeks book will not make another day trade this week."""
    return (
        f"Book {book_id} is meant to hold positions for weeks, and it has already "
        f"made {used} day trades in the last five business days. This "
        f"{side} order would close {symbol} on the same day the book opened it, "
        f"which would be day trade number {used + 1}, and four or more in five "
        "business days is what makes a live account a pattern day trader. Such an "
        f"account has to hold at least {_dollars(PDT_EQUITY_MINIMUM_USD)}, or it "
        "loses the right to day trade for 90 days. The paper account would have "
        "allowed this, so the book counts for itself. Nothing was sent."
    )


def _note_sentence(book_id: str, symbol: str, side: str, used: int) -> str:
    """The same fact, written down rather than acted on, for a momentum book."""
    return (
        f"Book {book_id} has already made {used} day trades in the last five "
        f"business days, and this {side} order would close {symbol} on the same "
        f"day the book opened it, which makes day trade number {used + 1}. A live "
        f"account holding less than {_dollars(PDT_EQUITY_MINIMUM_USD)} would have "
        "been blocked here. Day trading is this book's whole strategy, so the "
        "order goes out and this note is kept instead, which is how the cost of "
        "the rule gets measured at the end of the month rather than guessed at."
    )


def _dollars(value: float) -> str:
    """25,000 dollars, written the way a person says it."""
    return f"{value:,.0f} dollars"


# ---------------------------------------------------------------------------
# Reading the file back in
# ---------------------------------------------------------------------------


def _fills_from_data(data, where: Path, book_id: str) -> list[_Fill]:
    """Turn what was in the file into fills, refusing anything odd."""
    if not isinstance(data, dict):
        raise ValueError(
            f"The day trade file {where} should hold a list of named things, "
            f"book_id, version and fills, but it holds a {type(data).__name__}. "
            "Delete it and the count starts again from nothing."
        )

    stored_book = data.get("book_id")
    if isinstance(stored_book, str) and stored_book.strip().upper() != book_id:
        raise ValueError(
            f"The day trade file {where} belongs to book "
            f"{stored_book.strip().upper()}, but it was opened as book {book_id}. "
            "Every book counts its own day trades, so point this counter at that "
            "book's own file instead."
        )

    raw_fills = data.get("fills")
    if raw_fills is None:
        return []
    if not isinstance(raw_fills, list):
        raise ValueError(
            f"The fills section of the day trade file {where} should be a list of "
            f"fills, but it is a {type(raw_fills).__name__}. Delete the file and "
            "the count starts again from nothing."
        )

    fills: list[_Fill] = []
    for number, raw in enumerate(raw_fills, start=1):
        fills.append(_fill_from_json(raw, where, number))
    return fills


def _fill_from_json(raw, where: Path, number: int) -> _Fill:
    """One fill out of the file, checked the same way a fresh one is."""
    label = f"fill number {number} in the day trade file {where}"
    if not isinstance(raw, dict):
        raise ValueError(
            f"{label} should hold a symbol, a side, a quantity and a time, but it "
            f"is a {type(raw).__name__}. Delete the file and the count starts "
            "again from nothing."
        )
    for key in ("symbol", "side", "qty", "ts"):
        if key not in raw:
            raise ValueError(
                f"{label} has no {key}. Every fill needs a symbol, a side, a qty "
                "and a ts. Delete the file and the count starts again from "
                "nothing."
            )

    raw_ts = raw["ts"]
    if not isinstance(raw_ts, str):
        raise ValueError(
            f"The ts of {label} should be a time written as "
            f"2026-09-04T09:40:00-04:00, but it is {raw_ts!r}."
        )
    try:
        moment = datetime.fromisoformat(raw_ts)
    except ValueError as exc:
        raise ValueError(
            f"The ts of {label} is {raw_ts!r}, which is not a time this code can "
            "read. Write it as 2026-09-04T09:40:00-04:00, with the timezone on "
            "the end."
        ) from exc
    moment = _require_aware(moment, f"the ts of {label}").astimezone(NEW_YORK)

    return _Fill(
        symbol=_clean_symbol(raw["symbol"], f"the symbol of {label}"),
        side=_clean_side(raw["side"], f"the side of {label}"),
        qty=_whole_number_above_zero(raw["qty"], f"the qty of {label}"),
        ts=moment,
        trade_date=moment.date(),
        fill_id=_clean_fill_id(raw.get("fill_id")),
    )


def _fill_to_json(fill: _Fill) -> dict:
    """One fill on its way out to the file, in the order a person reads it."""
    return {
        "symbol": fill.symbol,
        "side": fill.side,
        "qty": fill.qty,
        "ts": fill.ts.isoformat(),
        "trade_date": fill.trade_date.isoformat(),
        "fill_id": fill.fill_id,
    }


# ---------------------------------------------------------------------------
# Small validators. Every message says what is wrong and what to do about it.
# ---------------------------------------------------------------------------


def _clean_symbol(symbol, label: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(f"{label} has to be a symbol such as AAPL, not {symbol!r}.")
    return symbol.strip().upper()


def _clean_side(side, label: str) -> str:
    if not isinstance(side, str):
        raise ValueError(
            f"{label} has to be the word BUY or the word SELL, not {side!r}."
        )
    cleaned = side.strip().upper()
    if cleaned not in VALID_SIDES:
        raise ValueError(
            f"{label} has to be BUY or SELL, not {side!r}. A short is a SELL and "
            "covering it is a BUY."
        )
    return cleaned


def _clean_book_id(book_id, label: str) -> str:
    """Book ids are short and upper case, so A and " a " mean the same book."""
    if not isinstance(book_id, str) or not book_id.strip():
        raise ValueError(f"{label} has to be a book id such as A, not {book_id!r}.")
    cleaned = book_id.strip().upper()
    if not _BOOK_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"{label} is {book_id!r}, which is not a book id. Use a short one such "
            "as A, B or C, because it becomes part of the file name."
        )
    return cleaned


def _clean_fill_id(fill_id) -> str | None:
    """The broker's id for a fill, or None when there is not one."""
    if fill_id is None:
        return None
    if not isinstance(fill_id, (str, int)) or isinstance(fill_id, bool):
        raise ValueError(
            f"fill_id has to be the broker's id for the fill, written as text, "
            f"not {fill_id!r}. Leave it out if there is not one."
        )
    cleaned = str(fill_id).strip()
    if not cleaned:
        raise ValueError(
            "fill_id is empty. Leave it out altogether if the fill has no id, "
            "because an empty one cannot tell two fills apart."
        )
    return cleaned


def _whole_number_above_zero(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{label} has to be a whole number, not {value!r}. To sell, use side "
            "SELL rather than a negative quantity."
        )
    if value <= 0:
        raise ValueError(
            f"{label} is {value}, and it has to be more than zero. To sell, use "
            "side SELL rather than a negative quantity."
        )
    return int(value)


def _require_aware(moment, label: str) -> datetime:
    """A moment in time that says which timezone it is in. Nothing is guessed."""
    if not isinstance(moment, datetime):
        raise ValueError(
            f"{label} has to be a date and time, but it is "
            f"{type(moment).__name__}."
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{label} is {moment.isoformat()}, which carries no timezone. This "
            "code will not guess whether that means New York, London or UTC, and "
            "the answer decides which trading day the fill counts against. Build "
            "the time with a timezone, for example datetime(2026, 9, 4, 9, 40, "
            'tzinfo=ZoneInfo("America/New_York")).'
        )
    return moment


def _as_plain_date(value, label: str) -> date:
    """A calendar date.

    A full date and time is accepted as long as it carries a timezone, and it is
    read in New York, because that is the market's clock. A date written as text,
    such as "2026-09-04", is accepted too, which is what a holiday list read out
    of a yaml file often looks like.
    """
    if isinstance(value, datetime):
        return _require_aware(value, label).astimezone(NEW_YORK).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"{label} is {value!r}, which is not a date this code can read. "
                "Write it as 2026-09-04."
            ) from exc
    raise ValueError(
        f"{label} has to be a date such as date(2026, 9, 4), but it is a "
        f"{type(value).__name__}."
    )


def _is_business_day(day: date, holidays: frozenset[date]) -> bool:
    """Monday to Friday, and not one of the days the market is shut."""
    return day.weekday() < 5 and day not in holidays


def _clean_holidays(holidays) -> frozenset[date]:
    """The days the market is shut, as a set of plain dates."""
    if holidays is None:
        return frozenset()
    if isinstance(holidays, (str, bytes)):
        raise ValueError(
            f"holidays has to be a list of dates such as [date(2026, 9, 7)], but "
            f"it is the single piece of text {holidays!r}."
        )
    return frozenset(
        _as_plain_date(item, "a date in the holidays list") for item in holidays
    )
