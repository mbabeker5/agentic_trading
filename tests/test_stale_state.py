"""A rehearsal must not be able to poison a real day. Backlog item 18.

On Saturday 2026-09-06 at 13:22 somebody ran the loop with
--now "2026-09-08 09:36" against the real output folder. It wrote
state_BOOK_A_2026-09-08.json through state_BOOK_E_2026-09-08.json, plus five
matching packet files, each one saying the pick had already been made under an
old rules stamp. The loop loads a state file by the date in its name and reads a
set picked_at as the pick already made, so on Tuesday 2026-09-08, the first
trading day of the experiment, all five books would have skipped their first
real pick. Nothing in any log would have looked wrong.

Two fixes, and this file tests both:

  (a) a tick pretending to be another DAY writes into
      output/rehearsal/<today's real date>/ and never into output/, so nothing
      it writes can be found by a real day
  (b) a state file for a day that has already begun, written before that day
      began, is moved to output/stale/ and the book starts the day fresh

Nothing here touches a broker, a network, or the real output folder.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_stale_state.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent import book_state as bs               # noqa: E402
from agent import loop                           # noqa: E402

NEW_YORK = ZoneInfo("America/New_York")
SATURDAY = date(2026, 9, 6)
MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)


def moment(day: date, hour: int = 9, minute: int = 36) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NEW_YORK)


class Quiet:
    """A broker that answers everything and holds nothing."""

    def account_summary(self, account=None):
        return {"items": [{"tag": "NetLiquidation", "value": "500000"}]}

    def portfolio(self, account=None, include_pnl=True):
        return {"positions": []}

    def open_orders(self, account=None, include_all=True):
        return {"orders": []}

    def executions(self, account=None, **kwargs):
        return {"executions": []}

    def snapshot(self, contracts, market_data_type=3):
        return {"snapshots": []}

    def historical_bars(self, contract, duration, bar_size, **kwargs):
        return {"bars": []}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A project root of its own, standing in for the real checkout.

    clone_root is pointed here too, so the rehearsal rule believes this is the
    real thing and fires. Without that the rule would correctly decide there is
    no real output folder to protect and leave the sandbox alone, which is what
    keeps every other test in this project writing where it expects to.
    """
    for name in ("config", "strategies"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir()
    # An ordinary morning: the 9 AM pre-flight passed. Without it the loop
    # refuses to open anything and says so once per book, which is another
    # test's subject, not this file's.
    (tmp_path / "output" / f"preflight_{date.today():%Y-%m-%d}.json").write_text(
        json.dumps({"verdict": "pass", "failed_checks": []}), encoding="utf-8")
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(loop.OUTPUT_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv("AGENTIC_TRADING_LIVE_ORDERS", raising=False)
    monkeypatch.setattr(loop, "clone_root", lambda: tmp_path)
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "not wanted in this test")
    loop._DB_TROUBLE.clear()
    bs.STALE_ARCHIVED.clear()
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    caught: list[tuple[str, str, str]] = []

    class Caught:
        @staticmethod
        def alert(level, title, body):
            caught.append((level, title, body))
            return ["captured"]

    monkeypatch.setattr(loop, "alerts_mod", Caught)
    return caught


def write_state(folder: Path, order_ref: str, day: date, created: datetime | None,
                picked: bool = True) -> Path:
    """One state file exactly as a tick leaves it, with the pick already made."""
    stored = {
        "book_id": order_ref[-1], "order_ref": order_ref, "date": f"{day:%Y-%m-%d}",
        "capital": 100000.0, "cash": 100000.0, "day_start_equity": 100000.0,
        "picks": [{"symbol": "NVDA"}] if picked else [],
        "picked_at": moment(day).isoformat() if picked else None,
        "tick_count": 3, "last_tick": moment(day, 9, 40).isoformat(),
    }
    if created is not None:
        stored["created_at"] = created.isoformat()
    path = folder / f"state_{order_ref}_{day:%Y-%m-%d}.json"
    path.write_text(json.dumps(stored, indent=2))
    return path


# ---------------------------------------------------------------------------
# (a) a run pretending to be another day writes somewhere else
# ---------------------------------------------------------------------------


def test_an_ordinary_tick_writes_to_the_real_output_folder():
    real = moment(MONDAY, 11, 5)
    assert loop.rehearsal_output_dir(real, real) is None


def test_a_pretend_time_on_today_is_not_a_rehearsal():
    """--now "14:00" is testing a phase of TODAY, and today's files are today's."""
    assert loop.rehearsal_output_dir(moment(MONDAY, 14, 0),
                                     moment(MONDAY, 7, 15)) is None


def test_a_pretend_day_is_sent_to_a_folder_of_its_own(sandbox):
    folder = loop.rehearsal_output_dir(moment(TUESDAY), moment(SATURDAY, 13, 22))
    assert folder == sandbox / "output" / "rehearsal" / "2026-09-06", (
        "named after the day the rehearsal really ran, so two rehearsals of the "
        "same day on different days do not overwrite each other")


def test_a_root_that_is_already_a_copy_is_left_alone(tmp_path, monkeypatch):
    """A test or a replay has no real output folder to protect."""
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    assert loop.rehearsal_output_dir(moment(TUESDAY), moment(SATURDAY)) is None


def test_the_saturday_rehearsal_writes_nothing_a_real_tuesday_would_find(
        sandbox, sent, capsys):
    """The incident itself, run again with the fix in place.

    A tick pretending to be Tuesday, run on a day that is not Tuesday. Not one
    file lands where the real Tuesday would look for it.
    """
    assert loop.main(["--now", "2026-09-15 11:05"], broker=Quiet()) == 0

    real = sandbox / "output"
    leaked = sorted(p.name for p in real.glob("*2026-09-15*"))
    assert leaked == [], f"a rehearsal wrote into the real output folder: {leaked}"
    assert not (real / "heartbeat").exists()
    assert not (real / "next_tick_seconds").exists()
    assert not (real / "loop.log").exists()

    where = real / "rehearsal" / f"{datetime.now(NEW_YORK).date():%Y-%m-%d}"
    assert (where / "state_BOOK_A_2026-09-15.json").exists()
    assert (where / "heartbeat").exists()
    assert (where / "next_tick_seconds").exists()
    assert (where / "loop.log").exists()

    printed = capsys.readouterr().out
    assert "REHEARSAL:" in printed
    assert str(where) in printed


def test_the_kill_switch_files_are_still_read_from_the_real_folder(sandbox, sent):
    """A rehearsal is stopped by a real STOP, and cannot write one of its own."""
    (sandbox / "output" / "LOOP_DISABLED").write_text("stopped by hand\n")
    assert loop.main(["--now", "2026-09-15 11:05"], broker=Quiet()) == 0
    assert not (sandbox / "output" / "rehearsal").exists(), (
        "it never got as far as writing anything")


# ---------------------------------------------------------------------------
# (b) a state file written before the day it claims cannot describe that day
# ---------------------------------------------------------------------------


def test_a_file_written_this_morning_for_today_is_fine(tmp_path):
    path = write_state(tmp_path, "BOOK_A", MONDAY, moment(MONDAY, 7, 0))
    stored = json.loads(path.read_text())
    assert bs.is_stale(path, MONDAY, stored, real_today=MONDAY) is False


def test_saturdays_file_for_tuesday_is_stale_on_tuesday(tmp_path):
    """The exact five files that would have skipped the first real pick."""
    path = write_state(tmp_path, "BOOK_A", TUESDAY, moment(SATURDAY, 13, 22))
    stored = json.loads(path.read_text())
    assert bs.is_stale(path, TUESDAY, stored, real_today=TUESDAY) is True


def test_the_same_file_is_not_stale_before_tuesday_arrives(tmp_path):
    """Early is not wrong. It only becomes wrong on the day it claims to be."""
    path = write_state(tmp_path, "BOOK_A", TUESDAY, moment(SATURDAY, 13, 22))
    stored = json.loads(path.read_text())
    assert bs.is_stale(path, TUESDAY, stored, real_today=SATURDAY) is False


def test_a_replay_of_a_day_gone_by_is_not_stale(tmp_path):
    """The replay gate builds today what it says happened last week."""
    path = write_state(tmp_path, "BOOK_A", date(2026, 9, 2), moment(MONDAY, 10, 0))
    stored = json.loads(path.read_text())
    assert bs.is_stale(path, date(2026, 9, 2), stored, real_today=MONDAY) is False


def test_a_file_with_no_created_at_falls_back_to_when_it_was_written(tmp_path):
    """Every file written before 2026-09-07 has no created_at, the five included."""
    path = write_state(tmp_path, "BOOK_A", TUESDAY, None)
    stored = json.loads(path.read_text())
    assert "created_at" not in stored
    saturday = datetime(2026, 9, 6, 13, 22, tzinfo=NEW_YORK).timestamp()
    import os
    os.utime(path, (saturday, saturday))
    assert bs.is_stale(path, TUESDAY, stored, real_today=TUESDAY) is True


def test_last_tick_is_not_what_decides_it(tmp_path):
    """The trap. The rehearsal's own last_tick says Tuesday, because it pretended.

    Only a real clock can tell these files apart, which is why created_at is
    stamped from the real clock and never from the tick's.
    """
    path = write_state(tmp_path, "BOOK_A", TUESDAY, moment(SATURDAY, 13, 22))
    stored = json.loads(path.read_text())
    assert stored["last_tick"].startswith("2026-09-08"), "as the rehearsal left it"
    assert bs.is_stale(path, TUESDAY, stored, real_today=TUESDAY) is True


def test_load_state_moves_it_aside_and_starts_the_day_fresh(tmp_path):
    """Past dates, because load_state asks the real clock what day it is.

    The Tuesday morning case is the same rule with real_today passed in, which
    the four tests above cover.
    """
    output = tmp_path / "output"
    output.mkdir()
    poison = write_state(output, "BOOK_A", date(2026, 9, 4),
                         moment(date(2026, 9, 2), 13, 22))

    state = bs.load_state("A", "BOOK_A", date(2026, 9, 4), capital=100000.0,
                          root=tmp_path)

    assert not poison.exists(), "the file the loop would have believed"
    moved = list((output / "stale").glob("state_BOOK_A_2026-09-04.moved-*.json"))
    assert len(moved) == 1, "moved, not deleted: it is evidence"
    assert state.picked_at is None, "so the book still has its first pick to make"
    assert state.picks == []
    assert state.created_at, "the fresh file knows when it was really made"


def test_the_day_carries_forward_from_the_day_before_not_from_the_stale_file(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    yesterday = bs.BookState(book_id="C", order_ref="BOOK_C", date="2026-09-03",
                             capital=100000.0, cash=90000.0)
    yesterday.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                       side="long", opened_on="2026-09-03"))
    bs.save_state(yesterday, root=tmp_path)
    write_state(output, "BOOK_C", date(2026, 9, 4), moment(date(2026, 9, 2), 13, 22))

    state = bs.load_state("C", "BOOK_C", date(2026, 9, 4), capital=100000.0,
                          root=tmp_path)

    assert list(state.all_positions()) == ["AAPL"], (
        "the insider and Congress books hold for weeks. Losing a position here "
        "would lose its stop with it")
    assert state.picked_at is None


def test_an_ordinary_file_is_loaded_exactly_as_before(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    today = date.today()
    kept = write_state(output, "BOOK_A", today, datetime.now(NEW_YORK))

    state = bs.load_state("A", "BOOK_A", today, capital=100000.0, root=tmp_path)

    assert kept.exists()
    assert state.picked_at is not None, "it really did pick, and must not pick again"
    assert not (output / "stale").exists()


def test_what_was_moved_is_written_down_for_the_loop_to_report(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    bs.STALE_ARCHIVED.clear()
    write_state(output, "BOOK_A", date(2026, 9, 4), moment(date(2026, 9, 2), 13, 22))
    bs.load_state("A", "BOOK_A", date(2026, 9, 4), capital=100000.0, root=tmp_path)

    assert len(bs.STALE_ARCHIVED) == 1
    row = bs.STALE_ARCHIVED[0]
    assert row["order_ref"] == "BOOK_A"
    assert row["date"] == "2026-09-04"
    assert row["written_at"].startswith("2026-09-02")
    bs.STALE_ARCHIVED.clear()


def test_the_loop_says_so_and_tells_mo(sandbox, sent, capsys):
    """The alarm for the failure that produced no alarm at all.

    Today's date, on purpose. A tick pretending to be another day now writes
    somewhere else entirely and would never open these files, so the only way to
    put the loop in front of one is to leave it a file for the day it is really
    living through, written before that day began. Which is exactly what
    Tuesday morning would have looked like.
    """
    output = sandbox / "output"
    today = date.today()
    written = datetime.now(NEW_YORK) - timedelta(days=2)
    for order_ref in ("BOOK_A", "BOOK_B", "BOOK_C", "BOOK_D", "BOOK_E"):
        write_state(output, order_ref, today, written)

    assert loop.main(["--now", f"{today:%Y-%m-%d} 11:05"], broker=Quiet()) == 0

    printed = capsys.readouterr().out
    assert "STALE STATE BOOK_A" in printed
    titles = [title for _level, title, _body in sent]
    assert any("state file from before today" in title for title in titles), titles
    assert len(sent) == 1, "one message for the finding, not one per book"
    assert "BOOK_E" in sent[0][1], "and it names all five"


def test_a_clean_morning_says_nothing_about_stale_files(sandbox, sent, capsys):
    bs.STALE_ARCHIVED.clear()
    assert loop.main(["--now", f"{date.today():%Y-%m-%d} 11:05"],
                     broker=Quiet()) == 0
    assert "STALE STATE" not in capsys.readouterr().out
    assert [t for _l, t, _b in sent if "stale" in t.lower()] == []


# ---------------------------------------------------------------------------
# The two halves together
# ---------------------------------------------------------------------------


def test_a_rehearsal_of_tomorrow_cannot_reach_tomorrow(sandbox, sent):
    """End to end, in the shape the incident really had.

    Rehearse a day that has not happened yet, then let that day arrive and see
    what the real tick loads. It must find nothing: the rehearsal is in its own
    folder, and even if it were not, a file written before the day began is
    moved aside rather than believed.
    """
    tomorrow = date.today() + timedelta(days=1)
    assert loop.main(["--now", f"{tomorrow:%Y-%m-%d} 11:05"], broker=Quiet()) == 0

    real = sandbox / "output"
    assert list(real.glob(f"state_*_{tomorrow:%Y-%m-%d}.json")) == []
    state = bs.load_state("A", "BOOK_A", tomorrow, capital=100000.0, root=sandbox)
    assert state.picked_at is None, "tomorrow's first pick is still to be made"
