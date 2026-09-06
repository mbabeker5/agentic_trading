"""Tests for the dead man's handle.

This is the only thing in the project that can decide, on its own, with nobody
watching, to trade. So the tests are mostly about all the times it must NOT:
a loop that is fine, a market that is shut, a position nobody's book owns, a
silence it has already dealt with, and an account that is not the paper one.

Then one test where it should fire, and it does, against
agent/replay/fake_broker.py: the kill switch really runs, the orders really get
cancelled and the positions really get closed inside the pretend broker.

Nothing here touches the network, IB Gateway, the MCP server or a real account.
Every alert channel is replaced and every file goes to a throwaway folder.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_deadman.py -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import alerts  # noqa: E402
import deadman as dm  # noqa: E402
import kill_switch as ks  # noqa: E402

from tests.test_kill_switch import (  # noqa: E402
    at, bars_from, clock_runner, contract, two_book_broker,
)

from agent.replay.fake_broker import FakeBroker  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: Tuesday 2026-09-08, half past ten in the morning. Market open, loop should
#: be ticking.
MID_MORNING = at(10, 30)

#: The same Tuesday at eight in the evening. Market shut.
EVENING = at(20, 0)


# ------------------------------------------------------------------- the setup

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
    """A throwaway project folder standing in for the whole project."""
    monkeypatch.setenv("AGENTIC_TRADING_ROOT", str(tmp_path))
    monkeypatch.delenv(ks.LIVE_KILL_ENV_VAR, raising=False)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    return tmp_path


def touch(root: Path, name: str, when: datetime, body: str = "x\n") -> Path:
    """Write a file under output/ and set its change time to a chosen moment."""
    path = root / "output" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
    return path


def book_state(root: Path, ref: str, day: str, symbol: str, qty: float,
               when: datetime) -> Path:
    """One book's state file, saying that book holds a position in one symbol."""
    return touch(root, f"state_{ref}_{day}.json", when, json.dumps({
        "book_id": ref.replace("BOOK_", "").lower(), "order_ref": ref, "date": day,
        "positions": {symbol: {"symbol": symbol, "qty": qty, "avg_cost": 100.0,
                               "side": "long" if qty > 0 else "short"}},
    }))


# ---------------------------------------------------------------- the heartbeat

def test_the_newest_file_is_the_heartbeat(home):
    touch(home, "loop.log", at(9, 40))
    touch(home, "tick_2026-09-08.log", at(10, 20))
    touch(home, "state_BOOK_A_2026-09-08.json", at(10, 5))
    beat = dm.heartbeat(home)
    assert beat.source == "output/tick_2026-09-08.log"
    assert beat.at == at(10, 20)


def test_a_heartbeat_file_wins_outright_when_it_exists(home):
    touch(home, "loop.log", at(10, 25))
    touch(home, "heartbeat", at(9, 31))
    beat = dm.heartbeat(home)
    assert beat.source == "output/heartbeat"
    assert beat.at == at(9, 31), (
        "the loop's own heartbeat is believed even when another file is newer")


def test_an_empty_output_folder_has_no_heartbeat_at_all(home):
    beat = dm.heartbeat(home)
    assert beat.at is None
    assert beat.incident == "never"


def test_files_that_are_not_the_loop_are_not_a_heartbeat(home):
    touch(home, "alerts.log", at(10, 29))
    touch(home, "watchdog.log", at(10, 29))
    touch(home, "shortlist_2026-09-08.json", at(10, 29))
    assert dm.heartbeat(home).at is None, (
        "the watchdog writing does not prove the loop is alive")


# -------------------------------------------------------------- market hours

def test_market_hours_are_weekdays_between_the_open_and_the_close():
    schedule = dm.Schedule()
    assert dm.in_market_hours(at(9, 30), schedule)
    assert dm.in_market_hours(at(15, 59), schedule)
    assert not dm.in_market_hours(at(9, 29), schedule)
    assert not dm.in_market_hours(at(16, 1), schedule)
    saturday = datetime(2026, 9, 12, 11, 0, tzinfo=EASTERN)
    assert not dm.in_market_hours(saturday, schedule)


def test_a_holiday_is_not_a_trading_day():
    schedule = dm.Schedule(holidays=("2026-09-08",))
    assert not dm.in_market_hours(at(11, 0), schedule), (
        "the loop is meant to be quiet on a holiday")


# ----------------------------------------------------- whose position is that

def test_a_tagged_order_belongs_to_its_book():
    assert dm.book_refs_on({"orderRef": "BOOK_A"}) == ["BOOK_A"]
    assert dm.book_refs_on({"order_refs": ["BOOK_C", "BOOK_D"]}) == ["BOOK_C", "BOOK_D"]
    assert dm.book_refs_on({"orderRef": "KILL_SWITCH"}) == []
    assert dm.book_refs_on({"orderRef": ""}) == []
    assert dm.book_refs_on({}) == []


def test_a_position_is_matched_to_a_book_by_its_state_file(home):
    book_state(home, "BOOK_C", "2026-09-08", "DELL", 20, at(10, 0))
    held = dm.book_symbols(home)
    assert held == {"DELL": "BOOK_C"}


def test_the_newest_state_file_per_book_is_the_one_that_counts(home):
    book_state(home, "BOOK_C", "2026-09-04", "AAPL", 5, at(10, 0))
    book_state(home, "BOOK_C", "2026-09-08", "DELL", 20, at(10, 0))
    assert dm.book_symbols(home) == {"DELL": "BOOK_C"}


def test_a_book_that_died_before_writing_today_still_owns_yesterdays_position(home):
    """Books C and D hold for weeks. A loop that never got to today's file has
    not stopped owning what it bought last Thursday."""
    book_state(home, "BOOK_C", "2026-09-04", "DELL", 20, at(10, 0))
    assert dm.book_symbols(home) == {"DELL": "BOOK_C"}


def test_a_flat_book_holds_nothing(home):
    book_state(home, "BOOK_C", "2026-09-08", "DELL", 0, at(10, 0))
    assert dm.book_symbols(home) == {}


def test_positions_split_into_the_books_and_the_orphans(home):
    positions = [{"symbol": "DELL", "position": 20},
                 {"symbol": "SPY", "position": 1}]
    theirs, orphans = dm.sort_positions(positions, {"DELL": "BOOK_C"})
    assert [p["symbol"] for p in theirs] == ["DELL"]
    assert theirs[0]["book_refs"] == ["BOOK_C"]
    assert [p["symbol"] for p in orphans] == ["SPY"], "Mo's one share is an orphan"


# ------------------------------------------------------------- doing nothing

def test_a_fresh_heartbeat_means_no_action(sent, home):
    touch(home, "loop.log", at(10, 25))
    broker = two_book_broker()
    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home)

    assert status == 0
    assert verdict.act is False and verdict.exposed is False
    assert "inside the 15 minute limit" in verdict.reason
    assert sent == [], "nobody was told anything"
    assert len(broker.positions) and broker.positions["SPY"] == 10, "nothing traded"
    assert not dm.state_path(home).exists()


def test_a_stale_heartbeat_outside_market_hours_means_no_action(sent, home):
    touch(home, "loop.log", at(9, 40))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(9, 40))
    broker = two_book_broker()
    status, verdict = dm.run(broker, really=True, now=EVENING, root=home)

    assert status == 0
    assert verdict.act is False
    assert "the market is shut" in verdict.reason
    assert sent == []
    assert broker.positions["SPY"] == 10


def test_the_broker_is_not_even_asked_when_the_loop_is_healthy(home):
    """Seventy-eight wake ups a day must cost nothing when nothing is wrong."""
    touch(home, "loop.log", at(10, 25))

    class ExplodingBroker:
        def portfolio(self, *a, **k):
            raise AssertionError("the broker should not have been read")

        def open_orders(self, *a, **k):
            raise AssertionError("the broker should not have been read")

    status, _ = dm.run(ExplodingBroker(), really=True, now=MID_MORNING, root=home)
    assert status == 0


# ------------------------------------------------------- an orphan on its own

def test_a_stale_loop_with_only_an_orphan_alerts_and_trades_nothing(sent, home):
    """The paper account's one share of SPY belongs to no book. The loop being
    dead is still worth a message, but nothing gets closed over it."""
    touch(home, "loop.log", at(10, 0))
    broker = FakeBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                        now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
                       "MANUAL")
    broker.advance_to(at(9, 40))

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home,
                             sleep=clock_runner(broker))

    assert status == 1, "it acted, by speaking"
    assert verdict.act is True and verdict.exposed is False
    assert [p["symbol"] for p in verdict.orphan_positions] == ["SPY"]
    assert broker.positions["SPY"] == 1, "the orphan was left exactly alone"

    assert len(sent) == 1
    level, title, body = sent[0]
    assert title == "The trading loop has stopped"
    assert "LEFT ALONE: SPY" in body
    assert json.loads(dm.state_path(home).read_text())["action"] == dm.ACTION_NOTIFIED


def test_speaking_about_a_silence_does_not_stop_it_firing_on_the_same_silence(home):
    """The hole this closes: at 10:30 no book held anything, so it only spoke.
    At 10:35 a book's position is visible. The same silence must still fire."""
    touch(home, "loop.log", at(10, 0))
    empty = FakeBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                       now=at(9, 30))
    dm.run(empty, really=True, now=MID_MORNING, root=home)
    assert json.loads(dm.state_path(home).read_text())["action"] == dm.ACTION_NOTIFIED

    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    broker = two_book_broker()
    status, verdict = dm.run(broker, really=True, now=at(10, 35), root=home,
                             sleep=clock_runner(broker))

    assert status == 1 and verdict.exposed is True
    assert broker.positions["SPY"] == 0, "it fired the second time"
    assert json.loads(dm.state_path(home).read_text())["action"] == dm.ACTION_FIRED


# -------------------------------------------------------------- firing for real

def test_a_stale_loop_holding_a_books_position_fires(sent, home):
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    book_state(home, "BOOK_C", "2026-09-08", "DELL", 20, at(10, 0))
    broker = two_book_broker()

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home,
                             sleep=clock_runner(broker))

    assert status == 1
    assert verdict.exposed is True
    assert verdict.age_minutes == 30.0
    assert {p["symbol"] for p in verdict.book_positions} == {"SPY", "DELL"}

    assert broker.positions["SPY"] == 0, "book A was closed out"
    assert broker.positions["DELL"] == 0, "book C was closed out"
    assert ks.working_orders(broker.open_orders()) == [], "both orders cancelled"

    titles = [title for _, title, _ in sent]
    assert titles[0] == "Loop is dead, pulling the kill switch"
    assert titles[1] == "Kill switch fired on account DUT077572", (
        "two messages: one saying why, one saying what happened")

    stored = json.loads(dm.state_path(home).read_text())
    assert stored["action"] == dm.ACTION_FIRED
    assert stored["outcome"] == "flat"
    assert sorted(stored["book_positions"]) == ["DELL", "SPY"]


def test_a_books_working_order_is_enough_on_its_own(home):
    """No position, just an order resting with a book's tag on it. Still ours."""
    touch(home, "loop.log", at(10, 0))
    broker = FakeBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                        now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 10, "orderType": "LMT",
                        "lmtPrice": 0.01}, "BOOK_B")

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home,
                             sleep=clock_runner(broker))

    assert status == 1 and verdict.exposed is True
    assert len(verdict.book_orders) == 1
    assert ks.working_orders(broker.open_orders()) == []


def test_it_fires_once_and_not_every_five_minutes(sent, home):
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    broker = two_book_broker()

    first, _ = dm.run(broker, really=True, now=MID_MORNING, root=home,
                      sleep=clock_runner(broker))
    assert first == 1 and len(sent) == 2

    # Five minutes later. The loop is still dead and the heartbeat has not moved.
    broker_again = two_book_broker()
    second, verdict = dm.run(broker_again, really=True, now=at(10, 35), root=home,
                             sleep=clock_runner(broker_again))

    assert second == 0, "the same silence, already dealt with"
    assert len(sent) == 2, "no second pair of messages"
    assert broker_again.positions["SPY"] == 10, "and nothing was traded again"


def test_a_loop_that_came_back_and_died_again_is_a_new_incident(sent, home):
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    first_broker = two_book_broker()
    dm.run(first_broker, really=True, now=MID_MORNING, root=home,
           sleep=clock_runner(first_broker))
    assert len(sent) == 2

    # The loop woke up at 11:00, wrote one line, and died again by 11:30.
    touch(home, "loop.log", at(11, 0))
    second_broker = two_book_broker()
    status, _ = dm.run(second_broker, really=True, now=at(11, 30), root=home,
                       sleep=clock_runner(second_broker))

    assert status == 1, "a different silence, so it acts again"
    assert second_broker.positions["SPY"] == 0
    assert len(sent) == 4


# ------------------------------------------------------------- a live account

def test_a_live_account_without_the_variable_alerts_and_trades_nothing(sent, home):
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    broker = two_book_broker(account_id="U1234567")

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home,
                             sleep=clock_runner(broker))

    assert status == 2
    assert verdict.exposed is True
    assert broker.positions["SPY"] == 10, "a live account is never flattened here"
    assert len(ks.working_orders(broker.open_orders())) == 2

    level, title, body = sent[-1]
    assert "LIVE account" in title
    assert "AGENTIC_TRADING_KILL_LIVE=yes" in body
    assert len(sent) == 1, "one message, and no kill switch behind it"


def test_a_live_account_with_the_variable_set_does_fire(sent, home, monkeypatch):
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "yes")
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    broker = two_book_broker(account_id="U1234567")

    status, _ = dm.run(broker, really=True, now=MID_MORNING, root=home,
                       sleep=clock_runner(broker))

    assert status == 1
    assert broker.positions["SPY"] == 0
    assert "LIVE account U1234567" in sent[-1][1]


# ---------------------------------------------------------------- the dry run

def test_a_dry_run_decides_and_does_nothing_at_all(sent, home, capsys):
    touch(home, "loop.log", at(10, 0))
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    broker = two_book_broker()

    status, verdict = dm.run(broker, really=False, now=MID_MORNING, root=home)

    assert status == 1, "it would have acted"
    assert verdict.exposed is True
    assert sent == [], "no alert"
    assert broker.positions["SPY"] == 10, "no trade"
    assert not dm.state_path(home).exists(), (
        "a dry run must not use up the incident the real run needs")
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed
    assert "run the kill switch for real" in printed


def test_the_dry_run_is_the_default_on_the_command_line(monkeypatch, home):
    """--really is the only thing that arms it, and main() honours --dry-run."""
    seen = {}

    def fake_run(broker, *, really, **kwargs):
        seen["really"] = really
        return 0, None

    monkeypatch.setattr(dm, "run", fake_run)
    monkeypatch.setattr(dm.broker_mod, "McpBroker", lambda *a, **k: object())

    dm.main([])
    assert seen["really"] is False
    dm.main(["--really"])
    assert seen["really"] is True
    dm.main(["--really", "--dry-run"])
    assert seen["really"] is False, "--dry-run wins, the same as the kill switch"


# ------------------------------------------------------------- broken plumbing

def test_a_broker_it_cannot_read_stops_it_without_a_second_alert(sent, home):
    """agent/watchdog.py already shouts about a Gateway that is down, every five
    minutes. This one does not shout the same thing again."""
    touch(home, "loop.log", at(10, 0))
    broker = two_book_broker()
    broker.inject_fault("gateway_down")

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home)

    assert status == 2
    assert verdict.broker_error
    assert sent == []
    assert not dm.state_path(home).exists()


def test_a_loop_that_never_wrote_anything_is_still_a_silence(sent, home):
    book_state(home, "BOOK_A", "2026-09-08", "SPY", 10, at(10, 0))
    # The state file is a heartbeat too, so hide it from the heartbeat by using
    # a name the loop does not write.
    (home / "output" / "state_BOOK_A_2026-09-08.json").rename(
        home / "output" / "book_a.json")
    broker = two_book_broker()

    status, verdict = dm.run(broker, really=True, now=MID_MORNING, root=home,
                             sleep=clock_runner(broker))

    assert verdict.heartbeat.at is None
    assert verdict.incident == "never"
    assert status == 1
    assert "has never been written" in sent[0][2]


def test_an_orders_symbol_is_found_inside_its_contract():
    """The real MCP server nests it there. The pretend broker puts it on top.
    Both have to read, or the alert names the wrong thing or nothing at all."""
    assert dm.symbol_of({"symbol": "SPY"}) == "SPY"
    assert dm.symbol_of({"contract": {"symbol": "SPY"}}) == "SPY"
    assert dm.symbol_of({}) == "?"
