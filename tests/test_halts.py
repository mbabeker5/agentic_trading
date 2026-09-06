"""A halt has to end, and a halt reason has to stop growing.

Two findings from the first replay gate run, and they are the same bug seen from
two angles.

Nothing anywhere cleared a halt. A book halted at 09:50 by one bad tick opened
nothing for the rest of the day, and a twenty minute Gateway outage cost the
whole session. What clears a halt now depends on why it was set, because those
are genuinely different situations: a disagreement that has gone away is over, a
loss cap is measured over a day, and somebody pulling the kill switch means a
person has to be involved before the books start again.

And BookState.halt() appended to one string every time it was called, while
reconciliation called it on every tick. The gate found one halt reason 2,276
characters long on a day when exactly one thing had gone wrong, stored in the
book file and quoted in full in every log line that mentioned it.

Nothing here touches a broker or a network.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_halts.py -q
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent import book_state as bs               # noqa: E402
from agent import guardrails as gr               # noqa: E402
from agent import loop                           # noqa: E402

BOOKS_YAML = REPO / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")
TUESDAY = date(2026, 9, 8)
WEDNESDAY = date(2026, 9, 9)


def at(hour: int, minute: int, day: date = TUESDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NEW_YORK)


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(10, 0), "testhash", write_ledger=False,
                         quiet=True)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("config", "strategies"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "not wanted in this test")
    monkeypatch.setattr(loop, "alerts_mod", None)
    monkeypatch.setattr(loop, "ALERTS_ERROR", "not wanted in this test")
    loop._DB_TROUBLE.clear()
    return tmp_path


def fresh_state() -> bs.BookState:
    return bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08",
                        capital=100000.0, cash=100000.0, day_start_equity=100000.0)


# ---------------------------------------------------------------------------
# The reason stops growing
# ---------------------------------------------------------------------------


def test_the_same_reason_every_tick_is_written_down_once():
    """Reconciliation calls halt() on every tick while a disagreement stands."""
    state = fresh_state()
    for minute in range(0, 60, 5):
        state.halt("3 problems across books C, D", cause=bs.HALT_RECONCILIATION,
                   at=at(10, minute).isoformat())

    assert len(state.halt_reasons) == 1
    assert state.halted is True
    assert len(state.halt_reason) < 400, (
        "the gate found one of these 2,276 characters long")


def test_only_the_five_most_recent_reasons_are_kept():
    state = fresh_state()
    for number in range(12):
        state.halt(f"problem number {number}", cause=bs.HALT_OTHER,
                   at=at(10, number).isoformat())

    assert len(state.halt_reasons) == bs.MAX_HALT_REASONS
    assert [row["reason"] for row in state.halt_reasons] == [
        f"problem number {n}" for n in range(7, 12)]


def test_one_very_long_reason_is_trimmed_rather_than_stored_whole():
    state = fresh_state()
    state.halt("x" * 5000, cause=bs.HALT_OTHER, at=at(10, 0).isoformat())
    assert len(state.halt_reasons[0]["reason"]) == bs.HALT_REASON_MAX_CHARS


def test_the_sentence_names_the_latest_reason_and_counts_the_rest():
    state = fresh_state()
    state.halt("the books and the broker disagree about AAPL",
               cause=bs.HALT_RECONCILIATION, at=at(9, 50).isoformat())
    state.halt("the daily loss cap was reached", cause=bs.HALT_LOSS_CAP,
               at=at(11, 20).isoformat())

    assert "the daily loss cap was reached" in state.halt_reason
    assert "11:20" in state.halt_reason
    assert "loss_cap" in state.halt_reason
    assert "1 earlier reason" in state.halt_reason
    assert len(state.halt_reason) < 400


def test_a_halt_survives_being_written_and_read_back(sandbox):
    state = fresh_state()
    state.halt("the books and the broker disagree", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())
    bs.save_state(state, root=sandbox)

    again = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert again.halted is True
    assert again.halt_causes() == {bs.HALT_RECONCILIATION}


def test_a_state_file_written_before_this_change_still_loads(sandbox):
    """An old file has halt_reason and no halt_reasons at all."""
    import json                                  # noqa: PLC0415

    path = sandbox / "output" / "state_BOOK_A_2026-09-08.json"
    path.write_text(json.dumps({
        "book_id": "A", "order_ref": "BOOK_A", "date": "2026-09-08",
        "capital": 100000.0, "halted": True,
        "halt_reason": "old style; appended; over and over"}))

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert state.halted is True
    assert state.halt_reasons == []
    assert state.halt_causes() == set()


# ---------------------------------------------------------------------------
# What lifts each kind of halt
# ---------------------------------------------------------------------------


def test_a_reconciliation_halt_lifts_when_the_books_and_broker_agree(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("3 problems across books C, D", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is False
    assert state.halt_reason is None
    assert state.halt_reasons == []


def test_a_reconciliation_halt_stays_while_they_still_disagree(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("3 problems across books C, D", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=False)
    assert state.halted is True


def test_a_reconciliation_halt_stays_when_nobody_could_ask(sandbox):
    """A Gateway outage answers None, and None is not a clean bill of health."""
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("3 problems across books C, D", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=None)
    assert state.halted is True


def test_a_loss_cap_halt_is_not_lifted_by_a_clean_reconciliation(sandbox):
    """A loss cap is about the money, not about who owns what."""
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("a guardrail asked for a halt for the rest of the day",
               cause=bs.HALT_LOSS_CAP, at=at(9, 50).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is True
    assert state.halt_causes() == {bs.HALT_LOSS_CAP}


def test_a_loss_cap_halt_clears_at_the_next_trading_day(sandbox):
    state = fresh_state()
    state.halt("a guardrail asked for a halt for the rest of the day",
               cause=bs.HALT_LOSS_CAP, at=at(15, 50).isoformat())
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   side="long", opened_on="2026-09-08"))
    bs.save_state(state, root=sandbox)

    tomorrow = bs.load_state("A", "BOOK_A", WEDNESDAY, capital=100000, root=sandbox)
    assert tomorrow.halted is False
    assert tomorrow.halt_reasons == []
    assert tomorrow.halt_reason is None
    assert len(tomorrow.all_positions()) == 1, "what it holds still carries over"


def test_a_kill_switch_halt_needs_the_loop_re_enabled_as_well(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("the kill switch flattened 2 position(s) in this book at the broker",
               cause=bs.HALT_KILL_SWITCH, at=at(9, 50).isoformat())

    (sandbox / "output" / "LOOP_DISABLED").write_text("pulled\n")
    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is True, "clean reconciliation on its own is not enough"

    (sandbox / "output" / "LOOP_DISABLED").unlink()
    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is False, "agent/reenable.sh has run and the books agree"


def test_a_kill_switch_halt_needs_a_clean_reconciliation_as_well(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("the kill switch flattened 2 position(s)", cause=bs.HALT_KILL_SWITCH,
               at=at(9, 50).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=False)
    assert state.halted is True, "reenable.sh on its own is not enough either"


def test_a_book_halted_twice_stays_halted_until_both_reasons_have_gone(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    state.halt("the books and the broker disagree", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())
    state.halt("a guardrail asked for a halt for the rest of the day",
               cause=bs.HALT_LOSS_CAP, at=at(10, 0).isoformat())

    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is True, "the loss cap is still holding it"
    assert state.halt_causes() == {bs.HALT_LOSS_CAP}
    assert "a guardrail asked" in state.halt_reason


def test_clearing_one_cause_leaves_the_others_alone():
    state = fresh_state()
    state.halt("one", cause=bs.HALT_RECONCILIATION, at=at(9, 50).isoformat())
    state.halt("two", cause=bs.HALT_LOSS_CAP, at=at(10, 0).isoformat())
    state.halt("three", cause=bs.HALT_RECONCILIATION, at=at(10, 5).isoformat())

    lifted = state.clear_halt(bs.HALT_RECONCILIATION)
    assert [row["reason"] for row in lifted] == ["one", "three"]
    assert state.halt_causes() == {bs.HALT_LOSS_CAP}
    assert state.halted is True


def test_clearing_everything_leaves_a_book_that_is_not_halted():
    state = fresh_state()
    state.halt("one", cause=bs.HALT_RECONCILIATION, at=at(9, 50).isoformat())
    state.halt("two", cause=bs.HALT_LOSS_CAP, at=at(10, 0).isoformat())

    state.clear_halt()
    assert state.halted is False
    assert state.halt_reason is None
    assert state.halt_reasons == []


def test_a_book_that_was_never_halted_is_left_alone(sandbox):
    tick = tick_for("A", at(10, 0))
    state = fresh_state()
    loop.clear_halts_that_are_over(tick, state, loop.read_guards(sandbox),
                                   reconciliation_clean=True)
    assert state.halted is False
    assert tick.notes == []
