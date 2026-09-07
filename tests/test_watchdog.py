"""Tests for the watchdog's decision rules.

Everything here exercises the pure part of
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py:
decide_actions(), its bookkeeping partner update_state(), and judge_restart(),
which is the rule for whether a restart of IB Gateway actually took. No test
here touches IB Gateway, sends an alert, or starts anything. The restart tests
feed made up probes to the decision, so no Gateway is started or stopped.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_watchdog.py -q
"""
from __future__ import annotations

import os
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


# ------------------------------------------------- proving a restart happened

BEFORE_LOGIN = datetime(2026, 9, 8, 6, 30, tzinfo=wd.EASTERN)
AFTER_LOGIN = datetime(2026, 9, 8, 10, 16, tzinfo=wd.EASTERN)

#: What Gateway looked like just before the watchdog started it: process 123,
#: logged in at half six this morning, port already shut.
BEFORE = wd.GatewayProbe(pid="123", login_at=BEFORE_LOGIN, port_open=False)

#: What a Gateway that really did come back looks like.
ALL_THREE = wd.GatewayProbe(pid="456", login_at=AFTER_LOGIN, port_open=True)


class FakeHandle:
    """Stands in for the handle the start script comes back as.

    poll() is None while the script is still running, which is what a working
    start looks like, because that script becomes Gateway and never returns.
    """

    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class FakeProbe:
    """Hands out a prepared list of looks at Gateway, then repeats the last one.

    The first call is the "before" look that restart_gateway() takes, so the
    list reads in the order the real thing would see them.
    """

    def __init__(self, *looks):
        self.looks = list(looks)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.looks[min(self.calls - 1, len(self.looks) - 1)]


def try_restart(*looks, exit_code=None, handle=True, wait_seconds=120,
                poll_seconds=5):
    """One restart attempt with made up answers. No Gateway is anywhere near it.

    Returns the outcome and the list of sleeps it asked for, so a test can say
    both what it decided and how long it was willing to wait.
    """
    slept: list[int] = []
    launcher = (lambda: (FakeHandle(exit_code), "IB Gateway starting"))
    if not handle:
        launcher = lambda: (None, "cannot restart, the script is missing")  # noqa: E731
    outcome = wd.restart_gateway(
        wait_seconds=wait_seconds, poll_seconds=poll_seconds,
        probe=FakeProbe(BEFORE, *looks), launcher=launcher,
        sleep=lambda seconds: slept.append(seconds))
    return outcome, slept


def test_the_same_process_id_back_again_is_not_a_restart():
    """Everything else can look right; the old process id means nothing started."""
    same_pid = wd.GatewayProbe(pid="123", login_at=AFTER_LOGIN, port_open=True)
    outcome, slept = try_restart(same_pid)

    assert outcome.took is False
    assert outcome.new_pid is False
    assert outcome.fresh_login is True and outcome.port_open is True
    assert "a different process id: no" in outcome.detail
    assert "was 123, now 123" in outcome.detail
    assert outcome.waited_seconds == 120, "it waits the whole two minutes first"
    assert len(slept) == 24


def test_a_new_process_that_never_logged_in_is_not_a_restart():
    """Gateway can start, fail the login and sit on the prompt all day."""
    no_login = wd.GatewayProbe(pid="456", login_at=BEFORE_LOGIN, port_open=True)
    outcome, _ = try_restart(no_login)

    assert outcome.took is False
    assert outcome.new_pid is True and outcome.port_open is True
    assert outcome.fresh_login is False
    assert "a newer login in the IBC log: no" in outcome.detail


def test_a_fresh_login_with_a_shut_port_is_not_a_restart():
    """Logged in but not listening is the hang the watchdog exists to catch."""
    shut_port = wd.GatewayProbe(pid="456", login_at=AFTER_LOGIN, port_open=False)
    outcome, _ = try_restart(shut_port)

    assert outcome.took is False
    assert outcome.new_pid is True and outcome.fresh_login is True
    assert outcome.port_open is False
    assert f"port {wd.GATEWAY_PORT} accepting connections: no" in outcome.detail


def test_all_three_proofs_together_are_a_restart():
    outcome, slept = try_restart(ALL_THREE)

    assert outcome.took is True
    assert (outcome.new_pid, outcome.fresh_login, outcome.port_open) == (True, True, True)
    assert slept == [], "there is nothing to wait for once all three are there"
    assert outcome.waited_seconds == 0


def test_a_start_script_that_exits_with_an_error_is_not_a_restart():
    """That script becomes Gateway when it works, so an exit code means it gave up."""
    outcome, slept = try_restart(ALL_THREE, exit_code=1)

    assert outcome.took is False
    assert "exited with code 1" in outcome.detail
    assert slept == [], "no point waiting two minutes for a script that has stopped"


def test_a_start_script_that_could_not_be_run_at_all_is_not_a_restart():
    outcome, slept = try_restart(ALL_THREE, handle=False)

    assert outcome.took is False
    assert "never ran" in outcome.detail
    assert slept == []


def test_a_slow_gateway_is_still_a_restart_once_it_finishes_starting():
    """It keeps looking for two minutes rather than judging the first glance."""
    starting = wd.GatewayProbe(pid="456", login_at=BEFORE_LOGIN, port_open=False)
    logged_in = wd.GatewayProbe(pid="456", login_at=AFTER_LOGIN, port_open=False)
    outcome, slept = try_restart(starting, logged_in, ALL_THREE)

    assert outcome.took is True
    assert slept == [5, 5], "two waits, then the third look had everything"
    assert outcome.waited_seconds == 10


def test_a_gateway_that_never_comes_back_gives_up_after_two_minutes():
    nothing = wd.GatewayProbe(pid=None, login_at=BEFORE_LOGIN, port_open=False)
    outcome, slept = try_restart(nothing)

    assert outcome.took is False
    assert outcome.waited_seconds == 120
    assert sum(slept) == 120
    assert "nothing running" in outcome.detail


def test_the_very_first_login_ever_still_counts_as_fresh():
    """An empty IBC log before the restart must not make a good restart look bad."""
    nothing_before = wd.GatewayProbe(pid=None, login_at=None, port_open=False)
    outcome = wd.judge_restart(nothing_before, ALL_THREE)
    assert outcome.took is True
    assert "was never, now 2026-09-08 10:16:00" in outcome.detail


def test_judge_restart_changes_nothing_it_was_given():
    before = wd.GatewayProbe(pid="123", login_at=BEFORE_LOGIN, port_open=False)
    after = wd.GatewayProbe(pid="456", login_at=AFTER_LOGIN, port_open=True)
    snapshot = (repr(before), repr(after))
    wd.judge_restart(before, after, None)
    assert (repr(before), repr(after)) == snapshot


def test_two_minutes_is_what_a_restart_gets():
    assert wd.RESTART_VERIFY_SECONDS == 120
    assert wd.RESTART_POLL_SECONDS == 5


# ----------------------------------------------- reading IBC's own login times

IBC_LINES = """Parsing arguments

Starting IBC version 3.24.2 on 2026-09-06 at 11:41:12
2026-09-06 11:41:20:118 IBC: Login dialog found
2026-09-06 11:42:11:200 IBC: Login has completed
2026-09-06 11:42:12:000 IBC: something else entirely
2026-09-06 13:22:04:542 IBC: Login has completed
2026-09-06 13:22:05:100 IBC: after the last login
"""


def test_the_newest_login_is_read_off_the_ibc_log(tmp_path):
    (tmp_path / "ibc-3.24.2_GATEWAY-10.45_Sunday.txt").write_text(IBC_LINES, encoding="utf-8")
    assert wd.newest_ibc_login(tmp_path) == datetime(2026, 9, 6, 13, 22, 4, tzinfo=wd.EASTERN)


def test_the_newest_log_file_wins_not_the_one_with_the_likeliest_name(tmp_path):
    """IBC names its logs after the weekday, so a restart past midnight moves file."""
    old = tmp_path / "ibc-3.24.2_GATEWAY-10.45_Wednesday.txt"
    old.write_text("2026-09-02 13:27:06:948 IBC: Login has completed\n", encoding="utf-8")
    new = tmp_path / "ibc-3.24.2_GATEWAY-10.45_Sunday.txt"
    new.write_text("2026-09-06 11:42:11:200 IBC: Login has completed\n", encoding="utf-8")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    assert wd.newest_ibc_login(tmp_path) == datetime(2026, 9, 6, 11, 42, 11, tzinfo=wd.EASTERN)


def test_no_ibc_log_at_all_is_no_login_rather_than_a_crash(tmp_path):
    assert wd.newest_ibc_login(tmp_path) is None
    assert wd.newest_ibc_login(tmp_path / "not there") is None


def test_a_log_with_no_login_line_reports_no_login(tmp_path):
    (tmp_path / "ibc-3.24.2_GATEWAY-10.45_Monday.txt").write_text(
        "2026-09-06 11:41:20:118 IBC: Login dialog found\n", encoding="utf-8")
    assert wd.newest_ibc_login(tmp_path) is None


# ------------------------------------------- what gets written down afterwards

def catch_alerts(monkeypatch) -> list[tuple[str, str]]:
    """Swallow the alerts and hand back (level, title) for each one."""
    sent: list[tuple[str, str]] = []

    def fake_alert(level, title, body):
        sent.append((level, title))
        return ["test"]

    monkeypatch.setattr(wd.alerts_module, "alert", fake_alert)
    return sent


def fake_outcome(took: bool) -> wd.RestartOutcome:
    return wd.RestartOutcome(took=took, new_pid=took, fresh_login=took, port_open=took,
                             detail="  a different process id: yes", waited_seconds=30)


def test_a_verified_restart_is_written_down_as_an_attempt(monkeypatch):
    sent = catch_alerts(monkeypatch)
    monkeypatch.setattr(wd, "restart_gateway", lambda *a, **k: fake_outcome(True))

    actions = wd.decide_actions(gateway_down(), MID_MORNING, {"checks": {}})
    _lines, happened = wd.perform(actions, allow_restart=True)
    state = wd.update_state(gateway_down(), MID_MORNING, {"checks": {}}, happened)

    assert state["checks"][wd.CHECK_GATEWAY_PROCESS]["restart_attempted"] is True
    assert ("error", "Watchdog: restart did not take") not in sent


def test_a_restart_that_did_not_take_is_not_written_down_as_an_attempt(monkeypatch):
    """It failed, so the outage keeps its restart in hand rather than spending it."""
    sent = catch_alerts(monkeypatch)
    monkeypatch.setattr(wd, "restart_gateway", lambda *a, **k: fake_outcome(False))

    actions = wd.decide_actions(gateway_down(), MID_MORNING, {"checks": {}})
    lines, happened = wd.perform(actions, allow_restart=True)
    state = wd.update_state(gateway_down(), MID_MORNING, {"checks": {}}, happened)

    assert state["checks"][wd.CHECK_GATEWAY_PROCESS]["restart_attempted"] is False
    assert ("error", "Watchdog: restart did not take") in sent
    assert any("NOT verified" in line for line in lines)
    assert restarts_in(happened) == [], "an unproved restart is not one of the things that happened"


def test_the_no_restart_flag_still_starts_nothing(monkeypatch):
    catch_alerts(monkeypatch)
    started: list[int] = []
    monkeypatch.setattr(wd, "restart_gateway",
                        lambda *a, **k: started.append(1) or fake_outcome(True))

    actions = wd.decide_actions(gateway_down(), MID_MORNING, {"checks": {}})
    lines, happened = wd.perform(actions, allow_restart=False)

    assert started == []
    assert any("--no-restart" in line for line in lines)
    assert restarts_in(happened) == []


def test_the_restart_did_not_take_message_says_which_of_the_three_failed():
    shut_port = wd.GatewayProbe(pid="456", login_at=AFTER_LOGIN, port_open=False)
    outcome = wd.judge_restart(BEFORE, shut_port, None, waited_seconds=120)
    alert = wd.restart_did_not_take_alert(wd.CHECK_GATEWAY_PROCESS, outcome)

    assert alert.kind == wd.ACTION_ALERT and alert.level == "error"
    assert alert.title == "Watchdog: restart did not take"
    assert "a different process id: yes" in alert.body
    assert "a newer login in the IBC log: yes" in alert.body
    assert f"port {wd.GATEWAY_PORT} accepting connections: no" in alert.body
    assert "120 seconds" in alert.body
    assert "What to do" in alert.body


# ------------------------------------------------------- the time zone check

# WHY THIS CHECK EXISTS. launchd fires a job on the Mac's own clock and nothing
# in a plist can pin a time zone. On the night of 2026-09-06 this Mac relinked
# /etc/localtime to America/Los_Angeles by itself, because macOS is set to pick
# the zone from the current location, and all nine jobs quietly became three
# hours late. Automatic zone selection is still on, so the watchdog asks this
# every run rather than trusting a note in the docs.

def _stub_verdict(monkeypatch, verdict):
    monkeypatch.setattr(wd.timezone_check, "check",
                        lambda *args, **kwargs: verdict)


def test_the_time_zone_check_passes_when_the_stamp_matches_the_mac(monkeypatch):
    _stub_verdict(monkeypatch, wd.timezone_check.Verdict(
        True, "this Mac is in America/Los_Angeles, -180 minutes from New York",
        system_zone="America/Los_Angeles", current_shift=-180,
        stamped_shift=-180))

    check = wd.check_time_zone()

    assert check.name == wd.CHECK_TIME_ZONE
    assert check.ok
    assert not check.skipped
    assert "America/Los_Angeles" in check.detail


def test_the_time_zone_check_fails_when_the_mac_has_moved(monkeypatch):
    """The whole point: a Mac that wanders must not fail silently."""
    _stub_verdict(monkeypatch, wd.timezone_check.Verdict(
        False,
        "this Mac has moved from America/New_York to America/Los_Angeles since "
        "the launchd jobs were written.",
        fix="python3 /somewhere/scripts/gen_launchd.py --install",
        system_zone="America/Los_Angeles", stamped_zone="America/New_York",
        current_shift=-180, stamped_shift=0))

    check = wd.check_time_zone()

    assert not check.ok
    assert not check.skipped, "a wrong zone is a miss, not something to skip"
    assert "moved" in check.detail
    # The advice that goes out with the alert has to carry the fix, because the
    # person reading it is reading it wondering why nothing fired.
    assert "gen_launchd.py --install" in wd.WHAT_TO_DO[wd.CHECK_TIME_ZONE]


def test_the_time_zone_check_never_takes_the_watchdog_down(monkeypatch):
    """A broken check must not stop the other six from being reported."""
    def explode(*args, **kwargs):
        raise RuntimeError("no zone database on this machine")
    monkeypatch.setattr(wd.timezone_check, "check", explode)

    check = wd.check_time_zone()

    assert check.ok
    assert check.skipped
    assert "no zone database" in check.detail


def test_the_time_zone_check_is_in_the_reported_order_and_has_advice():
    assert wd.CHECK_TIME_ZONE in wd.CHECK_ORDER
    assert wd.CHECK_TIME_ZONE in wd.WHAT_TO_DO
    # It can never cause a Gateway restart. Restarting Gateway would do nothing
    # whatever about a wrong time zone.
    assert wd.CHECK_TIME_ZONE not in wd.RESTART_CHECKS


def test_the_time_zone_check_is_asked_even_when_the_market_is_shut(monkeypatch):
    """The useful time to hear it is the evening before, not 09:35 on the day.

    Every other check that can be skipped is skipped outside market hours. This
    one is not, because the answer does not depend on the market being open and
    because a zone that moved overnight is worth knowing about before the open
    rather than after it.
    """
    asked = []
    monkeypatch.setattr(wd.timezone_check, "check",
                        lambda *a, **k: asked.append(True) or
                        wd.timezone_check.Verdict(True, "fine"))
    monkeypatch.setattr(wd, "check_gateway_process",
                        lambda: wd.Check(wd.CHECK_GATEWAY_PROCESS, ok=True))
    monkeypatch.setattr(wd, "check_gateway_port",
                        lambda *a, **k: wd.Check(wd.CHECK_GATEWAY_PORT, ok=True))
    monkeypatch.setattr(wd, "check_ib_and_market_data",
                        lambda **k: (wd.Check(wd.CHECK_IB_CONNECT, ok=True),
                                     wd.Check(wd.CHECK_MARKET_DATA, ok=True)))
    monkeypatch.setattr(wd, "check_disk",
                        lambda *a, **k: wd.Check(wd.CHECK_DISK, ok=True))

    # A Sunday evening, which is as shut as the market gets.
    sunday = datetime(2026, 9, 6, 21, 0, tzinfo=wd.EASTERN)
    checks = wd.run_checks(sunday, wd.Schedule())

    assert asked, "the time zone was not checked at all outside market hours"
    assert wd.CHECK_TIME_ZONE in checks
    assert checks[wd.CHECK_TIME_ZONE].ok
