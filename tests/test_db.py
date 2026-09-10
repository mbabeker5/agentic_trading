"""Tests for the SQLite system of record.

Six things are checked here, and they are the six that would actually hurt.

1. The schema applies to an empty database and gives the tables it promises.
2. Running the migration again does nothing, so a nightly job or a nervous
   person can run it as often as they like.
3. Every write helper round trips: what goes in comes back out unchanged.
4. Two writers at once do not fall over, which is the whole reason WAL and the
   busy timeout are switched on.
5. data/schema.sql and data/migrations/ have not drifted apart. The first is
   what a person reads, the second is what runs, so they must agree.
6. scripts/backup_db.sh really makes a copy and really deletes the old ones.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q

Nothing in here touches the network, the broker, or the real database.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "agent"
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import db  # noqa: E402

#: Every table the schema is meant to build, apart from the version table.
EXPECTED_TABLES = {
    "alerts", "daily_book_summaries", "day_trade_counters", "decisions", "fills",
    "orders", "position_snapshots", "preflight_results", "regime_flags", "scans",
    "shortlist_entries", "ticks", "watchdog_checks",
}


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """An empty, migrated database in a temporary folder, wired into db.py.

    Pointing db.db_path at the temporary file is what keeps every test in here
    away from the real /data/trading.sqlite. Every helper asks db_path() for
    the file, so one patch covers all of them.
    """
    target = tmp_path / "trading.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.migrate(target)
    return target


def table_names(path: Path) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()


def schema_of(path: Path) -> set[str]:
    """Every CREATE statement in the file, tidied so whitespace cannot matter."""
    conn = sqlite3.connect(str(path))
    try:
        return {" ".join((row[0] or "").split())
                for row in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
                if row[0]}
    finally:
        conn.close()


# ------------------------------------------------------------------ 1. the schema

def test_the_schema_applies_to_an_empty_database(tmp_path):
    target = tmp_path / "new.sqlite"
    assert not target.exists()
    applied = db.migrate(target)
    assert applied == ["0001_initial.sql"]
    assert target.exists()
    assert EXPECTED_TABLES <= table_names(target)


def test_the_connection_is_set_up_the_way_two_writers_need(fresh):
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_a_fill_cannot_point_at_an_order_that_is_not_there(fresh):
    """Foreign keys are off by default in SQLite, so this proves connect() has
    actually turned them on, not just that the schema mentions them."""
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fills (ts, order_id) VALUES ('2026-09-08 10:00:00', 999)")
    finally:
        conn.close()


def test_a_json_column_refuses_text_that_is_not_json(fresh):
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO alerts (ts, channels) "
                         "VALUES ('2026-09-08 10:00:00', 'not json at all')")
    finally:
        conn.close()


# ------------------------------------------------------------------ 2. idempotent

def test_migrating_again_does_nothing(tmp_path):
    target = tmp_path / "twice.sqlite"
    assert db.migrate(target) == ["0001_initial.sql"]
    assert db.migrate(target) == []
    assert db.migrate(target) == []
    assert EXPECTED_TABLES <= table_names(target)


def test_migrating_again_keeps_the_rows_that_are_already_there(tmp_path, monkeypatch):
    target = tmp_path / "keep.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.migrate(target)
    db.record_tick(book_id="A", phase="pick")
    db.migrate(target)
    assert db.counts()["ticks"] == 1


def test_a_migration_that_fails_leaves_nothing_behind(tmp_path):
    """Half a migration is worse than none, so it has to be all or nothing."""
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_fine.sql").write_text("CREATE TABLE fine (id INTEGER PRIMARY KEY);")
    (folder / "0002_broken.sql").write_text(
        "CREATE TABLE half (id INTEGER PRIMARY KEY);\nTHIS IS NOT SQL;")
    target = tmp_path / "broken.sqlite"

    with pytest.raises(db.DatabaseError):
        db.migrate(target, folder)

    names = table_names(target)
    assert "fine" in names, "the good migration should have stuck"
    assert "half" not in names, "the broken one should have rolled back completely"

    conn = db.connect(target)
    try:
        applied = [row["filename"] for row in
                   conn.execute("SELECT filename FROM schema_version")]
    finally:
        conn.close()
    assert applied == ["0001_fine.sql"]


def test_the_runner_script_says_what_it_would_do_and_writes_nothing(tmp_path):
    target = tmp_path / "dry.sqlite"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "migrate_db.py"),
         "--db", str(target), "--dry-run"],
        capture_output=True, text=True, check=False, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    assert "WOULD APPLY" in result.stdout
    assert not target.exists(), "a dry run must not create the file"


# ------------------------------------------------------------------ 3. round trips

def test_a_tick_round_trips(fresh):
    row_id = db.record_tick(ts="2026-09-08 09:35:00", book_id="A", phase="pick",
                            mode="dry_run", rules_commit="41d734d",
                            duration_ms=812, outcome="ok", notes="two picks")
    row = db._rows("SELECT * FROM ticks WHERE id=?", (row_id,))[0]
    assert row["ts"] == "2026-09-08 09:35:00"
    assert row["book_id"] == "A"
    assert row["phase"] == "pick"
    assert row["mode"] == "dry_run"
    assert row["rules_commit"] == "41d734d"
    assert row["duration_ms"] == 812
    assert row["outcome"] == "ok"
    assert row["notes"] == "two picks"


def test_a_scan_and_its_shortlist_round_trip(fresh):
    scan_id = db.record_scan(
        ts="2026-09-08 09:30:20", source="momentum",
        scan_codes=["TOP_PERC_GAIN", "HOT_BY_VOLUME"],
        stage_counts={"merged_unique": 120, "final": 2},
        diagnostics={"TOP_PERC_GAIN": {"rows": 50}}, market_data_type=3,
        entries=[
            {"symbol": "aapl", "side": "long", "score": 8.2, "rel_volume": 3.1,
             "avg_dollar_volume": 900000000, "flagged_by": ["TOP_PERC_GAIN"],
             "reasons": ["broke the opening range"]},
            {"symbol": "TSLA", "direction": "short", "score": 5.0},
        ])
    scan = db._rows("SELECT * FROM scans WHERE id=?", (scan_id,))[0]
    assert scan["source"] == "momentum"
    assert scan["scan_codes"] == "TOP_PERC_GAIN, HOT_BY_VOLUME"
    assert scan["market_data_type"] == "3"
    assert db._loads(scan["stage_counts"]) == {"merged_unique": 120, "final": 2}
    assert db._loads(scan["diagnostics"]) == {"TOP_PERC_GAIN": {"rows": 50}}

    entries = db._rows("SELECT * FROM shortlist_entries ORDER BY rank")
    assert [e["symbol"] for e in entries] == ["AAPL", "TSLA"], "symbols are upper cased"
    assert [e["rank"] for e in entries] == [1, 2], "rank follows the order given"
    assert entries[0]["direction"] == "long"
    assert entries[1]["direction"] == "short", "direction or side, either is read"
    assert entries[0]["dollar_volume"] == 900000000
    assert db._loads(entries[0]["tags"]) == ["TOP_PERC_GAIN"]
    assert db._loads(entries[0]["reasons"]) == ["broke the opening range"]
    assert entries[0]["traded"] == 0

    assert db.mark_shortlist_traded(scan_id, "aapl") is True
    again = db._rows("SELECT traded FROM shortlist_entries ORDER BY rank")
    assert [e["traded"] for e in again] == [1, 0]


def test_a_scan_with_no_entries_still_records_the_scan(fresh):
    scan_id = db.record_scan(source="insider", stage_counts={"final": 0})
    assert scan_id is not None
    assert db.counts()["scans"] == 1
    assert db.counts()["shortlist_entries"] == 0


def test_a_decision_round_trips(fresh):
    row_id = db.record_decision(
        ts="2026-09-08 09:35:02", book_id="A", shape="pick",
        model="openrouter/anthropic/claude-fable-5.1", prompt_hash="9f2c1a",
        packet_hash="7b3e", rules_commit="41d734d", symbol="aapl", action="pick",
        side="long", entry=231.10, stop=228.0, target=238.0, qty=40,
        confidence=0.71, rationale="broke the opening range", latency_ms=4210,
        tokens_in=5100, tokens_out=240, cost_usd=0.0184)
    row = db._rows("SELECT * FROM decisions WHERE id=?", (row_id,))[0]
    assert row["symbol"] == "AAPL"
    assert row["shape"] == "pick"
    assert row["packet_hash"] == "7b3e"
    assert row["entry"] == 231.10
    assert row["stop"] == 228.0
    assert row["target"] == 238.0
    assert row["qty"] == 40
    assert row["confidence"] == 0.71
    assert row["latency_ms"] == 4210
    assert row["tokens_in"] == 5100
    assert row["tokens_out"] == 240
    assert row["cost_usd"] == 0.0184
    assert row["rejected"] == 0


def test_a_refused_decision_keeps_the_guardrails_name(fresh):
    db.record_decision(book_id="B", symbol="MSFT", action="pick", rejected=True,
                       reject_reason="max_open_positions",
                       rationale="five already open")
    row = db._rows("SELECT * FROM decisions")[0]
    assert row["rejected"] == 1
    assert row["reject_reason"] == "max_open_positions"


class FakeResult:
    """Stands in for a DecisionResult from agent/decide.py, same field names."""

    def __init__(self, **kwargs):
        self.picks = kwargs.get("picks", [])
        self.skips = kwargs.get("skips", [])
        self.exits = kwargs.get("exits", [])
        self.rejections = kwargs.get("rejections", [])
        self.notes = kwargs.get("notes", [])
        self.model_response = kwargs.get("model_response", {})
        self.tokens_in = kwargs.get("tokens_in", 0)
        self.tokens_out = kwargs.get("tokens_out", 0)
        self.cost_usd = kwargs.get("cost_usd")
        self.prompt_hash = kwargs.get("prompt_hash", "")
        self.model = kwargs.get("model", "")
        self.book_id = kwargs.get("book_id")
        self.shape = kwargs.get("shape", "")
        self.error = kwargs.get("error")


def test_a_whole_decision_result_becomes_one_row_per_name(fresh):
    result = FakeResult(
        book_id="A", shape="pick", model="claude-fable-5.1", prompt_hash="9f2c1a",
        tokens_in=5100, tokens_out=240, cost_usd=0.0184,
        model_response={"latency_s": 4.21},
        picks=[{"symbol": "AAPL", "side": "long", "entry": 231.1, "stop": 228.0,
                "target": 238.0, "qty_hint": 40, "confidence": 0.71,
                "rationale": "broke the opening range"}],
        skips=[{"symbol": "NVDA", "rationale": "already extended"}],
        rejections=[{"symbol": "MSFT", "reason": "no borrow"}])
    ids = db.record_decision_result(result, ts="2026-09-08 09:35:02",
                                   rules_commit="41d734d", packet_hash="7b3e")
    assert len(ids) == 3

    rows = db._rows("SELECT * FROM decisions ORDER BY id")
    assert [r["symbol"] for r in rows] == ["AAPL", "NVDA", "MSFT"]
    assert [r["action"] for r in rows] == ["pick", "skip", "rejected"]
    assert rows[2]["rejected"] == 1
    assert rows[2]["reject_reason"] == "no borrow"
    assert rows[0]["qty"] == 40, "qty_hint becomes qty"
    for row in rows:
        assert row["book_id"] == "A"
        assert row["prompt_hash"] == "9f2c1a"
        assert row["packet_hash"] == "7b3e"
        assert row["rules_commit"] == "41d734d"


def test_the_cost_of_one_call_is_written_once_and_not_once_per_name(fresh):
    """One model call has one price. Three names must not triple the month's bill."""
    result = FakeResult(
        book_id="A", model="claude-fable-5.1", cost_usd=0.0184, tokens_in=5100,
        tokens_out=240, model_response={"latency_s": 4.21},
        picks=[{"symbol": "AAPL", "rationale": "one"},
               {"symbol": "MSFT", "rationale": "two"}],
        skips=[{"symbol": "NVDA", "rationale": "three"}])
    db.record_decision_result(result)

    rows = db._rows("SELECT symbol, cost_usd, tokens_in, latency_ms "
                    "FROM decisions ORDER BY id")
    assert [r["cost_usd"] for r in rows] == [0.0184, None, None]
    assert [r["tokens_in"] for r in rows] == [5100, None, None]
    assert [r["latency_ms"] for r in rows] == [4210, None, None]

    total = db._rows("SELECT SUM(cost_usd) AS spent FROM decisions")[0]["spent"]
    assert total == 0.0184


def test_a_decision_result_that_did_nothing_still_leaves_a_row(fresh):
    """A tick where the model was asked and said nothing is not the same as a
    tick where it was never asked, so the silence has to be on the record."""
    db.record_decision_result(FakeResult(book_id="A", shape="pick",
                                         notes=["nothing cleared the filters"]))
    rows = db._rows("SELECT * FROM decisions")
    assert len(rows) == 1
    assert rows[0]["action"] == "no_action"
    assert rows[0]["rationale"] == "nothing cleared the filters"


def test_an_order_round_trips_and_can_be_moved_on(fresh):
    decision_id = db.record_decision(book_id="A", symbol="AAPL", action="pick")
    order_id = db.record_order(
        ts="2026-09-08 09:35:09", book_id="A", order_ref="BOOK_A",
        broker_order_id=99001, parent_order_id=99000, oca_group="BOOK_A_AAPL",
        symbol="aapl", side="BUY", qty=40, order_type="LMT", limit_price=231.2,
        stop_price=228.0, tif="DAY", purpose="entry", status="submitted",
        decision_id=decision_id)
    row = db._rows("SELECT * FROM orders WHERE id=?", (order_id,))[0]
    assert row["symbol"] == "AAPL"
    assert row["order_ref"] == "BOOK_A"
    assert row["broker_order_id"] == "99001", "ids are kept as text"
    assert row["parent_order_id"] == "99000"
    assert row["oca_group"] == "BOOK_A_AAPL"
    assert row["limit_price"] == 231.2
    assert row["stop_price"] == 228.0
    assert row["tif"] == "DAY"
    assert row["purpose"] == "entry"
    assert row["status"] == "submitted"
    assert row["decision_id"] == decision_id

    assert db.update_order_status(order_id, "filled", broker_order_id=99002) is True
    after = db._rows("SELECT status, broker_order_id FROM orders WHERE id=?",
                     (order_id,))[0]
    assert after["status"] == "filled"
    assert after["broker_order_id"] == "99002"


def test_a_fill_round_trips_and_works_out_its_own_slippage(fresh):
    order_id = db.record_order(book_id="A", symbol="AAPL", side="BUY", qty=40)
    fill_id = db.record_fill(ts="2026-09-08 09:35:11", order_id=order_id,
                             exec_id="0001.abc", symbol="aapl", side="BUY", qty=40,
                             price=231.25, commission=1.0, decision_price=231.10)
    row = db._rows("SELECT * FROM fills WHERE id=?", (fill_id,))[0]
    assert row["symbol"] == "AAPL"
    assert row["exec_id"] == "0001.abc"
    assert row["price"] == 231.25
    assert row["commission"] == 1.0
    # Bought five cents above where we decided, forty shares, so two dollars.
    assert row["slippage_usd"] == pytest.approx(6.0)
    assert row["slippage_bps"] == pytest.approx(6.0 / (231.10 * 40) * 10000, rel=1e-6)


def test_slippage_matches_the_google_sheet_formula_both_ways():
    """The sheet works these out in columns U and V. If the two ever disagree,
    Mo reads one number in two places and gets two answers."""
    # BUY: paying more than we decided at is positive, and positive is bad.
    usd, bps = db.slippage("BUY", 100, 10.05, 10.00)
    assert usd == pytest.approx(5.0)
    assert bps == pytest.approx(50.0)
    # SELL: selling for less than we decided at is also positive, also bad.
    usd, bps = db.slippage("SELL", 100, 9.95, 10.00)
    assert usd == pytest.approx(5.0)
    assert bps == pytest.approx(50.0)
    # A quantity written negative for a sell must not flip the sign.
    assert db.slippage("SELL", -100, 9.95, 10.00)[0] == pytest.approx(5.0)
    # Anything missing gives nothing, rather than a zero that flatters us.
    assert db.slippage("BUY", 100, 10.05, None) == (None, None)
    assert db.slippage("", 100, 10.05, 10.00) == (None, None)


def test_the_same_execution_is_never_counted_twice(fresh):
    """The reconciler reads the day's executions again after a restart."""
    first = db.record_fill(exec_id="0001.abc", symbol="AAPL", side="BUY", qty=40,
                           price=231.25)
    second = db.record_fill(exec_id="0001.abc", symbol="AAPL", side="BUY", qty=40,
                            price=231.25)
    assert first == second
    assert db.counts()["fills"] == 1


def test_position_snapshots_round_trip_from_the_book_state_shape(fresh):
    """agent/book_state.py keeps positions as {SYMBOL: {...}}, so that shape has
    to work without the caller rearranging anything."""
    written = db.snapshot_positions(
        {"AAPL": {"qty": 40, "avg_cost": 231.25, "market_price": 232.0,
                  "market_value": 9280.0, "unrealized_pnl": 30.0,
                  "stop": 228.0, "target": 238.0},
         "MSFT": {"qty": -10, "avg_cost": 410.0, "last_close": 408.0}},
        ts="2026-09-08 10:15:00", book_id="A")
    assert written == 2
    rows = db._rows("SELECT * FROM position_snapshots ORDER BY symbol")
    assert [r["symbol"] for r in rows] == ["AAPL", "MSFT"]
    assert rows[0]["qty"] == 40
    assert rows[0]["market_price"] == 232.0
    assert rows[0]["stop"] == 228.0
    assert rows[1]["market_price"] == 408.0, "last_close stands in for market price"
    assert {r["ts"] for r in rows} == {"2026-09-08 10:15:00"}, "one moment, one stamp"


def test_a_list_of_positions_works_too(fresh):
    written = db.snapshot_positions(
        [{"symbol": "AAPL", "qty": 40}, {"symbol": "MSFT", "qty": 10}], book_id="B")
    assert written == 2


def test_a_flat_book_writes_no_snapshot_rows(fresh):
    assert db.snapshot_positions({}, book_id="A") == 0


def test_an_alert_round_trips(fresh):
    db.record_alert("warn", "market data", "delayed quotes only",
                    channels=["slack", "log"], ts="2026-09-08 09:02:11")
    row = db._rows("SELECT * FROM alerts")[0]
    assert row["level"] == "WARN"
    assert row["title"] == "market data"
    assert row["body"] == "delayed quotes only"
    assert db._loads(row["channels"]) == ["slack", "log"]


def test_an_alert_that_reached_nobody_is_still_recorded(fresh):
    db.record_alert("error", "gateway down", "nothing answered on 4002", channels=[])
    row = db._rows("SELECT * FROM alerts")[0]
    assert db._loads(row["channels"]) == []


def test_a_preflight_result_round_trips_and_only_keeps_the_latest_per_day(fresh):
    db.record_preflight("market_data", passed=False, detail={"ibkr_code": 10168},
                        verdict="fail", date="2026-09-08")
    db.record_preflight("market_data", passed=True, detail={"ibkr_code": None},
                        verdict="pass", date="2026-09-08")
    db.record_preflight("scanner", passed=True, detail={"candidates": 4},
                        verdict="pass", date="2026-09-08")

    rows = db._rows("SELECT * FROM preflight_results ORDER BY check_name")
    assert len(rows) == 2, "the second market_data run replaced the first"
    market = [r for r in rows if r["check_name"] == "market_data"][0]
    assert market["passed"] == 1
    assert market["verdict"] == "pass"
    assert db._loads(market["detail"]) == {"ibkr_code": None}


def test_a_watchdog_check_keeps_every_look_not_just_the_last(fresh):
    """When did this start failing is the question, and it needs all of them."""
    db.record_watchdog("gateway_port", ok=False, detail="nothing on 4002",
                       action_taken="restart_gateway", ts="2026-09-08 10:00:00")
    db.record_watchdog("gateway_port", ok=False, detail="still nothing",
                       ts="2026-09-08 10:05:00")
    db.record_watchdog("gateway_port", ok=True, detail="accepting connections",
                       ts="2026-09-08 10:10:00")
    rows = db._rows("SELECT * FROM watchdog_checks ORDER BY ts")
    assert len(rows) == 3
    assert [r["ok"] for r in rows] == [0, 0, 1]
    assert rows[0]["action_taken"] == "restart_gateway"


def test_a_day_trade_counter_updates_in_place_and_counts_the_blocks(fresh):
    db.record_day_trade_counter("A", count_5d=2, regime="old_pdt",
                                blocked=True, date="2026-09-08")
    db.record_day_trade_counter("A", count_5d=3, blocked=True, date="2026-09-08")
    db.record_day_trade_counter("A", count_5d=3, blocked=False, date="2026-09-08")

    rows = db._rows("SELECT * FROM day_trade_counters")
    assert len(rows) == 1, "one row per book per day"
    assert rows[0]["count_5d"] == 3
    assert rows[0]["would_have_blocked"] == 2, "blocked adds one, it does not set"
    assert rows[0]["regime"] == "old_pdt", "a later call without it leaves it alone"


def test_a_regime_flag_round_trips(fresh):
    db.record_regime("DUT077572", regime="old_pdt",
                     evidence={"tags_found": {"DayTradesRemaining": "3"}},
                     date="2026-09-08")
    row = db._rows("SELECT * FROM regime_flags")[0]
    assert row["account_id"] == "DUT077572"
    assert row["regime"] == "old_pdt"
    assert db._loads(row["evidence"]) == {"tags_found": {"DayTradesRemaining": "3"}}


def test_a_daily_summary_can_be_written_at_the_open_and_finished_at_the_close(fresh):
    db.upsert_daily_summary("2026-09-08", "A", start_equity=100000)
    db.upsert_daily_summary("2026-09-08", "A", end_equity=100310, spy_close=765.25,
                            trades=2, commissions=2.0, model_cost_usd=0.0368,
                            rule_triggers=1, missed_ticks=0,
                            max_drawdown_pct=-0.0041, notes="two entries")
    rows = db._rows("SELECT * FROM daily_book_summaries")
    assert len(rows) == 1
    row = rows[0]
    assert row["start_equity"] == 100000, "the morning figure survived the evening call"
    assert row["end_equity"] == 100310
    assert row["pnl_usd"] == pytest.approx(310.0), "worked out, not passed in"
    assert row["pnl_pct"] == pytest.approx(0.0031, abs=1e-6)
    assert row["spy_close"] == 765.25
    assert row["missed_ticks"] == 0


def test_a_timestamp_arrives_in_one_shape_however_it_was_given(fresh):
    from datetime import datetime
    assert db.as_ts("2026-09-08 09:35:00") == "2026-09-08 09:35:00"
    assert db.as_ts("2026-09-08T09:35:00-04:00") == "2026-09-08 09:35:00"
    assert db.as_ts(datetime(2026, 9, 8, 9, 35)) == "2026-09-08 09:35:00"
    assert db.as_date("2026-09-08T09:35:00-04:00") == "2026-09-08"


def test_a_broken_write_complains_and_returns_none_rather_than_raising(fresh, capsys):
    """Recording what happened must never be the thing that stops the loop."""
    db.db_path().unlink()
    db.db_path().parent.chmod(0o500)          # nothing may create the file again
    try:
        assert db.record_tick(book_id="A") is None
    finally:
        db.db_path().parent.chmod(0o700)
    assert "db:" in capsys.readouterr().err


# ------------------------------------------------------------------ 4. two writers

def test_two_writers_at_once_do_not_fall_over(fresh):
    """This is the reason WAL and the five second busy timeout are switched on.

    The loop and the watchdog both run on a schedule and will overlap. Each of
    these threads opens its own connection for every single write, which is
    exactly what the helpers do in real life, so this is the real contention
    and not a rehearsal of it.
    """
    problems: list[BaseException] = []
    rounds = 40

    def loop_writer():
        try:
            for number in range(rounds):
                db.record_tick(book_id="A", phase="pick", notes=f"loop {number}")
        except BaseException as exc:       # noqa: BLE001
            problems.append(exc)

    def watchdog_writer():
        try:
            for number in range(rounds):
                db.record_watchdog("gateway_port", ok=True, detail=f"watch {number}")
        except BaseException as exc:       # noqa: BLE001
            problems.append(exc)

    threads = [threading.Thread(target=loop_writer),
               threading.Thread(target=watchdog_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not problems, f"a writer fell over: {problems}"
    numbers = db.counts()
    assert numbers["ticks"] == rounds
    assert numbers["watchdog_checks"] == rounds


def test_a_reader_is_not_blocked_while_a_writer_holds_the_database(fresh):
    """The other half of what WAL buys: the nightly sheet sync can read the
    whole month while the watchdog is mid write, without either one waiting."""
    db.record_tick(book_id="A", phase="pick")
    writer = db.connect()
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO ticks (ts, book_id) VALUES (?, ?)",
                       ("2026-09-08 10:00:00", "B"))
        started = time.monotonic()
        rows = db._rows("SELECT * FROM ticks")
        took = time.monotonic() - started
        assert len(rows) == 1, "a reader sees the state before the open write"
        assert took < 1.0, "and it did not have to wait for it"
        writer.execute("COMMIT")
    finally:
        writer.close()
    assert db.counts()["ticks"] == 2


# ------------------------------------------------------------------ 5. no drift

def test_schema_sql_and_the_migrations_build_the_same_database(tmp_path):
    """data/schema.sql is what a person reads, data/migrations/ is what runs.

    If the two ever disagree, the readable one is a lie, and that is exactly
    the sort of lie nobody notices for a month. So this builds a database each
    way and compares every CREATE statement in them.
    """
    from_migrations = tmp_path / "migrated.sqlite"
    db.migrate(from_migrations)

    from_snapshot = tmp_path / "snapshot.sqlite"
    conn = sqlite3.connect(str(from_snapshot))
    try:
        conn.executescript((REPO / "data" / "schema.sql").read_text(encoding="utf-8"))
    finally:
        conn.close()

    assert schema_of(from_migrations) == schema_of(from_snapshot), (
        "data/schema.sql and data/migrations/ have drifted apart. Paste the new "
        "migration's statements into data/schema.sql.")


def test_the_data_folder_is_out_of_git_apart_from_the_schema():
    """A database is state, not source. Committing it would grow the repo by a
    gigabyte a month and put the day's trading into every clone."""
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in text
    assert "!data/schema.sql" in text
    assert "!data/migrations/" in text

    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/trading.sqlite"],
        cwd=str(REPO), capture_output=True, check=False)
    assert result.returncode == 0, "the database itself must be gitignored"


# ------------------------------------------------------------------ 6. backups

@pytest.mark.skipif(sys.platform == "win32", reason="a bash script")
def test_the_backup_script_makes_a_copy_and_deletes_the_old_ones(tmp_path):
    """Run against a whole temporary project, so the real database is untouched."""
    root = tmp_path / "project"
    (root / "data" / "backups").mkdir(parents=True)
    (root / "output").mkdir()
    (root / "scripts").mkdir()
    script = root / "scripts" / "backup_db.sh"
    script.write_text((REPO / "scripts" / "backup_db.sh").read_text(encoding="utf-8"),
                      encoding="utf-8")
    script.chmod(0o755)

    database = root / "data" / "trading.sqlite"
    db.migrate(database)
    conn = db.connect(database)
    try:
        conn.execute("INSERT INTO ticks (ts, book_id) VALUES ('2026-09-08 09:35:00', 'A')")
    finally:
        conn.close()

    # One copy that is well past the thirty day line, and one that is not.
    backups = root / "data" / "backups"
    old = backups / "trading_2026-01-01.sqlite"
    recent = backups / "trading_2026-09-05.sqlite"
    for path in (old, recent):
        path.write_bytes(b"an older copy")
    ancient = time.time() - 60 * 60 * 24 * 90
    yesterday = time.time() - 60 * 60 * 24
    os.utime(old, (ancient, ancient))
    os.utime(recent, (yesterday, yesterday))

    environment = {**os.environ, "AGENTIC_TRADING_ROOT": str(root)}
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                            check=False, env=environment)
    assert result.returncode == 0, result.stderr

    left = sorted(p.name for p in backups.glob("*"))
    assert old.name not in left, "a copy older than thirty days should be gone"
    assert recent.name in left, "yesterday's copy should have been kept"
    # Whatever today is. This used to look for a name starting
    # "trading_2026-09-0", which stopped matching on the tenth of the month.
    made = [name for name in left
            if name.startswith("trading_") and name != recent.name]
    assert made, f"no new backup was written, folder holds {left}"
    assert not [name for name in left if name.endswith(("-wal", "-shm"))], (
        "opening the copy to check it must not leave WAL files behind")

    # The copy has to be a real, readable database holding the real row.
    copy = backups / made[0]
    conn = sqlite3.connect(str(copy))
    try:
        assert conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1
    finally:
        conn.close()

    log = (root / "output" / "backup_db.log").read_text(encoding="utf-8")
    assert "backed up to" in log
    assert "deleted 1 older than 30 days" in log


@pytest.mark.skipif(sys.platform == "win32", reason="a bash script")
def test_the_backup_script_says_so_rather_than_failing_when_there_is_nothing_yet(tmp_path):
    root = tmp_path / "empty"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts" / "backup_db.sh"
    script.write_text((REPO / "scripts" / "backup_db.sh").read_text(encoding="utf-8"),
                      encoding="utf-8")
    script.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, check=False,
        env={**os.environ, "AGENTIC_TRADING_ROOT": str(root)})
    assert result.returncode == 0, result.stderr
    assert "nothing to back up" in result.stdout


def test_the_backup_script_finds_the_project_the_same_way_as_every_other_one():
    line = 'PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"'
    text = (REPO / "scripts" / "backup_db.sh").read_text(encoding="utf-8")
    assert text.count(line) == 1


def test_the_backup_script_is_valid_bash():
    result = subprocess.run(["bash", "-n", str(REPO / "scripts" / "backup_db.sh")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
