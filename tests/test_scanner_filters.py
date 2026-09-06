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
    FINVIZ_FLAG,
    FORBIDDEN_SCAN_CODES,
    HISTORY_REQUEST_BUDGET,
    SCAN_CODES,
    SCAN_SPECS,
    SCANNER_REQUESTS_PER_RUN,
    TOTAL_REQUEST_RATION,
    Candidate,
    FinvizSettings,
    OpeningMomentumScanner,
    parse_finviz_csv,
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
    def __init__(self, contract, long_name="Example Corp", stock_type="COMMON"):
        self.contract = contract
        self.longName = long_name
        self.stockType = stock_type


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
                  normal_close: float = 50.0, normal_volume: float = 500_000.0):
    """Thirty quiet sessions and then today.

    Thirty at 50 dollars on 500,000 shares is 25 million dollars a day, which
    clears the 20 million floor. 20,000 shares by 09:35 against a 500,000 share
    daily average is about 3.1 times the normal pace, which clears the 2 times
    floor. So every name built this way passes on liquidity and volume, and the
    only thing left for the test to be about is direction.
    """
    start = today_eastern() - timedelta(days=60)
    bars = [FakeBar(date=start + timedelta(days=n), close=normal_close,
                    volume=normal_volume) for n in range(30)]
    bars.append(FakeBar(date=today_eastern(), close=today_close,
                        volume=today_volume, high=today_close,
                        low=today_close * 0.98))
    return bars


def opening_bars(price: float):
    open_time = datetime.now(EASTERN).replace(hour=9, minute=30, second=0, microsecond=0)
    return [FakeBar(date=open_time, close=price, volume=5_000.0,
                    high=price * 1.01, low=price * 0.99)]


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

UNION_INTRADAY = {symbol: opening_bars(bars[-1].close)
                  for symbol, bars in UNION_BARS.items()}


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
# The Finviz cross-check, which is off
# ---------------------------------------------------------------------------


def test_finviz_is_off_in_the_shipped_settings_file():
    thresholds = load_thresholds(SHIPPED_CONFIG)
    assert thresholds.finviz.enabled is False
    assert thresholds.finviz.auth_token_key == "FINVIZ_AUTH_TOKEN"
    assert thresholds.finviz.secrets_file == "finviz.env"
    assert thresholds.as_dict()["finviz_enabled"] is False


def test_with_finviz_off_nothing_touches_the_network(monkeypatch):
    """Off means off: one line in the log and no request at all."""
    def explode(*args, **kwargs):
        raise AssertionError("the scanner reached for the network with Finviz off")

    monkeypatch.setattr(scanner_module.urllib.request, "urlopen", explode)

    ib = FakeIB()
    scanner = make_scanner(ib)
    assert scanner.thresholds.finviz.enabled is False
    asyncio.run(scanner.collect_candidates())

    assert scanner.finviz_report["symbols_added"] == 0
    assert scanner.finviz_report["symbols"] == []
    assert "off" in scanner.finviz_report["note"]
    assert not any(code == FINVIZ_FLAG for code, _ in ib.requested)


def test_with_finviz_off_no_candidate_is_flagged_by_it(monkeypatch, tmp_path):
    out = tmp_path / "shortlist.json"
    assert run_scanner_cli(monkeypatch, union_ib(), out) == 0
    written = json.loads(out.read_text(encoding="utf-8"))

    assert written["finviz"]["enabled"] is False
    assert written["finviz"]["symbols_added"] == 0
    for row in written["candidates"]:
        assert FINVIZ_FLAG not in row["flagged_by"]


def test_finviz_symbols_join_the_union_when_it_is_switched_on(monkeypatch):
    scanner = make_scanner(union_ib())
    scanner.thresholds.finviz = FinvizSettings(
        enabled=True, export_url="https://elite.finviz.com/export.ashx?v=111&auth=x")
    monkeypatch.setattr(
        scanner, "fetch_finviz_symbols",
        lambda settings: (["UPUP", "NEWNAME"], "read 2 tickers from Finviz"))

    candidates = asyncio.run(scanner.collect_candidates())
    by_symbol = {c.symbol: c for c in candidates}

    assert FINVIZ_FLAG in by_symbol["UPUP"].flagged_by, "an existing name is tagged, not duplicated"
    assert by_symbol["UPUP"].flagged_by == ["TOP_PERC_GAIN", FINVIZ_FLAG]
    assert by_symbol["NEWNAME"].flagged_by == [FINVIZ_FLAG]
    assert by_symbol["NEWNAME"].con_id == 0, "Finviz gives a ticker, not a contract id"
    assert scanner.finviz_report["symbols_added"] == 1
    assert len([c for c in candidates if c.symbol == "UPUP"]) == 1


def test_finviz_says_so_plainly_when_it_is_on_but_not_configured():
    scanner = make_scanner(FakeIB())
    settings = FinvizSettings(enabled=True, export_url="")
    symbols, note = scanner.fetch_finviz_symbols(settings)
    assert symbols == []
    assert "no export_url" in note


def test_a_finviz_export_is_read_for_its_ticker_column():
    body = ("No.,Ticker,Company,Sector,Price,Change,Volume\r\n"
            "1,NVDA,NVIDIA Corp,Technology,120.50,4.20%,180000000\r\n"
            "2,AMD,Advanced Micro Devices,Technology,160.10,3.10%,90000000\r\n"
            "3,NVDA,NVIDIA Corp,Technology,120.50,4.20%,180000000\r\n")
    assert parse_finviz_csv(body) == ["NVDA", "AMD"]


def test_a_finviz_export_with_no_ticker_column_gives_nothing():
    assert parse_finviz_csv("No.,Company,Price\r\n1,NVIDIA Corp,120.50\r\n") == []
    assert parse_finviz_csv("") == []


def test_rubbish_in_the_ticker_column_is_dropped_rather_than_guessed_at():
    body = "Ticker\r\nNVDA\r\n,\r\n   \r\nnot a ticker\r\nBRK.B\r\n"
    assert parse_finviz_csv(body) == ["NVDA", "BRK.B"]
