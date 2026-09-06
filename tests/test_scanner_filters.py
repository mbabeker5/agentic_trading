"""Tests for the scanner's number filters, run on made up bars.

The scanner itself talks to IB Gateway, but the arithmetic it does with the bars
Gateway hands back does not, and that arithmetic is where Mo's decisions live:
the liquidity floor of 20 million dollars of average daily trading over 30
sessions, the relative volume floor of 2 times normal measured at 09:35, and the
Momentum v2 changes approved on 2026-09-06.

Momentum v2 added four things these tests cover:

    A3   a volatility floor, a 14 day average true range above 50 cents and
         above 1.5 percent of the price
    A4   the shortlist ranked by relative volume alone, heaviest first, with a
         rank number on every row
    A5   long or short taken from the sign of the 9:30 to 9:35 candle, and no
         trade at all on a flat one
    A12  hard exclusions: SPACs, warrants, rights, preferred shares, anything
         not on a US venue, anything halted, and anything without 30 completed
         sessions of history

and took one thing away: the Finviz cross-check (decision D7), which is gone
from the scanner entirely and has a test below making sure it stays gone.

So these tests build bars by hand and check the sums. Nothing here connects to
Gateway, needs the market to be open, or needs a data subscription.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from agent.scanner import (
    DEFAULT_ATR_DAYS,
    DEFAULT_DOLLAR_VOLUME_SESSIONS,
    DEFAULT_MIN_ATR_PCT_OF_PRICE,
    DEFAULT_MIN_ATR_USD,
    DEFAULT_MIN_AVG_DOLLAR_VOLUME,
    DEFAULT_MIN_HISTORY_SESSIONS,
    DEFAULT_REL_VOLUME_BASELINE_DAYS,
    DEFAULT_REL_VOLUME_WINDOW,
    MIN_DAILY_BARS_FOR_AVERAGE,
    REL_VOLUME_ANCHOR_LABEL,
    REL_VOLUME_ANCHOR_MINUTES,
    SESSION_MINUTES,
    Thresholds,
    average_dollar_volume,
    average_true_range,
    bar_dollar_volume,
    direction_from_candle,
    expected_volume_by,
    halt_flag_from_details,
    human_dollars,
    load_thresholds,
    preferred_reason,
    relative_volume,
    right_reason,
    spac_reason,
    true_range,
    warrant_reason,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = PROJECT_ROOT / "config" / "guardrails.yaml"


# ---------------------------------------------------------------------------
# Made up bars
# ---------------------------------------------------------------------------


@dataclass
class FakeBar:
    """A daily bar shaped the way ib_async hands them back."""

    date: date
    close: float
    volume: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0


def sessions(count: int, close: float, volume: float) -> list[FakeBar]:
    """`count` identical completed sessions, oldest first."""
    return [
        FakeBar(date=date(2026, 7, 1), close=close, volume=volume)
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------
# One session's dollar volume
# ---------------------------------------------------------------------------


def test_one_session_is_worth_its_close_times_its_volume():
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), 50.0, 400_000)) == 20_000_000.0


def test_the_same_dollar_volume_can_come_from_very_different_share_counts():
    """The whole point of the change: 20 million dollars means one thing."""
    cheap = bar_dollar_volume(FakeBar(date(2026, 9, 1), 6.0, 3_333_334))
    dear = bar_dollar_volume(FakeBar(date(2026, 9, 1), 600.0, 33_334))
    assert round(cheap, -4) == round(dear, -4) == 20_000_000.0


def test_a_bar_with_nothing_usable_on_it_is_ignored():
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), 0.0, 400_000)) is None
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), 50.0, -1)) is None
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), 50.0, None)) is None
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), None, 400_000)) is None
    assert bar_dollar_volume(FakeBar(date(2026, 9, 1), "junk", 400_000)) is None


# ---------------------------------------------------------------------------
# The 30 session average
# ---------------------------------------------------------------------------


def test_thirty_flat_sessions_average_to_the_same_number():
    average, used = average_dollar_volume(sessions(30, 50.0, 500_000), 30)
    assert average == 25_000_000.0
    assert used == 30


def test_only_the_most_recent_thirty_sessions_count():
    """Forty sessions of history, and the ten oldest are not in the average."""
    bars = sessions(10, 1.0, 1.0) + sessions(30, 50.0, 500_000)
    average, used = average_dollar_volume(bars, 30)
    assert average == 25_000_000.0
    assert used == 30


def test_a_quiet_stretch_drags_the_average_down():
    """15 sessions at 30 million and 15 at 10 million average to 20 million."""
    bars = sessions(15, 30.0, 1_000_000) + sessions(15, 10.0, 1_000_000)
    average, used = average_dollar_volume(bars, 30)
    assert average == 20_000_000.0
    assert used == 30


def test_a_name_too_new_to_have_a_normal_gets_no_average_at_all():
    """Nine sessions is not enough history to say what normal looks like."""
    average, used = average_dollar_volume(sessions(9, 50.0, 500_000), 30)
    assert average is None
    assert used == 9


def test_exactly_ten_sessions_is_just_enough():
    average, used = average_dollar_volume(sessions(10, 50.0, 500_000), 30)
    assert average == 25_000_000.0
    assert used == 10
    assert MIN_DAILY_BARS_FOR_AVERAGE == 10


def test_a_name_with_less_than_thirty_sessions_averages_what_it_has():
    average, used = average_dollar_volume(sessions(18, 50.0, 500_000), 30)
    assert average == 25_000_000.0
    assert used == 18


def test_unreadable_bars_are_skipped_rather_than_counted_as_zero():
    """A broken bar in the middle should not drag the average towards nothing."""
    bars = sessions(30, 50.0, 500_000)
    bars[5] = FakeBar(date(2026, 7, 1), 0.0, 0.0)
    average, used = average_dollar_volume(bars, 30)
    assert average == 25_000_000.0
    assert used == 29


def test_asking_for_no_sessions_at_all_is_refused():
    with pytest.raises(ValueError, match="at least one"):
        average_dollar_volume(sessions(30, 50.0, 500_000), 0)


# ---------------------------------------------------------------------------
# The average true range, which is the volatility floor (change A3)
# ---------------------------------------------------------------------------


def range_bar(close: float, high: float, low: float) -> FakeBar:
    """One session with a high and a low worth measuring."""
    return FakeBar(date=date(2026, 7, 1), close=close, volume=500_000.0,
                   high=high, low=low)


def steady_sessions(count: int, close: float, spread: float) -> list[FakeBar]:
    """`count` sessions that all close at the same price and range `spread`."""
    return [
        range_bar(close, close + spread / 2, close - spread / 2)
        for _ in range(count)
    ]


def test_one_quiet_session_ranges_from_its_low_to_its_high():
    """No gap, so the plain high minus low is the biggest of the three."""
    bar = range_bar(close=50.0, high=51.0, low=49.5)
    assert true_range(bar, previous_close=50.0) == pytest.approx(1.5)


def test_a_gap_up_counts_from_yesterdays_close_not_from_todays_low():
    """This is the term a naive high minus low misses.

    Yesterday closed at 20. Today opened at 24 and traded between 24 and 25, so
    the high to low range is only 1 dollar, but anyone holding it overnight
    lived through a 5 dollar move. The true range is that 5.
    """
    bar = range_bar(close=24.5, high=25.0, low=24.0)
    assert true_range(bar, previous_close=20.0) == pytest.approx(5.0)


def test_a_gap_down_counts_the_same_way():
    """Closed at 30, opened at 26 and traded 25.5 to 26.5. The move is 4.5."""
    bar = range_bar(close=26.0, high=26.5, low=25.5)
    assert true_range(bar, previous_close=30.0) == pytest.approx(4.5)


def test_a_session_with_no_previous_close_has_no_true_range():
    assert true_range(range_bar(50.0, 51.0, 49.0), None) is None


def test_a_bar_with_no_high_or_low_has_no_true_range():
    assert true_range(FakeBar(date(2026, 7, 1), 50.0, 500_000), 50.0) is None


def test_fourteen_flat_sessions_average_to_their_own_range():
    """Every session ranges 1 dollar and closes flat, so the ATR is 1 dollar."""
    atr, used = average_true_range(steady_sessions(20, 50.0, 1.0), 14)
    assert atr == pytest.approx(1.0)
    assert used == 14


def test_the_first_bar_is_only_there_to_be_the_previous_close():
    """Fifteen bars give fourteen true ranges, because the first has no yesterday."""
    atr, used = average_true_range(steady_sessions(15, 50.0, 2.0), 14)
    assert atr == pytest.approx(2.0)
    assert used == 14

    atr, used = average_true_range(steady_sessions(14, 50.0, 2.0), 14)
    assert atr is None, "fourteen bars is only thirteen true ranges"
    assert used == 13


def test_the_gap_term_pulls_the_average_up():
    """Thirteen quiet sessions and then one that gapped.

    Twelve true ranges of 1 dollar and one of 5 dollars, over 13 sessions, is an
    average of about 1.31 dollars. A high minus low average would have said 1.
    """
    bars = steady_sessions(13, 20.0, 1.0)
    bars.append(range_bar(close=24.5, high=25.0, low=24.0))
    atr, used = average_true_range(bars, 13)
    assert used == 13
    assert atr == pytest.approx((12 * 1.0 + 5.0) / 13)


def test_only_the_most_recent_days_count_towards_the_atr():
    calm = steady_sessions(30, 50.0, 0.2)
    wild = steady_sessions(14, 50.0, 3.0)
    atr, used = average_true_range(calm + wild, 14)
    assert atr == pytest.approx(3.0)
    assert used == 14


def test_a_name_with_too_little_history_gets_no_atr_at_all():
    atr, used = average_true_range(steady_sessions(8, 50.0, 1.0), 14)
    assert atr is None
    assert used == 7


def test_asking_for_no_atr_days_at_all_is_refused():
    with pytest.raises(ValueError, match="at least one"):
        average_true_range(steady_sessions(20, 50.0, 1.0), 0)


def test_the_atr_defaults_are_the_approved_numbers():
    assert DEFAULT_ATR_DAYS == 14
    assert DEFAULT_MIN_ATR_USD == 0.50
    assert DEFAULT_MIN_ATR_PCT_OF_PRICE == 1.5


def passes_volatility_floor(bars: list[FakeBar], price: float) -> bool:
    """The same two part test the scanner applies, on its own so it can be read."""
    atr, _ = average_true_range(bars, DEFAULT_ATR_DAYS)
    if atr is None:
        return False
    return atr >= DEFAULT_MIN_ATR_USD and (atr / price * 100.0) >= (
        DEFAULT_MIN_ATR_PCT_OF_PRICE
    )


def test_a_name_that_moves_enough_in_both_ways_clears_the_volatility_floor():
    """A 40 dollar stock that ranges a dollar a day is 2.5 percent. Fine."""
    assert passes_volatility_floor(steady_sessions(20, 40.0, 1.0), 40.0) is True


def test_a_penny_of_daily_range_fails_the_fifty_cent_half():
    """A 3 dollar stock ranging 20 cents is 6.7 percent of its price, which
    clears the percentage half, and is still far too small to trade."""
    bars = steady_sessions(20, 3.0, 0.20)
    atr, _ = average_true_range(bars, DEFAULT_ATR_DAYS)
    assert atr == pytest.approx(0.20)
    assert atr / 3.0 * 100.0 > DEFAULT_MIN_ATR_PCT_OF_PRICE
    assert passes_volatility_floor(bars, 3.0) is False


def test_a_quiet_large_cap_fails_the_percentage_half():
    """A 400 dollar stock ranging 2 dollars is 5 times the 50 cent floor in
    dollars and only half a percent of its price, which is noise."""
    bars = steady_sessions(20, 400.0, 2.0)
    atr, _ = average_true_range(bars, DEFAULT_ATR_DAYS)
    assert atr == pytest.approx(2.0)
    assert atr > DEFAULT_MIN_ATR_USD
    assert passes_volatility_floor(bars, 400.0) is False


def test_a_name_with_no_atr_at_all_fails_the_floor():
    """Not measurable means not traded, which is the safe answer."""
    assert passes_volatility_floor(steady_sessions(5, 40.0, 2.0), 40.0) is False


def test_landing_exactly_on_either_half_is_allowed():
    """At or above, not above, which is what the numbers in the spec mean."""
    # 50 cents of range on the nose, on a 20 dollar stock, so 2.5 percent.
    on_the_dollar_line = steady_sessions(20, 20.0, 0.50)
    assert average_true_range(on_the_dollar_line, 14)[0] == pytest.approx(0.50)
    assert passes_volatility_floor(on_the_dollar_line, 20.0) is True

    # 1.5 percent on the nose, on a 100 dollar stock, so 1.50 of range.
    on_the_percentage_line = steady_sessions(20, 100.0, 1.50)
    assert average_true_range(on_the_percentage_line, 14)[0] == pytest.approx(1.50)
    assert passes_volatility_floor(on_the_percentage_line, 100.0) is True


# ---------------------------------------------------------------------------
# The 20 million dollar floor, passing and failing
# ---------------------------------------------------------------------------


def passes_floor(bars: list[FakeBar], floor: float = DEFAULT_MIN_AVG_DOLLAR_VOLUME) -> bool:
    """The same test the scanner applies, on its own so it can be read."""
    average, _ = average_dollar_volume(bars, DEFAULT_DOLLAR_VOLUME_SESSIONS)
    return (average or 0.0) >= floor


def test_a_busy_name_clears_the_twenty_million_dollar_floor():
    """500,000 shares a day at 50 dollars is 25 million a day."""
    assert passes_floor(sessions(30, 50.0, 500_000)) is True


def test_a_quiet_name_fails_the_twenty_million_dollar_floor():
    """300,000 shares a day at 50 dollars is 15 million a day."""
    assert passes_floor(sessions(30, 50.0, 300_000)) is False


def test_landing_exactly_on_the_floor_is_allowed():
    """400,000 shares at 50 dollars is 20 million on the nose."""
    assert passes_floor(sessions(30, 50.0, 400_000)) is True


def test_a_cheap_name_can_clear_the_dollar_floor_that_a_share_floor_would_pass_too():
    """4 million shares at 6 dollars is 24 million dollars a day."""
    assert passes_floor(sessions(30, 6.0, 4_000_000)) is True


def test_an_expensive_name_clears_the_dollar_floor_on_few_shares():
    """This is the case the old million share floor got wrong.

    50,000 shares a day at 600 dollars is 30 million dollars a day, which is
    plenty liquid, but it is nowhere near a million shares. Under the old rule
    it was thrown out.
    """
    bars = sessions(30, 600.0, 50_000)
    assert passes_floor(bars) is True
    average, _ = average_dollar_volume(bars, 30)
    assert average == 30_000_000.0


def test_a_cheap_busy_name_can_fail_the_dollar_floor_that_a_share_floor_would_pass():
    """The other half of the same case.

    1.5 million shares a day at 6 dollars is 9 million dollars, which is thin.
    The old million share floor waved it through.
    """
    assert passes_floor(sessions(30, 6.0, 1_500_000)) is False


def test_a_name_too_new_to_judge_fails_the_floor():
    assert passes_floor(sessions(5, 500.0, 5_000_000)) is False


# ---------------------------------------------------------------------------
# Relative volume, anchored at 09:35
# ---------------------------------------------------------------------------


def test_the_anchor_is_five_minutes_after_the_open():
    assert REL_VOLUME_ANCHOR_LABEL == "09:35"
    assert REL_VOLUME_ANCHOR_MINUTES == 5.0
    assert SESSION_MINUTES == 390


def test_a_normal_day_would_have_traded_five_three_hundred_and_ninetieths_by_935():
    """A million share name normally does about 12,821 shares by 9:35."""
    expected = expected_volume_by(1_000_000, REL_VOLUME_ANCHOR_MINUTES)
    assert round(expected) == 12_821


def test_twice_the_normal_pace_by_935_reads_as_two():
    normal_by_935 = 1_000_000 * (REL_VOLUME_ANCHOR_MINUTES / SESSION_MINUTES)
    ratio = relative_volume(
        normal_by_935 * 2, 1_000_000, REL_VOLUME_ANCHOR_MINUTES
    )
    assert round(ratio, 6) == 2.0


def test_a_name_at_normal_pace_by_935_fails_the_two_times_floor():
    normal_by_935 = 1_000_000 * (REL_VOLUME_ANCHOR_MINUTES / SESSION_MINUTES)
    ratio = relative_volume(normal_by_935, 1_000_000, REL_VOLUME_ANCHOR_MINUTES)
    assert ratio == pytest.approx(1.0)
    assert ratio < 2.0


def test_the_same_volume_means_something_different_at_935_and_at_1130():
    """30,000 shares by 9:35 is busy. The same 30,000 by 11:30 is quiet."""
    at_935 = relative_volume(30_000, 1_000_000, REL_VOLUME_ANCHOR_MINUTES)
    at_1130 = relative_volume(30_000, 1_000_000, 120.0)
    assert at_935 > 2.0
    assert at_1130 < 0.5


def test_a_name_with_no_normal_volume_gets_no_ratio():
    assert relative_volume(50_000, None, REL_VOLUME_ANCHOR_MINUTES) is None
    assert relative_volume(50_000, 0, REL_VOLUME_ANCHOR_MINUTES) is None
    assert relative_volume(None, 1_000_000, REL_VOLUME_ANCHOR_MINUTES) is None


def test_no_time_elapsed_gives_no_ratio_rather_than_dividing_by_zero():
    assert relative_volume(50_000, 1_000_000, 0.0) is None
    assert expected_volume_by(1_000_000, 0.0) is None


def test_the_elapsed_fraction_never_runs_past_a_whole_session():
    """Run the scanner after the close and the ratio is against a full day."""
    assert expected_volume_by(1_000_000, 900.0) == 1_000_000.0


# ---------------------------------------------------------------------------
# Reading the numbers out of the settings file
# ---------------------------------------------------------------------------


def test_the_built_in_defaults_are_mos_numbers():
    thresholds = Thresholds()
    assert thresholds.min_avg_dollar_volume == 20_000_000
    assert thresholds.dollar_volume_sessions == 30
    assert thresholds.price_floor == 5
    assert thresholds.rel_volume_min == 2.0
    assert thresholds.max_candidates == 20


def test_the_shipped_settings_file_carries_the_dollar_floor():
    thresholds = load_thresholds(SHIPPED_CONFIG)
    assert thresholds.min_avg_dollar_volume == 20_000_000
    assert thresholds.dollar_volume_sessions == 30
    assert thresholds.rel_volume_min == 2.0
    assert thresholds.source == str(SHIPPED_CONFIG)


def test_the_old_share_floor_is_read_but_never_filtered_on():
    """It is carried into the output so a run can be read back, and no further."""
    thresholds = load_thresholds(SHIPPED_CONFIG)
    assert thresholds.deprecated_min_avg_volume == 1_000_000
    assert not hasattr(thresholds, "min_avg_volume"), (
        "the scanner should no longer have a share volume threshold to filter on"
    )
    assert "min_avg_volume" not in thresholds.as_dict()
    assert thresholds.as_dict()["deprecated_min_avg_volume"] == 1_000_000


def test_a_settings_file_with_no_dollar_floor_falls_back_to_the_default(tmp_path: Path):
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"].pop("min_avg_dollar_volume")
    data["universe"].pop("dollar_volume_sessions")
    path = tmp_path / "old.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    thresholds = load_thresholds(path)
    assert thresholds.min_avg_dollar_volume == DEFAULT_MIN_AVG_DOLLAR_VOLUME
    assert thresholds.dollar_volume_sessions == DEFAULT_DOLLAR_VOLUME_SESSIONS


def test_a_book_can_ask_for_its_own_floor(tmp_path: Path):
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"]["min_avg_dollar_volume"] = 50_000_000
    data["universe"]["dollar_volume_sessions"] = 45
    path = tmp_path / "stricter.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    thresholds = load_thresholds(path)
    assert thresholds.min_avg_dollar_volume == 50_000_000
    assert thresholds.dollar_volume_sessions == 45


def test_a_silly_number_of_sessions_is_pushed_back_up_to_something_meaningful(
    tmp_path: Path,
):
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"]["dollar_volume_sessions"] = 2
    path = tmp_path / "silly.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert load_thresholds(path).dollar_volume_sessions == MIN_DAILY_BARS_FOR_AVERAGE


def test_the_thresholds_written_into_the_output_name_the_anchor():
    """A shortlist should say what its relative volume figures were measured against."""
    written = Thresholds().as_dict()
    assert written["rel_volume_anchor_eastern"] == "09:35"
    assert written["rel_volume_anchor_minutes"] == 5.0
    assert written["min_avg_dollar_volume"] == 20_000_000
    assert written["dollar_volume_sessions"] == 30


# ---------------------------------------------------------------------------
# The Momentum v2 settings: the volatility floor and the hard exclusions
# ---------------------------------------------------------------------------


def test_the_momentum_v2_defaults_are_the_approved_numbers():
    thresholds = Thresholds()
    assert thresholds.atr_days == 14
    assert thresholds.min_atr_usd == 0.50
    assert thresholds.min_atr_pct_of_price == 1.5
    assert thresholds.min_history_sessions == 30
    assert thresholds.exclude_spacs is True
    assert thresholds.exclude_warrants_and_rights is True
    assert thresholds.exclude_preferred is True
    assert thresholds.require_us_primary_listing is True
    assert thresholds.exclude_halted is True


def test_the_relative_volume_window_is_recorded_even_though_it_is_not_used_here():
    """The real 9:30 to 9:35 measurement is agent/preopen.py's job.

    These two are carried for the record, so a shortlist says what window the
    strategy is actually about, even when this scanner had to fall back to
    measuring the same idea from daily bars.
    """
    thresholds = Thresholds()
    assert thresholds.rel_volume_window == DEFAULT_REL_VOLUME_WINDOW == "09:30-09:35"
    assert thresholds.rel_volume_baseline_days == DEFAULT_REL_VOLUME_BASELINE_DAYS == 14
    written = thresholds.as_dict()
    assert written["rel_volume_window"] == "09:30-09:35"
    assert written["rel_volume_baseline_days"] == 14


def test_every_momentum_v2_number_reaches_the_written_output():
    """A run has to be readable back afterwards, so all of them are published."""
    written = Thresholds().as_dict()
    for key, expected in (
        ("atr_days", 14),
        ("min_atr_usd", 0.50),
        ("min_atr_pct_of_price", 1.5),
        ("min_history_sessions", 30),
        ("exclude_spacs", True),
        ("exclude_warrants_and_rights", True),
        ("exclude_preferred", True),
        ("require_us_primary_listing", True),
        ("exclude_halted", True),
    ):
        assert written[key] == expected, key


def test_the_settings_file_can_move_the_volatility_floor(tmp_path: Path):
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"]["atr_days"] = 21
    data["universe"]["min_atr_usd"] = 0.75
    data["universe"]["min_atr_pct_of_price"] = 2.0
    data["universe"]["min_history_sessions"] = 40
    path = tmp_path / "volatile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    thresholds = load_thresholds(path)
    assert thresholds.atr_days == 21
    assert thresholds.min_atr_usd == 0.75
    assert thresholds.min_atr_pct_of_price == 2.0
    assert thresholds.min_history_sessions == 40


def test_a_settings_file_with_no_volatility_keys_falls_back_to_the_defaults(
    tmp_path: Path,
):
    """The shipped file may not carry these yet, and that must not break a run."""
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    for key in ("atr_days", "min_atr_usd", "min_atr_pct_of_price",
                "min_history_sessions", "exclude_spacs",
                "exclude_warrants_and_rights", "exclude_preferred",
                "require_us_primary_listing", "exclude_halted"):
        data["universe"].pop(key, None)
    path = tmp_path / "bare.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    thresholds = load_thresholds(path)
    assert thresholds.atr_days == DEFAULT_ATR_DAYS
    assert thresholds.min_atr_usd == DEFAULT_MIN_ATR_USD
    assert thresholds.min_atr_pct_of_price == DEFAULT_MIN_ATR_PCT_OF_PRICE
    assert thresholds.min_history_sessions == DEFAULT_MIN_HISTORY_SESSIONS
    assert thresholds.exclude_spacs is True
    assert thresholds.require_us_primary_listing is True


def test_a_switch_written_out_in_words_is_read_as_words(tmp_path: Path):
    """bool("no") is True in Python, which would turn a switch back on."""
    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    data["universe"]["exclude_spacs"] = "no"
    data["universe"]["exclude_preferred"] = "off"
    data["universe"]["exclude_halted"] = "yes"
    path = tmp_path / "words.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    thresholds = load_thresholds(path)
    assert thresholds.exclude_spacs is False
    assert thresholds.exclude_preferred is False
    assert thresholds.exclude_halted is True


# ---------------------------------------------------------------------------
# The words a person reads
# ---------------------------------------------------------------------------


def test_dollar_figures_are_written_so_a_person_can_read_them():
    assert human_dollars(20_000_000) == "20.0 million dollars"
    assert human_dollars(1_400_000_000) == "1.4 billion dollars"
    assert human_dollars(45_000) == "45 thousand dollars"
    assert human_dollars(None) == "unknown"


def test_the_guardrails_and_the_scanner_agree_on_the_floor():
    """Two files hold this number, so a test makes sure they cannot drift apart."""
    from agent.guardrails import (
        DEFAULT_DOLLAR_VOLUME_SESSIONS as GUARDRAIL_SESSIONS,
        DEFAULT_MIN_AVG_DOLLAR_VOLUME as GUARDRAIL_FLOOR,
        load_guardrails,
    )

    assert GUARDRAIL_FLOOR == DEFAULT_MIN_AVG_DOLLAR_VOLUME
    assert GUARDRAIL_SESSIONS == DEFAULT_DOLLAR_VOLUME_SESSIONS

    settings = load_guardrails(SHIPPED_CONFIG)
    thresholds = load_thresholds(SHIPPED_CONFIG)
    assert settings.universe.min_avg_dollar_volume == thresholds.min_avg_dollar_volume
    assert settings.universe.dollar_volume_sessions == thresholds.dollar_volume_sessions
    assert settings.scanner.rel_volume_min == thresholds.rel_volume_min
    assert settings.universe.price_floor == thresholds.price_floor


def test_the_momentum_books_scan_on_the_same_numbers_as_the_shared_file():
    """Books A, B and E all point at the 20 million dollar floor."""
    from agent.guardrails import load_book_guardrails

    books_yaml = PROJECT_ROOT / "config" / "books.yaml"
    for book_id in ("A", "B", "E"):
        g = load_book_guardrails(books_yaml, book_id)
        assert g.universe.min_avg_dollar_volume == 20_000_000, book_id
        assert g.universe.dollar_volume_sessions == 30, book_id
        assert g.scanner.rel_volume_min == 2.0, book_id


# ---------------------------------------------------------------------------
# A stand in for IB Gateway that behaves the way this account really behaved
# ---------------------------------------------------------------------------
#
# Measured against the paper Gateway on 2026-09-06, in
# /Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/scan_probe.py
# and its follow up:
#
#   an UNFILTERED scan returns 50 rows in well under a second
#   the SAME scan with any filter on it returns ZERO rows, and the only sign of
#   trouble is error 162, "Scanner filter X is disabled", followed by 365, "no
#   scanner subscription found", on that request id
#
# Nothing raises. An empty list is what the caller sees, and an empty list is
# also what a quiet morning looks like. That is the whole reason the scanner
# stopped sending filters and started checking every scan against a control.

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from ib_async import ScannerSubscription, TagValue  # noqa: E402

import agent.scanner as scanner_module  # noqa: E402
from agent import scan_truth  # noqa: E402
from agent.scan_truth import ScanFailure  # noqa: E402
from agent.scanner import (  # noqa: E402
    CONTROL_SCAN_CODE,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    ENRICHMENT_CAP,
    FORBIDDEN_SCAN_CODES,
    HISTORY_REQUEST_BUDGET,
    SCAN_CODES,
    SCAN_SPECS,
    SCANNER_REQUESTS_PER_RUN,
    TOTAL_REQUEST_RATION,
    Candidate,
    OpeningMomentumScanner,
)

EASTERN = ZoneInfo("America/New_York")

# Snapshotted here, at import, before the fixture below shortens them, so the
# real production pauses can still be asserted on.
REAL_ERROR_SETTLE_S = scan_truth.ERROR_SETTLE_S
REAL_HISTORY_MIN_GAP_SECONDS = scanner_module.HISTORY_MIN_GAP_SECONDS

FILTER_DISABLED_162 = (
    "Historical Market Data Service error message:"
    "Scanner filter priceAbove is disabled."
)
NO_SUBSCRIPTION_365 = "No scanner subscription found for ticker id:{req}"
BENIGN_CANCELLED_162 = (
    "Historical Market Data Service error message:"
    "API scanner subscription cancelled: {req}"
)


@pytest.fixture(autouse=True)
def no_real_time_waits(monkeypatch):
    """Take the two real world pauses out, so the suite is not mostly sleeping.

    Both are real and both matter in production: the 0.3 second wait lets late
    error callbacks catch up before a scan is judged, and the quarter second gap
    between historical requests keeps Gateway friendly. Neither is what any test
    below is about, and the numbers themselves are pinned by
    test_the_pacing_budget_adds_up so shrinking them here cannot hide a change.
    """
    monkeypatch.setattr(scan_truth, "ERROR_SETTLE_S", 0.0)
    import agent.scanner as _scanner
    monkeypatch.setattr(_scanner, "HISTORY_MIN_GAP_SECONDS", 0.0)


class FakeEvent:
    """ib_async's += and -= event, small enough to read."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self

    def emit(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class FakeClient:
    """ib_async hands out request ids from this counter, so the fake does too."""

    def __init__(self):
        self._reqIdSeq = 3


class FakeContract:
    def __init__(self, symbol, con_id, primary="NASDAQ", currency="USD"):
        self.symbol = symbol
        self.conId = con_id
        self.primaryExchange = primary
        self.currency = currency
        self.exchange = "SMART"


class FakeContractDetails:
    """The three industry fields are here because IBKR really does send them.

    It does not always fill all three in, which is the whole reason the scanner
    tries them in order, so every one of them can be set to "" in a test.
    """

    def __init__(self, contract, long_name="Example Corp", stock_type="COMMON",
                 industry="Technology", category="Computers",
                 subcategory="Computer Software"):
        self.contract = contract
        self.longName = long_name
        self.stockType = stock_type
        self.industry = industry
        self.category = category
        self.subcategory = subcategory


class FakeRow:
    """One scanner row. Carries a contract and a rank and nothing else, which is
    all IBKR actually sends back."""

    def __init__(self, symbol, con_id, rank):
        self.contractDetails = FakeContractDetails(FakeContract(symbol, con_id))
        self.rank = rank


class FakeIB:
    """IB Gateway as it actually answered on 2026-09-06.

    filters_enabled=False is the state Mo's account was in: unfiltered scans
    work, filtered scans come back empty with 162 then 365 and no exception.

    scanner_dead=True is the worse state, where the scanner service answers
    nothing at all, filters or no filters. That is what the truth check exists
    to catch, because it is the one that would otherwise be read as a quiet day.
    """

    def __init__(self, rows_by_code=None, filters_enabled=False,
                 scanner_dead=False, daily_bars=None, intraday_bars=None,
                 rows=50):
        self.errorEvent = FakeEvent()
        self.client = FakeClient()
        self.rows_by_code = rows_by_code or {}
        self.filters_enabled = filters_enabled
        self.scanner_dead = scanner_dead
        self.daily_bars = daily_bars or {}
        self.intraday_bars = intraday_bars or {}
        self.default_rows = rows
        self.requested: list[tuple[str, list[tuple[str, str]]]] = []
        self.market_data_type = None
        self.connected = True

    # -- the scanner -------------------------------------------------------

    def _rows_for(self, scan_code):
        if scan_code in self.rows_by_code:
            return [FakeRow(symbol, con_id, rank)
                    for rank, (symbol, con_id) in enumerate(self.rows_by_code[scan_code])]
        return [FakeRow(f"{scan_code[:3]}{n:02d}", 90000 + n, n)
                for n in range(self.default_rows)]

    async def reqScannerDataAsync(self, subscription, _unused, filters):
        req_id = self.client._reqIdSeq
        self.client._reqIdSeq += 1
        sent = [(f.tag, f.value) for f in filters]
        self.requested.append((subscription.scanCode, sent))

        if self.scanner_dead or (sent and not self.filters_enabled):
            # Exactly what was measured: no rows, then 162 and then 365, and not
            # one exception between them.
            self.errorEvent.emit(req_id, 162, FILTER_DISABLED_162, None)
            self.errorEvent.emit(req_id, 365, NO_SUBSCRIPTION_365.format(req=req_id), None)
            return []

        rows = self._rows_for(subscription.scanCode)
        # Every healthy one-shot scan ends with this 162. It is benign and the
        # truth check knows it by its text.
        self.errorEvent.emit(req_id, 162, BENIGN_CANCELLED_162.format(req=req_id), None)
        return rows

    # -- everything else the scanner touches, all reads --------------------

    def reqMarketDataType(self, data_type):
        self.market_data_type = data_type

    async def reqHistoricalDataAsync(self, contract, endDateTime, durationStr,
                                     barSizeSetting, whatToShow, useRTH, formatDate):
        if barSizeSetting == "1 day":
            return list(self.daily_bars.get(contract.symbol, []))
        return list(self.intraday_bars.get(contract.symbol, []))

    async def reqContractDetailsAsync(self, contract):
        return [FakeContractDetails(FakeContract(contract.symbol, contract.conId or 1))]

    async def connectAsync(self, *args, **kwargs):
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def sub_for(scan_code):
    return ScannerSubscription(instrument="STK", locationCode="STK.US.MAJOR",
                               scanCode=scan_code, numberOfRows=50)


def make_scanner(ib, **kwargs):
    thresholds = Thresholds()
    for key, value in kwargs.items():
        setattr(thresholds, key, value)
    return OpeningMomentumScanner(ib, thresholds)


# ---------------------------------------------------------------------------
# The fake really does reproduce what was measured
# ---------------------------------------------------------------------------


def test_the_fake_gateway_answers_an_unfiltered_scan_with_fifty_rows():
    ib = FakeIB()
    capture = scan_truth.ErrorCapture(ib)
    sub = sub_for("TOP_PERC_GAIN")
    result = asyncio.run(scan_truth.run_scan_async(ib, sub, [], capture))
    assert len(result.rows) == 50
    assert scan_truth.hard_errors(result.errors) == [], (
        "the only message on a healthy scan is the benign cancelled notice")


def test_the_fake_gateway_answers_a_filtered_scan_with_nothing_and_two_errors():
    """The whole reason for this rework, reproduced."""
    ib = FakeIB()
    capture = scan_truth.ErrorCapture(ib)
    sub = sub_for("TOP_PERC_GAIN")
    result = asyncio.run(
        scan_truth.run_scan_async(ib, sub, [TagValue("priceAbove", "5")], capture))
    assert result.rows == []
    assert [code for code, _ in result.errors] == [162, 365]
    assert "disabled" in result.errors[0][1]


def test_a_filtered_scan_on_this_account_is_never_read_as_an_empty_morning():
    ib = FakeIB()
    capture = scan_truth.ErrorCapture(ib)
    control = asyncio.run(
        scan_truth.run_scan_async(ib, sub_for("MOST_ACTIVE"), [], capture))
    filtered = asyncio.run(
        scan_truth.run_scan_async(ib, sub_for("TOP_PERC_GAIN"),
                                  [TagValue("priceAbove", "5")], capture))
    with pytest.raises(ScanFailure) as exc:
        scan_truth.assert_trustworthy(filtered, control)
    assert "162" in str(exc.value) and "365" in str(exc.value)


# ---------------------------------------------------------------------------
# The scanner asks for four unfiltered scans and a control, and nothing else
# ---------------------------------------------------------------------------


def test_the_scanner_sends_no_filters_to_gateway_at_all():
    """The rework in one assertion: every request goes out with an empty filter list."""
    ib = FakeIB()
    scanner = make_scanner(ib)
    asyncio.run(scanner.collect_candidates())
    assert ib.requested, "no scan was requested at all"
    for scan_code, filters in ib.requested:
        assert filters == [], f"{scan_code} was sent filters: {filters}"


def test_the_scanner_asks_for_the_four_codes_plus_the_control():
    ib = FakeIB()
    scanner = make_scanner(ib)
    asyncio.run(scanner.collect_candidates())
    asked = [code for code, _ in ib.requested]
    assert asked[0] == CONTROL_SCAN_CODE, "the control goes first"
    assert asked[1:] == list(SCAN_CODES)
    assert asked[1:] == ["TOP_PERC_GAIN", "TOP_PERC_LOSE", "HOT_BY_VOLUME",
                         "HIGH_STVOLUME_5MIN"]
    assert len(asked) == SCANNER_REQUESTS_PER_RUN


def test_top_open_perc_gain_is_never_requested():
    """IBKR staff confirmed it returns nothing before the session is under way,
    which is the one moment this scanner runs."""
    assert "TOP_OPEN_PERC_GAIN" in FORBIDDEN_SCAN_CODES
    assert "TOP_OPEN_PERC_GAIN" not in SCAN_CODES
    assert "TOP_OPEN_PERC_GAIN" != CONTROL_SCAN_CODE

    ib = FakeIB()
    scanner = make_scanner(ib)
    asyncio.run(scanner.collect_candidates())
    asked = {code for code, _ in ib.requested}
    assert not asked & FORBIDDEN_SCAN_CODES

    with pytest.raises(ValueError, match="TOP_PERC_GAIN"):
        scanner.make_subscription("TOP_OPEN_PERC_GAIN")


def test_every_scan_gets_its_own_line_in_the_diagnostics():
    ib = FakeIB()
    scanner = make_scanner(ib)
    asyncio.run(scanner.collect_candidates())

    diagnostics = scanner.scan_diagnostics
    assert set(diagnostics) == set(SCAN_CODES) | {CONTROL_SCAN_CODE}
    for code, block in diagnostics.items():
        assert block["rows"] == 50
        assert block["completed"] is True
        assert block["filters"] == []
        assert isinstance(block["elapsed_s"], float)
        assert block["errors"], "even a healthy scan records its benign cancel notice"
    assert diagnostics[CONTROL_SCAN_CODE]["role"] == "control"
    assert diagnostics["TOP_PERC_GAIN"]["direction"] == DIRECTION_LONG
    assert diagnostics["TOP_PERC_LOSE"]["direction"] == DIRECTION_SHORT
    assert diagnostics["HOT_BY_VOLUME"]["direction"] is None


# ---------------------------------------------------------------------------
# A scan that cannot be believed stops everything
# ---------------------------------------------------------------------------


def test_a_dead_scanner_raises_rather_than_returning_an_empty_list():
    ib = FakeIB(scanner_dead=True)
    scanner = make_scanner(ib)
    with pytest.raises(ScanFailure) as exc:
        asyncio.run(scanner.collect_candidates())
    assert "162" in str(exc.value)
    assert "365" in str(exc.value)


def test_a_short_control_stops_the_run_even_when_the_gainers_scan_looks_fine():
    """The market is never this empty. Nineteen rows is a broken scanner."""
    ib = FakeIB(rows=19)
    scanner = make_scanner(ib)
    with pytest.raises(ScanFailure) as exc:
        asyncio.run(scanner.collect_candidates())
    assert "never this empty" in str(exc.value)


def run_scanner_cli(monkeypatch, ib, out_path, extra=()):
    """Drive agent/scanner.py's own main() with the fake Gateway in place of IB."""
    monkeypatch.setattr(scanner_module, "IB", lambda *a, **k: ib)
    monkeypatch.setattr(
        scanner_module.OpeningMomentumScanner, "measure_session_progress",
        _fixed_session_progress)
    return scanner_module.main(["--out", str(out_path), *extra])


async def _fixed_session_progress(self, reference_symbol):
    """Pin the run to the 09:35 anchor so the tests do not depend on the clock."""
    self.session_minutes_elapsed = REL_VOLUME_ANCHOR_MINUTES
    self.data_as_of = datetime.now(EASTERN).isoformat()



def test_a_failed_scan_never_overwrites_yesterdays_shortlist(monkeypatch, tmp_path):
    """The rule that matters most. An empty file and a broken scanner must never
    look the same to the loop, so a broken scan writes nothing at all."""
    out = tmp_path / "shortlist_2026-09-08.json"
    yesterday = {"candidates": [{"symbol": "NVDA", "direction": "long"}],
                 "trade_date": "2026-09-05"}
    out.write_text(json.dumps(yesterday), encoding="utf-8")
    before = out.read_text(encoding="utf-8")

    code = run_scanner_cli(monkeypatch, FakeIB(scanner_dead=True), out)

    assert code == 3, "a scan that cannot be trusted exits 3, not 0 and not 1"
    assert out.read_text(encoding="utf-8") == before, (
        "the previous shortlist was overwritten, which is the exact failure this "
        "rework exists to prevent")


def test_the_failure_line_on_stderr_carries_the_codes(monkeypatch, tmp_path, capsys):
    out = tmp_path / "shortlist.json"
    code = run_scanner_cli(monkeypatch, FakeIB(scanner_dead=True), out)
    assert code == 3
    assert not out.exists()

    printed = capsys.readouterr().err
    line = next(ln for ln in printed.splitlines()
                if ln.startswith(scanner_module.SCAN_FAILURE_MARKER))
    payload = json.loads(line[len(scanner_module.SCAN_FAILURE_MARKER):])
    assert payload["codes"] == [162, 365]
    assert payload["wrote_anything"] is False
    assert "TOP_PERC_GAIN" in payload["scan_diagnostics"]


# ---------------------------------------------------------------------------
# The union across four scans, the dedupe, and which way each name is going
# ---------------------------------------------------------------------------


def today_eastern():
    return datetime.now(EASTERN).date()


def daily_history(today_close: float, today_volume: float = 20_000.0,
                  normal_close: float = 50.0, normal_volume: float = 500_000.0,
                  normal_range: float = 1.0):
    """Thirty quiet sessions and then today.

    Thirty at 50 dollars on 500,000 shares is 25 million dollars a day, which
    clears the 20 million floor. 20,000 shares by 09:35 against a 500,000 share
    daily average is about 3.1 times the normal pace, which clears the 2 times
    floor. Thirty completed sessions is exactly the history the hard exclusions
    ask for. Each of those sessions ranges a dollar, so the average true range
    is 1 dollar, which is over the 50 cent floor and over 1.5 percent of every
    price used below. So every name built this way passes on liquidity, volume,
    history and volatility, and the only thing left for a test to be about is
    direction.
    """
    start = today_eastern() - timedelta(days=60)
    bars = [FakeBar(date=start + timedelta(days=n), close=normal_close,
                    volume=normal_volume,
                    high=normal_close + normal_range / 2,
                    low=normal_close - normal_range / 2) for n in range(30)]
    bars.append(FakeBar(date=today_eastern(), close=today_close,
                        volume=today_volume, high=today_close,
                        low=today_close * 0.98))
    return bars


def opening_bars(price: float, candle: str = "up"):
    """Today's 9:30 to 9:35 candle, made to close up, down or flat.

    The sign of this candle is what decides long or short under change A5, so a
    test that cares about direction sets it here rather than leaving the open at
    whatever the dataclass defaults to.
    """
    open_time = datetime.now(EASTERN).replace(hour=9, minute=30, second=0, microsecond=0)
    if candle == "up":
        open_price = price * 0.99
    elif candle == "down":
        open_price = price * 1.01
    else:
        open_price = price
    return [FakeBar(date=open_time, open=open_price, close=price, volume=5_000.0,
                    high=max(open_price, price) * 1.002,
                    low=min(open_price, price) * 0.998)]


UNION_ROWS = {
    "TOP_PERC_GAIN": [("UPUP", 101), ("BOTH", 103), ("LIAR", 105)],
    "TOP_PERC_LOSE": [("DOWN", 102)],
    "HOT_BY_VOLUME": [("BOTH", 103), ("VOLO", 104), ("VDWN", 106)],
    "HIGH_STVOLUME_5MIN": [("VOLO", 104)],
}

UNION_BARS = {
    "UPUP": daily_history(55.0),     # up 10 percent, off the gainers list
    "DOWN": daily_history(45.0),     # down 10 percent, off the fallers list
    "BOTH": daily_history(55.0),     # on the gainers list and the volume list
    "VOLO": daily_history(52.0),     # volume lists only, and it is up
    "VDWN": daily_history(46.0),     # volume lists only, and it is down
    "LIAR": daily_history(45.0),     # on the gainers list but actually down
}

# The opening candle points the same way the day's move does, so these fixtures
# say the same thing twice and a test about the union is not accidentally a test
# about the candle rule. The candle tests below set it deliberately.
UNION_INTRADAY = {
    symbol: opening_bars(bars[-1].close,
                         "up" if bars[-1].close > 50.0 else "down")
    for symbol, bars in UNION_BARS.items()
}


def union_ib(**kwargs):
    return FakeIB(rows_by_code=UNION_ROWS, daily_bars=UNION_BARS,
                  intraday_bars=UNION_INTRADAY, **kwargs)


def test_the_four_scans_are_merged_and_a_repeated_name_appears_once():
    scanner = make_scanner(union_ib())
    candidates = asyncio.run(scanner.collect_candidates())

    symbols = [c.symbol for c in candidates]
    assert sorted(symbols) == ["BOTH", "DOWN", "LIAR", "UPUP", "VDWN", "VOLO"]
    assert len(symbols) == len(set(symbols)), "a name appeared twice"


def test_a_name_on_two_scans_keeps_both_and_goes_to_the_front():
    scanner = make_scanner(union_ib())
    candidates = asyncio.run(scanner.collect_candidates())
    by_symbol = {c.symbol: c for c in candidates}

    assert by_symbol["BOTH"].flagged_by == ["TOP_PERC_GAIN", "HOT_BY_VOLUME"]
    assert by_symbol["VOLO"].flagged_by == ["HOT_BY_VOLUME", "HIGH_STVOLUME_5MIN"]
    assert by_symbol["UPUP"].flagged_by == ["TOP_PERC_GAIN"]

    front = [c.symbol for c in candidates[:2]]
    assert set(front) == {"BOTH", "VOLO"}, (
        "names that more than one scan flagged should survive the enrichment cap")


def test_the_scans_say_which_way_a_name_is_going():
    scanner = make_scanner(union_ib())
    candidates = asyncio.run(scanner.collect_candidates())
    by_symbol = {c.symbol: c for c in candidates}

    assert by_symbol["UPUP"].directions_flagged == [DIRECTION_LONG]
    assert by_symbol["DOWN"].directions_flagged == [DIRECTION_SHORT]
    assert by_symbol["VOLO"].directions_flagged == [], (
        "a volume scan says a name is busy, not which way it is going")


def test_a_volume_only_name_takes_its_direction_from_its_own_move():
    scanner = make_scanner(FakeIB())
    up = Candidate(symbol="X", con_id=1, gain_pct=4.0)
    down = Candidate(symbol="Y", con_id=2, gain_pct=-4.0)
    flat = Candidate(symbol="Z", con_id=3, gain_pct=0.0)
    unknown = Candidate(symbol="W", con_id=4, gain_pct=None)

    assert scanner.resolve_direction(up) == DIRECTION_LONG
    assert scanner.resolve_direction(down) == DIRECTION_SHORT
    assert scanner.resolve_direction(flat) is None
    assert scanner.resolve_direction(unknown) is None


def test_a_scan_that_says_long_beats_the_price_when_the_scan_is_the_only_word():
    scanner = make_scanner(FakeIB())
    tagged = Candidate(symbol="X", con_id=1, gain_pct=None,
                       directions_flagged=[DIRECTION_SHORT])
    assert scanner.resolve_direction(tagged) == DIRECTION_SHORT


def test_the_shortlist_carries_longs_and_shorts_side_by_side(monkeypatch, tmp_path):
    """End to end through the real command line, on the fake Gateway."""
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    by_symbol = {c["symbol"]: c for c in written["candidates"]}

    assert by_symbol["UPUP"]["direction"] == DIRECTION_LONG
    assert by_symbol["DOWN"]["direction"] == DIRECTION_SHORT
    assert by_symbol["VOLO"]["direction"] == DIRECTION_LONG
    assert by_symbol["VDWN"]["direction"] == DIRECTION_SHORT
    assert "LIAR" not in by_symbol, (
        "a name off the gainers list that is actually down contradicts itself "
        "and should be dropped, not shortlisted with a trigger pointing the "
        "wrong way")

    # Both spellings, because loop.py reads one and decide.py reads either.
    for row in written["candidates"]:
        assert row["side"] == row["direction"]

    assert written["counts"]["final_long"] == 3
    assert written["counts"]["final_short"] == 2
    assert written["counts"]["passed_direction_agrees"] == 5


def test_the_written_file_carries_the_scan_diagnostics(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    diagnostics = written["scan_diagnostics"]
    assert set(diagnostics) == set(SCAN_CODES) | {CONTROL_SCAN_CODE}
    assert diagnostics[CONTROL_SCAN_CODE]["rows"] == 50
    assert diagnostics["TOP_PERC_LOSE"]["rows"] == 1
    assert written["scan_filters_sent"] == []
    assert written["scan_codes"] == list(SCAN_CODES)
    assert written["control_scan_code"] == CONTROL_SCAN_CODE
    assert written["scanner_requests_used"] == SCANNER_REQUESTS_PER_RUN


# ---------------------------------------------------------------------------
# The pacing budget
# ---------------------------------------------------------------------------


def test_the_pacing_budget_adds_up():
    """Gateway allows about sixty requests in any ten minutes, across the whole
    connection. Four scans plus a control is five of them, so the historical
    budget had to come down and the enrichment cap with it.

        5   scanner requests
       55   historical budget
       ---
       60   the ration
    """
    assert SCANNER_REQUESTS_PER_RUN == len(SCAN_CODES) + 1 == 5
    assert HISTORY_REQUEST_BUDGET == 55
    assert SCANNER_REQUESTS_PER_RUN + HISTORY_REQUEST_BUDGET == TOTAL_REQUEST_RATION == 60

    # And inside the historical budget: one reference request, one daily request
    # per enriched name, and one opening range per shortlisted name.
    reference = 1
    shortlist = Thresholds().max_candidates
    assert ENRICHMENT_CAP == 35
    assert reference + ENRICHMENT_CAP == 36
    # Worst case wants one more than there is, so one opening range is skipped
    # and the run says so. Every realistic run is far under.
    assert reference + ENRICHMENT_CAP + shortlist == 56
    assert HISTORY_REQUEST_BUDGET == 55

    # The real gaps, pinned here because the tests above switch them off.
    assert REAL_HISTORY_MIN_GAP_SECONDS == 0.25
    assert REAL_ERROR_SETTLE_S == 0.3


def test_the_run_counts_what_it_spent(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert written["scanner_requests_used"] == 5
    assert written["total_requests_used"] == (
        written["scanner_requests_used"] + written["historical_requests_used"])
    assert written["total_requests_used"] <= TOTAL_REQUEST_RATION
    assert written["total_request_ration"] == 60


# ---------------------------------------------------------------------------
# The volatility floor inside a real run (change A3)
# ---------------------------------------------------------------------------


def volatility_history(price: float, daily_range: float, normal_volume: float,
                       with_ranges: bool = True):
    """Thirty completed sessions at one price and one daily range, then today.

    with_ranges False leaves the highs and lows off the completed bars, which is
    what a name looks like when its range cannot be worked out at all.
    """
    start = today_eastern() - timedelta(days=60)
    bars = []
    for n in range(30):
        if with_ranges:
            bars.append(FakeBar(date=start + timedelta(days=n), close=price,
                                volume=normal_volume,
                                high=price + daily_range / 2,
                                low=price - daily_range / 2))
        else:
            bars.append(FakeBar(date=start + timedelta(days=n), close=price,
                                volume=normal_volume))
    today_close = price * 1.05
    bars.append(FakeBar(date=today_eastern(), close=today_close,
                        volume=normal_volume * 0.05, high=today_close, low=price))
    return bars


VOLATILITY_ROWS = {
    "TOP_PERC_GAIN": [("GOOD", 201), ("THIN", 202), ("QUIET", 203), ("NOATR", 204)],
    "TOP_PERC_LOSE": [],
    "HOT_BY_VOLUME": [],
    "HIGH_STVOLUME_5MIN": [],
}

VOLATILITY_BARS = {
    # 40 dollars, 1.20 of daily range, so 1.20 dollars and about 2.9 percent.
    "GOOD": volatility_history(40.0, 1.20, 600_000),
    # 10 dollars, 30 cents of daily range. 2.9 percent of its price, which
    # clears the percentage half, and under the 50 cent floor, which does not.
    "THIN": volatility_history(10.0, 0.30, 2_500_000),
    # 400 dollars, 2 dollars of daily range. Four times the 50 cent floor in
    # dollars, and half a percent of its price, which is noise.
    "QUIET": volatility_history(400.0, 2.00, 60_000),
    # No highs or lows at all, so there is no range to measure.
    "NOATR": volatility_history(40.0, 1.20, 600_000, with_ranges=False),
}

VOLATILITY_INTRADAY = {"GOOD": opening_bars(42.0, "up")}


def volatility_ib():
    return FakeIB(rows_by_code=VOLATILITY_ROWS, daily_bars=VOLATILITY_BARS,
                  intraday_bars=VOLATILITY_INTRADAY)


def test_the_volatility_floor_keeps_only_the_name_that_clears_both_halves(
    monkeypatch, tmp_path
):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, volatility_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    counts = written["counts"]

    assert counts["passed_dollar_volume"] == 4, (
        "all four are liquid enough, so the volatility filter is the only thing "
        "separating them")
    assert counts["passed_volatility"] == 1
    assert [c["symbol"] for c in written["candidates"]] == ["GOOD"]


def test_the_written_row_says_what_the_range_actually_was(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, volatility_ib(), out) == 0
    row = json.loads(out.read_text(encoding="utf-8"))["candidates"][0]

    assert row["atr"] == pytest.approx(1.20)
    assert row["atr_days_used"] == 14
    assert row["atr_pct_of_price"] == pytest.approx(1.20 / 42.0 * 100.0, abs=0.01)
    assert any("dollars in a normal session" in reason for reason in row["reasons"])
    assert any("percent of its price" in reason for reason in row["reasons"])


def test_a_name_without_enough_history_never_reaches_the_filters(monkeypatch, tmp_path):
    """The rule that replaced the listing age rule Mo rejected.

    Twenty completed sessions is a perfectly liquid, perfectly volatile name. It
    still comes off the list, because 30 sessions is what it takes to measure it.
    """
    bars = volatility_history(40.0, 1.20, 600_000)[-21:]
    assert len([b for b in bars if b.date != today_eastern()]) == 20

    ib = FakeIB(
        rows_by_code={"TOP_PERC_GAIN": [("YOUNG", 301)], "TOP_PERC_LOSE": [],
                      "HOT_BY_VOLUME": [], "HIGH_STVOLUME_5MIN": []},
        daily_bars={"YOUNG": bars},
    )
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, ib, out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert written["counts"]["daily_bars_ok"] == 1
    assert written["counts"]["passed_history"] == 0
    assert written["candidates"] == []


# ---------------------------------------------------------------------------
# The shortlist is ranked by relative volume, not by the size of the move (A4)
# ---------------------------------------------------------------------------


def test_the_score_is_now_simply_the_relative_volume():
    scanner = make_scanner(FakeIB())
    busy = Candidate(symbol="X", con_id=1, gain_pct=2.0, rel_volume=9.4)
    assert scanner.compute_score(busy) == pytest.approx(9.4)

    # The size of the move no longer enters into it at all.
    same_volume_bigger_move = Candidate(symbol="Y", con_id=2, gain_pct=25.0,
                                        rel_volume=9.4)
    assert scanner.compute_score(same_volume_bigger_move) == pytest.approx(9.4)


def test_a_name_with_no_relative_volume_scores_nothing():
    scanner = make_scanner(FakeIB())
    assert scanner.compute_score(Candidate(symbol="X", con_id=1)) == 0.0


RANK_ROWS = {
    "TOP_PERC_GAIN": [("MOVER", 401), ("MIDDLE", 402), ("HEAVY", 403)],
    "TOP_PERC_LOSE": [],
    "HOT_BY_VOLUME": [],
    "HIGH_STVOLUME_5MIN": [],
}

# All three are up on the day and all three clear every floor. The only thing
# that separates them is how much has traded, and how far they have moved.
RANK_BARS = {
    "HEAVY": daily_history(51.0, today_volume=60_000),    # up 2 percent, busiest
    "MIDDLE": daily_history(52.5, today_volume=30_000),   # up 5 percent
    "MOVER": daily_history(60.0, today_volume=20_000),    # up 20 percent, quietest
}

RANK_INTRADAY = {symbol: opening_bars(bars[-1].close, "up")
                 for symbol, bars in RANK_BARS.items()}


def rank_ib():
    return FakeIB(rows_by_code=RANK_ROWS, daily_bars=RANK_BARS,
                  intraday_bars=RANK_INTRADAY)


def test_the_busiest_name_ranks_first_even_though_it_moved_least(monkeypatch, tmp_path):
    """This is change A4 in one test.

    MOVER is up 20 percent and HEAVY is up 2 percent, so the old score would
    have put MOVER at the top. The published edge ranks by relative volume, and
    HEAVY is trading three times as heavily as MOVER, so it goes first now.
    """
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, rank_ib(), out) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))["candidates"]

    assert [row["symbol"] for row in rows] == ["HEAVY", "MIDDLE", "MOVER"]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert rows[0]["rel_volume"] > rows[1]["rel_volume"] > rows[2]["rel_volume"]
    assert rows[0]["gain_pct"] < rows[2]["gain_pct"], (
        "the name that moved most is last, which is the whole point of A4")


def test_the_score_written_into_the_file_is_the_relative_volume(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, rank_ib(), out) == 0
    for row in json.loads(out.read_text(encoding="utf-8"))["candidates"]:
        assert row["score"] == row["rel_volume"]


def test_the_shortlist_is_cut_to_the_top_few_by_relative_volume(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(
        monkeypatch, rank_ib(), out, extra=()) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["counts"]["final"] == 3

    # Now with room for one name only, the busiest one is the one kept.
    ib = rank_ib()
    scanner = make_scanner(ib, max_candidates=1)
    monkeypatch.setattr(
        scanner_module.OpeningMomentumScanner, "measure_session_progress",
        _fixed_session_progress)
    result = asyncio.run(scanner.run("SPY"))
    assert [c["symbol"] for c in result["candidates"]] == ["HEAVY"]
    assert result["candidates"][0]["rank"] == 1


def test_the_relative_volume_window_reaches_the_written_thresholds(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, rank_ib(), out) == 0
    thresholds = json.loads(out.read_text(encoding="utf-8"))["thresholds"]
    assert thresholds["rel_volume_window"] == "09:30-09:35"
    assert thresholds["rel_volume_baseline_days"] == 14
    assert thresholds["rel_volume_min"] == 2.0


# ---------------------------------------------------------------------------
# Direction comes from the 9:30 to 9:35 candle (change A5)
# ---------------------------------------------------------------------------


def test_a_candle_that_closed_above_its_open_is_a_long():
    assert direction_from_candle(10.0, 10.4) == DIRECTION_LONG


def test_a_candle_that_closed_below_its_open_is_a_short():
    assert direction_from_candle(10.0, 9.6) == DIRECTION_SHORT


def test_a_flat_candle_is_no_trade_at_all():
    """Not a shrug. The strategy says do not trade it, so None means dropped."""
    assert direction_from_candle(10.0, 10.0) is None


def test_a_candle_we_do_not_have_decides_nothing():
    assert direction_from_candle(None, 10.0) is None
    assert direction_from_candle(10.0, None) is None
    assert direction_from_candle("junk", 10.0) is None


CANDLE_ROWS = {
    "TOP_PERC_GAIN": [("RISE", 501), ("FADE", 502), ("FLAT", 503)],
    "TOP_PERC_LOSE": [],
    "HOT_BY_VOLUME": [],
    "HIGH_STVOLUME_5MIN": [],
}

# All three gapped up 10 percent overnight and all three came off the gainers
# list, so the old rule would have called all three long. What separates them is
# what the first five minutes actually did.
CANDLE_BARS = {symbol: daily_history(55.0) for symbol in ("RISE", "FADE", "FLAT")}
CANDLE_INTRADAY = {
    "RISE": opening_bars(55.0, "up"),
    "FADE": opening_bars(55.0, "down"),
    "FLAT": opening_bars(55.0, "flat"),
}


def candle_ib():
    return FakeIB(rows_by_code=CANDLE_ROWS, daily_bars=CANDLE_BARS,
                  intraday_bars=CANDLE_INTRADAY)


def test_the_opening_candle_overrules_the_scan_list_and_the_days_move(
    monkeypatch, tmp_path
):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, candle_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    by_symbol = {row["symbol"]: row for row in written["candidates"]}

    assert by_symbol["RISE"]["direction"] == DIRECTION_LONG
    assert by_symbol["FADE"]["direction"] == DIRECTION_SHORT, (
        "it gapped up and came off the gainers list, but the first five minutes "
        "faded, and the candle is what decides")
    assert by_symbol["FADE"]["side"] == DIRECTION_SHORT
    assert written["counts"]["final_long"] == 1
    assert written["counts"]["final_short"] == 1


def test_a_flat_opening_candle_drops_the_name_and_says_so(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, candle_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert "FLAT" not in {row["symbol"] for row in written["candidates"]}
    assert written["counts"]["passed_direction_agrees"] == 3
    assert written["counts"]["passed_direction_candle"] == 2
    assert written["counts"]["final"] == 2
    assert any("FLAT" in warning and "same price" in warning
               for warning in written["warnings"])


def test_the_written_row_carries_the_candle_it_was_judged_on(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, candle_ib(), out) == 0
    by_symbol = {row["symbol"]: row
                 for row in json.loads(out.read_text(encoding="utf-8"))["candidates"]}

    rise = by_symbol["RISE"]
    assert rise["opening_range_open"] < rise["opening_range_close"]
    fade = by_symbol["FADE"]
    assert fade["opening_range_open"] > fade["opening_range_close"]


def test_a_name_with_no_opening_candle_keeps_the_direction_it_already_had(
    monkeypatch, tmp_path
):
    """The scan list and the day's move stay as the fallback.

    Delayed data at 9:35 has no 9:30 bar yet, which is exactly this case, and a
    name should not be thrown away for it.
    """
    ib = FakeIB(rows_by_code=CANDLE_ROWS, daily_bars=CANDLE_BARS, intraday_bars={})
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, ib, out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert written["counts"]["passed_direction_candle"] == 3
    for row in written["candidates"]:
        assert row["direction"] == DIRECTION_LONG
        assert row["opening_range_open"] is None


# ---------------------------------------------------------------------------
# The hard exclusions (change A12)
# ---------------------------------------------------------------------------

ORDINARY = ("AAPL", "APPLE INC", "COMMON")


def test_an_ordinary_company_survives_all_four_exclusion_tests():
    """The one that matters most. None of these may fire on a real business."""
    for check in (spac_reason, warrant_reason, right_reason, preferred_reason):
        assert check(*ORDINARY) is None, check.__name__


def test_a_spac_is_recognised_by_its_name():
    assert spac_reason("PONO", "PONO CAPITAL ACQUISITION CORP", "COMMON")
    assert spac_reason("AACT", "ARES ACQUISITION HOLDINGS II", "COMMON")
    assert spac_reason("XYZ", "XYZ SPAC LTD", "COMMON")


def test_a_company_that_merely_says_space_is_not_a_spac():
    """SPAC is matched as a whole word, so SPACE and SPACEX are left alone."""
    assert spac_reason("SPCE", "VIRGIN GALACTIC SPACE HOLDINGS", "COMMON") is None
    assert spac_reason("RKLB", "ROCKET LAB SPACE SYSTEMS", "COMMON") is None


def test_a_warrant_is_recognised_three_different_ways():
    assert warrant_reason("ABCDW", "SOMETHING CORP", "COMMON"), "the NASDAQ fifth letter"
    assert warrant_reason("ABCD", "SOMETHING CORP WARRANT", "COMMON"), "the name"
    assert warrant_reason("ABCD", "SOMETHING CORP", "WAR"), "IBKR's own stock type"
    assert warrant_reason("BRK.WS", "SOMETHING CORP", "COMMON"), "the NYSE suffix"
    assert warrant_reason("ABC+", "SOMETHING CORP", "COMMON"), "the plus suffix"


def test_an_ordinary_ticker_ending_in_w_is_not_read_as_a_warrant():
    """A judgement call, and the same one the rights rule makes.

    A bare trailing W only means a warrant in the NASDAQ convention of a fifth
    letter on a four letter root. Reading it on any ticker would throw out these
    three real companies every single morning.
    """
    assert warrant_reason("LOW", "LOWES COMPANIES INC", "COMMON") is None
    assert warrant_reason("DOW", "DOW INC", "COMMON") is None
    assert warrant_reason("GLW", "CORNING INC", "COMMON") is None
    assert warrant_reason("SNOW", "SNOWFLAKE INC", "COMMON") is None


def test_a_rights_line_needs_the_name_to_say_so_as_well_as_the_ticker():
    assert right_reason("ABCR", "SOMETHING CORP RIGHTS", "COMMON")
    assert right_reason("ABC.RT", "SOMETHING CORP RIGHT", "COMMON")


def test_an_ordinary_ticker_ending_in_r_is_left_alone():
    """Dropping on the letter alone would throw out real businesses."""
    assert right_reason("PLTR", "PALANTIR TECHNOLOGIES INC", "COMMON") is None
    assert right_reason("BLDR", "BUILDERS FIRSTSOURCE INC", "COMMON") is None
    assert right_reason("CLX", "THE CLOROX COMPANY", "COMMON") is None


def test_a_preferred_share_is_recognised_by_name_ticker_or_type():
    assert preferred_reason("ABC", "SOMETHING CORP PREFERRED SERIES A", "COMMON")
    assert preferred_reason("ABC", "SOMETHING CORP PFD SER B", "COMMON")
    assert preferred_reason("BAC.PRK", "BANK OF AMERICA CORP", "COMMON")
    assert preferred_reason("BAC-PRB", "BANK OF AMERICA CORP", "COMMON")
    assert preferred_reason("ABC", "SOMETHING CORP", "PREFERRED")


def test_a_company_whose_ticker_merely_starts_with_pr_is_left_alone():
    """Plain PR inside a ticker would catch Prudential, so a separator is needed."""
    assert preferred_reason("PRU", "PRUDENTIAL FINANCIAL INC", "COMMON") is None
    assert preferred_reason("PG", "PROCTER AND GAMBLE CO", "COMMON") is None


def excluded(scanner, symbol, long_name, stock_type="COMMON"):
    candidate = Candidate(symbol=symbol, con_id=1, long_name=long_name,
                          stock_type=stock_type)
    return scanner.exclusion_verdict(candidate)


def test_the_verdict_gathers_all_four_tests_behind_one_answer():
    scanner = make_scanner(FakeIB())
    assert excluded(scanner, "AAPL", "APPLE INC") is None
    assert excluded(scanner, "PONO", "PONO CAPITAL ACQUISITION CORP")
    assert excluded(scanner, "ABCDW", "SOMETHING CORP")
    assert excluded(scanner, "ABCR", "SOMETHING CORP RIGHTS")
    assert excluded(scanner, "BAC.PRK", "BANK OF AMERICA CORP")


def test_each_exclusion_can_be_switched_off_on_its_own():
    scanner = make_scanner(FakeIB(), exclude_spacs=False)
    assert excluded(scanner, "PONO", "PONO CAPITAL ACQUISITION CORP") is None
    assert excluded(scanner, "ABCDW", "SOMETHING CORP"), "the others still fire"

    scanner = make_scanner(FakeIB(), exclude_warrants_and_rights=False)
    assert excluded(scanner, "ABCDW", "SOMETHING CORP") is None
    assert excluded(scanner, "ABCR", "SOMETHING CORP RIGHTS") is None

    scanner = make_scanner(FakeIB(), exclude_preferred=False)
    assert excluded(scanner, "BAC.PRK", "BANK OF AMERICA CORP") is None


def test_a_halted_name_is_dropped_when_ibkr_actually_says_so():
    scanner = make_scanner(FakeIB())
    scanner.halt_flags["HALT"] = True
    assert excluded(scanner, "HALT", "SOMETHING CORP") == "IBKR reported it as halted"

    scanner.halt_flags["HALT"] = False
    assert excluded(scanner, "HALT", "SOMETHING CORP") is None


def test_contract_details_are_read_for_a_halt_flag_without_inventing_one():
    class NoFlag:
        contract = None

    class WithFlag:
        contract = None

        def __init__(self, value):
            self.halted = value

    assert halt_flag_from_details(NoFlag()) is None, "no field means not known"
    assert halt_flag_from_details(WithFlag(0)) is False
    assert halt_flag_from_details(WithFlag(1)) is True
    assert halt_flag_from_details(WithFlag(2)) is True
    assert halt_flag_from_details(WithFlag(True)) is True


def test_the_run_says_plainly_that_it_could_not_check_for_a_halt(monkeypatch, tmp_path):
    """IBKR's contract details carry no halt flag on this account.

    So the run must say so rather than implying it looked and found nothing, and
    it must point at the check that really runs, on the order path.
    """
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    warnings = json.loads(out.read_text(encoding="utf-8"))["warnings"]

    halt_note = next(w for w in warnings if "halt check could not be made" in w)
    assert "guardrails.py" in halt_note
    assert "tick type 49" in halt_note


def test_a_name_on_a_foreign_venue_is_dropped_as_not_a_us_listing():
    """The US listing test is what keeps OTC and non-US lines out."""
    ib = FakeIB()
    scanner = make_scanner(ib)
    assert scanner.thresholds.require_us_primary_listing is True
    assert "NYSE" in scanner_module.ALLOWED_PRIMARY_EXCHANGES
    assert "PINK" not in scanner_module.ALLOWED_PRIMARY_EXCHANGES
    assert "OTC" not in scanner_module.ALLOWED_PRIMARY_EXCHANGES
    assert "LSE" not in scanner_module.ALLOWED_PRIMARY_EXCHANGES


def test_there_is_no_listing_age_rule_anywhere_in_the_scanner():
    """Mo rejected it. History requirements replaced it, and this pins that.

    A name is judged on whether it has enough sessions to be measured, which is
    min_history_sessions and the ATR window, not on how recently it listed.
    """
    source = (PROJECT_ROOT / "agent" / "scanner.py").read_text(encoding="utf-8")
    for phrase in ("days_since_listing", "listing_age", "min_listing_days"):
        assert phrase not in source, phrase
    assert Thresholds().min_history_sessions == 30


# ---------------------------------------------------------------------------
# The Finviz cross-check is gone and must stay gone (decision D7)
# ---------------------------------------------------------------------------


def test_nothing_in_the_scanner_reaches_for_finviz_any_more():
    """Mo decided not to buy Finviz Elite, so the whole path came out.

    The word is allowed to survive in exactly one place: the note near the top
    of the file explaining that the path was deleted on purpose, so nobody adds
    it back thinking its absence was an oversight. Anywhere else, in any line of
    real code, means the path has crept back in.
    """
    path = PROJECT_ROOT / "agent" / "scanner.py"
    mentions = [
        (number, line)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "finviz" in line.lower()
    ]
    for number, line in mentions:
        assert line.lstrip().startswith("#"), (
            f"line {number} of {path} is code that mentions Finviz: {line.strip()}")
        assert number < 100, (
            f"line {number} of {path} mentions Finviz outside the removal note")
    assert mentions, "the note explaining why it was removed should still be there"


def test_the_scanner_no_longer_has_any_finviz_machinery():
    for name in ("FinvizSettings", "parse_finviz_csv", "read_env_file",
                 "FINVIZ_FLAG", "SECRETS_DIR"):
        assert not hasattr(scanner_module, name), name
    for name in ("add_finviz_symbols", "fetch_finviz_symbols"):
        assert not hasattr(OpeningMomentumScanner, name), name
    assert "finviz_enabled" not in Thresholds().as_dict()


def test_no_finviz_block_is_written_into_the_shortlist(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert "finviz" not in written
    for row in written["candidates"]:
        assert "finviz" not in row["flagged_by"]
    assert "finviz" not in scanner_module.SCAN_CODE_LABELS


# ---------------------------------------------------------------------------
# The industry each name is in, which the sector cap reads (change A9)
# ---------------------------------------------------------------------------
#
# The sector cap lives in
# /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py
# and it refuses an entry outright when nobody can say what industry a name is
# in. This scanner is the only place in the project that already asks IBKR for
# contract details, so this is where that fact comes from.


class SectorIB(FakeIB):
    """A Gateway that answers contract details with the industry fields a test
    wants, and behaves exactly like FakeIB in every other way."""

    def __init__(self, rows_by_code=None, daily_bars=None, intraday_bars=None,
                 **detail_kwargs):
        super().__init__(rows_by_code=rows_by_code, daily_bars=daily_bars,
                         intraday_bars=intraday_bars)
        self.detail_kwargs = detail_kwargs

    async def reqContractDetailsAsync(self, contract):
        return [FakeContractDetails(
            FakeContract(contract.symbol, contract.conId or 1), **self.detail_kwargs)]


def looked_up_with(**detail_kwargs) -> Candidate:
    """One contract details lookup, with no scan and no bars around it."""
    scanner = make_scanner(SectorIB(**detail_kwargs))
    candidate = Candidate(symbol="X", con_id=1)
    asyncio.run(scanner.load_contract_details(candidate))
    return candidate


def test_the_industry_comes_from_ibkrs_industry_field_first():
    candidate = looked_up_with(industry="Technology", category="Computers",
                               subcategory="Computer Software")
    assert candidate.sector == "Technology"
    assert candidate.category == "Computers"
    assert candidate.subcategory == "Computer Software"


def test_the_industry_falls_back_to_the_category():
    """IBKR does not always fill all three in."""
    candidate = looked_up_with(industry="", category="Computers",
                               subcategory="Computer Software")
    assert candidate.sector == "Computers"


def test_the_industry_falls_back_to_the_subcategory_last():
    candidate = looked_up_with(industry="", category="",
                               subcategory="Computer Software")
    assert candidate.sector == "Computer Software"


def test_an_industry_nobody_named_comes_out_as_an_empty_string_not_none():
    """The sector cap has to have one kind of thing to read."""
    candidate = looked_up_with(industry="", category="", subcategory="")
    assert candidate.sector == ""
    assert candidate.sector is not None
    assert candidate.as_dict()["sector"] == ""
    assert candidate.as_dict()["category"] == ""
    assert candidate.as_dict()["subcategory"] == ""


def test_whitespace_around_an_industry_is_trimmed_off():
    assert looked_up_with(industry="  Technology  ").sector == "Technology"


def test_every_written_row_carries_its_industry(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))["candidates"]

    assert rows, "nothing was shortlisted, so this test proved nothing"
    for row in rows:
        assert "sector" in row
        assert "category" in row
        assert "subcategory" in row
        assert row["sector"] == "Technology"
    assert any("Technology industry" in reason for reason in rows[0]["reasons"])


def test_a_shortlisted_name_with_no_industry_is_named_in_the_warnings(
    monkeypatch, tmp_path
):
    """Those names cannot be entered, so somebody should see why."""
    ib = SectorIB(rows_by_code=UNION_ROWS, daily_bars=UNION_BARS,
                  intraday_bars=UNION_INTRADAY,
                  industry="", category="", subcategory="")
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, ib, out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    note = next(w for w in written["warnings"] if "No industry from IBKR" in w)
    assert "guardrails.py" in note
    assert "UPUP" in note
    for row in written["candidates"]:
        assert row["sector"] == ""
