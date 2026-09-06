"""Tests for the pre-open run, agent/preopen.py.

Nothing here touches the network, IB Gateway, the MCP server or a real account.
The broker is a twenty line fake built from handmade bars, and its three order
methods raise, so a test that ever tried to trade would fail loudly rather than
pass quietly. Every file goes to a throwaway folder through
AGENTIC_TRADING_ROOT, so the real output/ folder is never written to.

There are four kinds of test in here:

1. The arithmetic, on paper. Relative volume, average true range, the direction
   rule, the volatility filter and the ranking. No clock, no broker, no disk.
2. The plumbing. The pacer that keeps requests to four a minute across
   processes, the disk cache, and the timings file with its budget flags.
3. The morning, end to end. One tick at 9:05, one at 9:28, one at 9:35 and one
   at 9:50, driven by the same fake broker, checking that each one does its own
   job and nothing else.
4. One test that reads agent/preopen.py's own text and proves it cannot send,
   change or pull an order, because that file is only ever allowed to read.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_preopen.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import alerts  # noqa: E402
import preopen  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: Tuesday 2026-09-08, the day the real timings are going to be measured on.
TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int, second: int = 0, day: date = TUESDAY) -> datetime:
    """A moment on the test's Tuesday, New York time."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=EASTERN)


# ---------------------------------------------------------------------------
# The fake broker: six read methods, and three that must never be called
# ---------------------------------------------------------------------------


class RecordedBroker:
    """Everything agent/broker.py's Broker protocol asks for, out of handmade data.

    historical_bars answers three different questions depending on what it is
    asked for, the same way the real one does: "1 D" of five minute bars is
    today, "20 D" of five minute bars is the baseline, and "1 day" bars are the
    daily history. That split is what lets the test show the 9:35 fallback
    fetching today's opening bar because no live subscription was held.

    The three order methods raise. That is the point of them being here at all.
    """

    def __init__(self, quotes=None, baseline=None, daily=None, today=None):
        self.quotes = quotes or {}
        self.baseline = baseline or {}
        self.daily = daily or {}
        self.today = today or {}
        self.calls: list[str] = []
        self.history_calls: list[tuple] = []

    # -- reading ----------------------------------------------------------

    def account_summary(self, account=None) -> dict:
        self.calls.append("account_summary")
        return {"account": account or "DUT077572", "items": []}

    def portfolio(self, account=None, include_pnl=True) -> dict:
        self.calls.append("portfolio")
        return {"account": account or "DUT077572", "positions": [], "notes": []}

    def open_orders(self, account=None, include_all=True) -> dict:
        self.calls.append("open_orders")
        return {"orders": [], "notes": []}

    def executions(self, account=None, symbol=None, sec_type=None, exchange=None,
                   side=None, time=None) -> dict:
        self.calls.append("executions")
        return {"executions": [], "fills": [], "notes": []}

    def snapshot(self, contracts, market_data_type=3) -> dict:
        self.calls.append("snapshot")
        rows = []
        for contract in contracts:
            symbol = str(contract.get("symbol"))
            quote = self.quotes.get(symbol)
            if quote is None:
                continue
            rows.append({"symbol": symbol, **quote})
        return {"snapshots": rows, "notes": []}

    def historical_bars(self, contract, duration, bar_size, what="TRADES",
                        use_rth=True, end_date_time="") -> dict:
        symbol = str(contract.get("symbol"))
        self.history_calls.append((symbol, duration, bar_size))
        if duration == "1 D":
            return {"bars": list(self.today.get(symbol, [])), "notes": []}
        if bar_size == preopen.DAILY_SIZE:
            return {"bars": list(self.daily.get(symbol, [])), "notes": []}
        return {"bars": list(self.baseline.get(symbol, [])), "notes": []}

    # -- acting, all three of which must never happen here -----------------

    def place_order(self, contract, order, order_ref) -> dict:
        raise AssertionError("the pre-open tried to place an order")

    def bracket_order(self, contract, entry, stop, target, order_ref) -> dict:
        raise AssertionError("the pre-open tried to place a bracket")

    def cancel_order(self, order_id) -> dict:
        raise AssertionError("the pre-open tried to cancel an order")

    def global_cancel(self) -> dict:
        raise AssertionError("the pre-open tried to cancel every order")


# ---------------------------------------------------------------------------
# Handmade bars
# ---------------------------------------------------------------------------


def sessions_before(day: date, count: int) -> list[date]:
    """The weekdays before a day, oldest first. Good enough without a calendar."""
    out: list[date] = []
    cursor = day
    while len(out) < count:
        cursor -= timedelta(days=1)
        if cursor.weekday() < 5:
            out.append(cursor)
    return sorted(out)


def five_minute_bar(day: date, hour: int, minute: int, open_price: float,
                    close_price: float, volume: float) -> dict:
    """One five minute bar, stamped at its own start, the way IBKR sends them."""
    return {
        "time": f"{day.isoformat()} {hour:02d}:{minute:02d}:00",
        "open": open_price,
        "high": max(open_price, close_price) + 0.1,
        "low": min(open_price, close_price) - 0.1,
        "close": close_price,
        "volume": volume,
    }


def baseline_bars(window_volume: float, day: date = TUESDAY, days: int = 14,
                  price: float = 100.0) -> list[dict]:
    """Fourteen sessions of five minute bars, two bars a session.

    The 9:35 bar always carries twice the volume of the 9:30 one. If the window
    filter ever slipped and counted it, every ratio in these tests would halve,
    so it is a cheap trap for a real mistake.
    """
    bars: list[dict] = []
    for session in sessions_before(day, days):
        bars.append(five_minute_bar(session, 9, 30, price, price + 0.2, window_volume))
        bars.append(five_minute_bar(session, 9, 35, price + 0.2, price,
                                    window_volume * 2))
    return bars


def today_bars(window_volume: float, open_price: float = 100.0,
               close_price: float = 101.0, day: date = TUESDAY) -> list[dict]:
    """Today's opening five minutes, plus the five minutes after it."""
    return [
        five_minute_bar(day, 9, 30, open_price, close_price, window_volume),
        five_minute_bar(day, 9, 35, close_price, close_price + 0.5, window_volume * 3),
    ]


def daily_bars(day: date = TUESDAY, sessions: int = 40, close: float = 100.0,
               swing: float = 2.0, volume: float = 1_000_000.0) -> list[dict]:
    """Forty daily bars with a two dollar range, so the average true range is 2.00.

    Two dollars on a hundred dollar share is two percent, which clears the 1.5
    percent test, and a hundred million dollars a day clears the liquidity
    floor. These names are meant to pass everything except the tests each one is
    written to fail.
    """
    rows: list[dict] = []
    for session in sessions_before(day, sessions):
        rows.append({
            "time": session.isoformat(),
            "open": close - 0.5,
            "high": close + swing / 2,
            "low": close - swing / 2,
            "close": close,
            "volume": volume,
        })
    return rows


#: Four names, built so that each one proves a different rule.
#:
#:   HOT   six times its normal opening volume and rising. The right answer.
#:   FLAT  eight times its normal volume, so it would rank first, but its
#:         opening candle closes exactly where it opened. The direction rule
#:         has to throw it out, which is the only reason HOT wins.
#:   WARM  three times normal and rising. Second.
#:   COLD  exactly normal, so it fails the 2x floor.
SHORTLIST_NAMES = ("HOT", "FLAT", "WARM", "COLD")


def four_name_broker() -> RecordedBroker:
    quotes = {
        "HOT": {"last": 106.0, "close": 100.0},
        "FLAT": {"last": 105.0, "close": 100.0},
        "WARM": {"last": 104.0, "close": 100.0},
        "COLD": {"last": 103.0, "close": 100.0},
    }
    baseline = {name: baseline_bars(5_000.0) for name in SHORTLIST_NAMES}
    daily = {name: daily_bars() for name in SHORTLIST_NAMES}
    today = {
        "HOT": today_bars(30_000.0, 100.0, 101.0),
        "FLAT": today_bars(40_000.0, 100.0, 100.0),
        "WARM": today_bars(15_000.0, 100.0, 100.8),
        "COLD": today_bars(5_000.0, 100.0, 100.4),
    }
    return RecordedBroker(quotes=quotes, baseline=baseline, daily=daily, today=today)


# ---------------------------------------------------------------------------
# The setup
# ---------------------------------------------------------------------------


@pytest.fixture
def sent(monkeypatch):
    """Every alert this run would have sent, caught instead of delivered."""
    caught: list[tuple] = []
    monkeypatch.setattr(alerts, "alert",
                        lambda level, title, body: caught.append((level, title, body))
                        or ["log"])
    return caught


@pytest.fixture
def home(monkeypatch, tmp_path, sent):
    """A throwaway project folder, so nothing is written into the real output/."""
    monkeypatch.setenv("AGENTIC_TRADING_ROOT", str(tmp_path))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def settings():
    """The built-in defaults, so a test never depends on config/guardrails.yaml."""
    return preopen.Settings()


def run_tick(now, broker, settings, **kwargs):
    return preopen.step(now, broker=broker, universe=list(SHORTLIST_NAMES),
                        settings=settings, **kwargs)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. The arithmetic
# ---------------------------------------------------------------------------


def test_relative_volume_is_today_over_the_average_of_the_same_window():
    ratio, days = preopen.relative_volume_open_window(30_000, [5_000] * 14)
    assert ratio == pytest.approx(6.0)
    assert days == 14


def test_relative_volume_drops_days_with_no_volume_at_all():
    # A session that traded nothing in those five minutes is missing data, not a
    # quiet morning. Averaging the zero in would make today look twice as busy.
    ratio, days = preopen.relative_volume_open_window(10_000, [5_000, 5_000, 0, None])
    assert ratio == pytest.approx(2.0)
    assert days == 2


def test_relative_volume_with_nothing_to_divide_by_is_none():
    assert preopen.relative_volume_open_window(10_000, []) == (None, 0)
    assert preopen.relative_volume_open_window(None, [5_000])[0] is None


def test_average_true_range_uses_the_previous_close_not_just_high_minus_low():
    # Every session has a fifty cent high to low range, but the last one gaps up
    # ten dollars overnight. A range that ignored the previous close would call
    # this a fifty cent name. It moved ten dollars.
    bars = [{"high": 100.5, "low": 100.0, "close": 100.0},
            {"high": 110.5, "low": 110.0, "close": 110.0}]
    atr, sessions = preopen.average_true_range(bars, days=14)
    assert sessions == 1
    assert atr == pytest.approx(10.5)


def test_average_true_range_averages_the_last_however_many_sessions():
    bars = [{"high": 101.0, "low": 99.0, "close": 100.0} for _ in range(20)]
    atr, sessions = preopen.average_true_range(bars, days=14)
    assert sessions == 14
    assert atr == pytest.approx(2.0)


def test_average_true_range_needs_two_bars_to_say_anything():
    assert preopen.average_true_range([], days=14) == (None, 0)
    assert preopen.average_true_range([{"high": 1, "low": 0, "close": 1}]) == (None, 0)


def test_direction_follows_the_opening_candle():
    assert preopen.direction_from_candle(100.0, 101.0) == "long"
    assert preopen.direction_from_candle(101.0, 100.0) == "short"


def test_a_flat_candle_means_no_trade():
    # The paper's own rule. If the first five minutes said nothing, we do not
    # guess, and None is what stops the name being traded at all.
    assert preopen.direction_from_candle(100.0, 100.0) is None
    assert preopen.direction_from_candle(None, 100.0) is None
    assert preopen.direction_from_candle(100.0, None) is None


def test_volatility_filter_needs_both_the_dollars_and_the_percent():
    assert preopen.passes_volatility(2.0, 100.0) is True
    # Fifty cents on a hundred dollar share is half a percent, so the percent
    # test throws it out even though the dollar test passes.
    assert preopen.passes_volatility(0.50, 100.0) is False
    # Forty cents on a ten dollar share is four percent, but it is under the
    # fifty cent floor, so the dollar test throws it out.
    assert preopen.passes_volatility(0.40, 10.0) is False
    assert preopen.passes_volatility(0.60, 10.0) is True


def test_volatility_filter_fails_on_missing_numbers():
    assert preopen.passes_volatility(None, 100.0) is False
    assert preopen.passes_volatility(2.0, None) is False
    assert preopen.passes_volatility(2.0, 0.0) is False


def test_rank_candidates_sorts_busiest_first_and_numbers_them():
    rows = [{"symbol": "B", "relative_volume": 3.0},
            {"symbol": "A", "relative_volume": 6.0},
            {"symbol": "C", "relative_volume": None}]
    ranked = preopen.rank_candidates(rows)
    assert [row["symbol"] for row in ranked] == ["A", "B", "C"]
    assert [row["rank"] for row in ranked] == [1, 2, 3]
    # The rows handed in are left alone, so a caller can rank twice.
    assert "rank" not in rows[0]


def test_gap_percent_is_measured_against_yesterdays_close():
    assert preopen.gap_percent(106.0, 100.0) == pytest.approx(6.0)
    assert preopen.gap_percent(94.0, 100.0) == pytest.approx(-6.0)
    assert preopen.gap_percent(106.0, 0.0) is None
    assert preopen.gap_percent(None, 100.0) is None


def test_window_bar_takes_only_the_bars_inside_the_window():
    bars = today_bars(30_000.0)
    candle = preopen.window_bar(bars, TUESDAY, preopen.parse_clock("09:30"),
                                preopen.parse_clock("09:35"))
    assert candle is not None
    # The 9:35 bar carries three times the volume and must not be in here.
    assert candle["volume"] == pytest.approx(30_000.0)
    assert candle["open"] == pytest.approx(100.0)
    assert candle["close"] == pytest.approx(101.0)


def test_baseline_window_volumes_leaves_today_out():
    bars = baseline_bars(5_000.0) + today_bars(30_000.0)
    volumes = preopen.baseline_window_volumes(bars, TUESDAY,
                                              preopen.parse_clock("09:30"),
                                              preopen.parse_clock("09:35"), days=14)
    assert len(volumes) == 14
    assert all(volume == pytest.approx(5_000.0) for volume in volumes)


def test_phase_for_reads_the_clock(settings):
    assert preopen.phase_for(at(8, 55), settings) == preopen.PHASE_TOO_EARLY
    assert preopen.phase_for(at(9, 5), settings) == preopen.PHASE_GATHER
    assert preopen.phase_for(at(9, 28), settings) == preopen.PHASE_SUBSCRIBE
    assert preopen.phase_for(at(9, 31), settings) == preopen.PHASE_WATCH
    assert preopen.phase_for(at(9, 35), settings) == preopen.PHASE_RANK
    assert preopen.phase_for(at(9, 50), settings) == preopen.PHASE_DONE


# ---------------------------------------------------------------------------
# 2. The plumbing
# ---------------------------------------------------------------------------


def test_the_pacer_lets_four_requests_through_in_a_minute():
    pacer = preopen.Pacer()
    granted = [pacer.take(at(9, 5)) for _ in range(10)]
    assert granted.count(True) == preopen.HISTORY_REQUESTS_PER_MINUTE == 4
    assert granted.count(False) == 6
    assert pacer.remaining(at(9, 5)) == 0


def test_the_pacer_forgets_a_request_once_a_minute_has_passed():
    pacer = preopen.Pacer()
    for _ in range(4):
        assert pacer.take(at(9, 5)) is True
    assert pacer.take(at(9, 5, 59)) is False
    assert pacer.remaining(at(9, 6, 1)) == 4
    assert pacer.take(at(9, 6, 1)) is True


def test_the_pacer_remembers_across_ticks_through_the_state_file():
    first = preopen.Pacer()
    for _ in range(4):
        first.take(at(9, 5))
    stamps = first.as_stamps(at(9, 5))
    assert len(stamps) == 4
    # A second process, a second later, must see the four the first one sent.
    second = preopen.Pacer.from_stamps(stamps)
    assert second.remaining(at(9, 5, 1)) == 0
    assert second.take(at(9, 5, 1)) is False


def test_the_pacer_drops_stamps_it_cannot_read():
    pacer = preopen.Pacer.from_stamps(["not a time", None, at(9, 5).isoformat()])
    assert pacer.used_in_last_minute(at(9, 5, 30)) == 1


def test_the_cache_round_trips(home):
    bars = today_bars(30_000.0)
    assert preopen.write_cache("AAPL", TUESDAY, preopen.CACHE_BARS5M, bars) is True
    path = preopen.cache_path("AAPL", TUESDAY, preopen.CACHE_BARS5M)
    assert path.name == "AAPL_2026-09-08_bars5m.json"
    assert path.parent == home / "output" / "preopen_cache"
    loaded = preopen.read_cache("AAPL", TUESDAY, preopen.CACHE_BARS5M)
    assert loaded["symbol"] == "AAPL"
    assert loaded["day"] == "2026-09-08"
    assert preopen.cached_bars("AAPL", TUESDAY, preopen.CACHE_BARS5M) == bars


def test_an_unreadable_cache_file_is_a_miss_and_never_raises(home):
    path = preopen.cache_path("AAPL", TUESDAY, preopen.CACHE_DAILY)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exactly what a tick killed halfway through a write would leave behind.
    path.write_text('{"symbol": "AAPL", "bars": [{"clo', encoding="utf-8")
    assert preopen.read_cache("AAPL", TUESDAY, preopen.CACHE_DAILY) is None
    assert preopen.cached_bars("AAPL", TUESDAY, preopen.CACHE_DAILY) == []


def test_a_missing_cache_file_is_a_miss(home):
    assert preopen.read_cache("NOPE", TUESDAY, preopen.CACHE_DAILY) is None


def test_the_timings_file_records_a_step_inside_its_budget(home):
    timings = preopen.Timings(TUESDAY)
    row = timings.record("scan", at(9, 5), at(9, 5, 3))
    assert row["duration_seconds"] == pytest.approx(3.0)
    assert row["budget_seconds"] == 5.0
    assert row["over_budget"] is False

    saved = read_json(preopen.timings_path(TUESDAY))
    assert saved["day"] == "2026-09-08"
    assert saved["steps"][0]["name"] == "scan"
    assert saved["steps"][0]["over_budget"] is False


def test_a_crossed_duration_budget_is_flagged_and_alerted(home, sent):
    timings = preopen.Timings(TUESDAY)
    row = timings.record("scan", at(9, 5), at(9, 5, 9))
    assert row["over_budget"] is True
    assert row["duration_seconds"] == pytest.approx(9.0)

    saved = read_json(preopen.timings_path(TUESDAY))
    assert saved["steps"][0]["over_budget"] is True
    assert saved["alerts"][0]["step"] == "scan"

    assert len(sent) == 1
    level, title, body = sent[0]
    assert level == "warn"
    assert "scan" in title
    assert "5.0 seconds" in body


def test_a_crossed_wall_clock_deadline_is_flagged_and_alerted(home, sent):
    # The history pulls were supposed to be finished by 9:26 and were not.
    timings = preopen.Timings(TUESDAY)
    row = timings.record("history", at(9, 0), at(9, 40),
                         budget_name="history_done_by",
                         detail="3 name(s) never got their history")
    assert row["over_budget"] is True
    assert row["budget_deadline"] == "09:26"
    assert row["budget_seconds"] is None
    assert sent and "history" in sent[0][1]
    assert "3 name(s)" in sent[0][2]


def test_a_deadline_met_is_not_flagged(home, sent):
    timings = preopen.Timings(TUESDAY)
    row = timings.record("history", at(9, 0), at(9, 24),
                         budget_name="history_done_by")
    assert row["over_budget"] is False
    assert sent == []


def test_deadline_moment_only_answers_for_the_wall_clock_budgets(home):
    timings = preopen.Timings(TUESDAY)
    assert timings.deadline_moment("history_done_by") == at(9, 26)
    assert timings.deadline_moment("subscribe_done_by") == at(9, 29)
    assert timings.deadline_moment("orders_by") == at(9, 36, 30)
    # A duration budget has no deadline, and neither has a step nobody named.
    assert timings.deadline_moment("rank") is None
    assert timings.deadline_moment("nothing at all") is None


def test_the_budgets_hold_three_durations_and_three_deadlines():
    durations = [key for key, value in preopen.BUDGETS.items()
                 if isinstance(value, (int, float))]
    deadlines = [key for key, value in preopen.BUDGETS.items()
                 if isinstance(value, str)]
    assert sorted(durations) == ["model", "rank", "scan"]
    assert sorted(deadlines) == ["history_done_by", "orders_by", "subscribe_done_by"]
    assert preopen.BUDGETS["scan"] == 5.0
    assert preopen.BUDGETS["rank"] == 2.0
    assert preopen.BUDGETS["model"] == 45.0
    assert preopen.BUDGETS["orders_by"] == "09:36:30"


def test_settings_come_from_guardrails_yaml_when_it_is_there(tmp_path):
    path = tmp_path / "guardrails.yaml"
    path.write_text(
        "universe:\n"
        "  price_floor: 7\n"
        "  min_atr_usd: 0.75\n"
        "scanner:\n"
        "  rel_volume_min: 2.5\n"
        "  rel_volume_baseline_days: 10\n"
        "schedule:\n"
        '  preopen_history_done_by: "09:24"\n',
        encoding="utf-8")
    settings = preopen.load_settings(path)
    assert settings.price_floor == 7.0
    assert settings.min_atr_usd == 0.75
    assert settings.rel_volume_min == 2.5
    assert settings.rel_volume_baseline_days == 10
    assert settings.preopen_history_done_by == "09:24"
    # Everything the file did not mention keeps its default.
    assert settings.atr_days == preopen.DEFAULT_ATR_DAYS
    assert settings.max_candidates == preopen.DEFAULT_MAX_CANDIDATES


def test_a_missing_settings_file_falls_back_to_the_defaults(tmp_path):
    settings = preopen.load_settings(tmp_path / "not_here.yaml")
    assert settings.price_floor == preopen.DEFAULT_PRICE_FLOOR
    assert settings.rel_volume_window == "09:30-09:35"
    assert settings.source == "built-in defaults"


# ---------------------------------------------------------------------------
# 3. The morning, one tick at a time
# ---------------------------------------------------------------------------


def test_at_0905_it_gap_scans_and_starts_pulling_history(home, settings):
    broker = four_name_broker()
    answer = run_tick(at(9, 5), broker, settings)

    assert answer["phase"] == preopen.PHASE_GATHER
    assert answer["candidates"] == 4

    # Four names need eight requests. One tick may send four, and no more.
    assert len(broker.history_calls) == preopen.HISTORY_REQUESTS_PER_MINUTE
    assert broker.calls.count("snapshot") == 1

    # Biggest gap first, so HOT and FLAT got theirs and the other two wait.
    assert {call[0] for call in broker.history_calls} == {"HOT", "FLAT"}
    assert preopen.cache_path("HOT", TUESDAY, preopen.CACHE_BARS5M).exists()
    assert preopen.cache_path("HOT", TUESDAY, preopen.CACHE_DAILY).exists()
    assert not preopen.cache_path("COLD", TUESDAY, preopen.CACHE_BARS5M).exists()

    state = read_json(preopen.state_path(TUESDAY))
    assert sorted(state["candidates"]) == ["COLD", "FLAT", "HOT", "WARM"]
    assert preopen.history_outstanding(state) == ["COLD", "WARM"]

    saved = read_json(preopen.timings_path(TUESDAY))
    assert [row["name"] for row in saved["steps"]] == ["scan"]
    assert saved["steps"][0]["over_budget"] is False


def test_the_next_tick_finishes_the_history_and_does_not_scan_again(home, settings,
                                                                    sent):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    answer = run_tick(at(9, 6), broker, settings)

    # A minute later the pacer has room for four more, which is the rest.
    assert len(broker.history_calls) == 8
    # The gap scan runs every few minutes, not every tick.
    assert broker.calls.count("snapshot") == 1
    assert "the last gap scan was less than" in " ".join(answer["notes"])

    state = read_json(preopen.state_path(TUESDAY))
    assert preopen.history_outstanding(state) == []

    # The history step closed itself the moment the last file landed, well
    # inside its 9:26 deadline, so nobody was woken up.
    saved = read_json(preopen.timings_path(TUESDAY))
    history = [row for row in saved["steps"] if row["name"] == "history"]
    assert len(history) == 1
    assert history[0]["over_budget"] is False
    assert sent == []


def test_a_restart_does_not_pull_the_same_history_twice(home, settings):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    run_tick(at(9, 6), broker, settings)
    calls_so_far = len(broker.history_calls)

    # The state file is thrown away, as if the tick had never saved it. The
    # cache on disk is what makes the restart cheap.
    preopen.state_path(TUESDAY).unlink()
    run_tick(at(9, 10), broker, settings)
    assert len(broker.history_calls) == calls_so_far


def test_at_0928_it_settles_the_watch_list(home, settings):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    run_tick(at(9, 6), broker, settings)
    answer = run_tick(at(9, 28), broker, settings)

    assert answer["phase"] == preopen.PHASE_SUBSCRIBE
    assert answer["watch_list"] == 4

    state = read_json(preopen.state_path(TUESDAY))
    # Ordered biggest gap first, which is the order lines get claimed in.
    assert state["watch_list"] == ["HOT", "FLAT", "WARM", "COLD"]
    assert state["lines_available"] == preopen.STREAMING_LINES_WANTED
    assert state["subscribed_at"] == "2026-09-08T09:28:00-04:00"

    saved = read_json(preopen.timings_path(TUESDAY))
    names = [row["name"] for row in saved["steps"]]
    assert "subscribe" in names
    subscribe_step = [row for row in saved["steps"] if row["name"] == "subscribe"][0]
    assert subscribe_step["budget_deadline"] == "09:29"
    assert subscribe_step["over_budget"] is False


def test_fewer_lines_than_expected_keeps_the_top_sixty_and_says_so(home):
    # Eighty names are ready and the Gateway says it has room for seventy. The
    # rule is to keep sixty, not seventy, and to write down that it happened.
    state = preopen.new_state(TUESDAY)
    for index in range(80):
        symbol = f"N{index:03d}"
        state["candidates"][symbol] = {
            "symbol": symbol, "gap_pct": float(80 - index),
            preopen.CACHE_BARS5M: True, preopen.CACHE_DAILY: True}
    summary = preopen.subscribe(state, at(9, 28), lines_available=70)

    assert summary["watch_list"] == preopen.STREAMING_LINES_FALLBACK == 60
    assert state["watch_list"][0] == "N000"
    assert "70 streaming lines" in summary["note"]
    assert summary["note"] in state["notes"]


def test_at_0935_it_ranks_the_shortlist_from_the_recorded_bars(home, settings):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    run_tick(at(9, 6), broker, settings)
    run_tick(at(9, 28), broker, settings)
    answer = run_tick(at(9, 35), broker, settings)

    assert answer["phase"] == preopen.PHASE_RANK
    shortlist = answer["shortlist"]
    assert [row["symbol"] for row in shortlist] == ["HOT", "WARM"]
    assert [row["rank"] for row in shortlist] == [1, 2]

    top = shortlist[0]
    assert top["relative_volume"] == pytest.approx(6.0)
    assert top["baseline_days"] == 14
    assert top["direction"] == "long"
    assert top["atr"] == pytest.approx(2.0)
    assert top["opening_range_source"] == "today's five minute bars"

    state = read_json(preopen.state_path(TUESDAY))
    reasons = {row["symbol"]: row["reason"] for row in state["dropped"]}
    assert "flat" in reasons["FLAT"]
    assert "relative volume" in reasons["COLD"]

    saved = read_json(preopen.timings_path(TUESDAY))
    rank_step = [row for row in saved["steps"] if row["name"] == "rank"][0]
    assert rank_step["budget_seconds"] == 2.0
    assert rank_step["over_budget"] is False


def test_at_0950_there_is_nothing_left_to_do(home, settings):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    run_tick(at(9, 6), broker, settings)
    run_tick(at(9, 28), broker, settings)
    run_tick(at(9, 35), broker, settings)
    quiet_from = len(broker.history_calls), broker.calls.count("snapshot")

    answer = run_tick(at(9, 50), broker, settings)

    assert answer["phase"] == preopen.PHASE_DONE
    assert answer["did"] == []
    assert "finished for today" in " ".join(answer["notes"])
    # It asked the broker for nothing at all.
    assert (len(broker.history_calls), broker.calls.count("snapshot")) == quiet_from
    # And it left the shortlist exactly as it was.
    assert [row["symbol"] for row in answer["shortlist"]] == ["HOT", "WARM"]


def test_before_nine_there_is_nothing_to_do(home, settings):
    broker = four_name_broker()
    answer = run_tick(at(8, 55), broker, settings)
    assert answer["phase"] == preopen.PHASE_TOO_EARLY
    assert broker.calls == []
    assert broker.history_calls == []


# ---------------------------------------------------------------------------
# The late gappers
# ---------------------------------------------------------------------------


def late_broker() -> RecordedBroker:
    """The same four names plus one that only starts moving after 9:28."""
    broker = four_name_broker()
    broker.quotes["LATE"] = {"last": 120.0, "close": 100.0}
    broker.baseline["LATE"] = baseline_bars(5_000.0)
    broker.daily["LATE"] = daily_bars()
    broker.today["LATE"] = today_bars(50_000.0, 100.0, 103.0)
    return broker


def morning_up_to_the_bell(broker, settings, lines_available):
    preopen.step(at(9, 5), broker=broker, universe=list(SHORTLIST_NAMES),
                 settings=settings)
    preopen.step(at(9, 6), broker=broker, universe=list(SHORTLIST_NAMES),
                 settings=settings)
    preopen.step(at(9, 28), broker=broker, universe=list(SHORTLIST_NAMES),
                 settings=settings, lines_available=lines_available)


def test_a_late_gapper_is_skipped_with_a_reason_when_no_line_is_free(home, settings):
    broker = late_broker()
    # Four lines, four names on the list. There is no room for a fifth.
    morning_up_to_the_bell(broker, settings, lines_available=4)
    answer = preopen.step(at(9, 31), broker=broker,
                          universe=list(SHORTLIST_NAMES) + ["LATE"],
                          settings=settings)

    assert answer["phase"] == preopen.PHASE_WATCH
    assert answer["watch_list"] == 4
    assert "LATE arrived late and was skipped" in " ".join(answer["notes"])

    state = read_json(preopen.state_path(TUESDAY))
    late = state["late"][0]
    assert late["symbol"] == "LATE"
    assert late["joined"] is False
    assert "no streaming line free" in late["reason"]
    assert "LATE" not in state["watch_list"]


def test_a_late_gapper_joins_when_a_line_is_free(home, settings):
    broker = late_broker()
    # Five lines and four names, so one line is going spare.
    morning_up_to_the_bell(broker, settings, lines_available=5)
    calls_before = len(broker.history_calls)
    answer = preopen.step(at(9, 31), broker=broker,
                          universe=list(SHORTLIST_NAMES) + ["LATE"],
                          settings=settings)

    assert answer["watch_list"] == 5
    assert "1 late gapper(s) joined: LATE" in " ".join(answer["did"])

    state = read_json(preopen.state_path(TUESDAY))
    assert state["watch_list"][-1] == "LATE"
    assert state["late"][0]["joined"] is True
    # It also got its history, which is the only reason it can be ranked later.
    assert len(broker.history_calls) == calls_before + 2
    assert preopen.cache_path("LATE", TUESDAY, preopen.CACHE_DAILY).exists()


def test_a_late_gapper_that_joined_can_win_the_ranking(home, settings):
    broker = late_broker()
    morning_up_to_the_bell(broker, settings, lines_available=5)
    preopen.step(at(9, 31), broker=broker,
                 universe=list(SHORTLIST_NAMES) + ["LATE"], settings=settings)
    answer = preopen.step(at(9, 35), broker=broker,
                          universe=list(SHORTLIST_NAMES) + ["LATE"], settings=settings)

    # Ten times its normal opening volume, against HOT's six.
    assert [row["symbol"] for row in answer["shortlist"]] == ["LATE", "HOT", "WARM"]
    assert answer["shortlist"][0]["relative_volume"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# A missed morning
# ---------------------------------------------------------------------------


def test_a_history_pull_still_running_at_0928_crosses_its_budget(home, settings, sent):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)          # only two names get their history
    run_tick(at(9, 28), broker, settings)

    saved = read_json(preopen.timings_path(TUESDAY))
    history = [row for row in saved["steps"] if row["name"] == "history"][0]
    assert history["over_budget"] is True
    assert history["budget_deadline"] == "09:26"
    assert "never got" in history["detail"]

    titles = [title for _, title, _ in sent]
    assert any("history" in title for title in titles)


def test_a_quiet_morning_does_not_cry_wolf(home, settings, sent):
    """A pre-open that found no gappers is not a missed deadline.

    Nothing was pulled because nothing needed pulling. Raising the 9:26 alarm
    here would train Mo to ignore the one morning it means something.
    """
    broker = RecordedBroker(quotes={})
    preopen.step(at(9, 5), broker=broker, universe=["NOPE"], settings=settings)
    preopen.step(at(9, 28), broker=broker, universe=["NOPE"], settings=settings)

    saved = read_json(preopen.timings_path(TUESDAY))
    history = [row for row in saved["steps"] if row["name"] == "history"][0]
    assert history["over_budget"] is False
    assert "no name needed a history pull" in history["detail"]
    assert sent == []


def test_a_morning_where_the_subscribe_tick_never_ran_is_visible(home, settings, sent):
    broker = four_name_broker()
    run_tick(at(9, 5), broker, settings)
    run_tick(at(9, 6), broker, settings)
    # Straight from the history window to the bell. Nothing ran at 9:28.
    run_tick(at(9, 35), broker, settings)

    saved = read_json(preopen.timings_path(TUESDAY))
    subscribe = [row for row in saved["steps"] if row["name"] == "subscribe"][0]
    assert subscribe["over_budget"] is True
    assert "never ran" in subscribe["detail"]
    assert any("subscribe" in title for _, title, _ in sent)


# ---------------------------------------------------------------------------
# 4. It reads and it never trades
# ---------------------------------------------------------------------------


def test_preopen_can_never_send_an_order():
    """The pre-open is allowed to read the broker and nothing else.

    This reads the module's own text rather than trusting that no test happened
    to call one of them. If a future edit ever reaches for an order method, this
    fails on the next run, before anything reaches a real account.
    """
    text = Path(preopen.__file__).read_text(encoding="utf-8")
    for forbidden in ("place_order", "bracket_order", "cancel_order", "global_cancel"):
        assert forbidden not in text, (
            f"agent/preopen.py mentions {forbidden}. That file only reads.")


def test_a_whole_morning_never_touches_an_order_method(home, settings):
    # The fake broker's three order methods raise, so this passing at all is the
    # proof. The count of read calls is checked so the test cannot pass by doing
    # nothing.
    broker = late_broker()
    morning_up_to_the_bell(broker, settings, lines_available=5)
    preopen.step(at(9, 31), broker=broker,
                 universe=list(SHORTLIST_NAMES) + ["LATE"], settings=settings)
    preopen.step(at(9, 35), broker=broker,
                 universe=list(SHORTLIST_NAMES) + ["LATE"], settings=settings)
    preopen.step(at(9, 50), broker=broker,
                 universe=list(SHORTLIST_NAMES) + ["LATE"], settings=settings)

    assert broker.calls.count("snapshot") >= 2
    assert len(broker.history_calls) >= 10


def test_the_dry_run_prints_the_phase_and_touches_only_output(home, capsys):
    assert preopen.main(["--now", "2026-09-08 09:12"]) == 0
    printed = capsys.readouterr().out
    assert "Phase: gather" in printed
    assert "no broker was handed in" in printed
    assert str(home / "output") in printed
    # Everything it wrote is inside output/.
    written = {path.relative_to(home).parts[0] for path in home.rglob("*")
               if path.is_file()}
    assert written == {"output"}
