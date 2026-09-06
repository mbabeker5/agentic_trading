"""Tests for the day trade counter in agent/pdt.py.

The pattern day trader rule says four or more round trip day trades in five
business days, in a margin account, makes you a pattern day trader, and that
account then has to hold at least 25,000 dollars. The IBKR paper account this
project runs on ignores the rule, so agent/pdt.py counts day trades itself.
These tests are about that counting: what is a day trade and what is not, how
the five business day window slides over a weekend and over a holiday, which
books get refused and which only get a note, and that the count survives a
restart.

Nothing here touches the network, IB Gateway or a broker account, and nothing
here writes into the project's output folder: every counter is given a file
inside the test's own tmp_path.

Nothing here loads the real settings either. Another agent is adding the pdt
section to agent/guardrails.py right now, so the book settings and the order
below are small stand in objects with the same shape. agent/pdt.py reads both
with getattr, which is exactly what these prove.

Dates are in September 2026: 2026-09-04 is a Friday, 2026-09-05 a Saturday,
2026-09-06 a Sunday and 2026-09-07 a Monday.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent.pdt import (
    DEFAULT_MAX_DAY_TRADES_PER_5_DAYS,
    RULE_ID_PDT_LIMIT,
    DayTradeCounter,
    business_days_back,
    counter_for,
)

EASTERN = ZoneInfo("America/New_York")

# The days these tests lean on, written out so the arithmetic can be read.
THURSDAY_3 = date(2026, 9, 3)
FRIDAY_4 = date(2026, 9, 4)
SATURDAY_5 = date(2026, 9, 5)
MONDAY_7 = date(2026, 9, 7)
TUESDAY_8 = date(2026, 9, 8)
WEDNESDAY_9 = date(2026, 9, 9)
THURSDAY_10 = date(2026, 9, 10)
FRIDAY_11 = date(2026, 9, 11)
MONDAY_14 = date(2026, 9, 14)

# Labor Day 2026 falls on Monday 2026-09-07, so the US market is shut that day.
LABOR_DAY = MONDAY_7


# ---------------------------------------------------------------------------
# Helpers, and the stand in objects that play the part of the real settings
# ---------------------------------------------------------------------------


def et(day: int, hour: int, minute: int, month: int = 9, year: int = 2026) -> datetime:
    """A New York time. 2026-09-04 is a Friday."""
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN)


@dataclass(frozen=True)
class FakePdtSettings:
    """Stands in for the pdt section being added to agent/guardrails.py."""

    hard_limit: bool
    max_day_trades_per_5_days: int = 3


@dataclass(frozen=True)
class FakeSchedule:
    """Stands in for the schedule section, which may carry a holiday list."""

    holidays: tuple[date, ...] = ()


@dataclass(frozen=True)
class FakeBook:
    """Stands in for what load_book_guardrails() hands back for one book."""

    book_id: str
    pdt: FakePdtSettings | None = None
    schedule: FakeSchedule | None = None


@dataclass(frozen=True)
class FakeIntent:
    """Stands in for an agent.guardrails.OrderIntent."""

    symbol: str
    side: str
    qty: int = 100
    purpose: str = "exit"

    @property
    def is_closing(self) -> bool:
        return self.purpose in ("exit", "stop", "flatten")


# Book C, the insider book: holds for weeks, so a fourth day trade is refused.
INSIDER_BOOK = FakeBook(book_id="C", pdt=FakePdtSettings(hard_limit=True))

# Book A, a momentum book: day trading is the strategy, so it is never blocked.
MOMENTUM_BOOK = FakeBook(book_id="A", pdt=FakePdtSettings(hard_limit=False))


def make_counter(
    tmp_path: Path, book_id: str = "A", holidays=None
) -> DayTradeCounter:
    """A counter whose file lives in the test's own folder, never in output/."""
    return DayTradeCounter(
        book_id=book_id,
        store_path=tmp_path / f"pdt_BOOK_{book_id}.json",
        holidays=holidays,
    )


def round_trip(
    counter: DayTradeCounter,
    symbol: str,
    day: int,
    qty: int = 100,
    first: str = "BUY",
) -> None:
    """One opening fill in the morning and one closing fill in the afternoon."""
    second = "SELL" if first == "BUY" else "BUY"
    counter.record_fill(symbol, first, qty, et(day, 10, 0))
    counter.record_fill(symbol, second, qty, et(day, 14, 0))


def use_up_the_allowance(counter: DayTradeCounter, day: int, how_many: int) -> None:
    """Make a given number of day trades on one day, one per symbol."""
    for symbol in ("AAPL", "MSFT", "NVDA", "AMZN", "META")[:how_many]:
        round_trip(counter, symbol, day)


# ---------------------------------------------------------------------------
# What counts as a day trade and what does not
# ---------------------------------------------------------------------------


def test_a_buy_then_a_sell_of_the_same_symbol_on_the_same_day_is_one_day_trade(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("AAPL", "BUY", 100, et(4, 10, 0))
    counter.record_fill("AAPL", "SELL", 100, et(4, 15, 0))

    assert counter.count_last_5_business_days(FRIDAY_4) == 1


def test_a_buy_on_one_day_and_a_sell_the_next_day_is_not_a_day_trade(tmp_path: Path):
    counter = make_counter(tmp_path)
    counter.record_fill("AAPL", "BUY", 100, et(3, 10, 0))
    counter.record_fill("AAPL", "SELL", 100, et(4, 10, 0))

    assert counter.count_last_5_business_days(FRIDAY_4) == 0


def test_two_separate_round_trips_in_the_same_symbol_on_the_same_day_count_as_two(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("AAPL", "BUY", 100, et(4, 9, 40))
    counter.record_fill("AAPL", "SELL", 100, et(4, 10, 15))
    counter.record_fill("AAPL", "BUY", 100, et(4, 13, 0))
    counter.record_fill("AAPL", "SELL", 100, et(4, 15, 30))

    assert counter.count_last_5_business_days(FRIDAY_4) == 2


def test_a_short_then_a_cover_on_the_same_day_is_a_day_trade_too(tmp_path: Path):
    counter = make_counter(tmp_path)
    counter.record_fill("TSLA", "SELL", 50, et(4, 10, 0))
    counter.record_fill("TSLA", "BUY", 50, et(4, 14, 0))

    assert counter.count_last_5_business_days(FRIDAY_4) == 1


def test_selling_a_position_carried_in_from_yesterday_is_not_a_day_trade(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("MSFT", "BUY", 200, et(3, 11, 0))
    counter.record_fill("MSFT", "SELL", 200, et(4, 9, 45))

    assert counter.count_last_5_business_days(FRIDAY_4) == 0
    assert counter.count_last_5_business_days(THURSDAY_3) == 0


def test_a_fill_that_crosses_through_zero_counts_one_day_trade_and_leaves_the_rest_open(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("NVDA", "BUY", 100, et(4, 10, 0))
    counter.record_fill("NVDA", "SELL", 150, et(4, 14, 0))

    assert counter.count_last_5_business_days(FRIDAY_4) == 1
    # The 50 shares left over are a short opened today, so buying them back
    # would close something opened today.
    assert counter.would_be_day_trade("NVDA", "BUY", FRIDAY_4) is True


def test_one_closing_fill_is_one_day_trade_however_many_shares_it_sells(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("AAPL", "BUY", 100, et(4, 9, 40))
    counter.record_fill("AAPL", "BUY", 300, et(4, 10, 5))
    counter.record_fill("AAPL", "SELL", 400, et(4, 15, 0))

    assert counter.count_last_5_business_days(FRIDAY_4) == 1


# ---------------------------------------------------------------------------
# The five business day window
# ---------------------------------------------------------------------------


def test_business_days_back_skips_the_weekend_and_hands_the_days_back_oldest_first():
    assert business_days_back(THURSDAY_10, 5) == [
        FRIDAY_4,
        MONDAY_7,
        TUESDAY_8,
        WEDNESDAY_9,
        THURSDAY_10,
    ]
    # Asked on a Saturday, the window is the five business days before it.
    assert business_days_back(SATURDAY_5, 1) == [FRIDAY_4]


def test_day_trades_on_the_friday_still_count_on_the_thursday_and_drop_out_on_the_friday(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    round_trip(counter, "AAPL", day=4)

    # Five business days ending Thursday 2026-09-10 reach back over the weekend
    # to Friday 2026-09-04, so the day trade is still inside the window.
    assert business_days_back(THURSDAY_10, 5) == [
        FRIDAY_4,
        MONDAY_7,
        TUESDAY_8,
        WEDNESDAY_9,
        THURSDAY_10,
    ]
    assert counter.count_last_5_business_days(THURSDAY_10) == 1

    # One business day later the window starts on the Monday, and the Friday has
    # fallen out of the back of it.
    assert business_days_back(FRIDAY_11, 5) == [
        MONDAY_7,
        TUESDAY_8,
        WEDNESDAY_9,
        THURSDAY_10,
        FRIDAY_11,
    ]
    assert counter.count_last_5_business_days(FRIDAY_11) == 0


def test_a_holiday_in_the_window_keeps_the_same_day_trades_inside_it_one_day_longer(
    tmp_path: Path,
):
    counter = make_counter(tmp_path, holidays=[LABOR_DAY])
    round_trip(counter, "AAPL", day=4)

    # With Monday 2026-09-07 shut, the window ending on Friday 2026-09-11 has to
    # reach one day further back, so it still holds Friday 2026-09-04. Without
    # the holiday that same Friday had already dropped out.
    assert business_days_back(FRIDAY_11, 5, [LABOR_DAY]) == [
        FRIDAY_4,
        TUESDAY_8,
        WEDNESDAY_9,
        THURSDAY_10,
        FRIDAY_11,
    ]
    assert counter.count_last_5_business_days(FRIDAY_11) == 1

    # It drops out on the next business day, Monday 2026-09-14.
    assert business_days_back(MONDAY_14, 5, [LABOR_DAY]) == [
        TUESDAY_8,
        WEDNESDAY_9,
        THURSDAY_10,
        FRIDAY_11,
        MONDAY_14,
    ]
    assert counter.count_last_5_business_days(MONDAY_14) == 0


# ---------------------------------------------------------------------------
# Would the next order be a day trade
# ---------------------------------------------------------------------------


def test_would_be_day_trade_is_true_for_the_closing_side_and_false_for_the_opening_side(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    counter.record_fill("AAPL", "BUY", 100, et(4, 10, 0))

    assert counter.would_be_day_trade("AAPL", "SELL", FRIDAY_4) is True
    assert counter.would_be_day_trade("AAPL", "BUY", FRIDAY_4) is False
    # A short opened today is the mirror image of a long opened today.
    counter.record_fill("TSLA", "SELL", 100, et(4, 10, 30))
    assert counter.would_be_day_trade("TSLA", "BUY", FRIDAY_4) is True
    assert counter.would_be_day_trade("TSLA", "SELL", FRIDAY_4) is False


def test_would_be_day_trade_is_false_when_nothing_at_all_was_opened_today(
    tmp_path: Path,
):
    counter = make_counter(tmp_path)
    # Bought yesterday and still held, so today's fills opened nothing.
    counter.record_fill("AAPL", "BUY", 100, et(3, 10, 0))

    assert counter.would_be_day_trade("AAPL", "SELL", FRIDAY_4) is False
    assert counter.would_be_day_trade("AAPL", "BUY", FRIDAY_4) is False
    assert counter.would_be_day_trade("GOOG", "SELL", FRIDAY_4) is False


# ---------------------------------------------------------------------------
# The check the trading loop calls
# ---------------------------------------------------------------------------


def test_the_hard_limit_blocks_the_fourth_day_trade_on_the_insider_book(
    tmp_path: Path,
):
    counter = make_counter(tmp_path, book_id="C")
    use_up_the_allowance(counter, day=7, how_many=3)
    counter.record_fill("TSLA", "BUY", 100, et(7, 11, 0))

    decision = counter.check(
        INSIDER_BOOK, FakeIntent(symbol="TSLA", side="SELL"), MONDAY_7
    )

    assert decision.allowed is False
    assert decision.rule_ids == [RULE_ID_PDT_LIMIT]
    assert decision.day_trades_used == 3
    assert decision.limit == 3
    assert decision.hard_limit is True
    assert decision.symbol == "TSLA"
    assert len(decision.reasons) == 1
    assert "pattern day trader" in decision.reasons[0]
    assert decision.summary.startswith("blocked:")


def test_the_third_day_trade_is_still_allowed_on_the_insider_book(tmp_path: Path):
    counter = make_counter(tmp_path, book_id="C")
    use_up_the_allowance(counter, day=7, how_many=2)
    counter.record_fill("TSLA", "BUY", 100, et(7, 11, 0))

    decision = counter.check(
        INSIDER_BOOK, FakeIntent(symbol="TSLA", side="SELL"), MONDAY_7
    )

    assert decision.allowed is True
    assert decision.would_have_blocked is False
    assert decision.rule_ids == []
    assert decision.reasons == []
    assert decision.day_trades_used == 2
    assert decision.summary == "allowed"


def test_the_momentum_book_is_never_blocked_but_records_what_the_rule_would_cost(
    tmp_path: Path,
):
    counter = make_counter(tmp_path, book_id="A")
    use_up_the_allowance(counter, day=7, how_many=3)
    counter.record_fill("TSLA", "BUY", 100, et(7, 11, 0))

    decision = counter.check(
        MOMENTUM_BOOK, FakeIntent(symbol="TSLA", side="SELL"), MONDAY_7
    )

    assert decision.allowed is True
    assert decision.would_have_blocked is True
    assert decision.hard_limit is False
    assert decision.day_trades_used == 3
    assert decision.rule_ids == []
    assert len(decision.reasons) == 1
    assert "25,000 dollars" in decision.reasons[0]
    assert decision.summary.startswith("allowed, but a live account")


def test_an_order_that_is_not_a_day_trade_at_all_is_allowed_even_over_the_limit(
    tmp_path: Path,
):
    counter = make_counter(tmp_path, book_id="C")
    use_up_the_allowance(counter, day=7, how_many=4)

    # Nothing in GOOG was opened today, so buying it cannot close anything.
    decision = counter.check(
        INSIDER_BOOK, FakeIntent(symbol="GOOG", side="BUY", purpose="entry"), MONDAY_7
    )

    assert decision.allowed is True
    assert decision.would_have_blocked is False
    assert decision.rule_ids == []
    assert decision.reasons == []
    assert decision.day_trades_used == 4


def test_a_book_with_no_pdt_section_gets_no_hard_limit_and_an_allowance_of_three(
    tmp_path: Path,
):
    counter = make_counter(tmp_path, book_id="B")
    use_up_the_allowance(counter, day=7, how_many=3)
    counter.record_fill("TSLA", "BUY", 100, et(7, 11, 0))

    decision = counter.check(
        FakeBook(book_id="B"), FakeIntent(symbol="TSLA", side="SELL"), MONDAY_7
    )

    assert decision.limit == DEFAULT_MAX_DAY_TRADES_PER_5_DAYS
    assert decision.hard_limit is False
    assert decision.allowed is True
    assert decision.would_have_blocked is True


# ---------------------------------------------------------------------------
# The file on disk
# ---------------------------------------------------------------------------


def test_fills_persist_so_a_second_counter_on_the_same_file_still_counts_them(
    tmp_path: Path,
):
    store = tmp_path / "pdt_BOOK_A.json"
    first = DayTradeCounter(book_id="A", store_path=store)
    round_trip(first, "AAPL", day=4)
    round_trip(first, "MSFT", day=4)

    second = DayTradeCounter(book_id="A", store_path=store)

    assert second.count_last_5_business_days(FRIDAY_4) == 2
    assert second.would_be_day_trade("AAPL", "SELL", FRIDAY_4) is False


def test_the_same_fill_id_recorded_twice_only_counts_once(tmp_path: Path):
    counter = make_counter(tmp_path)
    for _ in range(2):
        counter.record_fill("AAPL", "BUY", 100, et(4, 10, 0), fill_id="F1")
        counter.record_fill("AAPL", "SELL", 100, et(4, 14, 0), fill_id="F2")

    assert counter.count_last_5_business_days(FRIDAY_4) == 1

    saved = json.loads((tmp_path / "pdt_BOOK_A.json").read_text(encoding="utf-8"))
    assert len(saved["fills"]) == 2


def test_the_file_on_disk_is_json_a_person_can_read(tmp_path: Path):
    counter = make_counter(tmp_path, book_id="C")
    counter.record_fill("AAPL", "BUY", 100, et(4, 10, 0), fill_id="F1")

    saved = json.loads((tmp_path / "pdt_BOOK_C.json").read_text(encoding="utf-8"))

    assert saved["book_id"] == "C"
    assert saved["version"] == 1
    assert saved["fills"] == [
        {
            "symbol": "AAPL",
            "side": "BUY",
            "qty": 100,
            "ts": "2026-09-04T10:00:00-04:00",
            "trade_date": "2026-09-04",
            "fill_id": "F1",
        }
    ]


def test_a_day_trade_file_that_is_not_json_is_refused_and_the_file_is_named(
    tmp_path: Path,
):
    store = tmp_path / "pdt_BOOK_A.json"
    store.write_text("this is not json at all", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        DayTradeCounter(book_id="A", store_path=store)

    assert str(store) in str(caught.value)


def test_counter_for_reads_the_book_id_and_the_holidays_off_the_settings(
    tmp_path: Path,
):
    book = FakeBook(
        book_id="D",
        pdt=FakePdtSettings(hard_limit=True),
        schedule=FakeSchedule(holidays=(LABOR_DAY,)),
    )

    counter = counter_for(book, store_dir=tmp_path)

    assert counter.book_id == "D"
    assert counter.store_path == tmp_path / "pdt_BOOK_D.json"
    assert counter.holidays == frozenset({LABOR_DAY})


# ---------------------------------------------------------------------------
# Nonsense is refused rather than guessed at
# ---------------------------------------------------------------------------


def test_a_time_with_no_timezone_is_refused_rather_than_guessed_at(tmp_path: Path):
    counter = make_counter(tmp_path)

    with pytest.raises(ValueError) as caught:
        counter.record_fill("AAPL", "BUY", 100, datetime(2026, 9, 4, 10, 0))

    assert "timezone" in str(caught.value)


def test_a_side_that_is_not_buy_or_sell_is_refused(tmp_path: Path):
    counter = make_counter(tmp_path)

    with pytest.raises(ValueError) as caught:
        counter.record_fill("AAPL", "HOLD", 100, et(4, 10, 0))

    assert "BUY" in str(caught.value)


@pytest.mark.parametrize("qty", [0, -100, 1.5, True])
def test_a_quantity_that_is_not_a_whole_number_above_zero_is_refused(
    tmp_path: Path, qty
):
    counter = make_counter(tmp_path)

    with pytest.raises(ValueError):
        counter.record_fill("AAPL", "BUY", qty, et(4, 10, 0))
