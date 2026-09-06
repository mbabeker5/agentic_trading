"""Tests for the scanner's number filters, run on made up bars.

The scanner itself talks to IB Gateway, but the arithmetic it does with the bars
Gateway hands back does not, and that arithmetic is where Mo's two decisions of
2026-09-06 live: the liquidity floor of 20 million dollars of average daily
trading over 30 sessions, and the relative volume floor of 2 times normal
measured at 09:35.

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
    DEFAULT_DOLLAR_VOLUME_SESSIONS,
    DEFAULT_MIN_AVG_DOLLAR_VOLUME,
    MIN_DAILY_BARS_FOR_AVERAGE,
    REL_VOLUME_ANCHOR_LABEL,
    REL_VOLUME_ANCHOR_MINUTES,
    SESSION_MINUTES,
    Thresholds,
    average_dollar_volume,
    bar_dollar_volume,
    expected_volume_by,
    human_dollars,
    load_thresholds,
    relative_volume,
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
