"""The thing that watches the trading plumbing and tells Mo when it breaks.

One run of this script is one health check. It looks at eight things, decides
what to do about what it found, and exits. launchd wakes it every five minutes
during market hours and once an hour the rest of the time. See
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/LAUNCHD.md

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py --once

What it checks
--------------

1. gateway_process  IB Gateway is actually running on this Mac.
2. gateway_port     Something is accepting connections on port 4002, the paper
                    port. A process with a closed port is a hung Gateway.
3. ib_connect       A read only connection gets through and the account it
                    reports is DUT077572, the paper account. Read only, so this
                    connection cannot place an order even by accident.
4. ib_answers       That same connection asks a real question, for the list of
                    positions, and gets an answer inside twenty seconds. A
                    Gateway that has lost its upstream connection to IBKR still
                    accepts logins and still hands over the account id, so the
                    first three checks all pass while nothing works. This is the
                    one that catches it. Added 2026-09-07 after two outages in
                    one day, both of them invisible to checks 1 to 3.
5. market_data      SPY quotes are real time rather than delayed. IBKR error
                    354 means the subscription is missing and we are on delayed
                    prices. Error 10197 means a competing live session: Mo has a
                    quote screen or the mobile app open on the live login and it
                    has taken the data feed. That one is never Gateway's fault,
                    so it never causes a restart.
6. loop_tick        The trading loop wrote a tick recently. Checked only during
                    market hours, and only when the loop's launchd job is
                    loaded, because a loop that was never switched on has no
                    heartbeat to miss.
7. disk_free        More than one gigabyte free. IB Gateway writes a lot of logs
                    and a full disk fails everything at once.
8. time_zone        The launchd jobs still fire at the right New York minute.

What it does about it
---------------------

The rules live in decide_actions(), which is a pure function: hand it the check
results, the time, and what it knew last run, and it hands back a list of
actions. It reads no files and sends nothing, which is why it can be tested
properly. The rules are:

* The first time a check misses, alert once.
* If that miss is IB Gateway being down, or Gateway being up and not answering,
  also schedule exactly one restart attempt through agent/start_gateway.sh. One
  attempt per outage, not one per wake up, and never a second Gateway on top of
  a running one: when a Gateway is sitting there useless, agent/stop_gateway.sh
  runs first and the start only follows once it is gone.
* A restart only counts once it has been proved. The start script exiting 0
  proves nothing, because that script becomes Gateway when it works. So the
  watchdog looks at Gateway before it starts anything, then watches for two
  minutes and wants all four of: a different process id, a "Login has
  completed" line in the IBC log newer than the one it saw before, port 4002
  accepting a connection, and a read that actually comes back. Anything less is
  a "restart did not take" message that says which of the four did and did not
  happen, and the attempt is not written down as an attempt.
* A check that keeps missing re-alerts at most every thirty minutes, so an
  outage over lunch is two or three messages rather than fifty.
* A check that comes back alerts once, at level info, so Mo knows it is over.
* Error 10197 never triggers a restart.

What it can never do
--------------------

Place an order, change an order, or cancel one. The only broker connection it
opens is read only, and the only thing it can start is IB Gateway itself.

How long a run can take
-----------------------

launchd wakes this every five minutes, so a run that hangs would be found still
going by the next one. Two bounds stop that. The checks share a ninety second
wall clock deadline: when it runs out, whatever has not been asked yet is
reported as skipped rather than asked, so the run always finishes and always
writes its line. A restart attempt sits outside that deadline on purpose, since
proving a restart takes two minutes by design, but it is bounded too: at most
sixty seconds stopping the old Gateway and a hundred and twenty proving the new
one. Ninety plus sixty plus a hundred and twenty is two hundred and seventy
seconds, still inside the five minute gap.

If an earlier copy is somehow still running, its API client id is still taken,
and connecting on a taken id gives IBKR error 326. That is not a broken Gateway
and must not be reported as one, so the watchdog moves to a spare id and says
in its own log that the previous copy has not finished. This is not
hypothetical: it happened at 09:40 on 2026-09-07.

Flags
-----

    --once               do one check and exit. This is the default and the
                         only mode; the flag exists so the launchd job says
                         plainly what it is asking for.
    --market-hours-only  do nothing outside 09:30 to 16:00 on a weekday.
    --no-restart         alert about a dead Gateway but do not start it.
    --dry-run            run the checks, print what would happen, change
                         nothing and send nothing.

Where it keeps its memory
-------------------------

/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/watchdog_state.json
holds one entry per check: whether it passed, when it started failing, when it
was last alerted about, and whether a restart has already been tried. Delete
that file and the next run treats everything as fresh.

A one line summary of every run is appended to
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/watchdog.log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402

# SQLite is the system of record (docs/DATA.md), so every look the watchdog
# takes lands in the watchdog_checks table as well as in output/watchdog.log.
# These pile up all day on purpose: the question worth asking of the watchdog is
# almost always "when did this start failing", and that needs the whole run of
# checks rather than the most recent verdict. Optional, because a database that
# cannot be opened is no reason to stop watching IB Gateway.
try:
    import db as db_module  # noqa: E402
except Exception:           # noqa: BLE001
    db_module = None        # type: ignore[assignment]
from paths import agent_dir, config_dir, output_dir, project_root  # noqa: E402
import timezone_check  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 4002          # IB Gateway paper. Live is 4001 and never belongs here.
PAPER_ACCOUNT = "DUT077572"

#: Our own API client id. Every program that talks to Gateway needs its own:
#: 99 is the smoke test, 100 is the MCP server, 201 is the scanner, 251 is the
#: pre-flight. This is 250.
CLIENT_ID = 250

#: Where to go when 250 is taken. IBKR answers a connection on an id another
#: session already holds with error 326, and the only copy that ever holds 250
#: is an earlier watchdog run that has not finished. That is a watchdog problem,
#: not a Gateway problem, so it must not be reported as one.
#:
#: The range is 2500 to 2502 on purpose: three is enough for the overlap of two
#: or three stuck runs, and four digits starting with 25 keeps them clearly the
#: watchdog's own while staying far away from every id in use today (99, 100,
#: 201, 250, 251, 252, 260, 261, 282). Nothing else in this project may take an
#: id in this range.
SPARE_CLIENT_IDS = (2500, 2501, 2502)

#: How long a read is given before the Gateway counts as not answering. Twenty
#: seconds. A healthy Gateway answers a positions request in well under a
#: tenth of a second, so this is not a tight bound, it is the difference
#: between slow and dead.
ANSWER_TIMEOUT_SECONDS = 20

#: The whole run of checks gets this long. See "How long a run can take" above.
RUN_DEADLINE_SECONDS = 90

#: Stopping a stuck Gateway before starting a new one. agent/stop_gateway.sh
#: waits thirty seconds on the IBC command port and fifteen more after a TERM,
#: so sixty is enough for the slow path and short enough to stay inside the
#: five minute gap between wake ups.
STOP_TIMEOUT_SECONDS = 60

#: The launchd job that runs the trading loop. Used only to tell "the loop is
#: late" apart from "the loop was never switched on".
TICK_JOB_LABEL = "com.mtalib.agentic-trading.tick"

#: Under this much free space, alert. One gigabyte.
DISK_FLOOR_BYTES = 1024 ** 3

#: How long a check has to keep failing before we say so again.
REALERT_AFTER = timedelta(minutes=30)

#: How long to give a restart before deciding it did not take. IB Gateway needs
#: the best part of a minute to start, log in and open its port, so two minutes
#: is generous without leaving the watchdog run hanging around forever.
RESTART_VERIFY_SECONDS = 120

#: How often to look while waiting for those two minutes.
RESTART_POLL_SECONDS = 5

#: IBC writes one line like this every time a login goes through:
#:     2026-09-06 11:42:11:200 IBC: Login has completed
#: That line, and its time, is the only proof we have that a fresh Gateway got
#: all the way in rather than sitting on a login prompt.
IBC_LOGIN_MARKER = "Login has completed"
IBC_LOG_GLOB = "ibc-*.txt"

#: IBKR message codes worth naming.
CODE_NO_SUBSCRIPTION = 354        # not subscribed, delayed prices only
CODE_NO_API_SUBSCRIPTION = 10089  # needs an extra subscription for the API
CODE_NOT_SUBSCRIBED = 10168       # not subscribed and delayed is not enabled either
CODE_COMPETING_SESSION = 10197    # a live login is holding the market data feed
CODE_CLIENT_ID_IN_USE = 326       # another session already has this client id
CODE_UPSTREAM_BROKEN = 2110       # "Connectivity between Trader Workstation and
                                  # server is broken." Gateway is logged in and
                                  # cut off from IBKR at the same time, which is
                                  # the exact state that fooled every check on
                                  # the night of 2026-09-06 into 2026-09-07.
CODE_UPSTREAM_RESTORED = 1102     # "Connectivity has been restored." The other
                                  # half of the pair, and the reason 2110 is not
                                  # read on its own: the IBC log for 2026-09-06
                                  # has a connectivity loss at 15:40 and this
                                  # three minutes later, and a blip that mended
                                  # itself must not page anybody.

#: The three codes that all mean the same thing: no real time quotes for us.
#: IBKR picks between them depending on what it was last asked for, so all three
#: are treated the same. All three were seen from this Gateway on 2026-09-06.
NOT_SUBSCRIBED_CODES = (CODE_NO_SUBSCRIPTION, CODE_NO_API_SUBSCRIPTION,
                        CODE_NOT_SUBSCRIBED)

#: IBC restarts IB Gateway by itself every night around 2 AM Eastern. A watchdog
#: that starts a second Gateway in the middle of that gives two logins fighting
#: over one session, so it keeps its hands off during this window.
IBC_NIGHTLY_RESTART = (clock_time(1, 45), clock_time(2, 30))

CHECK_GATEWAY_PROCESS = "gateway_process"
CHECK_GATEWAY_PORT = "gateway_port"
CHECK_IB_CONNECT = "ib_connect"
CHECK_IB_ANSWERS = "ib_answers"
CHECK_MARKET_DATA = "market_data"
CHECK_LOOP_TICK = "loop_tick"
CHECK_DISK = "disk_free"
CHECK_TIME_ZONE = "time_zone"

#: The order checks are reported and acted on in. Stable so that two runs with
#: the same problems produce the same actions in the same order.
CHECK_ORDER = (
    CHECK_GATEWAY_PROCESS,
    CHECK_GATEWAY_PORT,
    CHECK_IB_CONNECT,
    CHECK_IB_ANSWERS,
    CHECK_MARKET_DATA,
    CHECK_LOOP_TICK,
    CHECK_DISK,
    CHECK_TIME_ZONE,
)

#: Only a miss on one of these can lead to starting IB Gateway.
RESTART_CHECKS = (CHECK_GATEWAY_PROCESS, CHECK_GATEWAY_PORT, CHECK_IB_ANSWERS)

ACTION_ALERT = "alert"
ACTION_RESTART = "restart_gateway"

#: The one line of advice that goes out with each alert.
WHAT_TO_DO = {
    CHECK_GATEWAY_PROCESS: (
        "Start it with agent/start_gateway.sh and watch your phone, IBKR Mobile "
        "may ask you to approve the login."),
    CHECK_GATEWAY_PORT: (
        "If Gateway is on screen but the port is shut, it has hung. Stop it with "
        "agent/stop_gateway.sh, then start it with agent/start_gateway.sh."),
    CHECK_IB_CONNECT: (
        "Gateway is up but will not hand over the account. Check it is logged "
        "into the paper account and that the API is enabled on port 4002."),
    CHECK_IB_ANSWERS: (
        "Gateway is logged in and cut off from IBKR at the same time, so every "
        "read hangs. Nothing you do inside the Gateway window fixes this. Stop "
        "it with agent/stop_gateway.sh and start it with agent/start_gateway.sh; "
        "the watchdog is already trying that once itself."),
    CHECK_MARKET_DATA: (
        "The agent is pricing from stale or delayed quotes. Close any IBKR quote "
        "screen, Client Portal watchlist or mobile app on the live login, or "
        "check the market data subscription in Client Portal."),
    CHECK_LOOP_TICK: (
        "The trading loop has stopped waking up. Check "
        "output/tick_YYYY-MM-DD.log and whether the launchd job is still loaded."),
    CHECK_DISK: (
        "Free some space. IB Gateway's own logs under output/ibc_logs are "
        "usually the biggest thing there."),
    CHECK_TIME_ZONE: (
        "Every launchd job fires at the wrong minute until they are written "
        "again for this Mac's zone. One command fixes it and reloads them: "
        "python3 scripts/gen_launchd.py --install"),
}


# ------------------------------------------------------------- the small types

@dataclass(frozen=True)
class Check:
    """What one health check found.

    ok       True when the thing is fine.
    detail   One sentence a person can read at 09:35 in the morning.
    code     The IBKR message code when there was one, otherwise None.
    level    What level to alert at when this check misses. Warn for things that
             are not broken machinery, error for things that are.
    skipped  True when the check does not apply right now, which is neither a
             pass nor a miss. A skipped check is ignored entirely: it raises no
             alert and it clears whatever the last run remembered about it.
    """
    name: str
    ok: bool
    detail: str = ""
    code: int | None = None
    level: str = "error"
    skipped: bool = False


@dataclass(frozen=True)
class Action:
    """One thing the watchdog has decided to do."""
    kind: str                  # ACTION_ALERT or ACTION_RESTART
    check: str                 # which check led to it
    level: str = "info"
    title: str = ""
    body: str = ""


@dataclass(frozen=True)
class GatewayProbe:
    """One look at IB Gateway. Taken twice: once before a restart, once after.

    pid        the process id IBC is running under, or None when nothing is.
    login_at   the time of the newest "Login has completed" line in the IBC log.
    port_open  whether anything accepts a connection on the paper API port.
    """
    pid: str | None = None
    login_at: datetime | None = None
    port_open: bool = False


@dataclass(frozen=True)
class RestartOutcome:
    """Whether a restart really happened, and the evidence either way.

    took            every proof came back. Only this counts as a restart.
    new_pid         the process id changed.
    fresh_login     the IBC log has a newer login than before the restart.
    port_open       port 4002 is accepting connections again.
    answers         a read came back from the new Gateway. None means the
                    question was never reached, because one of the first three
                    had already failed and there was nothing worth asking.
    detail          the lines a person reads to see what did not happen.
    waited_seconds  how long we watched before giving up or being satisfied.
    """
    took: bool
    new_pid: bool
    fresh_login: bool
    port_open: bool
    detail: str
    waited_seconds: int = 0
    answers: bool | None = None


@dataclass
class Schedule:
    """When the market is open, and how often the loop is meant to wake up.

    holidays is the days the US market is shut that are not weekends, held as
    plain "YYYY-MM-DD" strings exactly as config/guardrails.yaml writes them,
    the same way agent/deadman.py holds them.
    """
    open_at: clock_time = clock_time(9, 30)
    close_at: clock_time = clock_time(16, 0)
    holidays: tuple = ()
    loop_minutes: int = 5

    @property
    def stale_after(self) -> timedelta:
        """Two loop intervals. Past this, the loop's heartbeat counts as missed."""
        return timedelta(minutes=2 * self.loop_minutes)


class Deadline:
    """A wall clock budget for one run of the checks.

    launchd wakes the watchdog every five minutes, so a check that hangs would
    leave the last run still going when the next one arrives, and by 09:40 on
    2026-09-07 that had already happened: a stuck copy still held client id 250
    and the fresh copy could not connect at all.

    Every check is bounded on its own, but bounded things add up, so the run
    carries this as well. Before each remaining check the run asks whether there
    is time left; when there is not, the rest are reported as skipped rather
    than asked. Skipped is the honest answer: nobody looked. It raises no alert
    and clears nothing that was known, so a run that ran out of time is quiet
    rather than wrong.

    clock is swappable so tests can make time pass without waiting for it.
    """

    def __init__(self, seconds: float = RUN_DEADLINE_SECONDS, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self.started = clock()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed())

    def expired(self) -> bool:
        return self.remaining() <= 0

    def out_of_time(self, name: str) -> Check:
        """The skipped Check to report for something there was no time to ask."""
        return Check(name, ok=True, skipped=True,
                     detail=(f"not checked, the run ran out of time after "
                             f"{self.elapsed():.0f} seconds of its "
                             f"{self.seconds:.0f} second budget"))


# ------------------------------------------------------------------- settings

def _parse_clock(text, fallback: clock_time) -> clock_time:
    try:
        hours, _, minutes = str(text).partition(":")
        return clock_time(int(hours), int(minutes))
    except (TypeError, ValueError):
        return fallback


def load_schedule() -> Schedule:
    """Market hours from config/guardrails.yaml, with sane values if it is unreadable.

    Read with a plain YAML load rather than by importing agent/guardrails.py, so
    that a watchdog run cannot be broken by work in progress on the guardrails.
    """
    default = Schedule()
    try:
        import yaml
        raw = yaml.safe_load((config_dir() / "guardrails.yaml").read_text(encoding="utf-8"))
        block = (raw or {}).get("schedule") or {}
    except Exception:                                             # noqa: BLE001
        return default
    return Schedule(
        open_at=_parse_clock(block.get("scan_start"), default.open_at),
        close_at=_parse_clock(block.get("market_close"), default.close_at),
        holidays=tuple(str(day) for day in (block.get("holidays") or [])),
        loop_minutes=int(block.get("loop_minutes") or default.loop_minutes),
    )


def is_trading_day(now: datetime, schedule: Schedule) -> bool:
    """True when the US market trades on the day this moment falls on.

    A weekday that is not one of the days named in schedule.holidays. Read
    straight off the schedule rather than by importing agent/guardrails.py, for
    the same reason load_schedule() reads the YAML itself: a watchdog run must
    not be breakable by work in progress on the guardrails. agent/guardrails.py
    answers the same question with is_trading_date() for everything that does
    hold a Guardrails object.

    Why it exists: on 2026-09-07, Labor Day, the market_data check reported a
    miss every five minutes all day because the market was shut and the quotes
    were delayed. A closed Monday has to be as quiet as a Saturday.
    """
    if now.weekday() >= 5:
        return False
    return f"{now.date():%Y-%m-%d}" not in (schedule.holidays or ())


def in_market_hours(now: datetime, schedule: Schedule) -> bool:
    """True on a trading day between the open and the close."""
    if not is_trading_day(now, schedule):
        return False
    return schedule.open_at <= now.time() < schedule.close_at


def state_path() -> Path:
    return output_dir() / "watchdog_state.json"


def load_state() -> dict:
    """What the last run knew. An unreadable file is treated as a fresh start."""
    try:
        loaded = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"checks": {}}
    if not isinstance(loaded, dict):
        return {"checks": {}}
    loaded.setdefault("checks", {})
    return loaded


def save_state(state: dict) -> None:
    state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _read_time(text) -> datetime | None:
    """Read one of our own ISO timestamps back. None when it is missing or junk."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=EASTERN)


# ------------------------------------------------------------ the actual rules

def _as_check(name: str, value) -> Check:
    """Accept either a Check or a plain dict, so tests can use whichever is clearer."""
    if isinstance(value, Check):
        return value
    data = dict(value or {})
    data.pop("name", None)
    return Check(name=name, **data)


def _may_restart(check: Check, checks: dict[str, Check]) -> bool:
    """Whether this miss is the kind that starting IB Gateway would fix.

    Two ways in, and they are not the same shape.

    ib_answers is the straightforward one. A Gateway that is logged in and not
    answering is dead machinery whatever its process list says, and the only
    thing that has ever fixed it is a stop and a start. So it is allowed on its
    own. restart_gateway() stops the old copy first in that case, which is why
    this can say yes to a Gateway that is running.

    gateway_process and gateway_port are the older way in, and they still want
    no Gateway process running at all. Starting a second Gateway on top of a
    running one gives two logins fighting over the same session, which is worse
    than the hang it was meant to fix, and a port that is shut on a process that
    is up tells us nothing about whether that process is mid-start or wedged.
    That one stays a decision for a person.

    Either way, message code 10197 is never a reason. It means Mo's own quote
    screen has the data feed and Gateway is perfectly healthy.
    """
    if check.name not in RESTART_CHECKS:
        return False
    if check.code == CODE_COMPETING_SESSION:
        return False
    if check.name == CHECK_IB_ANSWERS:
        return True
    process = checks.get(CHECK_GATEWAY_PROCESS)
    return process is not None and not process.ok and not process.skipped


def in_nightly_restart_window(now: datetime) -> bool:
    """True during IBC's own 2 AM restart, when we must not start a second Gateway."""
    start, end = IBC_NIGHTLY_RESTART
    return start <= now.time() < end


def _stamp(moment: datetime | None) -> str:
    return "never" if moment is None else f"{moment:%Y-%m-%d %H:%M:%S}"


def judge_restart(before: GatewayProbe, after: GatewayProbe,
                  launch_exit: int | None = None,
                  waited_seconds: int = 0,
                  answers: bool | None = None) -> RestartOutcome:
    """Did the restart actually take? Pure: it only reads its arguments.

    Four proofs, and all of them have to be there, because each one on its own
    can lie:

    * a different process id. The same process id back again does not mean
      Gateway restarted, it means we are looking at the Gateway that was
      already sitting there.
    * a login in the IBC log newer than the one taken before the restart. A
      process can start, fail its login and sit on the prompt for hours, so a
      new process id on its own is not a Gateway anyone can trade through.
    * port 4002 accepting a connection. Logged in but not listening is exactly
      the hang this watchdog exists to catch.
    * a read that comes back. Added 2026-09-07, because the outage that day had
      all of the first three and still could not answer a single request: the
      process was new, the login was fresh, the port was open, and IBKR was not
      there. The first three are all local; this is the only one that proves
      anything about the other end.

    answers is None when nobody asked, which is what happens when one of the
    first three had already failed and there was no point. That is not counted
    against the restart, it just is not counted for it either.

    The start script's exit code short circuits the lot. agent/start_gateway.sh
    becomes Gateway when it works and never returns, so any exit code at all
    means it gave up first, usually a missing credentials file or a Gateway
    version that is not installed.
    """
    if launch_exit is not None and launch_exit != 0:
        return RestartOutcome(
            took=False, new_pid=False, fresh_login=False, port_open=False,
            waited_seconds=waited_seconds,
            detail=(f"  the start script exited with code {launch_exit} instead of "
                    "becoming IB Gateway, so nothing was started"))

    new_pid = bool(after.pid) and after.pid != before.pid
    fresh_login = after.login_at is not None and (
        before.login_at is None or after.login_at > before.login_at)
    port_open = bool(after.port_open)

    yes_no = {True: "yes", False: "no"}
    lines = [
        f"  a different process id: {yes_no[new_pid]} "
        f"(was {before.pid or 'nothing running'}, now {after.pid or 'nothing running'})",
        f"  a newer login in the IBC log: {yes_no[fresh_login]} "
        f"(was {_stamp(before.login_at)}, now {_stamp(after.login_at)})",
        f"  port {GATEWAY_PORT} accepting connections: {yes_no[port_open]}",
    ]
    if answers is None:
        lines.append("  IBKR answering a read: not asked, "
                     "one of the first three had already failed")
    else:
        lines.append(f"  IBKR answering a read: {yes_no[bool(answers)]}")

    return RestartOutcome(took=new_pid and fresh_login and port_open
                          and answers is not False,
                          new_pid=new_pid, fresh_login=fresh_login,
                          port_open=port_open, answers=answers,
                          detail="\n".join(lines),
                          waited_seconds=waited_seconds)


def restart_did_not_take_alert(check: str, outcome: RestartOutcome) -> Action:
    """The message for a restart that was tried and cannot be confirmed. Pure."""
    return Action(
        kind=ACTION_ALERT, check=check, level="error",
        title="Watchdog: restart did not take",
        body=("IB Gateway was started but the restart cannot be confirmed. Here is "
              f"what was and was not seen in the {outcome.waited_seconds} seconds "
              "after it was started:\n\n"
              f"{outcome.detail}\n\n"
              "All of them have to be true before this counts as a restart, so it "
              "is not being written down as one.\n\n"
              "What to do: run agent/start_gateway.sh yourself and watch the Gateway "
              "window. IBKR Mobile may be waiting for you to approve the login. "
              "output/gateway_launch.log and output/ibc_logs hold what happened."))


def _restart_already_tried(state: dict) -> bool:
    """True when this outage has already had its one restart attempt."""
    for name in RESTART_CHECKS:
        entry = (state.get("checks") or {}).get(name) or {}
        if entry.get("restart_attempted") and not entry.get("ok", True):
            return True
    return False


def decide_actions(checks: dict, now: datetime, state: dict) -> list[Action]:
    """Work out what to do. Pure: no files, no network, no clock of its own.

    checks is {check name: Check} (a plain dict per check works too), now is the
    time, state is what load_state() returned last run. The answer is a list of
    Actions for the caller to carry out, or to print and ignore in a dry run.
    """
    remembered = state.get("checks") or {}
    actions: list[Action] = []
    restart_scheduled = False
    already_tried = _restart_already_tried(state)

    names = [name for name in CHECK_ORDER if name in checks]
    names += sorted(name for name in checks if name not in CHECK_ORDER)

    normalised = {name: _as_check(name, checks[name]) for name in names}

    for name in names:
        check = normalised[name]
        if check.skipped:
            continue

        previous = remembered.get(name) or {}
        was_failing = bool(previous) and not previous.get("ok", True)

        if check.ok:
            if was_failing:
                actions.append(Action(
                    kind=ACTION_ALERT, check=name, level="info",
                    title=f"Recovered: {name}",
                    body=check.detail or "This check is passing again."))
            continue

        advice = WHAT_TO_DO.get(name, "")
        body = check.detail or "This check failed."
        if advice:
            body = f"{body}\n\nWhat to do: {advice}"

        if not was_failing:
            actions.append(Action(
                kind=ACTION_ALERT, check=name, level=check.level,
                title=f"Watchdog: {name} failed", body=body))
            if (not restart_scheduled and not already_tried
                    and not in_nightly_restart_window(now)
                    and _may_restart(check, normalised)):
                restart_scheduled = True
                actions.append(Action(
                    kind=ACTION_RESTART, check=name, level="info",
                    title="Starting IB Gateway",
                    body="One restart attempt, through agent/start_gateway.sh."))
            continue

        # Still failing. Say so again, but not more than every thirty minutes.
        last_alert = _read_time(previous.get("last_alert_at"))
        if last_alert is None or now - last_alert >= REALERT_AFTER:
            since = previous.get("failing_since") or "some time ago"
            actions.append(Action(
                kind=ACTION_ALERT, check=name, level=check.level,
                title=f"Watchdog: {name} is still failing",
                body=f"{body}\n\nFailing since {since}."))

    return actions


def update_state(checks: dict, now: datetime, state: dict,
                 actions: list[Action]) -> dict:
    """The state to save after those actions were carried out. Pure as well.

    Kept separate from decide_actions so the rules can be read without the
    bookkeeping around them, and so a dry run can decide without recording.
    """
    remembered = dict(state.get("checks") or {})
    stamp = now.isoformat()

    alerted = {action.check for action in actions if action.kind == ACTION_ALERT}
    restarted = {action.check for action in actions if action.kind == ACTION_RESTART}

    for name, raw in checks.items():
        check = _as_check(name, raw)
        if check.skipped:
            # Not applicable right now, so forget what we knew. That way a
            # heartbeat that was failing at the close does not produce a
            # "recovered" message at the open the next morning.
            remembered.pop(name, None)
            continue

        previous = remembered.get(name) or {}
        was_failing = bool(previous) and not previous.get("ok", True)

        if check.ok:
            remembered[name] = {
                "ok": True,
                "detail": check.detail,
                "checked_at": stamp,
            }
            continue

        remembered[name] = {
            "ok": False,
            "detail": check.detail,
            "code": check.code,
            "checked_at": stamp,
            "failing_since": previous.get("failing_since") if was_failing else stamp,
            "last_alert_at": stamp if name in alerted else previous.get("last_alert_at"),
            "restart_attempted": bool(previous.get("restart_attempted")) or name in restarted,
        }

    return {"checks": remembered, "updated_at": stamp}


# --------------------------------------------------------------- the checks

def _pgrep_ibc() -> tuple[list[str], str | None]:
    """Ask which IB Gateway processes are running.

    IBC is what starts Gateway, so the thing to look for is IBC's own class
    name. Returns the process ids it found and, separately, a message when the
    question itself could not be asked, which is not the same as "none running".
    """
    try:
        finished = subprocess.run(["pgrep", "-f", "ibcalpha.ibc"],
                                  capture_output=True, text=True, timeout=10)
    except Exception as exc:                                      # noqa: BLE001
        return [], f"could not ask which processes are running: {exc}"
    return [line for line in finished.stdout.split() if line.strip()], None


def gateway_pid() -> str | None:
    """The process id IB Gateway is running under, or None when it is not."""
    pids, _error = _pgrep_ibc()
    return pids[0] if pids else None


def check_gateway_process() -> Check:
    """Is IB Gateway running?"""
    pids, error = _pgrep_ibc()
    if error:
        return Check(CHECK_GATEWAY_PROCESS, ok=False, detail=error)
    if pids:
        return Check(CHECK_GATEWAY_PROCESS, ok=True,
                     detail=f"IB Gateway is running, process {pids[0]}.")
    return Check(CHECK_GATEWAY_PROCESS, ok=False,
                 detail="No IB Gateway process is running on this Mac.")


def port_is_open(host: str = GATEWAY_HOST, port: int = GATEWAY_PORT,
                 timeout: int = 3) -> tuple[bool, str]:
    """Does anything accept a connection on that port, and if not, why not?

    This is as read only as a check can be: the socket is opened and closed
    again without a single byte being sent, so it cannot ask Gateway for
    anything, let alone tell it to do anything.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, str(exc)


def check_gateway_port(host: str = GATEWAY_HOST, port: int = GATEWAY_PORT) -> Check:
    """Is anything accepting connections on the paper API port?"""
    open_now, why = port_is_open(host, port)
    if not open_now:
        return Check(CHECK_GATEWAY_PORT, ok=False,
                     detail=f"Nothing is accepting connections on {host}:{port} ({why}).")
    return Check(CHECK_GATEWAY_PORT, ok=True,
                 detail=f"{host}:{port} is accepting connections.")


def ibc_log_dir() -> Path:
    return output_dir() / "ibc_logs"


def _parse_ibc_time(line: str) -> datetime | None:
    """Read the timestamp off the front of an IBC log line.

    The lines look like this, with the milliseconds hung on the end of the time
    with another colon rather than a full stop:

        2026-09-06 11:42:11:200 IBC: Login has completed
    """
    parts = line.split()
    if len(parts) < 2:
        return None
    bits = parts[1].split(":")
    if len(bits) < 3:
        return None
    try:
        moment = datetime.strptime(f"{parts[0]} {bits[0]}:{bits[1]}:{bits[2]}",
                                   "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return moment.replace(tzinfo=EASTERN)


def newest_ibc_login(log_dir: Path | None = None) -> datetime | None:
    """When IBC last finished a login, read from the newest IBC log file.

    IBC names its log files after the day of the week, so a Gateway started
    just after midnight writes into a different file from the one that was
    being written a minute earlier. Picking the newest file by when it was last
    written, rather than by the name that looks right, survives that.
    """
    folder = log_dir or ibc_log_dir()
    try:
        logs = sorted(folder.glob(IBC_LOG_GLOB), key=lambda path: path.stat().st_mtime)
    except OSError:
        return None
    if not logs:
        return None
    try:
        lines = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if IBC_LOGIN_MARKER not in line:
            continue
        moment = _parse_ibc_time(line)
        if moment is not None:
            return moment
    return None


def probe_gateway() -> GatewayProbe:
    """One look at IB Gateway: which process, when it logged in, is the port up.

    This is the only part of the restart check that touches the machine, which
    is what lets judge_restart() below be a pure function that tests can feed
    made up answers to.
    """
    return GatewayProbe(pid=gateway_pid(), login_at=newest_ibc_login(),
                        port_open=port_is_open()[0])


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(float(value))


def _connect_read_only(ib, codes: list[int], client_id: int = CLIENT_ID,
                       spares=SPARE_CLIENT_IDS):
    """Get a read only session, moving off our own client id if it is taken.

    Returns (client_id used, note, failures). A client_id of None means no id
    worked and failures says what each one said. The note is empty on the
    ordinary path and says which spare was used, and why, when it was not.

    IBKR answers a connection on an id that another session already holds with
    error 326, and ib_async may show it either as that code on the error event
    or as a closed socket whose message mentions the id. Both are checked,
    because at 09:40 on 2026-09-07 this run saw the code and the message.

    The only thing that ever holds client id 250 is an earlier watchdog that has
    not finished, so this is never news about IB Gateway and must never be
    reported as ib_connect failing. Moving to a spare gets the run its answers
    and leaves a line saying the other copy is still there.
    """
    failures: list[str] = []
    for index, candidate in enumerate((client_id, *spares)):
        before = len(codes)
        try:
            ib.connect(GATEWAY_HOST, GATEWAY_PORT, clientId=candidate,
                       timeout=15, readonly=True)
        except Exception as exc:                                  # noqa: BLE001
            failures.append(f"client id {candidate}: {exc}")
            taken = (CODE_CLIENT_ID_IN_USE in codes[before:]
                     or "already in use" in str(exc).lower())
            if not taken:
                return None, "", failures
            continue
        if index == 0:
            return candidate, "", failures
        return candidate, (
            f" Client id {client_id} was already in use, so an earlier watchdog "
            f"copy is still running and this one moved to the spare id "
            f"{candidate}."), failures
    return None, "", failures


def _positions_answer(ib, timeout: int = ANSWER_TIMEOUT_SECONDS,
                      codes: list[int] | None = None) -> Check:
    """Ask the open connection a real question and hold it to twenty seconds.

    This is the check that the outages of 2026-09-07 needed and did not have.
    Gateway kept its port open and its login all night while its own upstream
    connection to IBKR was gone, so the handshake proved nothing: every
    reqPositions, account update and reqExecutions simply never came back.

    Asking again after connecting is not the waste it looks. ib_async asks for
    the positions itself while connecting, but it logs a timeout there and
    carries on, because raiseSyncErrors is off by default. That swallowed
    timeout is precisely why ib_connect reported ok all night. The answer has to
    be asked for by something that treats not getting one as a failure.

    Two ways to fail, and they are the same illness:

    * the request does not answer inside the bound. ib_async raises through
      asyncio.wait_for once ib.RequestTimeout is set on the connection, which
      on Python 3.11 and later is the builtin TimeoutError; both names are
      caught below because they are the same class.
    * IBKR says warning 2110, "Connectivity between Trader Workstation and
      server is broken", which is Gateway admitting it up front. That one
      arrives with the handshake rather than with the read, which is why every
      message seen on this connection counts and not only the ones that turned
      up while the read was outstanding. The list is made fresh per connection,
      so there is nothing stale in it.

      2110 is read together with its opposite, 1102, "connectivity has been
      restored". Whichever of the two IBKR said last is the state now. Without
      that, a blip that mended itself in three minutes would page Mo, and the
      IBC log for 2026-09-06 has exactly such a pair in it.
    """
    seen = codes if codes is not None else []
    started = time.monotonic()
    try:
        positions = ib.reqPositions()
    except Exception as exc:                                      # noqa: BLE001
        took = time.monotonic() - started
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return Check(CHECK_IB_ANSWERS, ok=False,
                         detail=("Gateway is logged in but IBKR is not answering "
                                 f"(positions request timed out after {timeout} s); "
                                 "it has lost its upstream connection."))
        # Something else went wrong. Still a miss, because a read that raises is
        # a read nobody got, but the cause is not ours to name.
        return Check(CHECK_IB_ANSWERS, ok=False,
                     detail=("Gateway is logged in and the positions request "
                             f"failed after {took:.0f} s: {exc}"))
    took = time.monotonic() - started

    upstream = [c for c in seen
                if c in (CODE_UPSTREAM_BROKEN, CODE_UPSTREAM_RESTORED)]
    if upstream and upstream[-1] == CODE_UPSTREAM_BROKEN:
        return Check(CHECK_IB_ANSWERS, ok=False, code=CODE_UPSTREAM_BROKEN,
                     detail=("Gateway is logged in but IBKR is not answering "
                             f"(IBKR warning {CODE_UPSTREAM_BROKEN}, connectivity "
                             "between Trader Workstation and server is broken); "
                             "it has lost its upstream connection."))

    held = len(list(positions or []))
    return Check(CHECK_IB_ANSWERS, ok=True,
                 detail=(f"Gateway answered a positions request in {took:.2f} s, "
                         f"{held} position{'' if held == 1 else 's'}."))


def check_ib(port_ok: bool, market_hours: bool = True,
             client_id: int = CLIENT_ID,
             ask_answers: bool = True) -> tuple[Check, Check, Check]:
    """One read only connection, three answers: the login, a read, the quotes.

    readonly=True on purpose. A read only API session cannot place, change or
    cancel an order, so the watchdog cannot touch the account even if something
    in it went badly wrong.

    The read is only asked once the login came back with the right account,
    because there is nothing to ask on otherwise, and the quote half is only
    asked while the market is open. Nothing is trading at nine in the evening,
    so "no bid came back" would mean nothing then, and the watchdog would spend
    every night saying so.
    """
    skipped_data = Check(CHECK_MARKET_DATA, ok=True, skipped=True,
                         detail="not checked, there was no connection to ask on")
    skipped_answers = Check(CHECK_IB_ANSWERS, ok=True, skipped=True,
                            detail="not checked, there was no connection to ask on")
    if not port_ok:
        return (Check(CHECK_IB_CONNECT, ok=True, skipped=True,
                      detail="not checked, the port is shut"),
                Check(CHECK_IB_ANSWERS, ok=True, skipped=True,
                      detail="not checked, the port is shut"),
                skipped_data)

    try:
        from ib_async import IB, Stock
    except Exception as exc:                                      # noqa: BLE001
        return (Check(CHECK_IB_CONNECT, ok=False,
                      detail=f"ib_async will not import: {exc}"),
                skipped_answers, skipped_data)

    codes: list[int] = []
    ib = IB()
    ib.errorEvent += lambda reqId, code, msg, *rest: codes.append(code)
    try:
        used, note, failures = _connect_read_only(ib, codes, client_id)
        if used is None:
            return (Check(CHECK_IB_CONNECT, ok=False,
                          detail="Could not connect to IB Gateway: "
                                 + "; ".join(failures)),
                    skipped_answers, skipped_data)

        # Set only once the connection is up, so it bounds the reads below and
        # nothing else. ib_async runs connect through the same timeout, and the
        # connect already carries its own fifteen second bound, so setting this
        # first would wrap a fifteen second thing in a twenty second thing and
        # turn a slow login into an ib_connect failure.
        ib.RequestTimeout = ANSWER_TIMEOUT_SECONDS

        accounts = list(ib.managedAccounts() or [])
        if PAPER_ACCOUNT not in accounts:
            return (Check(CHECK_IB_CONNECT, ok=False,
                          detail=(f"Gateway answered with accounts {accounts or 'none'}, "
                                  f"not the paper account {PAPER_ACCOUNT}.")),
                    skipped_answers, skipped_data)
        connect = Check(CHECK_IB_CONNECT, ok=True,
                        detail=f"Connected read only, account {PAPER_ACCOUNT}.{note}")

        answers = (_positions_answer(ib, ANSWER_TIMEOUT_SECONDS, codes)
                   if ask_answers else
                   Check(CHECK_IB_ANSWERS, ok=True, skipped=True,
                         detail="not asked for on this connection"))

        if not market_hours:
            return connect, answers, Check(
                CHECK_MARKET_DATA, ok=True, skipped=True,
                detail="not checked, the market is shut")

        spy = Stock("SPY", "SMART", "USD")
        try:
            ib.qualifyContracts(spy)
            ib.reqMarketDataType(1)      # 1 is real time. 3 would be delayed.
            ticker = ib.reqMktData(spy, "", True, False)
            ib.sleep(5)
            bid, ask = ticker.bid, ticker.ask
            ib.cancelMktData(spy)
        except Exception as exc:                                  # noqa: BLE001
            return connect, answers, Check(
                CHECK_MARKET_DATA, ok=False,
                detail=f"Asking for a SPY quote failed: {exc}")

        if CODE_COMPETING_SESSION in codes:
            return connect, answers, Check(
                CHECK_MARKET_DATA, ok=False, code=CODE_COMPETING_SESSION, level="warn",
                detail=("Competing live session: Mo has a live quote screen or the IBKR "
                        "app open and it is holding the market data feed. Close it."))
        subscription_problem = next((c for c in codes if c in NOT_SUBSCRIBED_CODES), None)
        if subscription_problem is not None:
            return connect, answers, Check(
                CHECK_MARKET_DATA, ok=False, code=subscription_problem, level="warn",
                detail=(f"IBKR message {subscription_problem}: not subscribed to real "
                        "time data for the API, so SPY is on delayed prices only."))
        if _is_number(bid) and _is_number(ask):
            return connect, answers, Check(
                CHECK_MARKET_DATA, ok=True,
                detail=f"SPY real time quote, bid {bid} ask {ask}.")
        return connect, answers, Check(
            CHECK_MARKET_DATA, ok=False, level="warn",
            detail=("Asked for a real time SPY quote and no bid or ask came back "
                    f"within five seconds. Gateway messages: {sorted(set(codes)) or 'none'}."))
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:                                         # noqa: BLE001
            pass


def check_ib_and_market_data(port_ok: bool, market_hours: bool = True,
                             client_id: int = CLIENT_ID) -> tuple[Check, Check]:
    """The login and the quote feed, without the read in between.

    Kept because agent/preflight.py asks for exactly these two and nothing else.
    The pre-flight runs at 09:00 with its own timings to keep, so it is not made
    to sit through a twenty second read it never asked for.
    """
    connect, _answers, data = check_ib(port_ok, market_hours=market_hours,
                                       client_id=client_id, ask_answers=False)
    return connect, data


def ask_ib_answers(client_id: int = CLIENT_ID) -> Check:
    """Open a read only connection of our own and ask the one bounded question.

    Used as the fourth proof that a restart took: a Gateway that came back with
    a new process id, a fresh login and an open port, and still cannot answer a
    read, has not come back at all.
    """
    connect, answers, _data = check_ib(port_ok=True, market_hours=False,
                                       client_id=client_id)
    if connect.skipped or not connect.ok:
        return Check(CHECK_IB_ANSWERS, ok=False,
                     detail=f"could not ask: {connect.detail}")
    return answers


def tick_job_loaded(label: str = TICK_JOB_LABEL) -> bool:
    """Is the trading loop's launchd job switched on?

    Used only to tell a loop that has stopped apart from a loop that was never
    started, so the watchdog does not shout every half hour about a heartbeat
    from a job Mo has deliberately not loaded yet.
    """
    try:
        finished = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10)
    except Exception:                                             # noqa: BLE001
        return False
    return finished.returncode == 0


def last_tick_time() -> tuple[datetime | None, str]:
    """When the loop last wrote anything down, and where that was read from.

    Two places are checked and the newer wins: the last line of output/loop.log,
    and the last_tick field of the day's state files, including the per book
    ones the multi book work will write.
    """
    best: datetime | None = None
    where = "nothing found"

    log = output_dir() / "loop.log"
    try:
        lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        lines = []
    if lines:
        stamp = lines[-1].split("|", 1)[0].strip()
        parts = stamp.split()
        if len(parts) >= 2:
            try:
                moment = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S")
                best = moment.replace(tzinfo=EASTERN)
                where = "output/loop.log"
            except ValueError:
                pass

    for path in sorted(output_dir().glob("state_*.json")):
        try:
            moment = _read_time(json.loads(path.read_text(encoding="utf-8")).get("last_tick"))
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if moment and (best is None or moment > best):
            best, where = moment, f"output/{path.name}"

    return best, where


def check_loop_tick(now: datetime, schedule: Schedule, market_hours: bool) -> Check:
    """Has the trading loop woken up recently? Only asked during market hours."""
    if not market_hours:
        return Check(CHECK_LOOP_TICK, ok=True, skipped=True,
                     detail="not checked, the market is shut")
    if not tick_job_loaded():
        return Check(CHECK_LOOP_TICK, ok=True, skipped=True,
                     detail=f"not checked, the launchd job {TICK_JOB_LABEL} is not loaded")

    moment, where = last_tick_time()
    limit = schedule.stale_after
    if moment is None:
        return Check(CHECK_LOOP_TICK, ok=False,
                     detail="The trading loop has never written a tick.")
    age = now - moment
    if age > limit:
        minutes = int(age.total_seconds() // 60)
        return Check(CHECK_LOOP_TICK, ok=False,
                     detail=(f"The trading loop last ticked {minutes} minutes ago "
                             f"({where} says {moment:%Y-%m-%d %H:%M}), and it is meant "
                             f"to tick every {schedule.loop_minutes} minutes."))
    return Check(CHECK_LOOP_TICK, ok=True,
                 detail=f"Last tick {moment:%H:%M} from {where}.")


def check_time_zone(now: datetime | None = None) -> Check:
    """Do the loaded launchd jobs still fire at the right New York minute?

    launchd fires on the Mac's own clock and no plist can pin a zone, so the
    wake up times are written in local time and stamped with the zone they were
    converted for. This compares that stamp against the Mac now.

    It is asked at every run, market hours or not, because the answer does not
    depend on the market being open and because the useful time to hear it is
    the evening before rather than 09:35 on the day. It is the cheapest check
    here: two symlink reads and some arithmetic, no network and no broker.

    Quiet when nothing is installed, the same restraint check_loop_tick shows
    when the tick job is not loaded. A Mac with no jobs on it is not a fault.

    Why it exists: on the night of 2026-09-06 this Mac relinked /etc/localtime
    to America/Los_Angeles by itself, because macOS is set to choose the zone
    from the current location, and all nine jobs became three hours late with
    nothing to show for it. Automatic zone selection is still on.
    """
    try:
        verdict = timezone_check.check(project_root(), when=now)
    except Exception as exc:                        # never take the watchdog down
        return Check(CHECK_TIME_ZONE, ok=True, skipped=True,
                     detail=f"not checked, the time zone check itself failed: {exc}")
    if verdict.ok:
        return Check(CHECK_TIME_ZONE, ok=True, detail=verdict.detail)
    return Check(CHECK_TIME_ZONE, ok=False, detail=verdict.detail)


def check_disk(floor: int = DISK_FLOOR_BYTES) -> Check:
    """Is there room left on the disk this project writes to?"""
    try:
        usage = shutil.disk_usage(project_root())
    except OSError as exc:
        return Check(CHECK_DISK, ok=False, detail=f"could not read the disk: {exc}")
    free_gb = usage.free / (1024 ** 3)
    if usage.free < floor:
        return Check(CHECK_DISK, ok=False, level="warn",
                     detail=f"Only {free_gb:.2f} GB free on the disk holding the project.")
    return Check(CHECK_DISK, ok=True, detail=f"{free_gb:.1f} GB free.")


def run_checks(now: datetime, schedule: Schedule,
               deadline: Deadline | None = None) -> dict[str, Check]:
    """Do all eight checks and hand back the results, in the usual order.

    The whole set shares one ninety second budget. Before each remaining check
    the budget is asked whether there is time left, and once there is not, the
    rest come back skipped rather than asked. So a check that hangs costs the
    run the checks after it, not the run itself: the line still gets written and
    launchd's next wake up never finds this one still going.

    The IB connection is the only expensive one here and it carries three of the
    eight, so it is asked as one block.
    """
    deadline = deadline or Deadline()
    market_hours = in_market_hours(now, schedule)
    results: dict[str, Check] = {}

    def ask(name: str, work):
        results[name] = deadline.out_of_time(name) if deadline.expired() else work()

    ask(CHECK_GATEWAY_PROCESS, check_gateway_process)
    ask(CHECK_GATEWAY_PORT, check_gateway_port)

    port = results[CHECK_GATEWAY_PORT]
    if deadline.expired():
        for name in (CHECK_IB_CONNECT, CHECK_IB_ANSWERS, CHECK_MARKET_DATA):
            results[name] = deadline.out_of_time(name)
    else:
        (results[CHECK_IB_CONNECT],
         results[CHECK_IB_ANSWERS],
         results[CHECK_MARKET_DATA]) = check_ib(
            port_ok=port.ok and not port.skipped, market_hours=market_hours)

    ask(CHECK_LOOP_TICK, lambda: check_loop_tick(now, schedule, market_hours))
    ask(CHECK_DISK, check_disk)
    ask(CHECK_TIME_ZONE, lambda: check_time_zone(now))
    return results


# ------------------------------------------------------------ carrying it out

def launch_gateway():
    """Start IB Gateway in the background and come straight back.

    agent/start_gateway.sh never returns when it works, it becomes Gateway, so
    this launches it detached and does not wait. The handle is kept anyway,
    because the one path where that script does return is the path where it
    gave up, and its exit code is the quickest way to know that. Its output goes
    to output/gateway_launch.log.

    Returns (handle, message). A handle of None means nothing was started at all.
    """
    script = agent_dir() / "start_gateway.sh"
    if not script.exists():
        return None, f"cannot restart, {script} is missing"
    log = output_dir() / "gateway_launch.log"
    try:
        log_file = open(log, "a", encoding="utf-8")
        log_file.write(f"\n----- started by the watchdog at "
                       f"{datetime.now(EASTERN):%Y-%m-%d %H:%M:%S %Z} -----\n")
        log_file.flush()
        started = subprocess.Popen(["/bin/bash", str(script)], stdout=log_file,
                                   stderr=log_file, cwd=str(project_root()),
                                   start_new_session=True)
    except Exception as exc:                                      # noqa: BLE001
        return None, f"could not start IB Gateway: {exc}"
    return started, f"IB Gateway starting, output going to {log}"


def stop_gateway(timeout: int = STOP_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Run agent/stop_gateway.sh and wait for it. Returns (worked, message).

    Only used on the ib_answers path, where a Gateway is sitting there logged in
    and cut off from IBKR. Starting a second one on top of that gives two logins
    fighting over one session, and the "different process id" proof could never
    come true while the old process is still there, so the old one has to go
    first. That script exits 0 only when no Gateway process remains.
    """
    script = agent_dir() / "stop_gateway.sh"
    if not script.exists():
        return False, f"cannot stop the old Gateway, {script} is missing"
    try:
        finished = subprocess.run(["/bin/bash", str(script)], capture_output=True,
                                  text=True, timeout=timeout, cwd=str(project_root()))
    except Exception as exc:                                      # noqa: BLE001
        return False, f"stopping the old Gateway failed: {exc}"
    if finished.returncode != 0:
        return False, (f"stop_gateway.sh exited {finished.returncode}, the old "
                       "Gateway is still there")
    return True, "the old Gateway was stopped"


def restart_gateway(wait_seconds: int = RESTART_VERIFY_SECONDS,
                    poll_seconds: int = RESTART_POLL_SECONDS,
                    probe=None, launcher=None, sleep=time.sleep,
                    stop_first: bool = False, stopper=None,
                    answering=None) -> RestartOutcome:
    """Start IB Gateway, then prove it really came back.

    Look at Gateway first, stop the old one when there is one worth stopping,
    start it, then keep looking until either the three local proofs in
    judge_restart() are there or the two minutes are up. Once they are, ask the
    fourth: does the new Gateway answer a read. The looking is done by probe(),
    the asking by answering(), the deciding by judge_restart(), which is why the
    whole rule can be tested with made up answers and no Gateway anywhere near
    it.

    stop_first is set when the reason for the restart is a Gateway that is
    running and not answering, since that process has to be gone before a new
    one means anything.

    Stops early on a start script that exited with an error, because nothing is
    going to change in the remaining two minutes if the script has already
    given up.
    """
    probe = probe or probe_gateway
    launcher = launcher or launch_gateway
    stopper = stopper or stop_gateway
    answering = answering or (lambda: ask_ib_answers().ok)

    before = probe()
    stop_note = ""
    if stop_first and before.pid:
        worked, stop_note = stopper()
        if not worked:
            return RestartOutcome(took=False, new_pid=False, fresh_login=False,
                                  port_open=False, waited_seconds=0,
                                  detail=f"  {stop_note}, so nothing was started")

    handle, message = launcher()
    if handle is None:
        return RestartOutcome(took=False, new_pid=False, fresh_login=False,
                              port_open=False, waited_seconds=0,
                              detail=f"  the start script never ran: {message}")

    waited = 0
    while True:
        exit_code = handle.poll()
        after = probe()
        outcome = judge_restart(before, after, exit_code, waited_seconds=waited)
        if outcome.took:
            # The three local proofs are in. The one that matters is whether
            # IBKR is on the other end, and that is worth asking only now.
            return judge_restart(before, after, exit_code, waited_seconds=waited,
                                 answers=bool(answering()))
        if exit_code not in (None, 0) or waited >= wait_seconds:
            return outcome
        sleep(poll_seconds)
        waited += poll_seconds


def perform(actions: list[Action], allow_restart: bool) -> tuple[list[str], list[Action]]:
    """Do the actions, describe what happened, and say which ones really happened.

    Two lists come back. The first is one line per action for the run log. The
    second is what update_state() should be told about, which is not always what
    was decided: a restart that could not be proved is dropped from it and
    replaced by the alert about that, so nothing writes down an attempt that
    did not work.
    """
    done: list[str] = []
    happened: list[Action] = []
    for action in actions:
        if action.kind == ACTION_ALERT:
            delivered = alerts_module.alert(action.level, action.title, action.body)
            done.append(f"alert [{action.level}] {action.title} "
                        f"-> {', '.join(delivered) or 'nothing'}")
            happened.append(action)
        elif action.kind == ACTION_RESTART:
            if not allow_restart:
                done.append("restart skipped, --no-restart was given")
                continue
            # A Gateway that is up and not answering has to be stopped before a
            # new one is worth anything. A Gateway that is not running at all
            # has nothing to stop.
            outcome = restart_gateway(stop_first=(action.check == CHECK_IB_ANSWERS))
            done.append(f"restart: {'verified' if outcome.took else 'NOT verified'} "
                        f"after {outcome.waited_seconds}s")
            done.extend(outcome.detail.splitlines())
            if outcome.took:
                happened.append(action)
                continue
            failed = restart_did_not_take_alert(action.check, outcome)
            delivered = alerts_module.alert(failed.level, failed.title, failed.body)
            done.append(f"alert [{failed.level}] {failed.title} "
                        f"-> {', '.join(delivered) or 'nothing'}")
            happened.append(failed)
    return done, happened


def record_checks(checks: dict, now: datetime, done: list[str] | None = None) -> int:
    """Every check into the database, one row each, every run. Returns how many.

    Unlike the pre-flight these are not updated in place. The whole run of them
    is the record, because "when did this start failing" cannot be answered from
    the latest verdict alone.

    What was done about it goes on the row too, so a Gateway restart is visible
    next to the check that asked for it rather than only in a log file.

    Never raises. A watchdog that fell over writing down its own answer would be
    worse than no watchdog.
    """
    if db_module is None:
        return 0
    action = "; ".join(done or []) or None
    written = 0
    for name in CHECK_ORDER:
        check = checks.get(name)
        if check is None:
            continue
        try:
            db_module.record_watchdog(
                check_name=name,
                ok=(None if check.skipped else check.ok),
                detail=(f"skipped: {check.detail}" if check.skipped else check.detail),
                action_taken=action, ts=now)
            written += 1
        except Exception as exc:                                  # noqa: BLE001
            print(f"watchdog: could not record {name} in the database: {exc!r}",
                  file=sys.stderr)
    return written


def append_run_log(line: str) -> None:
    try:
        with (output_dir() / "watchdog.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def summarise(checks: dict[str, Check]) -> str:
    bits = []
    for name in CHECK_ORDER:
        check = checks.get(name)
        if check is None:
            continue
        bits.append(f"{name}={'skip' if check.skipped else ('ok' if check.ok else 'FAIL')}")
    return " ".join(bits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One health check of IB Gateway, the market data feed, the "
                    "trading loop and the disk. Places no orders.")
    parser.add_argument("--once", action="store_true", default=True,
                        help="Do one check and exit. The default and the only mode.")
    parser.add_argument("--market-hours-only", action="store_true",
                        help="Do nothing outside 09:30 to 16:00 on a weekday.")
    parser.add_argument("--no-restart", action="store_true",
                        help="Alert about a dead Gateway but do not start it.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the checks, print what would happen, change nothing.")
    args = parser.parse_args(argv)

    now = datetime.now(EASTERN)
    schedule = load_schedule()
    market_hours = in_market_hours(now, schedule)

    if args.market_hours_only and not market_hours:
        print(f"{now:%Y-%m-%d %H:%M:%S %Z}: outside market hours, nothing to do.")
        return 0

    checks = run_checks(now, schedule, Deadline())
    state = load_state()
    actions = decide_actions(checks, now, state)

    print(f"{now:%Y-%m-%d %H:%M:%S %Z} watchdog, market hours: "
          f"{'yes' if market_hours else 'no'}")
    for name in CHECK_ORDER:
        check = checks.get(name)
        if check is None:
            continue
        mark = "skip" if check.skipped else ("ok  " if check.ok else "FAIL")
        print(f"  [{mark}] {name}: {check.detail}")

    if args.dry_run:
        print("\ndry run, nothing was sent and nothing was changed.")
        if not actions:
            print("  no actions")
        for action in actions:
            print(f"  would {action.kind}: [{action.level}] {action.title}")
        return 0

    # What was decided is not always what happened, so the state is written from
    # what happened. An unproved restart is not recorded as an attempt.
    lines, happened = perform(actions, allow_restart=not args.no_restart)
    for line in lines:
        print(f"  {line}")
    save_state(update_state(checks, now, state, happened))
    record_checks(checks, now, lines)

    failed = [name for name, check in checks.items() if not check.ok and not check.skipped]
    append_run_log(f"{now:%Y-%m-%d %H:%M:%S %Z} | {summarise(checks)} | "
                   f"actions={len(actions)} | failed={','.join(failed) or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
