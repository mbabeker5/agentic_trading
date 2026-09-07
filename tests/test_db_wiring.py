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

import dataclasses
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


def test_an_order_points_at_the_judgement_that_caused_it(database):
    """Item 14. The column was NULL on every order row ever written.

    A dry run writes the judgement first and the order second, so the id is
    there to be passed. Nothing passed it until 2026-09-06.
    """
    tick = tick_for("A")
    tick.phase = "pick"
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    guard = gr.load_book_guardrails(BOOKS_YAML, "A")
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=40, limit_price=231.20,
                            purpose="entry", book_id="A", sector="Technology")

    decision_id = tick.record(state, "AAPL", "would place BUY 40 AAPL limit 231.20",
                              "allowed by the guardrails. no limit was breached",
                              model="claude-fable-5.1", cost=0.0184,
                              prompt_hash="9f2c1a")
    assert decision_id, "the decisions row id is what the order row has to carry"
    loop.record_order_row(tick, guard, intent, stop=228.0, status="dry_run",
                          decision_id=decision_id)

    row = rows(database, "SELECT * FROM orders")[0]
    assert row["decision_id"] == decision_id


# ---------------------------------------------------------------------------
# From a trade back to the judgement that caused it (item 14)
# ---------------------------------------------------------------------------


class Filling:
    """A broker that takes one order and then reports one execution for it.

    Nothing leaves this object. fill() is a separate step on purpose, because
    that is what really happens to a limit order: it goes out, it rests, and the
    execution turns up on a later look rather than in the reply.
    """

    def __init__(self, order_id: int = 7001):
        self.order_id = order_id
        self.placed: list[dict] = []
        self._executions: list[dict] = []

    # -- reading ----------------------------------------------------------

    def account_summary(self, account=None):
        return {"items": [{"tag": "NetLiquidation", "value": "100000"}]}

    def portfolio(self, account=None, include_pnl=True):
        return {"positions": [], "totals": {}, "notes": []}

    def open_orders(self, account=None, include_all=True):
        return {"orders": [], "notes": []}

    def executions(self, account=None, **kwargs):
        return {"executions": list(self._executions), "notes": []}

    def snapshot(self, contracts, market_data_type=3):
        return {"market_data_type": market_data_type,
                "snapshots": [{"symbol": c.get("symbol"), "last": 231.25,
                               "close": 231.25, "halted": 0} for c in contracts],
                "notes": []}

    def historical_bars(self, contract, duration, bar_size, **kwargs):
        return {"bars": [], "notes": []}

    # -- acting -----------------------------------------------------------

    def place_order(self, contract, order, order_ref):
        self.placed.append({"contract": contract, "order": dict(order),
                            "order_ref": order_ref})
        return {"sent": True, "order_id": self.order_id, "filled_qty": 0.0,
                "avg_fill_price": None, "working": True, "error": None,
                "confirmed_by": "open_orders"}

    def bracket_order(self, contract, entry, stop, target=None, order_ref=""):
        answer = self.place_order(contract, entry, order_ref)
        answer["legs"] = []
        answer["bracketed"] = True
        answer["oca_group"] = "BOOK_A-AAPL-1"
        return answer

    def cancel_order(self, order_id):
        return {"order_id": order_id, "cancelled": True, "still_working": False}

    def global_cancel(self):
        raise AssertionError("no test here cancels everything")

    def fill(self, symbol: str = "AAPL", shares: int = 40, price: float = 231.25):
        self._executions.append({
            "execId": "0001.abc", "orderId": self.order_id, "orderRef": "BOOK_A",
            "symbol": symbol, "side": "BOT", "shares": shares, "price": price,
            "commission": 1.0, "time": "2026-09-08 09:38:11"})


def test_a_trade_row_carries_the_model_the_cost_and_the_reason_behind_it(
        database, tmp_path, monkeypatch):
    """Item 14, the whole chain: a fake fill back to the judgement that caused it.

    The fill points at its order, the order points at its decision, and
    db.trades_for_date joins the three. Until 2026-09-06 the middle link was
    missing, so every trade row the nightly Sheet sync wrote came out with a
    blank model, a blank cost, a blank prompt hash and a blank reason, and a
    month of results could not be read against the model that produced it or the
    price it cost.
    """
    for name in ("config", "strategies", "agent", "venv312"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir(exist_ok=True)
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")

    book = dataclasses.replace(gr.load_book(BOOKS_YAML, "A"), mode="full")
    tick = loop.BookTick(book, at(9, 35), "testhash", write_ledger=False, quiet=True)
    tick.phase = "pick"
    guard = gr.load_book_guardrails(BOOKS_YAML, "A")
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=tmp_path)
    state.triggered["AAPL"] = {"at": "2026-09-08 09:35:02", "price": 231.10,
                               "stop": 228.0, "qty": 40}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=40, limit_price=231.20,
                            purpose="entry", book_id="A", sector="Technology")
    account_state = bs.account_state_for(state, gr, at(9, 35), "DUT077572", False)
    broker = Filling()

    answer = loop.consider(tick, state, guard, account_state, intent, broker,
                           loop.read_guards(tmp_path),
                           model="claude-fable-5.1", cost=0.0184,
                           prompt_hash="9f2c1a", stop=228.0)
    assert answer.allowed, f"the guardrails refused it: {answer.reasons}"
    assert tick.sent == 1

    # The order row exists before the broker answers now, and the broker's own
    # two names for it are written in afterwards.
    order = rows(database, "SELECT * FROM orders")[0]
    assert order["decision_id"] is not None
    assert order["broker_order_id"] == "7001"
    assert order["oca_group"] == "BOOK_A-AAPL-1"
    assert order["status"] == "submitted"

    # The fill turns up on a later look, which is what a resting limit order does.
    broker.fill()
    assert loop.ingest_fills(tick, state, guard, broker)

    trades = db.trades_for_date(TUESDAY)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["symbol"] == "AAPL"
    assert trade["book_id"] == "A"
    assert trade["model"] == "claude-fable-5.1"
    assert trade["cost_usd"] == pytest.approx(0.0184)
    assert trade["prompt_hash"] == "9f2c1a"
    assert trade["rationale"] == ("allowed by the guardrails. no limit was breached"), (
        "the Reason column of the Trades tab comes from the decision's rationale")
    assert trade["decision_ts"] is not None
    assert trade["purpose"] == "entry"


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
# The day trade counter and the daily scoreboard
# ---------------------------------------------------------------------------


def test_where_a_book_stands_against_the_day_trade_limit_is_written_down(database):
    """One row per book per day, with the rulebook it was worked out under on it."""
    tick = tick_for("C", at(14, 30))
    loop.record_day_trade_row(tick, loop.DayTradeVerdict(
        is_day_trade=True, blocked=True, reason="already made 3 in five days",
        used=3, regime="old_pdt"))

    row = rows(database, "SELECT * FROM day_trade_counters")[0]
    assert row["book_id"] == "C"
    assert row["date"] == "2026-09-08"
    assert row["count_5d"] == 3
    assert row["regime"] == "old_pdt", (
        "FINRA retired the old rule on 2026-06-04, so a count read back without "
        "the rulebook beside it cannot be interpreted at all")
    assert row["would_have_blocked"] == 1


def test_the_cost_of_the_rule_adds_up_across_the_day(database):
    """would_have_blocked counts refusals, so it has to be added to, not replaced.

    Book A day trades on purpose, so the limit only flags it. The number of
    times it was flagged is the whole measurement: it is what says what the rule
    would have cost had this been a live account held to it.
    """
    tick = tick_for("A", at(11, 0))
    for _ in range(3):
        loop.record_day_trade_row(tick, loop.DayTradeVerdict(
            is_day_trade=True, blocked=False, reason="flagged only", used=4,
            would_have_blocked=True, regime="old_pdt"))

    counted = rows(database, "SELECT * FROM day_trade_counters")
    assert len(counted) == 1, "one book on one day is one row, updated in place"
    assert counted[0]["would_have_blocked"] == 3


def test_a_book_that_never_day_traded_gets_no_counter_row(database):
    """A row of zeroes reads as though the counter looked and found none."""
    tick = tick_for("A", at(11, 0))
    loop.record_day_trade_row(tick, loop.DayTradeVerdict(
        is_day_trade=False, blocked=False,
        reason="not a day trade, this position was not opened today"))
    assert rows(database, "SELECT * FROM day_trade_counters") == []


def test_the_end_of_day_scoreboard_lands_in_the_summaries_table(database):
    """The one table where each book gets its own equity curve.

    The Sheet's Daily tab follows the one paper account all five books share, so
    this is the only place book A's day can be told apart from book E's.
    """
    tick = tick_for("A", at(16, 5))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.realized_pnl_today = 1500.0      # a book is worth what it started the
    state.model_cost_today = 0.0412        # day with plus what it has made since
    loop.write_daily(tick, state)

    row = rows(database, "SELECT * FROM daily_book_summaries")[0]
    assert row["book_id"] == "A"
    assert row["date"] == "2026-09-08"
    assert row["start_equity"] == pytest.approx(100000.0)
    assert row["end_equity"] == pytest.approx(101500.0)
    assert row["pnl_usd"] == pytest.approx(1500.0), (
        "worked out inside db.upsert_daily_summary from the two equity figures, "
        "so the loop cannot disagree with the database about the same number")
    assert row["model_cost_usd"] == pytest.approx(0.0412)
    assert "end of day" in row["notes"]
    assert state.daily_written is True


def test_a_column_nothing_measures_is_left_empty_rather_than_zeroed(database):
    """NULL says not measured. A zero says measured, and it was none.

    spy_close, max_drawdown_pct, rule_triggers and missed_ticks have nothing
    working them out yet. Writing zeroes into them would put four made up
    numbers straight into the Sheet's Books tab.
    """
    tick = tick_for("A", at(16, 5))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    loop.write_daily(tick, state)

    row = rows(database, "SELECT * FROM daily_book_summaries")[0]
    for column in ("spy_close", "max_drawdown_pct", "rule_triggers",
                   "missed_ticks"):
        assert row[column] is None, f"{column} is not measured, so it must be blank"
    assert row["trades"] == 0, "no fills is a measured zero, not a blank"


def test_a_whole_tick_writes_down_how_long_it_took(database, tmp_path, monkeypatch):
    """A tick with no duration on it cannot be told from a tick that never ran.

    The attendance register is the only place a missed tick can ever be counted
    from, so the row has to say the tick happened AND how long it took.
    """
    for name in ("config", "strategies", "agent", "venv312"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir(exist_ok=True)
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(loop.LIVE_ENV_VAR, raising=False)

    class Quiet:
        def account_summary(self, account=None):
            return {"items": []}

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

    book = gr.load_book(BOOKS_YAML, "A")
    guard = gr.load_book_guardrails(BOOKS_YAML, "A")
    loop.run_book(book, guard, at(9, 40), loop.read_guards(), Quiet(),
                  "DUT077572", {}, "testhash", write_ledger=False, quiet=True)

    row = rows(database, "SELECT * FROM ticks")[0]
    assert row["book_id"] == "A"
    assert row["rules_commit"] == "testhash"
    assert row["duration_ms"] is not None
    assert 0 <= row["duration_ms"] < 60000


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
