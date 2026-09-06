"""The loop, the pre-flight, the watchdog and the alerts all write to SQLite.

Since 2026-09-06 the database is the system of record and the Google Sheet is a
nightly view of it (docs/DATA.md). The Sheet writes are still there, second, and
they stay until ledger/sync_sheet.py takes that job over. What this file checks
is the first half: that a tick, a morning check, a health check and an alert all
land in the database, and that a database which cannot be written to costs a row
rather than a tick.

That last one is the important test in here. The loop is what holds the risk
limits. Recording what it did must never be the thing that stops it doing it.

Nothing here touches a broker, a network or the real database.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_db_wiring.py -q
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "agent") not in sys.path:
    sys.path.insert(0, str(REPO / "agent"))

import alerts as alerts_module              # noqa: E402
import db                                   # noqa: E402
import preflight                            # noqa: E402
import watchdog as watchdog_module          # noqa: E402

from agent import book_state as bs          # noqa: E402
from agent import guardrails as gr          # noqa: E402
from agent import loop                      # noqa: E402

BOOKS_YAML = REPO / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")
TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 8, hour, minute, tzinfo=NEW_YORK)


@pytest.fixture()
def database(tmp_path, monkeypatch):
    """An empty migrated database, wired into every module that writes to one."""
    target = tmp_path / "trading.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.migrate(target)
    loop._DB_TROUBLE.clear()
    return target


def rows(path: Path, sql: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(sql))
    finally:
        conn.close()


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(9, 40), "testhash", write_ledger=False,
                         quiet=True)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_a_judgement_lands_in_the_decisions_table(database):
    tick = tick_for("A")
    tick.phase = "pick"
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)

    tick.record(state, "AAPL", "picked, long entry 100.00",
                "it broke the opening range on rising volume",
                model="claude-fable-5.1", cost=0.0021, prompt_hash="abc123")

    found = rows(database, "SELECT * FROM decisions")
    assert len(found) == 1
    row = found[0]
    assert row["book_id"] == "A"
    assert row["symbol"] == "AAPL"
    assert row["shape"] == "pick"
    assert row["action"] == "picked, long entry 100.00"
    assert row["rationale"] == "it broke the opening range on rising volume"
    assert row["rules_commit"] == "testhash"
    assert row["cost_usd"] == pytest.approx(0.0021)
    assert row["rejected"] == 0
    assert "[rules" not in (row["rationale"] or ""), (
        "the rules hash is its own column, not something to search a sentence for")


def test_a_guardrail_firing_is_a_rejected_decision_named_by_its_rule(database):
    tick = tick_for("A")
    tick.phase = "pick"
    tick.rule("sector_cap", "AAPL: too much of this book is already in technology",
              "the order was not placed")

    row = rows(database, "SELECT * FROM decisions")[0]
    assert row["rejected"] == 1
    assert row["reject_reason"] == "sector_cap"
    assert row["symbol"] == "AAPL", "the ticker is lifted into its own column"
    assert row["book_id"] == "A"

    # And it reads back out of the Rules Log as that rule rather than as a
    # decision, which is what the month end count of which limit bit is built on.
    ledger = db.rules_log_rows(date=at(9, 40).date())
    assert [line["rule"] for line in ledger] == ["sector_cap"]


def test_a_line_with_no_ticker_on_it_gets_no_ticker(database):
    tick = tick_for("A")
    tick.rule("daily_summary", "book A: end of day, worth 100,000", "written at the close")
    assert rows(database, "SELECT symbol FROM decisions")[0]["symbol"] is None


def test_the_symbol_reader_does_not_invent_one():
    assert loop._symbol_in("AAPL: something happened") == "AAPL"
    assert loop._symbol_in("BRK.B: something happened") == "BRK.B"
    assert loop._symbol_in("book A: end of day") is None
    assert loop._symbol_in("the pre-open run raised ValueError: no") is None
    assert loop._symbol_in("") is None
    assert loop._symbol_in("no colon at all") is None


def test_an_order_nobody_sent_is_written_down_anyway(database):
    """All five books are on dry run, so the orders they did not send are the result."""
    tick = tick_for("A")
    guard = gr.load_book_guardrails(BOOKS_YAML, "A")
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=50.0,
                            purpose="entry", book_id="A")

    row_id = loop.record_order_row(tick, guard, intent, stop=48.5, status="dry_run")
    assert row_id

    row = rows(database, "SELECT * FROM orders")[0]
    assert row["book_id"] == "A"
    assert row["order_ref"] == "BOOK_A"
    assert row["symbol"] == "AAPL"
    assert row["side"] == "BUY"
    assert row["qty"] == 100
    assert row["order_type"] == "LMT"
    assert row["limit_price"] == pytest.approx(50.0)
    assert row["stop_price"] == pytest.approx(48.5)
    assert row["purpose"] == "entry"
    assert row["status"] == "dry_run"


def test_what_a_book_was_holding_is_snapshotted_with_its_stop(database):
    tick = tick_for("A", at(10, 15))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(
        symbol="AAPL", qty=100, avg_cost=100.0, entry=100.0, side="long",
        opened_on="2026-09-08", stop=98.5, target=0.0, last_close=101.0,
        market_value=10100.0))

    loop.snapshot_book_positions(tick, state)

    row = rows(database, "SELECT * FROM position_snapshots")[0]
    assert row["book_id"] == "A"
    assert row["symbol"] == "AAPL"
    assert row["qty"] == 100
    assert row["market_price"] == pytest.approx(101.0)
    assert row["stop"] == pytest.approx(98.5), (
        "a stop that quietly went missing is only visible if it was recorded")
    assert row["target"] is None
    assert row["unrealized_pnl"] == pytest.approx(100.0)


def test_a_flat_book_writes_no_snapshot_rows(database):
    """The snapshot for a book holding nothing is the absence of rows."""
    tick = tick_for("A", at(10, 15))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    loop.snapshot_book_positions(tick, state)
    assert rows(database, "SELECT * FROM position_snapshots") == []


# ---------------------------------------------------------------------------
# A database that will not answer costs a row, never a tick
# ---------------------------------------------------------------------------


def test_a_database_error_is_logged_and_the_tick_carries_on(database, capsys):
    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("no such table: decisions")

    real = db.record_decision
    db.record_decision = explode
    try:
        assert loop.db_call("record_decision", ts=at(9, 40)) is None
        assert loop.db_call("record_decision", ts=at(9, 41)) is None
    finally:
        db.record_decision = real

    complaint = capsys.readouterr().err
    assert "record_decision" in complaint
    assert "The tick carries on" in complaint
    assert complaint.count("no such table") == 1, (
        "twelve copies of one complaint is how a real message gets lost")


def test_a_writer_that_does_not_exist_is_a_complaint_not_a_crash(database, capsys):
    assert loop.db_call("record_something_invented") is None
    assert "record_something_invented" in capsys.readouterr().err


def test_a_missing_database_module_does_not_stop_a_tick(monkeypatch, capsys):
    loop._DB_TROUBLE.clear()
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "ImportError: no db")
    assert loop.db_call("record_tick") is None
    assert "could not be imported" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Alerts, the pre-flight and the watchdog
# ---------------------------------------------------------------------------


def test_every_alert_lands_in_the_alerts_table(database, monkeypatch):
    """One funnel, one row. Every caller in the project goes through alert()."""
    monkeypatch.setattr(alerts_module, "read_env_file", lambda path: {})
    monkeypatch.setattr(alerts_module, "send_slack",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no token")))
    monkeypatch.setattr(alerts_module, "send_macos_notification",
                        lambda *a, **k: False)
    monkeypatch.setattr(alerts_module, "append_log", lambda *a, **k: True)

    delivered = alerts_module.alert("error", "Book A halted",
                                    "reconciliation disagreed about AAPL")

    row = rows(database, "SELECT * FROM alerts")[0]
    assert row["level"] == "ERROR"
    assert row["title"] == "Book A halted"
    assert "reconciliation disagreed" in row["body"]
    assert "log" in delivered


def test_an_alert_that_reached_nobody_is_still_recorded(database, monkeypatch):
    """We tried to shout and nothing got through is exactly the thing to record."""
    monkeypatch.setattr(alerts_module, "read_env_file", lambda path: {})
    monkeypatch.setattr(alerts_module, "send_slack",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no token")))
    monkeypatch.setattr(alerts_module, "send_macos_notification",
                        lambda *a, **k: False)
    monkeypatch.setattr(alerts_module, "append_log",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read only")))

    alerts_module.alert("error", "Gateway is down", "nothing on port 4002")
    row = rows(database, "SELECT * FROM alerts")[0]
    assert row["channels"] == "[]"


def test_the_morning_checks_land_in_the_preflight_table(database):
    results = [
        preflight.Result("gateway_login", True, "logged in as DUT077572"),
        preflight.Result("market_data", False, "delayed data only",
                         facts={"market_data_type": 3}),
    ]
    assert preflight.record_checks(results, "fail", at(9, 0)) == 2

    found = {row["check_name"]: row for row in
             rows(database, "SELECT * FROM preflight_results")}
    assert found["gateway_login"]["passed"] == 1
    assert found["market_data"]["passed"] == 0
    assert found["market_data"]["verdict"] == "fail"
    assert "delayed data only" in found["market_data"]["detail"]
    assert found["gateway_login"]["date"] == "2026-09-08"


def test_running_the_morning_checks_twice_updates_the_row(database):
    preflight.record_checks(
        [preflight.Result("gateway_login", False, "not logged in")], "fail", at(9, 0))
    preflight.record_checks(
        [preflight.Result("gateway_login", True, "logged in")], "pass", at(9, 20))

    found = rows(database, "SELECT * FROM preflight_results")
    assert len(found) == 1, "one row per check per day, not a second opinion"
    assert found[0]["passed"] == 1
    assert found[0]["verdict"] == "pass"


def test_every_watchdog_look_lands_in_its_own_row(database):
    checks = {
        "gateway_process": watchdog_module.Check("gateway_process", True, "running"),
        "gateway_port": watchdog_module.Check("gateway_port", False, "nothing on 4002"),
    }
    assert watchdog_module.record_checks(checks, at(10, 5), ["restart: verified"]) == 2
    assert watchdog_module.record_checks(checks, at(10, 10)) == 2

    found = rows(database, "SELECT * FROM watchdog_checks ORDER BY id")
    assert len(found) == 4, (
        "these pile up all day on purpose: when did this start failing needs "
        "the whole run of checks, not the latest verdict")
    assert found[0]["action_taken"] == "restart: verified"
    assert found[1]["ok"] == 0
    assert found[2]["action_taken"] is None


def test_a_skipped_watchdog_check_is_neither_a_pass_nor_a_miss(database):
    checks = {"market_data": watchdog_module.Check(
        "market_data", True, "the market is shut", skipped=True)}
    watchdog_module.record_checks(checks, at(20, 0))
    row = rows(database, "SELECT * FROM watchdog_checks")[0]
    assert row["ok"] is None
    assert row["detail"].startswith("skipped: ")
