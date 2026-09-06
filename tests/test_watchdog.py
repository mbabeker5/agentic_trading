"""Tests for the watchdog's decision rules.

Everything here exercises the pure part of
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py,
which is decide_actions() and its bookkeeping partner update_state(). No test
here touches IB Gateway, sends an alert, or starts anything.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_watchdog.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import watchdog as wd  # noqa: E402

MID_MORNING = datetime(2026, 9, 8, 10, 15, tzinfo=wd.EASTERN)   # a Tuesday
AFTER_HOURS = datetime(2026, 9, 8, 18, 40, tzinfo=wd.EASTERN)
SATURDAY = datetime(2026, 9, 12, 11, 0, tzinfo=wd.EASTERN)


# ----------------------------------------------------------------- helpers

def healthy() -> dict[str, wd.Check]:
    """Every check passing, which is what a normal Tuesday morning looks like."""
    return {
        wd.CHECK_GATEWAY_PROCESS: wd.Check(wd.CHECK_GATEWAY_PROCESS, ok=True,
                                           detail="IB Gateway is running, process 123."),
        wd.CHECK_GATEWAY_PORT: wd.Check(wd.CHECK_GATEWAY_PORT, ok=True,
                                        detail="127.0.0.1:4002 is accepting connections."),
        wd.CHECK_IB_CONNECT: wd.Check(wd.CHECK_IB_CONNECT, ok=True,
                                      detail="Connected read only, account DUT077572."),
        wd.CHECK_MARKET_DATA: wd.Check(wd.CHECK_MARKET_DATA, ok=True,
                                       detail="SPY real time quote, bid 769.4 ask 769.5."),
        wd.CHECK_LOOP_TICK: wd.Check(wd.CHECK_LOOP_TICK, ok=True,
                                     detail="Last tick 10:10 from output/loop.log."),
        wd.CHECK_DISK: wd.Check(wd.CHECK_DISK, ok=True, detail="412.0 GB free."),
    }


def gateway_down() -> dict[str, wd.Check]:
    """What the checks look like when IB Gateway is not running at all.

    Both Gateway checks miss, and the two that depend on a connection are
    skipped rather than counted as failures, because there was nothing to ask.
    """
    checks = healthy()
    checks[wd.CHECK_GATEWAY_PROCESS] = wd.Check(
        wd.CHECK_GATEWAY_PROCESS, ok=False,
        detail="No IB Gateway process is running on this Mac.")
    checks[wd.CHECK_GATEWAY_PORT] = wd.Check(
        wd.CHECK_GATEWAY_PORT, ok=False,
        detail="Nothing is accepting connections on 127.0.0.1:4002.")
    checks[wd.CHECK_IB_CONNECT] = wd.Check(
        wd.CHECK_IB_CONNECT, ok=True, skipped=True,
        detail="not checked, the port is shut")
    checks[wd.CHECK_MARKET_DATA] = wd.Check(
        wd.CHECK_MARKET_DATA, ok=True, skipped=True,
        detail="not checked, there was no connection to ask on")
    return checks


def step(checks: dict, now: datetime, state: dict) -> tuple[list[wd.Action], dict]:
    """One whole run: decide, then record, the way main() does it."""
    actions = wd.decide_actions(checks, now, state)
    return actions, wd.update_state(checks, now, state, actions)


def alerts_in(actions: list[wd.Action]) -> list[wd.Action]:
    return [a for a in actions if a.kind == wd.ACTION_ALERT]


def restarts_in(actions: list[wd.Action]) -> list[wd.Action]:
    return [a for a in actions if a.kind == wd.ACTION_RESTART]


# ------------------------------------------------------------------- healthy

def test_a_healthy_run_says_nothing_and_does_nothing():
    actions, state = step(healthy(), MID_MORNING, {"checks": {}})
    assert actions == []
    assert all(entry["ok"] for entry in state["checks"].values())


def test_a_healthy_run_after_a_healthy_run_still_says_nothing():
    _, state = step(healthy(), MID_MORNING, {"checks": {}})
    actions, _ = step(healthy(), MID_MORNING + timedelta(minutes=5), state)
    assert actions == []


# ---------------------------------------------------------- gateway goes down

def test_the_first_gateway_miss_alerts_and_starts_gateway_once():
    actions, state = step(gateway_down(), MID_MORNING, {"checks": {}})

    raised = alerts_in(actions)
    assert [a.check for a in raised] == [wd.CHECK_GATEWAY_PROCESS, wd.CHECK_GATEWAY_PORT]
    assert all(a.level == "error" for a in raised)
    assert "What to do" in raised[0].body

    started = restarts_in(actions)
    assert len(started) == 1, "exactly one restart attempt, not one per failing check"
    assert started[0].check == wd.CHECK_GATEWAY_PROCESS

    assert state["checks"][wd.CHECK_GATEWAY_PROCESS]["restart_attempted"] is True
    assert state["checks"][wd.CHECK_GATEWAY_PROCESS]["failing_since"] == MID_MORNING.isoformat()


def test_a_second_miss_within_thirty_minutes_is_silent_and_does_not_restart_again():
    _, state = step(gateway_down(), MID_MORNING, {"checks": {}})

    five_minutes_later = MID_MORNING + timedelta(minutes=5)
    actions, state = step(gateway_down(), five_minutes_later, state)
    assert actions == [], "the same outage five minutes on is not news"

    twenty_nine_minutes_later = MID_MORNING + timedelta(minutes=29)
    actions, _ = step(gateway_down(), twenty_nine_minutes_later, state)
    assert actions == []


def test_a_miss_that_has_lasted_half_an_hour_is_mentioned_again_but_not_restarted():
    _, state = step(gateway_down(), MID_MORNING, {"checks": {}})

    later = MID_MORNING + timedelta(minutes=31)
    actions, state = step(gateway_down(), later, state)

    raised = alerts_in(actions)
    assert len(raised) == 2, "one per still failing check"
    assert all("still failing" in a.title for a in raised)
    assert restarts_in(actions) == [], "the one restart attempt has already been used"

    # And the clock resets, so the next reminder is another half hour away.
    actions, _ = step(gateway_down(), later + timedelta(minutes=5), state)
    assert actions == []


def test_the_outage_only_ever_gets_one_restart_even_over_hours():
    state: dict = {"checks": {}}
    now = MID_MORNING
    restarts = 0
    for _ in range(40):                       # a bit over three hours of wake ups
        actions, state = step(gateway_down(), now, state)
        restarts += len(restarts_in(actions))
        now += timedelta(minutes=5)
    assert restarts == 1


# ------------------------------------------------------------------ recovery

def test_a_recovery_is_announced_once_at_level_info():
    _, state = step(gateway_down(), MID_MORNING, {"checks": {}})

    back_up = MID_MORNING + timedelta(minutes=10)
    actions, state = step(healthy(), back_up, state)

    raised = alerts_in(actions)
    assert [a.check for a in raised] == [wd.CHECK_GATEWAY_PROCESS, wd.CHECK_GATEWAY_PORT]
    assert all(a.level == "info" for a in raised)
    assert all(a.title.startswith("Recovered") for a in raised)
    assert restarts_in(actions) == []

    # The next healthy run is quiet.
    actions, _ = step(healthy(), back_up + timedelta(minutes=5), state)
    assert actions == []


def test_a_second_outage_after_a_recovery_gets_its_own_restart():
    _, state = step(gateway_down(), MID_MORNING, {"checks": {}})
    _, state = step(healthy(), MID_MORNING + timedelta(minutes=10), state)

    actions, _ = step(gateway_down(), MID_MORNING + timedelta(minutes=60), state)
    assert len(restarts_in(actions)) == 1, "a fresh outage earns a fresh attempt"


# -------------------------------------------------------- the market data feed

def test_a_competing_live_session_alerts_at_warn_and_never_restarts():
    checks = healthy()
    checks[wd.CHECK_MARKET_DATA] = wd.Check(
        wd.CHECK_MARKET_DATA, ok=False, code=wd.CODE_COMPETING_SESSION, level="warn",
        detail=("Competing live session: Mo has a live quote screen or the IBKR app "
                "open and it is holding the market data feed. Close it."))

    actions, state = step(checks, MID_MORNING, {"checks": {}})

    raised = alerts_in(actions)
    assert len(raised) == 1
    assert raised[0].check == wd.CHECK_MARKET_DATA
    assert raised[0].level == "warn"
    assert restarts_in(actions) == [], "10197 is Mo's own screen, not a broken Gateway"
    assert state["checks"][wd.CHECK_MARKET_DATA]["code"] == wd.CODE_COMPETING_SESSION


def test_ten_one_nine_seven_on_a_gateway_check_still_never_restarts():
    """Belt and braces: the code wins even when the failing check is a restartable one."""
    checks = gateway_down()
    checks[wd.CHECK_GATEWAY_PORT] = wd.Check(
        wd.CHECK_GATEWAY_PORT, ok=False, code=wd.CODE_COMPETING_SESSION,
        detail="port check reported a competing live session")
    checks[wd.CHECK_GATEWAY_PROCESS] = wd.Check(
        wd.CHECK_GATEWAY_PROCESS, ok=True, detail="IB Gateway is running, process 123.")

    actions, _ = step(checks, MID_MORNING, {"checks": {}})
    assert len(alerts_in(actions)) == 1
    assert restarts_in(actions) == []


def test_a_missing_subscription_alerts_at_warn():
    checks = healthy()
    checks[wd.CHECK_MARKET_DATA] = wd.Check(
        wd.CHECK_MARKET_DATA, ok=False, code=wd.CODE_NO_SUBSCRIPTION, level="warn",
        detail="Not subscribed to real time data, so SPY is on delayed prices only.")
    actions, _ = step(checks, MID_MORNING, {"checks": {}})
    assert alerts_in(actions)[0].level == "warn"
    assert restarts_in(actions) == []


# ------------------------------------------------------------- a hung gateway

def test_a_running_gateway_with_a_shut_port_alerts_but_starts_no_second_copy():
    """Two Gateways logged into one account fight over the session, so we do not."""
    checks = healthy()
    checks[wd.CHECK_GATEWAY_PORT] = wd.Check(
        wd.CHECK_GATEWAY_PORT, ok=False,
        detail="Nothing is accepting connections on 127.0.0.1:4002.")

    actions, _ = step(checks, MID_MORNING, {"checks": {}})
    assert [a.check for a in alerts_in(actions)] == [wd.CHECK_GATEWAY_PORT]
    assert restarts_in(actions) == []


# ------------------------------------------------------ the loop's heartbeat

def test_a_stale_tick_during_market_hours_is_a_miss():
    checks = healthy()
    checks[wd.CHECK_LOOP_TICK] = wd.Check(
        wd.CHECK_LOOP_TICK, ok=False,
        detail=("The trading loop last ticked 47 minutes ago, and it is meant to "
                "tick every 5 minutes."))

    actions, state = step(checks, MID_MORNING, {"checks": {}})
    raised = alerts_in(actions)
    assert [a.check for a in raised] == [wd.CHECK_LOOP_TICK]
    assert raised[0].level == "error"
    assert restarts_in(actions) == [], "a late loop is not a reason to restart Gateway"
    assert state["checks"][wd.CHECK_LOOP_TICK]["ok"] is False


def test_a_stale_tick_outside_market_hours_is_skipped_and_says_nothing():
    checks = healthy()
    checks[wd.CHECK_LOOP_TICK] = wd.Check(
        wd.CHECK_LOOP_TICK, ok=True, skipped=True,
        detail="not checked, the market is shut")

    actions, state = step(checks, AFTER_HOURS, {"checks": {}})
    assert actions == []
    assert wd.CHECK_LOOP_TICK not in state["checks"], (
        "a skipped check is forgotten, so it cannot produce a recovery message "
        "at the open the next morning")


def test_a_heartbeat_failing_at_the_close_does_not_recover_loudly_the_next_day():
    stale = healthy()
    stale[wd.CHECK_LOOP_TICK] = wd.Check(
        wd.CHECK_LOOP_TICK, ok=False, detail="The trading loop last ticked 40 minutes ago.")
    _, state = step(stale, MID_MORNING, {"checks": {}})
    assert state["checks"][wd.CHECK_LOOP_TICK]["ok"] is False

    shut = healthy()
    shut[wd.CHECK_LOOP_TICK] = wd.Check(wd.CHECK_LOOP_TICK, ok=True, skipped=True,
                                        detail="not checked, the market is shut")
    _, state = step(shut, AFTER_HOURS, state)

    actions, _ = step(healthy(), MID_MORNING + timedelta(days=1), state)
    assert actions == []


def test_check_loop_tick_skips_when_the_market_is_shut(monkeypatch):
    monkeypatch.setattr(wd, "tick_job_loaded", lambda *a, **k: True)
    monkeypatch.setattr(wd, "last_tick_time", lambda: (None, "nothing found"))
    check = wd.check_loop_tick(AFTER_HOURS, wd.Schedule(), market_hours=False)
    assert check.skipped is True


def test_check_loop_tick_notices_a_late_loop_during_market_hours(monkeypatch):
    monkeypatch.setattr(wd, "tick_job_loaded", lambda *a, **k: True)
    monkeypatch.setattr(wd, "last_tick_time",
                        lambda: (MID_MORNING - timedelta(minutes=47), "output/loop.log"))
    check = wd.check_loop_tick(MID_MORNING, wd.Schedule(), market_hours=True)
    assert check.ok is False and check.skipped is False
    assert "47 minutes ago" in check.detail


def test_check_loop_tick_is_happy_with_a_recent_tick(monkeypatch):
    monkeypatch.setattr(wd, "tick_job_loaded", lambda *a, **k: True)
    monkeypatch.setattr(wd, "last_tick_time",
                        lambda: (MID_MORNING - timedelta(minutes=4), "output/loop.log"))
    check = wd.check_loop_tick(MID_MORNING, wd.Schedule(), market_hours=True)
    assert check.ok is True and check.skipped is False


def test_check_loop_tick_stays_quiet_when_the_loop_job_is_not_loaded(monkeypatch):
    monkeypatch.setattr(wd, "tick_job_loaded", lambda *a, **k: False)
    monkeypatch.setattr(wd, "last_tick_time", lambda: (None, "nothing found"))
    check = wd.check_loop_tick(MID_MORNING, wd.Schedule(), market_hours=True)
    assert check.skipped is True
    assert "not loaded" in check.detail


# ---------------------------------------------------------- odds and ends

def test_market_hours_are_weekdays_between_the_open_and_the_close():
    schedule = wd.Schedule()
    assert wd.in_market_hours(MID_MORNING, schedule) is True
    assert wd.in_market_hours(AFTER_HOURS, schedule) is False
    assert wd.in_market_hours(SATURDAY, schedule) is False
    assert wd.in_market_hours(datetime(2026, 9, 8, 9, 29, tzinfo=wd.EASTERN), schedule) is False
    assert wd.in_market_hours(datetime(2026, 9, 8, 9, 30, tzinfo=wd.EASTERN), schedule) is True
    assert wd.in_market_hours(datetime(2026, 9, 8, 16, 0, tzinfo=wd.EASTERN), schedule) is False


def test_two_loop_intervals_is_what_counts_as_stale():
    assert wd.Schedule(loop_minutes=5).stale_after == timedelta(minutes=10)
    assert wd.Schedule(loop_minutes=15).stale_after == timedelta(minutes=30)


def test_a_check_can_be_handed_in_as_a_plain_dictionary():
    checks = {wd.CHECK_DISK: {"ok": False, "detail": "Only 0.40 GB free.", "level": "warn"}}
    actions, _ = step(checks, MID_MORNING, {"checks": {}})
    assert len(alerts_in(actions)) == 1
    assert alerts_in(actions)[0].level == "warn"


def test_an_unreadable_state_file_is_treated_as_a_fresh_start(tmp_path, monkeypatch):
    broken = tmp_path / "watchdog_state.json"
    broken.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setattr(wd, "state_path", lambda: broken)
    assert wd.load_state() == {"checks": {}}


def test_decide_actions_changes_nothing_it_was_given():
    """It is meant to be pure, so prove it does not quietly edit its arguments."""
    checks = gateway_down()
    state = {"checks": {wd.CHECK_GATEWAY_PORT: {"ok": False, "last_alert_at": None}}}
    before = repr(state)
    wd.decide_actions(checks, MID_MORNING, state)
    assert repr(state) == before


def test_no_restart_while_ibc_is_doing_its_own_nightly_restart():
    """IBC restarts Gateway itself around 2 AM. Two starters make two Gateways."""
    two_am = datetime(2026, 9, 9, 2, 0, tzinfo=wd.EASTERN)
    actions, _ = step(gateway_down(), two_am, {"checks": {}})
    assert len(alerts_in(actions)) == 2, "still worth saying Gateway is down"
    assert restarts_in(actions) == []

    quarter_past_three = datetime(2026, 9, 9, 3, 15, tzinfo=wd.EASTERN)
    actions, _ = step(gateway_down(), quarter_past_three, {"checks": {}})
    assert len(restarts_in(actions)) == 1, "outside the window it restarts as normal"


def test_the_nightly_restart_window_covers_the_two_am_job():
    assert wd.in_nightly_restart_window(datetime(2026, 9, 9, 1, 44, tzinfo=wd.EASTERN)) is False
    assert wd.in_nightly_restart_window(datetime(2026, 9, 9, 1, 45, tzinfo=wd.EASTERN)) is True
    assert wd.in_nightly_restart_window(datetime(2026, 9, 9, 2, 29, tzinfo=wd.EASTERN)) is True
    assert wd.in_nightly_restart_window(datetime(2026, 9, 9, 2, 30, tzinfo=wd.EASTERN)) is False


def test_both_no_subscription_codes_mean_the_same_thing():
    assert wd.CODE_NO_SUBSCRIPTION in wd.NOT_SUBSCRIBED_CODES
    assert wd.CODE_NO_API_SUBSCRIPTION in wd.NOT_SUBSCRIBED_CODES
    assert wd.CODE_COMPETING_SESSION not in wd.NOT_SUBSCRIBED_CODES
