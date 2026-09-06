"""Tests for agent/margin_regime.py, the day trading regime switch.

Two rulebooks exist in 2026. The old one is the pattern day trader rule, which
counts four day trades in five business days and demands 25,000 dollars. The new
one, which FINRA put in its place with effect from 2026-06-04, counts nothing
and instead insists an order never leaves the account short of margin during the
day. IBKR says which one an account is under through five account summary tags.

These tests cover three things: reading those tags without guessing, the
intraday margin deficit check that replaces counting under the new rules, and
the assertion that stops a settings change quietly making a deficit possible.

Nothing here touches the network, IB Gateway or a broker account. The settings,
the account snapshot and the order are small stand in objects, because
agent/margin_regime.py reads all three with getattr and never imports
agent/guardrails.py.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_margin_regime.py -q
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent.margin_regime import (
    DAY_TRADE_TAGS,
    RULE_ID_IMD,
    ImdDecision,
    MarginRegimeConfigError,
    Regime,
    as_regime,
    assert_structurally_impossible,
    detect_regime,
    imd_check,
    read_regime_setting,
    write_regime_setting,
)

REAL_CONFIG = (
    Path(__file__).resolve().parent.parent / "config" / "guardrails.yaml"
)


# ---------------------------------------------------------------------------
# Stand in objects, shaped like the real settings, snapshot and order
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeMoney:
    """Stands in for agent.guardrails.MoneyConfig."""

    gross_exposure_pct_max: float = 100.0
    allow_margin_borrowing: bool | None = None
    max_leverage: float | None = None


@dataclass(frozen=True)
class FakeGuardrails:
    """Stands in for what load_book_guardrails() hands back for one book."""

    money: FakeMoney = field(default_factory=FakeMoney)
    book_id: str | None = "A"


@dataclass
class FakeState:
    """Stands in for agent.guardrails.AccountState.

    gross_exposure_now() is a method on the real one, so it is a method here.
    cash is left None on purpose most of the time, because the real snapshot
    does not carry one and the check has to work out free cash from equity.
    """

    equity: float = 100_000.0
    gross_exposure: float = 0.0
    pending_order_notional: float = 0.0
    cash: float | None = None

    def gross_exposure_now(self) -> float:
        return abs(self.gross_exposure)


@dataclass
class FakeIntent:
    """Stands in for agent.guardrails.OrderIntent."""

    symbol: str = "AAPL"
    side: str = "BUY"
    qty: int = 100
    limit_price: float | None = 50.0
    purpose: str = "entry"

    @property
    def notional(self) -> float | None:
        if self.limit_price is None:
            return None
        return self.qty * self.limit_price


def tags(**pairs) -> list[dict]:
    """Account summary items the way agent/mcp_client.py hands them back."""
    return [{"account": "DUT077572", "tag": tag, "value": str(value)}
            for tag, value in pairs.items()]


def counting_tags(remaining: int = 3) -> list[dict]:
    """All five day trade tags, holding counts, which is the old rule running."""
    return [{"account": "U28440091", "tag": tag, "value": str(remaining)}
            for tag in DAY_TRADE_TAGS]


# The tags the paper account DUT077572 actually returned on 2026-09-06, cut down
# to the handful this file cares about. Not one of the five day trade tags was
# among the 74 it sent, which is the reading this project has to handle.
PAPER_ACCOUNT_2026_09_06 = tags(
    AccountType="INDIVIDUAL",
    NetLiquidation="1000175.35",
    TotalCashValue="999233.85",
    BuyingPower="3999243.66",
    GrossPositionValue="769.42",
    EquityWithLoanValue="1000003.27",
)


# ---------------------------------------------------------------------------
# Reading the tags
# ---------------------------------------------------------------------------


def test_five_counting_tags_mean_the_old_pattern_day_trader_rule():
    reading = detect_regime(counting_tags(3))

    assert reading.regime is Regime.OLD_PDT
    assert reading.numbers["DayTradesRemaining"] == 3.0
    assert reading.missing == ()
    assert reading.account == "U28440091"


def test_three_counting_tags_are_enough_to_read_it_as_the_old_rule():
    """IBKR has been seen to send a short set, and three is the line we drew."""
    reading = detect_regime(tags(**{
        "DayTradesRemaining": 2,
        "DayTradesRemainingT+1": 2,
        "DayTradesRemainingT+2": 1,
    }))

    assert reading.regime is Regime.OLD_PDT
    assert len(reading.numbers) == 3
    assert "DayTradesRemainingT+4" in reading.missing


def test_two_counting_tags_are_not_enough_and_stay_unknown():
    reading = detect_regime(tags(**{
        "DayTradesRemaining": 2,
        "DayTradesRemainingT+1": 2,
    }))

    assert reading.regime is Regime.UNKNOWN
    assert "Too little to decide on" in reading.note


def test_zero_day_trades_left_is_still_the_old_rule_not_the_new_one():
    """Nothing left to spend is the old rule biting, not the rule being gone."""
    reading = detect_regime(counting_tags(0))

    assert reading.regime is Regime.OLD_PDT


def test_minus_one_means_unlimited_and_so_the_new_rules():
    reading = detect_regime(counting_tags(-1))

    assert reading.regime is Regime.NEW_IMD
    assert "unlimited" in reading.note


def test_one_minus_one_among_counts_is_enough_to_mean_the_new_rules():
    reading = detect_regime(tags(**{
        "DayTradesRemaining": -1,
        "DayTradesRemainingT+1": 3,
        "DayTradesRemainingT+2": 3,
        "DayTradesRemainingT+3": 3,
    }))

    assert reading.regime is Regime.NEW_IMD


def test_no_day_trade_tags_at_all_mean_the_new_rules():
    reading = detect_regime(PAPER_ACCOUNT_2026_09_06)

    assert reading.regime is Regime.NEW_IMD
    assert reading.values == {}
    assert list(reading.missing) == list(DAY_TRADE_TAGS)
    assert "none of the five" in reading.note


def test_an_empty_answer_is_read_as_no_tags_rather_than_as_an_error():
    assert detect_regime([]).regime is Regime.NEW_IMD
    assert detect_regime(None).regime is Regime.NEW_IMD


def test_a_tag_that_is_not_a_number_makes_it_unknown_and_keeps_the_evidence():
    reading = detect_regime(tags(**{
        "DayTradesRemaining": "unlimited",
        "DayTradesRemainingT+1": 3,
        "DayTradesRemainingT+2": 3,
        "DayTradesRemainingT+3": 3,
    }))

    assert reading.regime is Regime.UNKNOWN
    assert reading.values["DayTradesRemaining"] == "unlimited"
    assert "DayTradesRemaining" not in reading.numbers
    assert "not a number" in reading.note


def test_a_negative_that_is_not_minus_one_is_not_guessed_at():
    reading = detect_regime(counting_tags(-2))

    assert reading.regime is Regime.UNKNOWN
    assert "Only -1 means" in reading.note


def test_the_tags_are_read_from_ib_async_objects_too():
    """ib_async hands back objects with .account, .tag and .value, not dicts."""

    class Row:
        def __init__(self, tag, value):
            self.account = "U28440091"
            self.tag = tag
            self.value = value
            self.currency = "USD"

    reading = detect_regime([Row(tag, "4") for tag in DAY_TRADE_TAGS])

    assert reading.regime is Regime.OLD_PDT
    assert reading.account == "U28440091"


def test_the_tags_are_read_from_a_plain_mapping_too():
    reading = detect_regime({tag: "1" for tag in DAY_TRADE_TAGS})

    assert reading.regime is Regime.OLD_PDT


def test_the_whole_mcp_answer_is_accepted_not_just_its_items():
    """agent/mcp_client.py returns {"account": ..., "items": [...]}."""
    reading = detect_regime({"account": "DUT077572", "items": counting_tags(3)})

    assert reading.regime is Regime.OLD_PDT


def test_a_reading_goes_into_json_with_its_evidence_intact():
    written = detect_regime(counting_tags(3)).as_dict()

    assert written["regime"] == "old_pdt"
    assert written["tags_found"]["DayTradesRemaining"] == "3"
    assert written["tags_missing"] == []
    assert written["note"]


def test_text_instead_of_tags_is_refused_rather_than_read_as_nothing():
    with pytest.raises(ValueError) as caught:
        detect_regime("DayTradesRemaining=3")

    assert "tag and value pairs" in str(caught.value)


# ---------------------------------------------------------------------------
# Turning a settings word into a regime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word, expected",
    [("old_pdt", Regime.OLD_PDT), ("new_imd", Regime.NEW_IMD),
     ("unknown", Regime.UNKNOWN), ("  OLD_PDT  ", Regime.OLD_PDT),
     (None, Regime.UNKNOWN)],
)
def test_a_settings_word_becomes_a_regime(word, expected):
    assert as_regime(word) is expected


def test_a_word_that_is_not_a_regime_is_refused_and_says_the_three_that_are():
    with pytest.raises(MarginRegimeConfigError) as caught:
        as_regime("pattern_day_trader", "pdt.regime")

    message = str(caught.value)
    assert "old_pdt" in message and "new_imd" in message and "unknown" in message


def test_a_regime_writes_itself_out_as_the_plain_word():
    assert str(Regime.NEW_IMD) == "new_imd"
    assert Regime.NEW_IMD == "new_imd"


# ---------------------------------------------------------------------------
# The intraday margin deficit check
# ---------------------------------------------------------------------------


def test_an_order_that_fits_inside_the_book_is_allowed():
    verdict = imd_check(FakeGuardrails(), FakeState(equity=100_000.0),
                        FakeIntent(qty=100, limit_price=50.0))

    assert verdict.allowed is True
    assert verdict.rule_ids == []
    assert verdict.checked is True
    assert "cannot create an intraday margin deficit" in verdict.note


def test_an_order_that_would_take_the_book_over_its_own_worth_is_refused():
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=100_000.0, gross_exposure=90_000.0),
        FakeIntent(qty=400, limit_price=50.0),      # 20,000 dollars more
    )

    assert verdict.allowed is False
    assert verdict.rule_ids == [RULE_ID_IMD]
    assert "110,000.00 dollars" in verdict.reasons[0]
    assert "borrow" in verdict.reasons[0]


def test_money_already_on_order_counts_against_the_line():
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=100_000.0, gross_exposure=50_000.0,
                  pending_order_notional=45_000.0),
        FakeIntent(qty=200, limit_price=50.0),      # 10,000 dollars more
    )

    assert verdict.allowed is False
    assert "on order" in verdict.reasons[0]


def test_the_cash_test_is_not_run_twice_when_it_says_the_same_thing():
    """A snapshot with no cash figure gives cash as equity less positions, which
    is the gross exposure test written out again. One complaint, not two."""
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=100_000.0, gross_exposure=90_000.0),
        FakeIntent(qty=400, limit_price=50.0),
    )

    assert verdict.allowed is False
    assert len(verdict.reasons) == 1


def test_an_order_that_would_spend_cash_the_book_does_not_have_is_refused():
    """The cash test on its own, with a snapshot that carries a real cash figure.

    Equity is large so the gross exposure test has plenty of room, which leaves
    only the cash test to bite.
    """
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=1_000_000.0, gross_exposure=0.0, cash=5_000.0),
        FakeIntent(qty=200, limit_price=50.0),      # 10,000 dollars of cash
    )

    assert verdict.allowed is False
    assert verdict.rule_ids == [RULE_ID_IMD]
    assert "cash" in verdict.reasons[0]


def test_an_order_that_spends_exactly_the_cash_there_is_still_goes():
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=1_000_000.0, gross_exposure=0.0, cash=10_000.0),
        FakeIntent(qty=200, limit_price=50.0),
    )

    assert verdict.allowed is True


def test_both_tests_can_fail_at_once_and_both_reasons_are_kept():
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=10_000.0, gross_exposure=9_000.0, cash=100.0),
        FakeIntent(qty=100, limit_price=50.0),
    )

    assert verdict.allowed is False
    assert len(verdict.reasons) == 2
    assert verdict.rule_ids == [RULE_ID_IMD, RULE_ID_IMD]


def test_a_short_entry_counts_the_same_way_a_buy_does():
    """A short raises gross exposure, and the borrow costs more than the sale."""
    verdict = imd_check(
        FakeGuardrails(),
        FakeState(equity=100_000.0, gross_exposure=95_000.0),
        FakeIntent(side="SELL", qty=200, limit_price=50.0),
    )

    assert verdict.allowed is False


def test_getting_out_of_a_position_is_never_refused_here():
    for purpose in ("exit", "stop", "flatten"):
        verdict = imd_check(
            FakeGuardrails(),
            FakeState(equity=1_000.0, gross_exposure=100_000.0),
            FakeIntent(qty=1000, limit_price=500.0, purpose=purpose),
        )
        assert verdict.allowed is True, purpose
        assert "cannot create an intraday margin deficit" in verdict.note


def test_an_order_with_no_price_cannot_be_tested_and_says_so():
    verdict = imd_check(FakeGuardrails(), FakeState(),
                        FakeIntent(limit_price=None))

    assert verdict.allowed is True
    assert verdict.checked is False
    assert "no limit price" in verdict.note


def test_no_account_snapshot_means_the_test_could_not_run():
    verdict = imd_check(FakeGuardrails(), None, FakeIntent())

    assert verdict.allowed is True
    assert verdict.checked is False
    assert "No account snapshot" in verdict.note


def test_a_book_with_nothing_left_in_it_is_left_to_the_daily_loss_cap():
    verdict = imd_check(FakeGuardrails(), FakeState(equity=0.0), FakeIntent())

    assert verdict.allowed is True
    assert verdict.checked is False


def test_a_settings_file_that_raised_its_own_cap_cannot_move_this_line():
    """100 percent is written into the code, not read out of the settings."""
    loosened = FakeGuardrails(money=FakeMoney(gross_exposure_pct_max=200.0))

    verdict = imd_check(loosened,
                        FakeState(equity=100_000.0, gross_exposure=90_000.0),
                        FakeIntent(qty=400, limit_price=50.0))

    assert verdict.allowed is False
    assert "100 percent" in verdict.reasons[0]


def test_a_tighter_cap_in_the_settings_is_respected():
    tighter = FakeGuardrails(money=FakeMoney(gross_exposure_pct_max=50.0))

    verdict = imd_check(tighter,
                        FakeState(equity=100_000.0, gross_exposure=45_000.0),
                        FakeIntent(qty=200, limit_price=50.0))

    assert verdict.allowed is False
    assert "50 percent" in verdict.reasons[0]


def test_the_answer_reads_like_a_guardrails_decision():
    """The loop reads allowed, reasons and rule_ids the same way either side."""
    verdict = ImdDecision()
    verdict.add(RULE_ID_IMD, "over the line")

    assert verdict.allowed is False
    assert verdict.summary == "blocked: over the line"


# ---------------------------------------------------------------------------
# The assertion that keeps a deficit impossible
# ---------------------------------------------------------------------------


def test_the_shipped_settings_make_a_deficit_impossible():
    assert_structurally_impossible(FakeGuardrails())


def test_a_gross_exposure_cap_above_100_percent_fails_loudly():
    with pytest.raises(MarginRegimeConfigError) as caught:
        assert_structurally_impossible(
            FakeGuardrails(money=FakeMoney(gross_exposure_pct_max=150.0)))

    message = str(caught.value)
    assert "150 percent" in message
    assert "broker's money" in message


def test_no_gross_exposure_cap_at_all_fails_loudly():
    with pytest.raises(MarginRegimeConfigError) as caught:
        assert_structurally_impossible(
            FakeGuardrails(money=FakeMoney(gross_exposure_pct_max=None)))

    assert "Set it to 100" in str(caught.value)


def test_switching_borrowing_on_fails_loudly():
    with pytest.raises(MarginRegimeConfigError) as caught:
        assert_structurally_impossible(
            FakeGuardrails(money=FakeMoney(allow_margin_borrowing=True)))

    assert "never borrowing" in str(caught.value)


def test_leverage_above_one_fails_loudly():
    with pytest.raises(MarginRegimeConfigError) as caught:
        assert_structurally_impossible(
            FakeGuardrails(money=FakeMoney(max_leverage=4.0)))

    assert "anything above 1 is borrowing" in str(caught.value)


def test_leverage_of_exactly_one_is_not_borrowing():
    assert_structurally_impossible(FakeGuardrails(money=FakeMoney(max_leverage=1.0)))


def test_every_book_we_ship_still_makes_a_deficit_impossible():
    """The claim in docs/STRATEGY.md, checked against the settings we ship.

    The shared file leaves money.gross_exposure_pct_max out and the loader
    defaults it to 100, so the number that matters lives in each book's own
    strategy.yaml. Every one of them has to be at or below 100 percent, or the
    promise that the new day trading rules cost us nothing stops being true.
    """
    import yaml

    strategies = REAL_CONFIG.parent.parent / "strategies"
    files = sorted(strategies.glob("*/strategy.yaml"))
    assert files, f"no strategy files found under {strategies}"

    for path in files:
        money = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("money")
        cap = (money or {}).get("gross_exposure_pct_max", 100.0)
        assert_structurally_impossible(
            FakeGuardrails(money=FakeMoney(gross_exposure_pct_max=cap),
                           book_id=path.parent.name))


# ---------------------------------------------------------------------------
# The regime as a setting, read and written without losing the comments
# ---------------------------------------------------------------------------


def test_the_shipped_settings_say_unknown_and_fall_back_to_the_old_rule():
    regime, treat_unknown_as = read_regime_setting(REAL_CONFIG)

    assert regime is Regime.UNKNOWN
    assert treat_unknown_as is Regime.OLD_PDT


def test_a_missing_settings_file_reads_as_unknown_and_the_old_rule(tmp_path: Path):
    regime, treat_unknown_as = read_regime_setting(tmp_path / "nothing.yaml")

    assert regime is Regime.UNKNOWN
    assert treat_unknown_as is Regime.OLD_PDT


def test_writing_the_regime_changes_one_line_and_leaves_the_comments_alone(
    tmp_path: Path,
):
    copy = tmp_path / "guardrails.yaml"
    before = REAL_CONFIG.read_text(encoding="utf-8")
    copy.write_text(before, encoding="utf-8")

    assert write_regime_setting(copy, Regime.NEW_IMD) is True

    after = copy.read_text(encoding="utf-8")
    assert read_regime_setting(copy)[0] is Regime.NEW_IMD
    assert after.count("\n") == before.count("\n"), "no line was added or lost"
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines())
               if a != b]
    assert len(changed) == 1, changed
    assert changed[0][1].lstrip().startswith("regime: new_imd")
    assert "# old_pdt, new_imd, or unknown" in changed[0][1], "the comment stayed"
    assert "pattern day trader rule" in after, "the block's own comments stayed"


def test_writing_the_regime_it_already_says_changes_nothing(tmp_path: Path):
    copy = tmp_path / "guardrails.yaml"
    copy.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    before = copy.read_text(encoding="utf-8")

    assert write_regime_setting(copy, Regime.UNKNOWN) is False
    assert copy.read_text(encoding="utf-8") == before


def test_only_the_regime_inside_the_pdt_block_is_written(tmp_path: Path):
    """Another section with its own regime line must not be touched."""
    path = tmp_path / "guardrails.yaml"
    path.write_text(
        "scanner:\n"
        "  regime: old_pdt            # nothing to do with day trading\n"
        "\n"
        "pdt:\n"
        "  regime: unknown            # this is the one\n"
        "  hard_limit: false\n",
        encoding="utf-8")

    assert write_regime_setting(path, "new_imd") is True

    text = path.read_text(encoding="utf-8")
    assert "scanner:\n  regime: old_pdt" in text
    assert "  regime: new_imd            # this is the one\n" in text


def test_a_file_with_no_regime_line_says_what_to_add(tmp_path: Path):
    path = tmp_path / "guardrails.yaml"
    path.write_text("pdt:\n  hard_limit: false\n", encoding="utf-8")

    with pytest.raises(MarginRegimeConfigError) as caught:
        write_regime_setting(path, Regime.NEW_IMD)

    assert "regime: unknown" in str(caught.value)


def test_writing_into_a_file_that_is_not_there_says_which_file(tmp_path: Path):
    missing = tmp_path / "nothing.yaml"

    with pytest.raises(MarginRegimeConfigError) as caught:
        write_regime_setting(missing, Regime.NEW_IMD)

    assert str(missing) in str(caught.value)
