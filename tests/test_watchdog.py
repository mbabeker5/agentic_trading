"""Tests for the watchdog's decision rules.

Everything here exercises the pure part of
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py:
decide_actions(), its bookkeeping partner update_state(), and judge_restart(),
which is the rule for whether a restart of IB Gateway actually took. No test
here touches IB Gateway, sends an alert, or starts anything. The restart tests
feed made up probes to the decision, so no Gateway is started or stopped, and
the connection tests hand _connect_read_only() and _positions_answer() a stand
in object rather than an ib_async session.

The later sections are all about the same day, 2026-09-07, which produced four
separate lessons in about twelve hours:

* a Gateway logged in and cut off from IBKR at once, which every check passed,
  so ib_answers now asks it a real question;
* a restart that could show all three local proofs and still not work, so there
  is a fourth proof that IBKR is on the other end;
* a stuck copy of the watchdog holding client id 250, so a collision moves to a
  spare id instead of alerting, and the whole run is on a wall clock;
* Labor Day, a shut market that failed market_data every five minutes, so the
  market hours question knows about holidays.

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
        wd.CHECK_IB_ANSWERS: wd.Check(
            wd.CHECK_IB_ANSWERS, ok=True,
            detail="Gateway answered a positions request in 0.04 s, 1 position."),
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
    checks[wd.CHECK_IB_ANSWERS] = wd.Check(
        wd.CHECK_IB_ANSWERS, ok=True, skipped=True,
        detail="not checked, the port is shut")
    checks[wd.CHECK_MARKET_DATA] = wd.Check(
        wd.CHECK_MARKET_DATA, ok=True, skipped=True,
        detail="not checked, there was no connection to ask on")
    return checks


def gateway_not_answering() -> dict[str, wd.Check]:
    """The outage of 2026-09-07, twice in one day, as the checks now see it.

    Gateway is running, the port is open, the login goes through and the
    account id comes back. Every one of the old checks passes. The only thing
    wrong is that IBKR is not on the other end any more, and the only check
    that can tell is the one that asks a real question.
    """
    checks = healthy()
    checks[wd.CHECK_IB_ANSWERS] = wd.Check(
        wd.CHECK_IB_ANSWERS, ok=False,
        detail=("Gateway is logged in but IBKR is not answering (positions request "
                "timed out after 20 s); it has lost its upstream connection."))
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
                poll_seconds=5, answers=True, stop_first=False, stopper=None):
    """One restart attempt with made up answers. No Gateway is anywhere near it.

    answers stands in for the fourth proof, the read that either comes back
    from the new Gateway or does not. It is only ever asked once the first
    three proofs are in, so most of these tests never reach it.

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
        sleep=lambda seconds: slept.append(seconds),
        stop_first=stop_first,
        stopper=stopper or (lambda: (True, "the old Gateway was stopped")),
        answering=lambda: answers)
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
    monkeypatch.setattr(wd, "check_ib",
                        lambda **k: (wd.Check(wd.CHECK_IB_CONNECT, ok=True),
                                     wd.Check(wd.CHECK_IB_ANSWERS, ok=True),
                                     wd.Check(wd.CHECK_MARKET_DATA, ok=True)))
    monkeypatch.setattr(wd, "check_disk",
                        lambda *a, **k: wd.Check(wd.CHECK_DISK, ok=True))

    # A Sunday evening, which is as shut as the market gets.
    sunday = datetime(2026, 9, 6, 21, 0, tzinfo=wd.EASTERN)
    checks = wd.run_checks(sunday, wd.Schedule())

    assert asked, "the time zone was not checked at all outside market hours"
    assert wd.CHECK_TIME_ZONE in checks
    assert checks[wd.CHECK_TIME_ZONE].ok


# ------------------------------------------- a Gateway that will not answer

# WHY THIS CHECK EXISTS. On 2026-09-07 IB Gateway lost its upstream connection
# to IBKR twice, at 22:35 Pacific the night before and again at 07:50 New York
# in the morning, both times when the MacBook went to sleep. Both times it kept
# running, kept port 4002 open and kept completing the login handshake, so
# gateway_process, gateway_port and ib_connect all reported ok all night while
# every reqPositions, account update and reqExecutions timed out. Nothing
# restarted it. A person did, at 04:12 and 09:48, and each restart fixed it
# instantly. See journal/gateway_reads_2026-09-07.md.

def test_a_gateway_that_never_answers_fails_and_is_restarted_exactly_once():
    actions, state = step(gateway_not_answering(), MID_MORNING, {"checks": {}})

    raised = alerts_in(actions)
    assert [a.check for a in raised] == [wd.CHECK_IB_ANSWERS]
    assert raised[0].level == "error"
    assert "lost its upstream connection" in raised[0].body
    assert "What to do" in raised[0].body

    started = restarts_in(actions)
    assert len(started) == 1, "a Gateway that cannot answer is a dead Gateway"
    assert started[0].check == wd.CHECK_IB_ANSWERS
    assert state["checks"][wd.CHECK_IB_ANSWERS]["restart_attempted"] is True


def test_a_gateway_that_answers_says_nothing_and_starts_nothing():
    actions, state = step(healthy(), MID_MORNING, {"checks": {}})
    assert actions == []
    assert state["checks"][wd.CHECK_IB_ANSWERS]["ok"] is True


def test_the_outage_only_ever_gets_one_restart_however_long_it_lasts():
    """The whole night of 2026-09-07 in one test, five minutes at a time."""
    state: dict = {"checks": {}}
    now = MID_MORNING
    restarts = 0
    alerts = 0
    for _ in range(72):                       # six hours of wake ups
        actions, state = step(gateway_not_answering(), now, state)
        restarts += len(restarts_in(actions))
        alerts += len(alerts_in(actions))
        now += timedelta(minutes=5)
    assert restarts == 1
    # The budget is unchanged: once when it breaks, then every thirty minutes.
    assert alerts == 1 + 11


def test_a_gateway_that_starts_answering_again_is_announced_once():
    _, state = step(gateway_not_answering(), MID_MORNING, {"checks": {}})
    actions, state = step(healthy(), MID_MORNING + timedelta(minutes=10), state)

    raised = alerts_in(actions)
    assert [a.check for a in raised] == [wd.CHECK_IB_ANSWERS]
    assert raised[0].level == "info"
    assert raised[0].title.startswith("Recovered")

    actions, _ = step(healthy(), MID_MORNING + timedelta(minutes=15), state)
    assert actions == []


def test_a_gateway_that_is_down_altogether_does_not_get_two_restarts():
    """ib_answers is skipped when there is nothing to ask on, so it adds nothing."""
    actions, _ = step(gateway_down(), MID_MORNING, {"checks": {}})
    started = restarts_in(actions)
    assert len(started) == 1
    assert started[0].check == wd.CHECK_GATEWAY_PROCESS, "the process check owns that one"


def test_the_new_check_is_in_the_reported_order_and_can_cause_a_restart():
    assert wd.CHECK_IB_ANSWERS in wd.CHECK_ORDER
    assert wd.CHECK_IB_ANSWERS in wd.WHAT_TO_DO
    assert wd.CHECK_IB_ANSWERS in wd.RESTART_CHECKS
    # Right after ib_connect, because it is the same connection asked twice.
    order = list(wd.CHECK_ORDER)
    assert order.index(wd.CHECK_IB_ANSWERS) == order.index(wd.CHECK_IB_CONNECT) + 1


def test_twenty_seconds_is_what_a_read_gets():
    assert wd.ANSWER_TIMEOUT_SECONDS == 20


class FakeIB:
    """The smallest IB Gateway that can be interesting.

    positions is either a list to hand back, or an exception to raise, which is
    what a Gateway with no upstream connection does once ib.RequestTimeout is
    set on it.
    """

    RequestTimeout = 0

    def __init__(self, positions):
        self.positions = positions
        self.asked = 0

    def reqPositions(self):
        self.asked += 1
        if isinstance(self.positions, BaseException):
            raise self.positions
        return self.positions


def test_a_read_that_never_comes_back_is_the_failure_we_went_looking_for():
    import asyncio

    check = wd._positions_answer(FakeIB(asyncio.TimeoutError()), timeout=20, codes=[])

    assert check.name == wd.CHECK_IB_ANSWERS
    assert not check.ok and not check.skipped
    assert check.detail == ("Gateway is logged in but IBKR is not answering "
                            "(positions request timed out after 20 s); it has "
                            "lost its upstream connection.")


def test_warning_two_one_one_zero_is_the_same_failure_said_out_loud():
    """Gateway sometimes admits it: 2110, connectivity to the server is broken."""
    check = wd._positions_answer(FakeIB([]), timeout=20,
                                 codes=[wd.CODE_UPSTREAM_BROKEN])

    assert not check.ok
    assert check.code == wd.CODE_UPSTREAM_BROKEN
    assert "lost its upstream connection" in check.detail


def test_a_blip_that_mended_itself_is_not_reported_as_broken():
    """2110 then 1102 is a connection that dropped and came back. Not news.

    The IBC log for 2026-09-06 holds exactly this pair, a loss at 15:40 and a
    restore three minutes later, so reading a lone 2110 would have paged Mo
    about a Gateway that was working.
    """
    check = wd._positions_answer(
        FakeIB(["one position"]), timeout=20,
        codes=[wd.CODE_UPSTREAM_BROKEN, wd.CODE_UPSTREAM_RESTORED])

    assert check.ok
    assert "answered a positions request" in check.detail


def test_a_connection_that_dropped_again_after_coming_back_is_broken():
    """Whichever of the pair IBKR said last is the state now."""
    check = wd._positions_answer(
        FakeIB([]), timeout=20,
        codes=[wd.CODE_UPSTREAM_BROKEN, wd.CODE_UPSTREAM_RESTORED,
               wd.CODE_UPSTREAM_BROKEN])

    assert not check.ok
    assert check.code == wd.CODE_UPSTREAM_BROKEN


def test_a_read_that_comes_back_passes_and_says_how_long_it_took():
    check = wd._positions_answer(FakeIB(["one position"]), timeout=20, codes=[])

    assert check.ok and not check.skipped
    assert "Gateway answered a positions request in" in check.detail
    assert "1 position." in check.detail


def test_an_empty_account_still_counts_as_an_answer():
    """No positions is a perfectly good answer. Silence is not."""
    check = wd._positions_answer(FakeIB([]), timeout=20, codes=[])
    assert check.ok
    assert "0 positions." in check.detail


# --------------------------------------- the fourth proof that a restart took

def test_a_gateway_that_comes_back_and_still_cannot_answer_is_not_a_restart():
    """The whole point. The outage of 2026-09-07 had all three local proofs."""
    outcome, _ = try_restart(ALL_THREE, answers=False)

    assert outcome.took is False
    assert (outcome.new_pid, outcome.fresh_login, outcome.port_open) == (True, True, True)
    assert outcome.answers is False
    assert "IBKR answering a read: no" in outcome.detail


def test_a_gateway_that_comes_back_and_answers_is_a_restart():
    outcome, _ = try_restart(ALL_THREE, answers=True)

    assert outcome.took is True
    assert outcome.answers is True
    assert "IBKR answering a read: yes" in outcome.detail


def test_the_read_is_not_even_asked_while_the_first_three_are_missing():
    """No point asking a Gateway that has not started whether it can answer."""
    asked: list[int] = []
    nothing = wd.GatewayProbe(pid=None, login_at=BEFORE_LOGIN, port_open=False)
    outcome = wd.restart_gateway(
        wait_seconds=10, poll_seconds=5,
        probe=FakeProbe(BEFORE, nothing), launcher=lambda: (FakeHandle(None), "starting"),
        sleep=lambda seconds: None,
        answering=lambda: asked.append(1) or True)

    assert outcome.took is False
    assert asked == [], "nothing was there to ask"
    assert outcome.answers is None
    assert "not asked" in outcome.detail


def test_the_did_not_take_message_carries_the_fourth_proof_too():
    outcome, _ = try_restart(ALL_THREE, answers=False)
    alert = wd.restart_did_not_take_alert(wd.CHECK_IB_ANSWERS, outcome)

    assert alert.level == "error"
    assert "IBKR answering a read: no" in alert.body
    assert "What to do" in alert.body


def test_a_stuck_gateway_is_stopped_before_a_new_one_is_started():
    """Two logins fighting over one session is worse than the hang it fixes."""
    order: list[str] = []
    outcome = wd.restart_gateway(
        wait_seconds=10, poll_seconds=5,
        probe=FakeProbe(BEFORE, ALL_THREE),
        launcher=lambda: order.append("start") or (FakeHandle(None), "starting"),
        sleep=lambda seconds: None, stop_first=True,
        stopper=lambda: order.append("stop") or (True, "the old Gateway was stopped"),
        answering=lambda: True)

    assert order == ["stop", "start"]
    assert outcome.took is True


def test_a_gateway_that_will_not_stop_is_never_started_on_top_of():
    outcome = wd.restart_gateway(
        wait_seconds=10, poll_seconds=5,
        probe=FakeProbe(BEFORE, ALL_THREE),
        launcher=lambda: (_ for _ in ()).throw(AssertionError("must not start")),
        sleep=lambda seconds: None, stop_first=True,
        stopper=lambda: (False, "stop_gateway.sh exited 1, the old Gateway is still there"),
        answering=lambda: True)

    assert outcome.took is False
    assert "still there" in outcome.detail
    assert "nothing was started" in outcome.detail


def test_nothing_is_stopped_when_there_is_no_gateway_to_stop():
    """A Gateway that is not running has nothing to stop, so the stop is skipped."""
    stopped: list[int] = []
    nothing_before = wd.GatewayProbe(pid=None, login_at=None, port_open=False)
    outcome = wd.restart_gateway(
        wait_seconds=10, poll_seconds=5,
        probe=FakeProbe(nothing_before, ALL_THREE),
        launcher=lambda: (FakeHandle(None), "starting"),
        sleep=lambda seconds: None, stop_first=True,
        stopper=lambda: stopped.append(1) or (True, "stopped"),
        answering=lambda: True)

    assert stopped == []
    assert outcome.took is True


def test_only_the_not_answering_path_stops_the_old_gateway_first(monkeypatch):
    """A Gateway that is down has nothing to stop; one that is up and stuck does."""
    catch_alerts(monkeypatch)
    asked: list[bool] = []
    monkeypatch.setattr(wd, "restart_gateway",
                        lambda *a, **k: asked.append(k.get("stop_first")) or
                        fake_outcome(True))

    wd.perform(wd.decide_actions(gateway_down(), MID_MORNING, {"checks": {}}),
               allow_restart=True)
    wd.perform(wd.decide_actions(gateway_not_answering(), MID_MORNING, {"checks": {}}),
               allow_restart=True)

    assert asked == [False, True]


# ------------------------------------------ not colliding with its own copy

# WHY. At 09:40 on 2026-09-07 the watchdog could not connect at all: "Error 326
# client id 250 already in use", because an earlier copy of itself was still
# hung on the Gateway that had stopped answering. That is a watchdog problem
# wearing a Gateway problem's clothes, and reporting it as ib_connect failing
# would have been the second wrong alert of the morning.

class FakeConnector:
    """An IB Gateway that refuses the ids in taken and accepts anything else."""

    def __init__(self, taken=(), how="code"):
        self.taken = set(taken)
        self.how = how
        self.tried: list[int] = []
        self.codes: list[int] = []

    def connect(self, host, port, clientId, timeout, readonly):
        self.tried.append(clientId)
        if clientId not in self.taken:
            return
        if self.how == "code":
            self.codes.append(wd.CODE_CLIENT_ID_IN_USE)
            raise ConnectionError("Peer closed connection.")
        raise ConnectionError(f"Peer closed connection. clientId {clientId} "
                              "already in use?")


def connect_with(taken=(), how="code"):
    fake = FakeConnector(taken, how)
    used, note, failures = wd._connect_read_only(fake, fake.codes, wd.CLIENT_ID)
    return fake, used, note, failures


def test_the_ordinary_run_uses_its_own_client_id_and_says_nothing_about_it():
    fake, used, note, failures = connect_with()

    assert used == wd.CLIENT_ID == 250
    assert fake.tried == [250]
    assert note == "" and failures == []


def test_error_three_two_six_falls_through_to_the_spare_id():
    fake, used, note, _ = connect_with(taken={wd.CLIENT_ID})

    assert used == wd.SPARE_CLIENT_IDS[0]
    assert fake.tried == [250, wd.SPARE_CLIENT_IDS[0]]
    assert "already in use" in note
    assert "earlier watchdog copy is still running" in note


def test_a_closed_socket_that_only_says_already_in_use_counts_too():
    """ib_async sometimes shows the collision as a dropped socket, not a code."""
    fake, used, note, _ = connect_with(taken={wd.CLIENT_ID}, how="message")

    assert used == wd.SPARE_CLIENT_IDS[0]
    assert "spare id" in note


def test_two_stuck_copies_still_leave_a_spare():
    fake, used, _note, _ = connect_with(
        taken={wd.CLIENT_ID, wd.SPARE_CLIENT_IDS[0]})

    assert used == wd.SPARE_CLIENT_IDS[1]
    assert fake.tried == [250, wd.SPARE_CLIENT_IDS[0], wd.SPARE_CLIENT_IDS[1]]


def test_a_refusal_that_is_not_a_collision_is_not_retried():
    """A Gateway that is genuinely not there is news, and one attempt says so."""
    class Refuses(FakeConnector):
        def connect(self, host, port, clientId, timeout, readonly):
            self.tried.append(clientId)
            raise ConnectionRefusedError("Connect call failed")

    fake = Refuses()
    used, note, failures = wd._connect_read_only(fake, fake.codes, wd.CLIENT_ID)

    assert used is None
    assert fake.tried == [250], "no point trying four ids on a Gateway that is not there"
    assert note == ""
    assert "Connect call failed" in failures[0]


def test_the_spare_ids_belong_to_nobody_else():
    assert wd.CLIENT_ID not in wd.SPARE_CLIENT_IDS
    # The ids in use across this project today. A spare must never be one.
    assert not set(wd.SPARE_CLIENT_IDS) & {99, 100, 201, 250, 251, 252, 260, 261, 282}
    assert len(set(wd.SPARE_CLIENT_IDS)) == len(wd.SPARE_CLIENT_IDS)


# ---------------------------------------------- the run cannot outlast itself

class FakeClock:
    """A clock that only moves when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def quiet_checks(monkeypatch, clock=None, cost=0.0):
    """Every real check replaced by an instant passing one, optionally costing time."""
    def cheap(name, result=None):
        def run(*args, **kwargs):
            if clock is not None:
                clock.advance(cost)
            return result or wd.Check(name, ok=True, detail="fine")
        return run

    monkeypatch.setattr(wd, "check_gateway_process", cheap(wd.CHECK_GATEWAY_PROCESS))
    monkeypatch.setattr(wd, "check_gateway_port", cheap(wd.CHECK_GATEWAY_PORT))
    monkeypatch.setattr(wd, "check_ib",
                        lambda **k: (wd.Check(wd.CHECK_IB_CONNECT, ok=True),
                                     wd.Check(wd.CHECK_IB_ANSWERS, ok=True),
                                     wd.Check(wd.CHECK_MARKET_DATA, ok=True)))
    monkeypatch.setattr(wd, "check_loop_tick", cheap(wd.CHECK_LOOP_TICK))
    monkeypatch.setattr(wd, "check_disk", cheap(wd.CHECK_DISK))
    monkeypatch.setattr(wd, "check_time_zone", cheap(wd.CHECK_TIME_ZONE))


def test_a_run_with_time_to_spare_asks_everything(monkeypatch):
    clock = FakeClock()
    quiet_checks(monkeypatch, clock, cost=1.0)

    checks = wd.run_checks(MID_MORNING, wd.Schedule(),
                           wd.Deadline(seconds=90, clock=clock))

    assert set(checks) == set(wd.CHECK_ORDER)
    assert not any(check.skipped for check in checks.values())


def test_a_check_that_hangs_does_not_hold_the_run_past_the_deadline(monkeypatch):
    """The first check eats the whole budget. The rest are skipped, not asked."""
    clock = FakeClock()
    quiet_checks(monkeypatch)
    asked: list[str] = []

    def hangs():
        asked.append(wd.CHECK_GATEWAY_PROCESS)
        clock.advance(400)                    # a check that went away for ages
        return wd.Check(wd.CHECK_GATEWAY_PROCESS, ok=True, detail="eventually")

    def never(*args, **kwargs):
        asked.append("something after it")
        return wd.Check(wd.CHECK_DISK, ok=True)

    monkeypatch.setattr(wd, "check_gateway_process", hangs)
    monkeypatch.setattr(wd, "check_disk", never)
    monkeypatch.setattr(wd, "check_ib",
                        lambda **k: asked.append("ib") or (None, None, None))

    checks = wd.run_checks(MID_MORNING, wd.Schedule(),
                           wd.Deadline(seconds=90, clock=clock))

    assert asked == [wd.CHECK_GATEWAY_PROCESS], "nothing after the hang was asked"
    assert set(checks) == set(wd.CHECK_ORDER), "the run still reports on all eight"
    assert checks[wd.CHECK_GATEWAY_PROCESS].ok
    for name in wd.CHECK_ORDER[1:]:
        assert checks[name].skipped, f"{name} should have been skipped"
        assert "ran out of time" in checks[name].detail


def test_a_run_that_ran_out_of_time_says_nothing_and_forgets_nothing_it_should(monkeypatch):
    """Skipped is nobody looked, so it raises no alert and starts no Gateway."""
    clock = FakeClock()
    quiet_checks(monkeypatch)
    monkeypatch.setattr(wd, "check_gateway_process",
                        lambda: clock.advance(400) or
                        wd.Check(wd.CHECK_GATEWAY_PROCESS, ok=True))

    checks = wd.run_checks(MID_MORNING, wd.Schedule(),
                           wd.Deadline(seconds=90, clock=clock))
    actions = wd.decide_actions(checks, MID_MORNING, {"checks": {}})

    assert actions == []


def test_ninety_seconds_is_the_budget_and_it_fits_inside_the_wake_up():
    assert wd.RUN_DEADLINE_SECONDS == 90
    # 90 for the checks, 60 to stop a stuck Gateway, 120 to prove the new one.
    # launchd wakes this every 300 seconds, and 270 is less than 300.
    total = (wd.RUN_DEADLINE_SECONDS + wd.STOP_TIMEOUT_SECONDS
             + wd.RESTART_VERIFY_SECONDS)
    assert total < 300


def test_the_deadline_reports_how_much_of_the_budget_went(monkeypatch):
    clock = FakeClock()
    deadline = wd.Deadline(seconds=90, clock=clock)
    assert not deadline.expired() and deadline.remaining() == 90

    clock.advance(30)
    assert deadline.remaining() == 60
    clock.advance(70)
    assert deadline.expired() and deadline.remaining() == 0

    skipped = deadline.out_of_time(wd.CHECK_DISK)
    assert skipped.skipped and skipped.ok
    assert "ran out of time after 100 seconds" in skipped.detail


# ------------------------------------------------ a closed Monday is closed

# WHY. 2026-09-07 is Labor Day. The market was shut all day, SPY quotes were
# delayed because there were no live quotes to have, and market_data reported a
# miss every five minutes from the open to the close. A holiday has to be as
# quiet as a Saturday.

LABOR_DAY = datetime(2026, 9, 7, 11, 0, tzinfo=wd.EASTERN)      # a Monday, shut


def holiday_schedule() -> wd.Schedule:
    return wd.Schedule(holidays=("2026-09-07", "2026-11-26", "2026-12-25"))


def test_a_market_holiday_is_not_a_trading_day():
    schedule = holiday_schedule()
    assert wd.is_trading_day(LABOR_DAY, schedule) is False
    assert wd.in_market_hours(LABOR_DAY, schedule) is False


def test_the_tuesday_after_the_holiday_is_a_trading_day():
    schedule = holiday_schedule()
    tuesday = datetime(2026, 9, 8, 11, 0, tzinfo=wd.EASTERN)
    assert wd.is_trading_day(tuesday, schedule) is True
    assert wd.in_market_hours(tuesday, schedule) is True


def test_a_holiday_at_eleven_in_the_morning_skips_the_quotes_and_the_heartbeat(monkeypatch):
    """The two checks that only make sense while the market is open."""
    asked: list[bool] = []
    monkeypatch.setattr(wd, "check_gateway_process",
                        lambda: wd.Check(wd.CHECK_GATEWAY_PROCESS, ok=True))
    monkeypatch.setattr(wd, "check_gateway_port",
                        lambda *a, **k: wd.Check(wd.CHECK_GATEWAY_PORT, ok=True))
    monkeypatch.setattr(wd, "check_disk", lambda *a, **k: wd.Check(wd.CHECK_DISK, ok=True))
    monkeypatch.setattr(wd, "check_time_zone",
                        lambda *a, **k: wd.Check(wd.CHECK_TIME_ZONE, ok=True))

    def fake_ib(port_ok, market_hours=True, **kwargs):
        asked.append(market_hours)
        return (wd.Check(wd.CHECK_IB_CONNECT, ok=True),
                wd.Check(wd.CHECK_IB_ANSWERS, ok=True),
                wd.Check(wd.CHECK_MARKET_DATA, ok=True, skipped=True,
                         detail="not checked, the market is shut"))

    monkeypatch.setattr(wd, "check_ib", fake_ib)
    checks = wd.run_checks(LABOR_DAY, holiday_schedule())

    assert asked == [False], "the quote feed was asked about as if the market were open"
    assert checks[wd.CHECK_MARKET_DATA].skipped
    assert checks[wd.CHECK_LOOP_TICK].skipped
    assert "market is shut" in checks[wd.CHECK_LOOP_TICK].detail
    # The Gateway checks still run. A holiday is no reason to stop watching it.
    assert not checks[wd.CHECK_GATEWAY_PROCESS].skipped
    assert not checks[wd.CHECK_IB_ANSWERS].skipped


def test_a_holiday_says_nothing_all_day():
    """The whole of Labor Day, five minutes at a time, in silence."""
    schedule = holiday_schedule()
    checks = healthy()
    checks[wd.CHECK_MARKET_DATA] = wd.Check(
        wd.CHECK_MARKET_DATA, ok=True, skipped=True,
        detail="not checked, the market is shut")
    checks[wd.CHECK_LOOP_TICK] = wd.Check(
        wd.CHECK_LOOP_TICK, ok=True, skipped=True,
        detail="not checked, the market is shut")

    state: dict = {"checks": {}}
    now = LABOR_DAY
    said = 0
    for _ in range(72):
        assert wd.in_market_hours(now, schedule) is False
        actions, state = step(checks, now, state)
        said += len(actions)
        now += timedelta(minutes=5)
    assert said == 0


def test_the_holidays_are_read_off_the_real_config_file():
    """Whatever config/guardrails.yaml says, the watchdog reads the same list."""
    schedule = wd.load_schedule()
    assert "2026-09-07" in schedule.holidays, (
        "Labor Day 2026 is missing from schedule.holidays in config/guardrails.yaml")
    assert all(isinstance(day, str) for day in schedule.holidays)


def test_a_read_that_fails_some_other_way_is_a_miss_without_a_diagnosis():
    """A read that raises is a read nobody got, but the cause is not ours to name."""
    check = wd._positions_answer(FakeIB(ConnectionError("Socket disconnect")),
                                 timeout=20, codes=[])

    assert not check.ok
    assert "Socket disconnect" in check.detail
    assert "lost its upstream connection" not in check.detail
