"""Tests for the five virtual books that share one paper account.

The rules in tests/test_guardrails.py are about one set of settings. These are
about five: that config/books.yaml holds the books Mo decided on, that each
strategy folder loads and makes sense, and that the limits added for the books
(gross exposure, the short floor, the borrow check, entries a day, the time
stop, the mirrored short stop, the trailing stop and the wrong book check) each
say no when they should and yes when they should.

Nothing here touches the network, IB Gateway or a broker account. Dates are in
September 2026: 2026-09-02 is a Wednesday, so 2026-09-04 is a Friday,
2026-09-05 a Saturday and 2026-09-07 a Monday.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from agent.guardrails import (
    BOOK_MODES_ALLOWED,
    AccountState,
    BookConfig,
    GuardrailConfigError,
    GuardrailUsageError,
    Guardrails,
    OrderIntent,
    PositionInfo,
    check_order,
    load_book,
    load_book_guardrails,
    load_books,
    must_flatten_now,
    stop_price_for,
    time_stop_due,
    trading_days_between,
    trailing_stop_price,
)

try:  # Python 3.9 and later
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    raise

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOKS_YAML = PROJECT_ROOT / "config" / "books.yaml"
SHIPPED_CONFIG = PROJECT_ROOT / "config" / "guardrails.yaml"
STRATEGIES = PROJECT_ROOT / "strategies"

EASTERN = ZoneInfo("America/New_York")

# The five books Mo decided on, 2026-09-06.
EXPECTED_BOOKS = {
    "A": ("strategies/momentum_hybrid", "openrouter/anthropic/claude-fable-5.1"),
    "B": ("strategies/momentum_rules", None),
    "C": ("strategies/insider", "openrouter/anthropic/claude-fable-5.1"),
    "D": ("strategies/congress", "openrouter/anthropic/claude-fable-5.1"),
    "E": ("strategies/momentum_hybrid", "openrouter/openai/gpt-6-astra"),
}

MOMENTUM_BOOKS = ("A", "B", "E")
OVERNIGHT_BOOKS = ("C", "D")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def et(day: int, hour: int, minute: int, month: int = 9, year: int = 2026) -> datetime:
    """A New York time. 2026-09-02 is a Wednesday."""
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN)


# A quiet mid morning moment on a Wednesday, inside every book's entry window.
MID_MORNING = et(2, 10, 0)


def position(symbol: str, qty: int, price: float) -> PositionInfo:
    return PositionInfo(
        symbol=symbol, qty=qty, avg_cost=price, market_value=qty * price
    )


def short_position(symbol: str, qty: int, price: float) -> PositionInfo:
    """A short shows up at the broker as negative shares and a negative value."""
    return PositionInfo(
        symbol=symbol, qty=-abs(qty), avg_cost=price, market_value=-abs(qty) * price
    )


def book_state(
    book_id: str,
    now: datetime = MID_MORNING,
    equity: float = 100000.0,
    positions: dict[str, PositionInfo] | None = None,
    gross_exposure: float | None = None,
    entries_opened_today: int = 0,
    pending_order_notional: float = 0.0,
    realized_pnl_today: float = 0.0,
    unrealized_pnl: float = 0.0,
) -> AccountState:
    """A snapshot of one book, with everything else left quiet."""
    return AccountState(
        equity=equity,
        day_start_equity=equity,
        realized_pnl_today=realized_pnl_today,
        unrealized_pnl=unrealized_pnl,
        open_positions=positions or {},
        pending_order_notional=pending_order_notional,
        now=now,
        kill_switch_present=False,
        account_id="DUT077572",
        book_id=book_id,
        gross_exposure=gross_exposure,
        entries_opened_today=entries_opened_today,
    )


def buy(
    book_id: str,
    symbol: str = "AAPL",
    qty: int = 100,
    limit_price: float | None = 50.0,
    **kwargs,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side="BUY",
        qty=qty,
        limit_price=limit_price,
        book_id=book_id,
        **kwargs,
    )


def short(
    book_id: str,
    symbol: str = "AAPL",
    qty: int = 100,
    limit_price: float | None = 50.0,
    shortable: bool = True,
    borrow_fee_pct_annual: float | None = 0.25,
    shares_available_to_borrow: int | None = 1_000_000,
    **kwargs,
) -> OrderIntent:
    """A short that is easy to borrow unless a test says otherwise.

    The three borrow facts default to a comfortable name: the broker says yes,
    the borrow costs a quarter of a percent a year, and there are a million
    shares to be had. A test that wants one of the three to fail passes just
    that one, so it is obvious which leg of the rule is being tested.
    """
    return OrderIntent(
        symbol=symbol,
        side="SELL",
        qty=qty,
        limit_price=limit_price,
        purpose="entry",
        book_id=book_id,
        shortable=shortable,
        borrow_fee_pct_annual=borrow_fee_pct_annual,
        shares_available_to_borrow=shares_available_to_borrow,
        **kwargs,
    )


def temp_project(
    tmp_path: Path,
    strategy: str = "momentum_hybrid",
    strategy_changes: dict | None = None,
    book_changes: dict | None = None,
) -> Path:
    """A copy of the real project settings in a temporary folder, with edits.

    Used where a test needs a number the shipped files do not carry, for example
    a trailing stop on the momentum book. changes are nested the same way the
    yaml is: {"risk": {"trailing_stop_pct": 4}}. A value of None removes that
    setting. Returns the path of the temporary books.yaml.
    """
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "strategies" / strategy).mkdir(parents=True, exist_ok=True)

    (tmp_path / "config" / "guardrails.yaml").write_text(
        SHIPPED_CONFIG.read_text(encoding="utf-8"), encoding="utf-8"
    )

    strategy_data = yaml.safe_load(
        (STRATEGIES / strategy / "strategy.yaml").read_text(encoding="utf-8")
    )
    for section, settings in (strategy_changes or {}).items():
        if settings is None:
            strategy_data.pop(section, None)
            continue
        for key, value in settings.items():
            if value is None:
                strategy_data[section].pop(key, None)
            else:
                strategy_data[section][key] = value
    (tmp_path / "strategies" / strategy / "strategy.yaml").write_text(
        yaml.safe_dump(strategy_data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    book = {
        "book_id": "A",
        "name": "A book for a test",
        "strategy_dir": f"strategies/{strategy}",
        "order_ref": "BOOK_A",
        "capital_usd": 100000,
        "model": "none",
        "enabled": True,
        "mode": "dry_run",
        "start_date": "2026-09-08",
        "end_date": "2026-10-06",
        "notes": "Built by a test, not by anyone who meant it.",
    }
    book.update(book_changes or {})
    registry = {
        "shared": {
            "account_id": "DUT077572",
            "gateway_port": 4002,
            "ledger_config": "config/ledger.json",
            "timezone": "America/New_York",
            "guardrails": "config/guardrails.yaml",
        },
        "books": [book],
    }
    books_path = tmp_path / "config" / "books.yaml"
    books_path.write_text(
        yaml.safe_dump(registry, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return books_path


@pytest.fixture()
def momentum() -> Guardrails:
    """Book A: opening momentum, hybrid, as it actually ships."""
    return load_book_guardrails(BOOKS_YAML, "A")


@pytest.fixture()
def insider() -> Guardrails:
    """Book C: insider buying, which holds overnight."""
    return load_book_guardrails(BOOKS_YAML, "C")


@pytest.fixture()
def congress() -> Guardrails:
    """Book D: Congress trades, the longest held of the five."""
    return load_book_guardrails(BOOKS_YAML, "D")


# ---------------------------------------------------------------------------
# The register of books
# ---------------------------------------------------------------------------


def test_books_yaml_holds_the_five_books_mo_decided_on():
    registry = load_books(BOOKS_YAML)
    assert registry.book_ids == ("A", "B", "C", "D", "E")
    assert len(registry.books) == 5

    for book in registry.books:
        strategy_dir, model = EXPECTED_BOOKS[book.book_id]
        assert book.strategy_dir == strategy_dir
        assert book.model == model
        assert book.capital_usd == 100000
        assert book.enabled is True
        assert book.mode == "dry_run"
        assert book.start_date == date(2026, 9, 8)
        assert book.end_date == date(2026, 10, 6)
        assert book.notes.strip(), f"book {book.book_id} has no notes"


def test_every_book_has_its_own_order_reference():
    """The order reference is how a fill in a shared account finds its book."""
    registry = load_books(BOOKS_YAML)
    refs = [book.order_ref for book in registry.books]
    assert refs == ["BOOK_A", "BOOK_B", "BOOK_C", "BOOK_D", "BOOK_E"]
    assert len(set(refs)) == 5
    for book in registry.books:
        assert book.order_ref == f"BOOK_{book.book_id}"


def test_only_book_b_runs_without_a_model():
    registry = load_books(BOOKS_YAML)
    without = [book.book_id for book in registry.books if not book.uses_a_model]
    assert without == ["B"]


def test_the_shared_block_names_the_paper_account_and_the_port():
    shared = load_books(BOOKS_YAML).shared
    assert shared.account_id == "DUT077572"
    assert shared.gateway_port == 4002
    assert shared.ledger_config_path == "config/ledger.json"
    assert shared.timezone == "America/New_York"
    assert (PROJECT_ROOT / shared.ledger_config_path).exists()
    assert (PROJECT_ROOT / shared.guardrails_path).exists()


def test_asking_for_a_book_that_is_not_there_says_which_ones_are():
    with pytest.raises(GuardrailConfigError) as caught:
        load_book(BOOKS_YAML, "Z")
    assert "A, B, C, D, E" in str(caught.value)


def test_a_book_id_is_read_the_same_however_it_is_typed():
    assert load_book(BOOKS_YAML, " c ").book_id == "C"


def test_a_book_may_only_run_in_one_of_the_three_named_modes(tmp_path: Path):
    """dry_run writes the order down, tiny risks a small pot, full risks it all."""
    assert BOOK_MODES_ALLOWED == ("dry_run", "tiny", "full")
    books_path = temp_project(tmp_path, book_changes={"mode": "live"})
    with pytest.raises(GuardrailConfigError, match="has to be one of"):
        load_books(books_path)


def test_every_book_is_still_on_dry_run_today():
    """Nothing sends an order until Mo promotes a book by hand."""
    for book in load_books(BOOKS_YAML).books:
        assert book.mode == "dry_run", f"book {book.book_id} is not on dry_run"
        assert book.sends_orders is False
        assert book.promoted_on is None, "nothing has been promoted yet"
        assert book.rules_commit is None, "nothing has been promoted yet"


def test_an_older_file_written_with_a_hyphen_still_reads_as_dry_run(tmp_path: Path):
    """dry-run and dry_run are the same mode, so punctuation cannot break a load."""
    books_path = temp_project(tmp_path, book_changes={"mode": "dry-run"})
    assert load_books(books_path).get("A").mode == "dry_run"


def test_a_dry_run_book_is_sized_against_its_whole_capital(tmp_path: Path):
    """A rehearsal that sizes differently from the real thing is not a rehearsal."""
    books_path = temp_project(tmp_path, book_changes={"mode": "dry_run"})
    book = load_books(books_path).get("A")
    assert book.effective_capital() == 100000.0
    assert load_book_guardrails(books_path, "A").money.starting_equity == 100000.0


def test_a_tiny_book_is_sized_against_the_two_thousand_dollar_pot(tmp_path: Path):
    """tiny sends real paper orders, but only ever risks the small pot."""
    books_path = temp_project(
        tmp_path,
        book_changes={
            "mode": "tiny",
            "promoted_on": "2026-10-13",
            "rules_commit": "abc1234",
        },
    )
    book = load_books(books_path).get("A")
    assert book.mode == "tiny"
    assert book.sends_orders is True
    assert book.tiny_capital_usd == 2000.0
    assert book.effective_capital() == 2000.0
    assert load_book_guardrails(books_path, "A").money.starting_equity == 2000.0


def test_a_full_book_is_sized_against_its_whole_capital(tmp_path: Path):
    books_path = temp_project(
        tmp_path,
        book_changes={
            "mode": "full",
            "promoted_on": "2026-10-13",
            "rules_commit": "abc1234",
        },
    )
    book = load_books(books_path).get("A")
    assert book.sends_orders is True
    assert book.effective_capital() == 100000.0
    assert load_book_guardrails(books_path, "A").money.starting_equity == 100000.0


def test_a_tiny_book_is_actually_held_to_the_smaller_pot_on_an_order(tmp_path: Path):
    """The 15 percent cap now means 300 dollars, not 15,000."""
    books_path = temp_project(
        tmp_path,
        book_changes={
            "mode": "tiny",
            "promoted_on": "2026-10-13",
            "rules_commit": "abc1234",
        },
    )
    g = load_book_guardrails(books_path, "A")
    state = book_state("A", equity=2000.0)

    fine = check_order(g, state, buy("A", qty=6, limit_price=50.0))
    assert fine.allowed is True, fine.reasons

    too_big = check_order(g, state, buy("A", qty=7, limit_price=50.0))
    assert too_big.allowed is False
    assert "max_position_pct" in too_big.rule_ids


@pytest.mark.parametrize("mode", ["tiny", "full"])
def test_a_book_that_sends_orders_needs_its_promotion_written_down(
    tmp_path: Path, mode: str
):
    """A mode change on its own can never start sending orders."""
    books_path = temp_project(tmp_path, book_changes={"mode": mode})
    with pytest.raises(GuardrailConfigError, match="promoted_on"):
        load_books(books_path)

    half = temp_project(
        tmp_path, book_changes={"mode": mode, "promoted_on": "2026-10-13"}
    )
    with pytest.raises(GuardrailConfigError, match="rules_commit"):
        load_books(half)


def test_an_order_reference_that_does_not_match_its_book_is_refused(tmp_path: Path):
    books_path = temp_project(tmp_path, book_changes={"order_ref": "MOMENTUM"})
    with pytest.raises(GuardrailConfigError, match="has to tag its orders"):
        load_books(books_path)


def test_a_book_that_ends_before_it_starts_is_refused(tmp_path: Path):
    books_path = temp_project(tmp_path, book_changes={"end_date": "2026-09-01"})
    with pytest.raises(GuardrailConfigError, match="before it starts"):
        load_books(books_path)


def test_a_missing_strategy_folder_is_named(tmp_path: Path):
    books_path = temp_project(
        tmp_path, book_changes={"strategy_dir": "strategies/nowhere"}
    )
    with pytest.raises(GuardrailConfigError, match="no strategy.yaml in it"):
        load_book_guardrails(books_path, "A")


# ---------------------------------------------------------------------------
# Every strategy folder loads and holds what its spec says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", ["A", "B", "C", "D", "E"])
def test_every_book_loads_its_strategy_and_keeps_the_shared_account(book_id: str):
    g = load_book_guardrails(BOOKS_YAML, book_id)
    assert g.book_id == book_id
    assert g.order_ref == f"BOOK_{book_id}"
    assert g.account.account_id == "DUT077572"
    assert g.account.mode == "paper"
    assert g.account.gateway_port == 4002
    assert g.schedule.timezone == "America/New_York"
    assert g.money.starting_equity == 100000
    assert g.strategy is not None
    assert g.strategy.status == "provisional", "the numbers are not approved yet"
    assert g.kill_switch.file == "output/STOP"


@pytest.mark.parametrize("name", ["momentum_hybrid", "momentum_rules", "insider", "congress"])
def test_every_strategy_folder_has_a_yaml_and_a_prompt(name: str):
    """A book is two files: the numbers, and the words handed to the model.

    What is inside prompt.md belongs to the decision step, not to the
    guardrails, so this only checks the file is there and is not empty.
    """
    folder = STRATEGIES / name
    assert (folder / "strategy.yaml").exists()
    prompt = (folder / "prompt.md").read_text(encoding="utf-8")
    assert prompt.strip(), f"strategies/{name}/prompt.md is empty"


@pytest.mark.parametrize("name", ["momentum_hybrid", "momentum_rules", "insider", "congress"])
def test_every_strategy_file_says_it_is_provisional(name: str):
    text = (STRATEGIES / name / "strategy.yaml").read_text(encoding="utf-8")
    assert text.lstrip().startswith("#")
    assert "PROVISIONAL" in text.split("strategy:")[0]
    assert "status: provisional" in text


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_momentum_books_match_their_spec(book_id: str):
    g = load_book_guardrails(BOOKS_YAML, book_id)
    assert g.money.max_position_pct == 15
    assert g.money.max_open_positions == 5
    assert g.money.max_daily_loss_pct == 2
    assert g.money.gross_exposure_pct_max == 100
    assert g.risk.stop_loss_pct == 1.5
    assert g.risk.use_opening_range_low_if_tighter is True
    assert g.universe.price_floor == 5
    assert g.universe.min_avg_dollar_volume == 20_000_000
    assert g.universe.dollar_volume_sessions == 30
    assert g.universe.min_avg_volume == 1000000, "kept only as a deprecated alias"
    assert g.universe.allow_shorts is True
    assert g.universe.short_price_floor == 10
    assert g.universe.require_shortable is True
    assert g.universe.max_borrow_fee_pct == 1.0
    assert g.universe.borrow_availability_multiple == 10
    assert g.pdt.hard_limit is False, "day trading is the whole strategy here"
    assert g.pdt.max_day_trades_per_5_days == 3
    assert g.pdt.assumed_live_equity_min_usd == 25000
    assert g.schedule.pick_time.strftime("%H:%M") == "09:35"
    assert g.schedule.entries_until.strftime("%H:%M") == "11:00"
    assert g.schedule.flatten_at.strftime("%H:%M") == "15:55"
    assert g.schedule.loop_minutes == 5
    assert g.schedule.entries_per_day_max == 5
    assert g.strategy.holds_overnight is False
    assert g.strategy.flat_by_close is True


def test_the_three_momentum_books_differ_only_in_who_decides():
    """If the rules underneath differ, the model comparison means nothing."""
    a = load_book_guardrails(BOOKS_YAML, "A")
    b = load_book_guardrails(BOOKS_YAML, "B")
    e = load_book_guardrails(BOOKS_YAML, "E")

    for other in (b, e):
        assert other.money == a.money
        assert other.risk == a.risk
        assert other.universe == a.universe
        assert other.scanner == a.scanner
        assert other.schedule == a.schedule

    assert a.discretion == "hybrid"
    assert e.discretion == "hybrid"
    assert b.discretion == "rules_only"
    assert load_book(BOOKS_YAML, "B").model is None


def test_the_insider_book_matches_its_spec(insider: Guardrails):
    assert insider.strategy.name == "Insider buying"
    assert insider.money.max_position_pct == 5
    assert insider.money.max_open_positions == 10
    assert insider.money.max_daily_loss_pct == 2
    assert insider.risk.stop_loss_pct == 8
    assert insider.risk.trailing_stop_pct == 10
    assert insider.risk.trailing_activation_pct == 8
    assert insider.risk.time_stop_trading_days == 30
    assert insider.universe.price_floor == 5
    assert insider.universe.min_avg_volume == 500000
    assert insider.universe.allow_shorts is False
    assert insider.universe.short_price_floor is None
    assert insider.schedule.entries_per_day_max == 3
    assert insider.schedule.loop_minutes == 30
    assert insider.pdt.hard_limit is True, "a day trade here is a mistake"
    assert insider.pdt.max_day_trades_per_5_days == 3
    assert insider.holds_overnight is True
    assert insider.flat_by_close is False
    assert insider.sweep is not None
    assert insider.sweep["transaction_code"] == "P"
    assert insider.sweep["exclude_10b5_1_plans"] is True
    assert insider.sweep["min_buy_usd"] == 25000
    assert insider.sweep["max_candidates"] == 15


def test_the_congress_book_matches_its_spec(congress: Guardrails):
    assert congress.strategy.name == "Congress trades"
    assert congress.money.max_position_pct == 5
    assert congress.money.max_open_positions == 10
    assert congress.risk.stop_loss_pct == 10
    assert congress.risk.trailing_stop_pct == 12
    assert congress.risk.trailing_activation_pct == 10
    assert congress.risk.time_stop_trading_days == 60
    assert congress.universe.price_floor == 10
    assert congress.universe.min_avg_volume == 1000000
    assert congress.universe.allow_shorts is False
    assert congress.schedule.entries_per_day_max == 2
    assert congress.pdt.hard_limit is True, "a day trade here is a mistake"
    assert congress.pdt.max_day_trades_per_5_days == 3
    assert congress.holds_overnight is True
    assert congress.flat_by_close is False
    assert congress.sweep is not None
    assert congress.sweep["max_trade_age_days"] == 60
    assert congress.sweep["runup_skip_pct"] == 15
    assert congress.sweep["min_band_usd_single"] == 15001


def test_a_book_only_writes_down_what_it_changes(tmp_path: Path):
    """Anything a strategy file leaves out is inherited from the shared one."""
    books_path = temp_project(
        tmp_path, strategy_changes={"money": {"max_position_pct": None}}
    )
    g = load_book_guardrails(books_path, "A")
    assert g.money.max_position_pct == 15  # from config/guardrails.yaml


def test_the_deprecated_share_volume_floor_is_still_accepted(tmp_path: Path):
    """An older settings file that only knows about shares still loads."""
    books_path = temp_project(
        tmp_path,
        strategy_changes={
            "universe": {
                "min_avg_dollar_volume": None,
                "dollar_volume_sessions": None,
                "min_avg_volume": 750000,
            }
        },
    )
    g = load_book_guardrails(books_path, "A")
    assert g.universe.min_avg_volume == 750000
    # And the dollar floor falls back to the shared file rather than vanishing.
    assert g.universe.min_avg_dollar_volume == 20_000_000
    assert g.universe.dollar_volume_sessions == 30


def test_a_settings_file_with_no_share_volume_floor_at_all_still_loads(tmp_path: Path):
    """min_avg_volume is optional now. Nothing breaks when it is deleted outright."""
    from agent.guardrails import load_guardrails

    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"].pop("min_avg_volume")
    path = tmp_path / "no_share_floor.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    g = load_guardrails(path)
    assert g.universe.min_avg_volume is None
    assert g.universe.min_avg_dollar_volume == 20_000_000


def test_a_book_may_set_its_own_dollar_volume_floor(tmp_path: Path):
    books_path = temp_project(
        tmp_path,
        strategy_changes={
            "universe": {
                "min_avg_dollar_volume": 50_000_000,
                "dollar_volume_sessions": 60,
            }
        },
    )
    g = load_book_guardrails(books_path, "A")
    assert g.universe.min_avg_dollar_volume == 50_000_000
    assert g.universe.dollar_volume_sessions == 60


def test_the_shared_settings_still_load_on_their_own_with_no_book():
    """The original settings file has no book, and nothing about it changed."""
    from agent.guardrails import load_guardrails

    shared = load_guardrails(SHIPPED_CONFIG)
    assert shared.book_id is None
    assert shared.order_ref is None
    assert shared.strategy is None
    assert shared.sweep is None
    assert shared.flat_by_close is True
    assert shared.universe.allow_shorts is False, "shorting stays off in the shared file"
    assert shared.universe.short_price_floor is None
    assert shared.universe.require_shortable is False
    assert shared.money.gross_exposure_pct_max == 100
    assert shared.money.tiny_capital_usd == 2000
    assert shared.schedule.entries_per_day_max is None
    assert shared.schedule.holidays == (), "no holiday calendar in month one"
    assert shared.universe.min_avg_dollar_volume == 20_000_000
    assert shared.universe.dollar_volume_sessions == 30
    assert shared.pdt.hard_limit is False
    assert shared.pdt.assumed_live_equity_min_usd == 25000


# ---------------------------------------------------------------------------
# The 15 percent cap on one position
# ---------------------------------------------------------------------------


def test_a_position_at_exactly_fifteen_percent_of_the_book_is_allowed(
    momentum: Guardrails,
):
    """300 shares at 50 dollars is 15,000, which is exactly the cap."""
    decision = check_order(
        momentum, book_state("A"), buy("A", qty=300, limit_price=50.0)
    )
    assert decision.allowed is True, decision.reasons


def test_a_position_over_fifteen_percent_of_the_book_is_blocked(momentum: Guardrails):
    decision = check_order(
        momentum, book_state("A"), buy("A", qty=301, limit_price=50.0)
    )
    assert decision.allowed is False
    assert "max_position_pct" in decision.rule_ids


def test_the_insider_book_keeps_its_own_smaller_five_percent_cap(insider: Guardrails):
    """Each book carries its own numbers, so one cap does not leak into another."""
    allowed = check_order(
        insider, book_state("C"), buy("C", qty=100, limit_price=50.0)
    )
    assert allowed.allowed is True, allowed.reasons

    blocked = check_order(
        insider, book_state("C"), buy("C", qty=101, limit_price=50.0)
    )
    assert blocked.allowed is False
    assert "max_position_pct" in blocked.rule_ids


# ---------------------------------------------------------------------------
# The gross exposure cap
# ---------------------------------------------------------------------------


def test_gross_exposure_at_seventy_four_percent_is_allowed(momentum: Guardrails):
    """59,000 already at work plus a 15,000 order is 74,000 of a 100,000 book."""
    state = book_state(
        "A", positions={"MSFT": position("MSFT", 590, 100.0)}
    )
    assert state.gross_exposure_now() == 59000.0
    decision = check_order(
        momentum, state, buy("A", symbol="AAPL", qty=300, limit_price=50.0)
    )
    assert decision.allowed is True, decision.reasons


def test_gross_exposure_at_one_hundred_and_one_percent_is_blocked(momentum: Guardrails):
    """90,000 at work plus an 11,000 order is 101,000, which is borrowing."""
    state = book_state("A", positions={"MSFT": position("MSFT", 900, 100.0)})
    assert state.gross_exposure_now() == 90000.0
    decision = check_order(
        momentum, state, buy("A", symbol="AAPL", qty=110, limit_price=100.0)
    )
    assert decision.allowed is False
    assert "gross_exposure_cap" in decision.rule_ids
    assert "101.0 percent" in " ".join(decision.reasons)


def test_a_short_counts_towards_gross_exposure_rather_than_against_it(
    momentum: Guardrails,
):
    """Long 60,000 and short 45,000 is 105,000 at risk, not 15,000."""
    state = book_state(
        "A",
        positions={
            "MSFT": position("MSFT", 600, 100.0),
            "TSLA": short_position("TSLA", 450, 100.0),
        },
    )
    assert state.gross_exposure_now() == 105000.0
    assert state.position_direction("TSLA") == "short"
    assert state.is_short("TSLA") is True
    assert state.position_direction("MSFT") == "long"
    assert state.position_direction("NVDA") == "flat"

    decision = check_order(
        momentum, state, buy("A", symbol="AAPL", qty=10, limit_price=50.0)
    )
    assert decision.allowed is False
    assert "gross_exposure_cap" in decision.rule_ids


def test_the_figure_the_loop_hands_in_wins_over_the_positions_it_can_see(
    momentum: Guardrails,
):
    """Five books share an account, so only the loop knows what belongs to one."""
    state = book_state(
        "A",
        positions={"MSFT": position("MSFT", 900, 100.0)},
        gross_exposure=1000.0,
    )
    assert state.gross_exposure_now() == 1000.0
    decision = check_order(
        momentum, state, buy("A", symbol="AAPL", qty=110, limit_price=100.0)
    )
    assert "gross_exposure_cap" not in decision.rule_ids


def test_getting_out_is_never_blocked_by_the_gross_exposure_cap(momentum: Guardrails):
    state = book_state("A", positions={"MSFT": position("MSFT", 1200, 100.0)})
    intent = OrderIntent(
        symbol="MSFT", side="SELL", qty=1200, purpose="flatten", book_id="A"
    )
    assert check_order(momentum, state, intent).allowed is True


# ---------------------------------------------------------------------------
# Shorting: the price floor and the borrow check
# ---------------------------------------------------------------------------


def test_a_short_below_the_ten_dollar_floor_is_blocked(momentum: Guardrails):
    decision = check_order(
        momentum, book_state("A"), short("A", symbol="AAPL", qty=100, limit_price=8.0)
    )
    assert decision.allowed is False
    assert "short_price_floor" in decision.rule_ids


def test_a_short_at_or_above_the_floor_goes_through(momentum: Guardrails):
    at_the_floor = check_order(
        momentum, book_state("A"), short("A", qty=100, limit_price=10.0)
    )
    assert at_the_floor.allowed is True, at_the_floor.reasons

    above = check_order(momentum, book_state("A"), short("A", qty=100, limit_price=12.0))
    assert above.allowed is True, above.reasons


def test_buying_a_cheap_stock_is_not_caught_by_the_short_floor(momentum: Guardrails):
    """The 10 dollar floor is for shorts only. Longs keep the 5 dollar floor."""
    decision = check_order(
        momentum, book_state("A"), buy("A", qty=100, limit_price=8.0)
    )
    assert "short_price_floor" not in decision.rule_ids
    assert decision.allowed is True, decision.reasons


def test_a_short_the_broker_has_not_confirmed_is_blocked(momentum: Guardrails):
    decision = check_order(
        momentum, book_state("A"), short("A", qty=100, limit_price=50.0, shortable=False)
    )
    assert decision.allowed is False
    assert "shortable_required" in decision.rule_ids
    assert "borrow" in " ".join(decision.reasons)


# ---------------------------------------------------------------------------
# The easy to borrow rule: three tests, and any one of them can say no
# ---------------------------------------------------------------------------


def test_an_easy_to_borrow_short_with_all_three_facts_goes_through(
    momentum: Guardrails,
):
    """IBKR rates it 3 of 3, the borrow is cheap, and there are shares to spare."""
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            borrow_fee_pct_annual=0.25,
            shares_available_to_borrow=50_000,
        ),
    )
    assert decision.allowed is True, decision.reasons


def test_a_borrowing_level_below_the_easy_band_is_blocked_on_its_own(
    momentum: Guardrails,
):
    """2.5 and below is not easy to borrow on IBKR's 0 to 3 scale."""
    decision = check_order(
        momentum,
        book_state("A"),
        short("A", qty=100, limit_price=50.0, shortable_level=2.5),
    )
    assert decision.allowed is False
    assert decision.rule_ids == ["shortable_required"]
    assert "0 to 3 borrowing scale" in " ".join(decision.reasons)


def test_a_borrowing_level_just_inside_the_easy_band_is_allowed(momentum: Guardrails):
    decision = check_order(
        momentum,
        book_state("A"),
        short("A", qty=100, limit_price=50.0, shortable_level=2.6),
    )
    assert decision.allowed is True, decision.reasons


def test_a_borrow_fee_over_one_percent_a_year_is_blocked_on_its_own(
    momentum: Guardrails,
):
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            borrow_fee_pct_annual=1.5,
        ),
    )
    assert decision.allowed is False
    assert decision.rule_ids == ["shortable_required"]
    assert "1.5 percent a year" in " ".join(decision.reasons)


def test_a_borrow_fee_of_exactly_the_limit_is_allowed(momentum: Guardrails):
    """Landing on a limit is allowed here, the same as everywhere else."""
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            borrow_fee_pct_annual=1.0,
        ),
    )
    assert decision.allowed is True, decision.reasons


def test_too_few_shares_available_to_borrow_is_blocked_on_its_own(
    momentum: Guardrails,
):
    """100 shares wanted needs 1,000 available, and 999 is not enough."""
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            shares_available_to_borrow=999,
        ),
    )
    assert decision.allowed is False
    assert decision.rule_ids == ["shortable_required"]
    assert "999 shares are available to borrow" in " ".join(decision.reasons)


def test_exactly_ten_times_the_shares_available_is_enough(momentum: Guardrails):
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            shares_available_to_borrow=1000,
        ),
    )
    assert decision.allowed is True, decision.reasons


def test_a_borrow_the_broker_priced_at_nothing_is_still_refused(momentum: Guardrails):
    """An unknown borrow cost is refused rather than assumed cheap."""
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            borrow_fee_pct_annual=None,
        ),
    )
    assert decision.allowed is False
    assert "did not say what borrowing the shares costs" in " ".join(decision.reasons)


def test_an_unknown_number_of_shares_to_borrow_is_refused_too(momentum: Guardrails):
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=3.0,
            shares_available_to_borrow=None,
        ),
    )
    assert decision.allowed is False
    assert "how many shares are available to borrow" in " ".join(decision.reasons)


def test_all_three_borrow_failures_are_reported_at_once(momentum: Guardrails):
    """The ledger should show every reason, not just the first one found."""
    decision = check_order(
        momentum,
        book_state("A"),
        short(
            "A",
            qty=100,
            limit_price=50.0,
            shortable_level=1.0,
            borrow_fee_pct_annual=8.0,
            shares_available_to_borrow=10,
        ),
    )
    assert decision.allowed is False
    assert decision.rule_ids == ["shortable_required"] * 3
    joined = " ".join(decision.reasons)
    assert "borrowing scale" in joined
    assert "percent a year" in joined
    assert "available to borrow" in joined


def test_the_shortable_flag_still_works_for_a_caller_with_no_level(
    momentum: Guardrails,
):
    """An older caller that only knows yes or no keeps working."""
    from agent.guardrails import easy_to_borrow

    assert easy_to_borrow(None, shortable=True) is True
    assert easy_to_borrow(None, shortable=False) is False
    assert easy_to_borrow(3.0, shortable=False) is True
    assert easy_to_borrow(1.0, shortable=True) is False


def test_a_borrowing_level_off_ibkrs_scale_is_refused_at_the_door():
    with pytest.raises(GuardrailUsageError, match="only runs from 0 to 3"):
        OrderIntent(
            symbol="AAPL", side="SELL", qty=10, limit_price=50.0, shortable_level=7.0
        )


def test_a_negative_borrow_fee_is_refused_at_the_door():
    with pytest.raises(GuardrailUsageError, match="cannot be negative"):
        OrderIntent(
            symbol="AAPL",
            side="SELL",
            qty=10,
            limit_price=50.0,
            borrow_fee_pct_annual=-1.0,
        )


def test_the_long_only_books_never_look_at_the_borrow_facts(insider: Guardrails):
    """require_shortable is off in book C, so none of the three tests run."""
    assert insider.universe.require_shortable is False
    decision = check_order(
        insider, book_state("C"), buy("C", qty=10, limit_price=50.0)
    )
    assert "shortable_required" not in decision.rule_ids
    assert decision.allowed is True, decision.reasons


def test_the_borrow_check_only_looks_at_orders_that_open_a_short(
    momentum: Guardrails,
):
    """Selling shares we own is an exit, not a short, whatever the flag says."""
    state = book_state("A", positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit",
        book_id="A", shortable=False,
    )
    decision = check_order(momentum, state, intent)
    assert decision.allowed is True, decision.reasons


def test_selling_more_than_we_hold_is_treated_as_opening_a_short(
    momentum: Guardrails,
):
    """100 held, 150 sold: 50 of them are borrowed, so the checks apply."""
    state = book_state("A", positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=150, limit_price=8.0, purpose="entry",
        book_id="A", shortable=False,
    )
    decision = check_order(momentum, state, intent)
    assert decision.allowed is False
    assert "short_price_floor" in decision.rule_ids
    assert "shortable_required" in decision.rule_ids


def test_the_long_only_books_cannot_short_at_all(insider: Guardrails):
    decision = check_order(
        insider, book_state("C"), short("C", qty=10, limit_price=50.0)
    )
    assert decision.allowed is False
    assert "no_shorts" in decision.rule_ids


# ---------------------------------------------------------------------------
# The mirrored stop for a short
# ---------------------------------------------------------------------------


def test_a_short_stop_sits_one_and_a_half_percent_above_entry(momentum: Guardrails):
    assert stop_price_for(momentum, 100.0, None, side="SELL") == 101.50


def test_a_nearer_opening_range_high_wins_for_a_short(momentum: Guardrails):
    assert stop_price_for(momentum, 100.0, None, side="SELL", opening_range_high=101.0) == 101.00


def test_a_wider_opening_range_high_loses_for_a_short(momentum: Guardrails):
    assert stop_price_for(momentum, 100.0, None, side="SELL", opening_range_high=105.0) == 101.50


def test_an_opening_range_high_below_where_we_sold_is_ignored(momentum: Guardrails):
    """A stop under the entry price of a short would be hit the moment it exists."""
    assert stop_price_for(momentum, 100.0, None, side="SELL", opening_range_high=99.0) == 101.50
    assert stop_price_for(momentum, 100.0, None, side="SELL", opening_range_high=100.0) == 101.50


def test_the_short_stop_is_always_above_the_entry_price(momentum: Guardrails):
    for entry_price in (10.0, 33.33, 250.0, 1234.56):
        assert stop_price_for(momentum, entry_price, None, side="SELL") > entry_price


def test_the_long_stop_is_unchanged_and_still_the_default(momentum: Guardrails):
    """The old two argument call still means a long, and still means the same."""
    assert stop_price_for(momentum, 100.0, None) == 98.50
    assert stop_price_for(momentum, 100.0, 99.0) == 99.00
    assert stop_price_for(momentum, 100.0, None, side="BUY") == 98.50


def test_the_long_and_short_stops_are_mirror_images(momentum: Guardrails):
    long_stop = stop_price_for(momentum, 200.0, None, side="BUY")
    short_stop = stop_price_for(momentum, 200.0, None, side="SELL")
    assert round(200.0 - long_stop, 2) == round(short_stop - 200.0, 2)


def test_a_side_that_is_not_buy_or_sell_is_refused(momentum: Guardrails):
    with pytest.raises(GuardrailUsageError, match="BUY for a long or SELL"):
        stop_price_for(momentum, 100.0, None, side="short")


# ---------------------------------------------------------------------------
# The trailing stop
# ---------------------------------------------------------------------------


def test_a_book_with_no_trailing_rule_never_gets_a_trailing_stop(momentum: Guardrails):
    assert momentum.risk.trailing_stop_pct is None
    assert trailing_stop_price(momentum, "BUY", 200.0, 100.0) is None


def test_the_insider_trailing_stop_stays_off_until_it_is_up_eight_percent(
    insider: Guardrails,
):
    assert trailing_stop_price(insider, "BUY", 107.99, 100.0) is None


def test_the_insider_trailing_stop_switches_on_exactly_at_eight_percent(
    insider: Guardrails,
):
    """Up 8 percent to 108, and the stop sits 10 percent below that."""
    assert trailing_stop_price(insider, "BUY", 108.0, 100.0) == 97.20


def test_the_insider_trailing_stop_follows_the_high(insider: Guardrails):
    assert trailing_stop_price(insider, "BUY", 150.0, 100.0) == 135.00


def test_the_congress_trailing_stop_uses_its_own_wider_numbers(congress: Guardrails):
    assert trailing_stop_price(congress, "BUY", 109.99, 100.0) is None
    assert trailing_stop_price(congress, "BUY", 110.0, 100.0) == 96.80


def test_a_short_trailing_stop_follows_the_low_and_sits_above_it(tmp_path: Path):
    """Down is the good direction for a short, so the stop trails downwards."""
    books_path = temp_project(
        tmp_path,
        strategy_changes={
            "risk": {"trailing_stop_pct": 10, "trailing_activation_pct": 8}
        },
    )
    g = load_book_guardrails(books_path, "A")

    assert trailing_stop_price(g, "SELL", 92.01, 100.0) is None
    assert trailing_stop_price(g, "SELL", 92.0, 100.0) == 101.20
    assert trailing_stop_price(g, "SELL", 80.0, 100.0) == 88.00
    # The long side of the same settings still points the other way.
    assert trailing_stop_price(g, "BUY", 108.0, 100.0) == 97.20


def test_half_a_trailing_rule_is_refused_at_load_time(tmp_path: Path):
    books_path = temp_project(
        tmp_path, strategy_changes={"risk": {"trailing_stop_pct": 10}}
    )
    with pytest.raises(GuardrailConfigError, match="go together"):
        load_book_guardrails(books_path, "A")


# ---------------------------------------------------------------------------
# How many new names a book may open in a day
# ---------------------------------------------------------------------------


def test_the_congress_book_stops_after_two_new_names_in_a_day(congress: Guardrails):
    one_more = check_order(
        congress,
        book_state("D", entries_opened_today=1),
        buy("D", symbol="LMT", qty=10, limit_price=100.0),
    )
    assert one_more.allowed is True, one_more.reasons

    third = check_order(
        congress,
        book_state("D", entries_opened_today=2),
        buy("D", symbol="LMT", qty=10, limit_price=100.0),
    )
    assert third.allowed is False
    assert "entries_per_day" in third.rule_ids
    assert "already opened 2 new positions today" in " ".join(third.reasons)


def test_the_insider_book_gets_three_a_day(insider: Guardrails):
    assert insider.schedule.entries_per_day_max == 3
    decision = check_order(
        insider,
        book_state("C", entries_opened_today=3),
        buy("C", qty=10, limit_price=50.0),
    )
    assert decision.allowed is False
    assert "entries_per_day" in decision.rule_ids


def test_adding_to_a_name_already_held_is_not_a_new_entry(congress: Guardrails):
    state = book_state(
        "D",
        entries_opened_today=2,
        positions={"LMT": position("LMT", 10, 100.0)},
    )
    decision = check_order(
        congress, state, buy("D", symbol="LMT", qty=10, limit_price=100.0)
    )
    assert decision.allowed is True, decision.reasons


def test_getting_out_is_never_blocked_by_the_daily_entry_count(congress: Guardrails):
    state = book_state(
        "D", entries_opened_today=9, positions={"LMT": position("LMT", 50, 100.0)}
    )
    intent = OrderIntent(
        symbol="LMT", side="SELL", qty=50, purpose="exit", book_id="D"
    )
    assert check_order(congress, state, intent).allowed is True


def test_a_nonsense_entry_count_is_refused_at_the_door():
    with pytest.raises(GuardrailUsageError, match="entries_opened_today"):
        book_state("A", entries_opened_today=-1)


# ---------------------------------------------------------------------------
# The time stop
# ---------------------------------------------------------------------------


def test_trading_days_skip_the_weekend():
    friday = date(2026, 9, 4)
    assert friday.weekday() == 4, "2026-09-04 should be a Friday"
    assert trading_days_between(friday, date(2026, 9, 4)) == 0  # same day
    assert trading_days_between(friday, date(2026, 9, 5)) == 0  # Saturday
    assert trading_days_between(friday, date(2026, 9, 6)) == 0  # Sunday
    assert trading_days_between(friday, date(2026, 9, 7)) == 1  # Monday
    assert trading_days_between(friday, date(2026, 9, 8)) == 2  # Tuesday
    assert trading_days_between(friday, date(2026, 9, 11)) == 5  # the next Friday


def test_a_time_stop_across_a_weekend_counts_trading_days_not_calendar_days(
    tmp_path: Path,
):
    """Opened on a Friday with a two day clock: due on Tuesday, not on Sunday."""
    books_path = temp_project(
        tmp_path, strategy_changes={"risk": {"time_stop_trading_days": 2}}
    )
    g = load_book_guardrails(books_path, "A")
    friday = date(2026, 9, 4)

    assert time_stop_due(g, friday, date(2026, 9, 5)) is False  # Saturday
    assert time_stop_due(g, friday, date(2026, 9, 6)) is False  # Sunday
    assert time_stop_due(g, friday, date(2026, 9, 7)) is False  # Monday, one day
    assert time_stop_due(g, friday, date(2026, 9, 8)) is True   # Tuesday, two days
    assert time_stop_due(g, friday, date(2026, 9, 14)) is True  # long past it


def test_the_insider_time_stop_is_thirty_trading_days(insider: Guardrails):
    opened = date(2026, 9, 8)
    assert time_stop_due(insider, opened, date(2026, 10, 19)) is False  # 29 days
    assert time_stop_due(insider, opened, date(2026, 10, 20)) is True   # 30 days


def test_the_congress_time_stop_is_sixty_trading_days(congress: Guardrails):
    opened = date(2026, 9, 8)
    assert congress.risk.time_stop_trading_days == 60
    assert time_stop_due(congress, opened, date(2026, 11, 30)) is False
    assert time_stop_due(congress, opened, date(2026, 12, 1)) is True


def test_a_date_with_no_timezone_attached_is_still_fine_but_a_bare_string_is_not(
    insider: Guardrails,
):
    with pytest.raises(GuardrailUsageError, match="has to be a date"):
        time_stop_due(insider, "2026-09-08", date(2026, 10, 20))


# ---------------------------------------------------------------------------
# Books that hold overnight are not sold off at the close
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", OVERNIGHT_BOOKS)
def test_a_book_that_holds_overnight_is_never_flattened(book_id: str):
    g = load_book_guardrails(BOOKS_YAML, book_id)
    assert g.flat_by_close is False
    for moment in (et(2, 15, 54), et(2, 15, 55), et(2, 15, 59), et(2, 16, 30)):
        assert must_flatten_now(g, moment) is False


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_a_momentum_book_is_still_sold_off_at_five_to_four(book_id: str):
    g = load_book_guardrails(BOOKS_YAML, book_id)
    assert g.flat_by_close is True
    assert must_flatten_now(g, et(2, 15, 54)) is False
    assert must_flatten_now(g, et(2, 15, 55)) is True
    assert must_flatten_now(g, et(2, 15, 59)) is True
    assert must_flatten_now(g, et(2, 16, 0)) is False


def test_an_overnight_book_still_opens_nothing_new_after_its_entry_window(
    insider: Guardrails,
):
    """Not being flattened is not the same as being allowed to keep buying."""
    assert insider.schedule.entries_until.strftime("%H:%M") == "15:50"

    in_time = check_order(
        insider, book_state("C", now=et(2, 15, 49)), buy("C", qty=10, limit_price=50.0)
    )
    assert in_time.allowed is True, in_time.reasons

    too_late = check_order(
        insider, book_state("C", now=et(2, 15, 51)), buy("C", qty=10, limit_price=50.0)
    )
    assert too_late.allowed is False
    assert "entry_window" in too_late.rule_ids

    later_still = check_order(
        insider, book_state("C", now=et(2, 15, 56)), buy("C", qty=10, limit_price=50.0)
    )
    assert later_still.allowed is False
    assert "entry_window" in later_still.rule_ids
    assert "flatten_time" in later_still.rule_ids


def test_an_overnight_book_can_still_be_closed_late_in_the_day(insider: Guardrails):
    state = book_state(
        "C", now=et(2, 15, 56), positions={"AAPL": position("AAPL", 100, 50.0)}
    )
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, purpose="exit", book_id="C"
    )
    assert check_order(insider, state, intent).allowed is True


def test_a_naive_time_is_still_refused_even_by_a_book_that_never_flattens(
    insider: Guardrails,
):
    with pytest.raises(GuardrailUsageError, match="carries no timezone"):
        must_flatten_now(insider, datetime(2026, 9, 2, 15, 55))


# ---------------------------------------------------------------------------
# An order has to say which book it came from
# ---------------------------------------------------------------------------


def test_an_order_tagged_for_another_book_is_refused(momentum: Guardrails):
    decision = check_order(momentum, book_state("A"), buy("C", qty=10, limit_price=50.0))
    assert decision.allowed is False
    assert "wrong_book" in decision.rule_ids
    assert "book C" in " ".join(decision.reasons)
    assert "book A" in " ".join(decision.reasons)


def test_an_order_with_no_book_at_all_is_refused_by_a_book(momentum: Guardrails):
    intent = OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=50.0)
    decision = check_order(momentum, book_state("A"), intent)
    assert decision.allowed is False
    assert "wrong_book" in decision.rule_ids


def test_the_right_book_passes(momentum: Guardrails):
    decision = check_order(momentum, book_state("A"), buy("A", qty=10, limit_price=50.0))
    assert decision.allowed is True, decision.reasons


def test_a_snapshot_of_the_wrong_book_is_refused_too(momentum: Guardrails):
    decision = check_order(momentum, book_state("E"), buy("A", qty=10, limit_price=50.0))
    assert decision.allowed is False
    assert "wrong_book" in decision.rule_ids


def test_the_wrong_book_blocks_an_exit_as_well_as_an_entry(momentum: Guardrails):
    """The one place a closing order is refused, because it would sell the wrong thing."""
    state = book_state("A", positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, purpose="exit", book_id="D"
    )
    decision = check_order(momentum, state, intent)
    assert decision.allowed is False
    assert "wrong_book" in decision.rule_ids


def test_a_book_id_is_read_the_same_however_it_is_typed_on_an_order(
    momentum: Guardrails,
):
    intent = OrderIntent(
        symbol="AAPL", side="BUY", qty=10, limit_price=50.0, book_id=" a "
    )
    assert intent.book_id == "A"
    assert check_order(momentum, book_state(" a "), intent).allowed is True


def test_a_nonsense_book_id_is_refused_at_the_door():
    with pytest.raises(GuardrailUsageError, match="not a book id"):
        OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=50.0, book_id="book A")


# ---------------------------------------------------------------------------
# Every new rule id has to be able to fire
# ---------------------------------------------------------------------------


NEW_RULE_IDS = {
    "wrong_book",
    "gross_exposure_cap",
    "short_price_floor",
    "shortable_required",
    "entries_per_day",
}


def test_every_new_rule_id_can_block_an_order():
    """One scenario per new rule, so none of them can quietly stop working."""
    momentum = load_book_guardrails(BOOKS_YAML, "A")
    congress = load_book_guardrails(BOOKS_YAML, "D")

    scenarios: dict[str, tuple[Guardrails, AccountState, OrderIntent]] = {
        "wrong_book": (
            momentum,
            book_state("A"),
            buy("B", qty=10, limit_price=50.0),
        ),
        "gross_exposure_cap": (
            momentum,
            book_state("A", positions={"MSFT": position("MSFT", 900, 100.0)}),
            buy("A", symbol="AAPL", qty=110, limit_price=100.0),
        ),
        "short_price_floor": (
            momentum,
            book_state("A"),
            short("A", qty=100, limit_price=6.0),
        ),
        "shortable_required": (
            momentum,
            book_state("A"),
            short("A", qty=100, limit_price=50.0, shortable=False),
        ),
        "entries_per_day": (
            congress,
            book_state("D", entries_opened_today=2),
            buy("D", qty=10, limit_price=50.0),
        ),
    }

    assert set(scenarios) == NEW_RULE_IDS, "a new rule id has no scenario"

    for rule_id, (guardrails, state, intent) in scenarios.items():
        decision = check_order(guardrails, state, intent)
        assert decision.allowed is False, rule_id
        assert rule_id in decision.rule_ids, (rule_id, decision.rule_ids)
        # Plain language check: every reason is a real sentence, not a code.
        for reason in decision.reasons:
            assert reason.endswith(".") and len(reason.split()) >= 6, reason


def test_a_book_config_is_a_plain_readable_record():
    """The loop reads these fields straight off, so their names are the contract."""
    book = load_book(BOOKS_YAML, "A")
    assert isinstance(book, BookConfig)
    assert (
        book.book_id,
        book.order_ref,
        book.strategy_dir,
        book.capital_usd,
        book.enabled,
        book.mode,
    ) == ("A", "BOOK_A", "strategies/momentum_hybrid", 100000.0, True, "dry_run")
    assert book.model == "openrouter/anthropic/claude-fable-5.1"
    assert copy.copy(book) == book
