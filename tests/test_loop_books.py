"""Tests for the five book trading loop in agent/loop.py.

Everything here runs against a tiny fake broker defined at the top of this file,
one that counts the calls it gets. Nothing touches IB Gateway, the MCP server,
the SEC or Google Sheets, and nothing here can place an order. The replay
harness in agent/replay/fake_broker.py is a much richer fake and it is
deliberately not imported: these tests are about the loop, and a test that
depends on two moving parts tells you less when it goes red.

The thing most of these are really checking is that nothing gets sent. There are
four locks on the live path and each one is tested on its own, because a safety
net that is only tested as a whole tells you nothing about which strand is
holding.

Dates: 2026-09-08 is a Tuesday and the market is open. 2026-09-12 is a Saturday.
2026-09-07 is a Monday, Labor Day, and the market is shut: it is one of the three
dates in schedule.holidays in config/guardrails.yaml.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_books.py -q
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import date, datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent import book_state as bs
from agent import broker as broker_mod
from agent import guardrails as gr
from agent import loop
from agent import pdt as pdt_mod

REAL_ROOT = Path(__file__).resolve().parent.parent
BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")

TUESDAY = date(2026, 9, 8)
SATURDAY = date(2026, 9, 12)


def at(hour: int, minute: int, day: date = TUESDAY) -> datetime:
    return datetime.combine(day, clock_time(hour, minute), tzinfo=NEW_YORK)


# ---------------------------------------------------------------------------
# The fake broker: nine methods, and it counts the three that could do harm
# ---------------------------------------------------------------------------


class CountingBroker:
    """Everything agent/broker.py's Broker protocol asks for, and nothing more.

    The three order methods raise. That is the point: if the loop ever calls one
    of them in a test, the test fails loudly rather than quietly passing with a
    None back.
    """

    def __init__(self, positions=None, orders=None, price=100.0, bars=None):
        self._positions = positions or []
        self._orders = orders or []
        self._price = price
        self._bars = bars
        self.calls: list[str] = []
        self.order_calls: list[tuple] = []
        self.allow_orders = False

    # -- reading ----------------------------------------------------------

    def account_summary(self, account=None) -> dict:
        self.calls.append("account_summary")
        return {"account": account or "DUT077572",
                "items": [{"tag": "NetLiquidation", "value": "1000000"},
                          {"tag": "TotalCashValue", "value": "1000000"}]}

    def portfolio(self, account=None, include_pnl=True) -> dict:
        self.calls.append("portfolio")
        return {"account": account or "DUT077572", "positions": self._positions,
                "totals": {}, "notes": []}

    def open_orders(self, account=None, include_all=True) -> dict:
        self.calls.append("open_orders")
        return {"orders": list(self._orders), "notes": []}

    def executions(self, account=None, symbol=None, sec_type=None, exchange=None,
                   side=None, time=None) -> dict:
        self.calls.append("executions")
        return {"executions": [], "fills": [], "notes": []}

    def snapshot(self, contracts, market_data_type=3) -> dict:
        """Every quote says which market data type it is, because a real one does.

        A broker that answers a snapshot without saying whether the price is
        live or fifteen minutes old is not modelling a quiet market, it is
        modelling one that cannot answer, and the loop refuses to open a
        position on a price whose age nobody will vouch for.
        """
        self.calls.append("snapshot")
        return {"market_data_type": int(market_data_type),
                "snapshots": [{"symbol": c.get("symbol"), "last": self._price,
                               "close": self._price, "marketPrice": self._price,
                               "marketDataType": int(market_data_type)}
                              for c in contracts], "notes": []}

    def historical_bars(self, contract, duration, bar_size, what="TRADES",
                        use_rth=True, end_date_time="") -> dict:
        self.calls.append("historical_bars")
        if self._bars is not None:
            return {"bars": list(self._bars), "notes": []}
        return {"bars": [{"time": "2026-09-08 09:35:00", "open": self._price,
                          "high": self._price, "low": self._price,
                          "close": self._price, "volume": 10000,
                          "average": self._price}], "notes": []}

    # -- acting -----------------------------------------------------------

    def place_order(self, contract, order, order_ref) -> dict:
        self.order_calls.append(("place", contract, order, order_ref))
        if not self.allow_orders:
            raise AssertionError(
                "the loop tried to place an order in a test that forbids it: "
                f"{order} for {contract} tagged {order_ref}")
        return {"sent": True, "order_id": 1, "filled_qty": 0.0,
                "avg_fill_price": None, "working": True, "error": None,
                "raw": {}, "confirmed_by": "open_orders"}

    def cancel_order(self, order_id) -> dict:
        self.order_calls.append(("cancel", order_id))
        raise AssertionError("the loop tried to cancel an order in a test")

    def global_cancel(self) -> dict:
        self.order_calls.append(("global_cancel",))
        raise AssertionError("the loop tried to cancel every order in a test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A project root of its own, with its own empty output folder.

    config, strategies, agent and venv312 are symlinked to the real ones, so the
    books and their limits are the real files rather than a copy that could
    drift. Only output/ is fresh, which is what keeps one test from reading
    another one's state files.
    """
    for name in ("config", "strategies", "agent", "venv312"):
        (tmp_path / name).symlink_to(REAL_ROOT / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(loop.LIVE_ENV_VAR, raising=False)
    return tmp_path


@pytest.fixture
def books():
    return gr.load_books(BOOKS_YAML)


def guard_for(book_id: str) -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def plan_for(book_id: str) -> loop.BookPlan:
    registry = gr.load_books(BOOKS_YAML)
    return loop.plan_for(registry.get(book_id), guard_for(book_id))


def write_shortlist(root: Path, name: str, rows: list[dict]) -> Path:
    path = root / "output" / name
    path.write_text(json.dumps({"candidates": rows}))
    return path


# ---------------------------------------------------------------------------
# Which phase each strategy is in, at several times of day
# ---------------------------------------------------------------------------


def test_momentum_phases_through_the_day():
    plan = plan_for("A")
    assert plan.family == loop.MOMENTUM
    assert plan.manage_minutes == 5
    assert plan.flat_by_close is True

    # 09:00 is when the pre-open run starts, not when the book is idle. It
    # gathers the history the 09:35 ranking needs, spread out so the data budget
    # is not spent in the five minutes around the open. See docs/PREOPEN_FLOW.md.
    assert loop.phase_for(at(8, 55), plan)[0] == loop.IDLE
    assert loop.phase_for(at(9, 0), plan)[0] == loop.PREOPEN
    assert loop.phase_for(at(9, 25), plan)[0] == loop.PREOPEN
    assert loop.phase_for(at(9, 31), plan)[0] == loop.SCAN
    assert loop.phase_for(at(9, 36), plan)[0] == loop.PICK
    assert loop.phase_for(at(9, 36), plan, pick_done=True)[0] == loop.MANAGE
    assert loop.phase_for(at(10, 15), plan, pick_done=True)[0] == loop.MANAGE
    assert loop.phase_for(at(12, 5), plan, pick_done=True)[0] == loop.MANAGE
    # Past the entry window with no pick, it manages rather than picking.
    assert loop.phase_for(at(12, 5), plan)[0] == loop.MANAGE
    assert loop.phase_for(at(15, 46), plan, pick_done=True)[0] == loop.FLATTEN
    assert loop.phase_for(at(15, 56), plan, pick_done=True)[0] == loop.FLATTEN
    assert loop.phase_for(at(16, 5), plan, pick_done=True)[0] == loop.CLOSED
    assert loop.phase_for(at(10, 15, SATURDAY), plan)[0] == loop.CLOSED


def test_insider_phases_including_both_sweeps():
    plan = plan_for("C")
    assert plan.family == loop.INSIDER
    assert plan.manage_minutes == 30
    assert plan.flat_by_close is False
    assert [f"{t:%H:%M}" for t in plan.sweep_times] == ["07:00", "16:30"]

    assert loop.phase_for(at(7, 0), plan)[0] == loop.SWEEP
    assert loop.phase_for(at(16, 30), plan)[0] == loop.SWEEP
    # Once a slot has run it does not run again, however many ticks land in it.
    assert loop.phase_for(at(7, 5), plan, swept_at={"07:00": "done"})[0] == loop.IDLE
    # It never scans and it never flattens.
    assert loop.phase_for(at(9, 31), plan)[0] == loop.IDLE
    assert loop.phase_for(at(9, 36), plan)[0] == loop.IDLE
    assert loop.phase_for(at(9, 46), plan)[0] == loop.PICK
    assert loop.phase_for(at(15, 56), plan, pick_done=True)[0] == loop.MANAGE


def test_congress_has_one_sweep_and_a_thirty_minute_clock():
    plan = plan_for("D")
    assert plan.family == loop.CONGRESS
    assert [f"{t:%H:%M}" for t in plan.sweep_times] == ["07:30"]
    assert loop.phase_for(at(7, 30), plan)[0] == loop.SWEEP
    assert loop.phase_for(at(9, 46), plan)[0] == loop.PICK
    assert loop.phase_for(at(15, 56), plan, pick_done=True)[0] == loop.MANAGE
    assert loop.phase_for(at(16, 5), plan, pick_done=True)[0] == loop.CLOSED


def test_a_thirty_minute_book_waits_between_looks():
    plan = plan_for("C")
    last = at(10, 0).isoformat()
    assert loop.phase_for(at(10, 15), plan, pick_done=True,
                          last_manage_at=last)[0] == loop.IDLE
    assert loop.phase_for(at(10, 30), plan, pick_done=True,
                          last_manage_at=last)[0] == loop.MANAGE
    # A five minute book looks on every tick.
    momentum = plan_for("A")
    assert loop.phase_for(at(10, 5), momentum, pick_done=True,
                          last_manage_at=at(10, 0).isoformat())[0] == loop.MANAGE


# ---------------------------------------------------------------------------
# The four locks on the live path
# ---------------------------------------------------------------------------


def _book(book_id: str = "A", mode: str = "dry_run") -> gr.BookConfig:
    registry = gr.load_books(BOOKS_YAML)
    return dataclasses.replace(registry.get(book_id), mode=mode)


def test_every_book_in_the_register_is_dry_run(books):
    for book in books.books:
        assert book.mode == "dry_run", (
            f"book {book.book_id} is in {book.mode} mode. Nothing in this project "
            "may send an order until Mo promotes a book by hand.")


def test_a_dry_run_book_cannot_open_the_locks(sandbox):
    guards = loop.read_guards()
    open_locks, shut = loop.live_locks(_book("A", "dry_run"), "DUT077572", guards)
    assert open_locks is False
    assert any("dry_run mode" in reason for reason in shut)
    assert any(loop.LIVE_ENV_VAR in reason for reason in shut)


def test_a_full_book_without_the_environment_variable_is_still_shut(sandbox):
    guards = loop.read_guards()
    open_locks, shut = loop.live_locks(_book("A", "full"), "DUT077572", guards)
    assert open_locks is False
    assert shut == [f"{loop.LIVE_ENV_VAR} is not set to yes"]


def test_a_live_account_id_shuts_the_locks(sandbox):
    guards = loop.read_guards()
    open_locks, shut = loop.live_locks(_book("A", "full"), "U1234567", guards)
    assert open_locks is False
    assert any("does not start with DU" in reason for reason in shut)


@pytest.mark.parametrize("guard_file", ["STOP", "LOOP_DISABLED", "NO_TRADE_TODAY"])
def test_each_guard_file_shuts_the_locks(sandbox, guard_file):
    (sandbox / "output" / guard_file).write_text("")
    guards = loop.read_guards()
    open_locks, shut = loop.live_locks(_book("A", "full"), "DUT077572", guards)
    assert open_locks is False
    assert any(guard_file in reason for reason in shut)


def test_a_full_mode_book_without_the_variable_never_reaches_the_broker(sandbox):
    """The whole point: even with the mode open, nothing is sent."""
    broker = CountingBroker()
    guard = guard_for("A")
    book = _book("A", "full")
    tick = loop.BookTick(book, at(9, 40), "testhash", write_ledger=False, quiet=True)
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    account_state = bs.account_state_for(state, gr, at(9, 40), "DUT077572", False, {})
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=100.0,
                            purpose="entry", book_id="A", sector="Technology")

    decision = loop.consider(tick, state, guard, account_state, intent, broker,
                             loop.read_guards())

    assert decision.allowed is True, decision.reasons
    assert broker.order_calls == []
    assert tick.sent == 0
    assert tick.would_be_orders == 1


def test_the_order_reference_is_the_books_own_tag(sandbox):
    """Whatever else happens, an order carries the tag of the book that sent it."""
    broker = CountingBroker()
    broker.allow_orders = True
    guard = guard_for("A")
    tick = loop.BookTick(_book("A", "full"), at(9, 40), "testhash",
                         write_ledger=False, quiet=True)
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=100.0,
                            purpose="entry", book_id="A", sector="Technology")

    loop.submit(tick, state, intent, broker, guard)

    kind, contract, order, order_ref = broker.order_calls[0]
    assert kind == "place"
    assert order_ref == "BOOK_A" == guard.order_ref
    assert contract["symbol"] == "AAPL"
    assert order["action"] == "BUY" and order["totalQuantity"] == 10

    # And book C's tag is its own, so a fill can always be told apart.
    assert guard_for("C").order_ref == "BOOK_C"


# ---------------------------------------------------------------------------
# The three guard files, end to end
# ---------------------------------------------------------------------------


def test_loop_disabled_does_nothing_at_all(sandbox):
    (sandbox / "output" / "LOOP_DISABLED").write_text("")
    broker = CountingBroker()

    assert loop.main([], broker=broker) == 0
    assert broker.calls == []
    assert broker.order_calls == []
    assert not list((sandbox / "output").glob("state_*.json"))


def _momentum_shortlist():
    """Two candidate rows in the Momentum v2 shape (Mo, 2026-09-06).

    Each carries the first five minute candle, whose sign is the direction rule
    (item A5), the 14 day average true range the stop is measured from (item
    A1), its place in the relative volume ranking (item A4), and the industry
    the sector cap counts against (item A9). A row with no industry cannot be
    entered at all, so leaving one out is a test of that rule rather than a
    shortcut.
    """
    return [{"symbol": "AAPL", "opening_range_high": 100.0, "opening_range_low": 99.0,
             "opening_range_open": 99.2, "opening_range_close": 99.8,
             "atr": 2.0, "atr_pct_of_price": 2.0, "rank": 1, "sector": "Technology",
             "score": 3.0, "gain_pct": 4.0, "rel_volume": 3.0},
            {"symbol": "MSFT", "opening_range_high": 200.0, "opening_range_low": 198.0,
             "opening_range_open": 198.5, "opening_range_close": 199.5,
             "atr": 4.0, "atr_pct_of_price": 2.0, "rank": 2, "sector": "Health Care",
             "score": 2.5, "gain_pct": 3.0, "rel_volume": 2.5}]


def _pick_tick(sandbox, book_id="B", now=None, halt_reason=None, broker=None,
               guards=None):
    """Run one book through its pick phase with a shortlist already on disk.

    guards defaults to the marker files alone, with no day, so the pre-flight
    verdict is not consulted. Pass loop.read_guards(day=...) to test that half.
    """
    now = now or at(9, 40)
    write_shortlist(sandbox, f"shortlist_{now.date():%Y-%m-%d}.json",
                    _momentum_shortlist())
    registry = gr.load_books(BOOKS_YAML)
    book = registry.get(book_id)
    broker = broker or CountingBroker(price=100.0)
    return loop.run_book(book, guard_for(book_id), now,
                         guards if guards is not None else loop.read_guards(),
                         broker,
                         "DUT077572", {}, "testhash", write_ledger=False,
                         halt_reason=halt_reason, quiet=True), broker


def test_a_dry_run_book_picks_and_never_calls_an_order_method(sandbox):
    (tick, state), broker = _pick_tick(sandbox, "B")
    assert tick.phase == loop.PICK
    assert state.picks, "the rules only book should have picked from the shortlist"
    assert tick.would_be_orders >= 1
    assert broker.order_calls == []
    assert tick.sent == 0
    # And what it decided is written down, with the rules hash on every row.
    assert state.decisions
    assert all(row["rules_commit"] == "testhash" for row in state.decisions)


def test_no_trade_today_stops_entries_and_leaves_exits_alone(sandbox):
    (sandbox / "output" / "NO_TRADE_TODAY").write_text("")
    (tick, state), broker = _pick_tick(sandbox, "B")

    assert state.picks, "the picks are still made and written down"
    assert tick.would_be_orders == 0, "and not one of them became an order"
    assert broker.order_calls == []
    assert any("NO_TRADE_TODAY" in row["rationale"] for row in state.decisions)

    # An exit still goes through the checks, which is the half that matters.
    guard = guard_for("B")
    # shorts are switched off for month one, so let this closing sale be judged as an
    # exit rather than a short: the point of the test is the STOP and NO_TRADE gates
    guard = dataclasses.replace(guard, universe=dataclasses.replace(guard.universe, allow_shorts=True))
    guards = loop.read_guards()
    exit_intent = gr.OrderIntent(symbol="AAPL", side="SELL", qty=10,
                                 limit_price=100.0, purpose="exit", book_id="B")
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False, {})
    decision = gr.check_order(guard, account_state, exit_intent)
    assert decision.allowed is True, decision.reasons
    assert loop.entries_blocked_reason(guards, state) is not None


# --------------------------------- no pre-flight pass, no new position
#
# 2026-09-10. IB Gateway was down from about 03:00 to 11:27, the 09:00
# pre-flight could not reach it and wrote no verdict at all, and when Gateway
# came back nothing on disk said the morning had failed. The loop had no way of
# telling "the checks passed" from "the checks never ran". These tests hold the
# rule that fixes it: a missing verdict counts exactly like NO_TRADE_TODAY.


def write_verdict(sandbox, verdict, day=TUESDAY, failed=None):
    """Write output/preflight_YYYY-MM-DD.json the way agent/preflight.py does."""
    path = sandbox / "output" / f"preflight_{day:%Y-%m-%d}.json"
    path.write_text(json.dumps({"run_at": f"{day}T09:00:00-04:00",
                                "verdict": verdict, "dry_run": False,
                                "failed_checks": list(failed or [])}),
                    encoding="utf-8")
    return path


def test_no_pre_flight_verdict_stops_entries_and_leaves_exits_alone(sandbox):
    guards = loop.read_guards(day=TUESDAY)
    assert not guards.preflight_verdict.exists(), "no verdict was written"

    (tick, state), broker = _pick_tick(sandbox, "B", guards=guards)

    assert state.picks, "the picks are still made and written down"
    assert tick.would_be_orders == 0, "and not one of them became an order"
    assert broker.order_calls == []
    assert any("no pre-flight verdict" in row["rationale"]
               for row in state.decisions)

    # An exit still goes through the checks, which is the half that matters.
    guard = guard_for("B")
    guard = dataclasses.replace(
        guard, universe=dataclasses.replace(guard.universe, allow_shorts=True))
    exit_intent = gr.OrderIntent(symbol="AAPL", side="SELL", qty=10,
                                 limit_price=100.0, purpose="exit", book_id="B")
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False, {})
    decision = gr.check_order(guard, account_state, exit_intent)
    assert decision.allowed is True, decision.reasons
    assert loop.entries_blocked_reason(guards, state) is not None


def test_a_pre_flight_that_passed_lets_entries_through(sandbox):
    write_verdict(sandbox, "pass")
    guards = loop.read_guards(day=TUESDAY)
    assert guards.preflight_refusal is None

    (tick, state), broker = _pick_tick(sandbox, "B", guards=guards)

    assert state.picks
    assert tick.would_be_orders >= 1, "a passing morning opens positions"
    assert broker.order_calls == [], "still dry run, so nothing was sent"


def test_a_failed_pre_flight_verdict_stops_entries_and_names_the_checks(sandbox):
    write_verdict(sandbox, "fail", failed=["gateway_login", "market_data"])
    guards = loop.read_guards(day=TUESDAY)

    (tick, state), broker = _pick_tick(sandbox, "B", guards=guards)

    assert tick.would_be_orders == 0
    reason = loop.entries_blocked_reason(guards, state)
    assert reason and "gateway_login" in reason and "market_data" in reason


def test_yesterdays_verdict_does_not_count_for_today(sandbox):
    """A pass on file from Monday says nothing about Tuesday."""
    write_verdict(sandbox, "pass", day=date(2026, 9, 7))
    guards = loop.read_guards(day=TUESDAY)
    assert guards.preflight_refusal is not None
    assert "no pre-flight verdict" in guards.preflight_refusal


def test_a_verdict_file_that_cannot_be_read_counts_as_a_fail(sandbox):
    (sandbox / "output" / f"preflight_{TUESDAY:%Y-%m-%d}.json").write_text(
        "{half written", encoding="utf-8")
    guards = loop.read_guards(day=TUESDAY)
    reason = guards.preflight_refusal
    assert reason and "could not be read" in reason


def test_guards_with_no_day_do_not_consult_a_verdict(sandbox):
    """The readers that run before the clock is known must not be blocked."""
    guards = loop.read_guards()
    assert guards.preflight_verdict is None
    assert guards.preflight_refusal is None


def test_a_missing_verdict_shuts_the_live_order_path_too(sandbox):
    """Belt and braces: the same brake as NO_TRADE_TODAY on the live locks."""
    registry = gr.load_books(BOOKS_YAML)
    book = registry.get("B")
    open_now, shut = loop.live_locks(book, "DUT077572",
                                     loop.read_guards(day=TUESDAY))
    assert open_now is False
    assert any("pre-flight" in reason for reason in shut)


def test_the_tick_asks_for_the_verdict_of_the_day_it_thinks_it_is(sandbox):
    """A rehearsal of another date must look for that date's verdict."""
    source = (REAL_ROOT / "agent" / "loop.py").read_text(encoding="utf-8")
    assert "read_guards(day=now.date())" in source, (
        "run_one_tick has to pass the tick's own day, or the whole brake is off")


def test_stop_allows_exits_only(sandbox):
    (sandbox / "output" / "STOP").write_text("")
    (tick, state), broker = _pick_tick(sandbox, "B")

    assert tick.would_be_orders == 0
    assert broker.order_calls == []
    reason = loop.entries_blocked_reason(loop.read_guards(), state)
    assert reason and "STOP" in reason

    # With the stop file there, the guardrails refuse an entry and allow an exit.
    guard = guard_for("B")
    # shorts are off for month one; judge the closing sale as an exit, the test is about STOP
    guard = dataclasses.replace(guard, universe=dataclasses.replace(guard.universe, allow_shorts=True))
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572",
                                         kill_switch_present=True,
                                         broker_positions={})
    entry = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=100.0,
                           purpose="entry", book_id="B")
    exit_order = gr.OrderIntent(symbol="AAPL", side="SELL", qty=10, limit_price=100.0,
                                purpose="exit", book_id="B")
    assert gr.check_order(guard, account_state, entry).allowed is False
    assert "kill_switch" in gr.check_order(guard, account_state, entry).rule_ids
    assert gr.check_order(guard, account_state, exit_order).allowed is True


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_a_mismatch_halts_only_the_book_it_belongs_to(sandbox):
    books_state = {
        "A": {"positions": {"AAPL": 100}, "working_orders": {}},
        "B": {"positions": {"MSFT": 50}, "working_orders": {}},
    }
    # The broker has book B's holding and nothing of book A's.
    outcome = loop.run_reconciliation(
        [{"symbol": "MSFT", "qty": 50, "avg_cost": 200.0}], [], books_state, None)

    assert outcome.available is True
    assert outcome.ok is False
    assert outcome.books_to_halt == ["A"]
    assert "B" not in outcome.books_to_halt


def test_everything_matching_halts_nobody(sandbox):
    books_state = {"A": {"positions": {"AAPL": 100}, "working_orders": {}},
                   "B": {"positions": {}, "working_orders": {}}}
    outcome = loop.run_reconciliation(
        [{"symbol": "AAPL", "qty": 100, "avg_cost": 100.0}], [], books_state, None)
    assert outcome.ok is True
    assert outcome.books_to_halt == []


def test_a_halted_book_opens_nothing(sandbox):
    (tick, state), broker = _pick_tick(
        sandbox, "B", halt_reason="the books and the broker disagree")
    assert state.halted is True
    assert tick.would_be_orders == 0
    assert broker.order_calls == []


def test_the_loop_halts_every_book_when_reconciliation_is_missing(sandbox, monkeypatch):
    """agent/reconcile.py going missing must not let the loop carry on regardless."""
    monkeypatch.setattr(loop, "reconcile_mod", None)
    monkeypatch.setattr(loop, "RECONCILE_ERROR", "ModuleNotFoundError: no reconcile")
    outcome = loop.run_reconciliation([], [], {"A": {}, "B": {}, "C": {}}, None)

    assert outcome.available is False
    assert outcome.ok is False
    assert sorted(outcome.books_to_halt) == ["A", "B", "C"]
    assert "reconciliation unavailable, halting all books" in outcome.note


def test_broker_rows_are_translated_into_what_reconcile_reads():
    positions = {"SPY": {"symbol": "SPY", "position": 1.0, "avgCost": 766.15}}
    orders = [{"orderId": 4, "symbol": "SPY", "action": "BUY", "totalQuantity": 1,
               "orderRef": "BOOK_A"}]
    assert loop.broker_positions_for_reconcile(positions) == [
        {"symbol": "SPY", "qty": 1, "avg_cost": 766.15}]
    assert loop.broker_orders_for_reconcile(orders) == [
        {"orderId": 4, "symbol": "SPY", "side": "BUY", "qty": 1,
         "order_ref": "BOOK_A"}]


# ---------------------------------------------------------------------------
# The day trade counter
# ---------------------------------------------------------------------------


def _use_up_the_allowance(counter, day: date) -> None:
    """Three round trips today, which is the allowance in every strategy file."""
    when = datetime.combine(day, clock_time(10, 0), tzinfo=NEW_YORK)
    for symbol in ("AAA", "BBB", "CCC"):
        counter.record_fill(symbol, "BUY", 10, when)
        counter.record_fill(symbol, "SELL", 10, when)


def _fourth_day_trade(counter, day: date) -> gr.OrderIntent:
    """Open a fourth name today, so selling it now would be day trade number four."""
    when = datetime.combine(day, clock_time(11, 0), tzinfo=NEW_YORK)
    counter.record_fill("DDD", "BUY", 10, when)
    return gr.OrderIntent(symbol="DDD", side="SELL", qty=10, limit_price=50.0,
                          purpose="exit", book_id=None)


def test_a_fourth_day_trade_is_refused_on_book_c(tmp_path):
    guard = guard_for("C")
    assert guard.pdt.hard_limit is True
    counter = pdt_mod.DayTradeCounter("C", tmp_path / "pdt_BOOK_C.json")
    _use_up_the_allowance(counter, TUESDAY)
    intent = dataclasses.replace(_fourth_day_trade(counter, TUESDAY), book_id="C")

    verdict = loop.day_trade_check(guard, intent, TUESDAY, counter, opened_on="2026-09-08")

    assert verdict.blocked is True
    assert verdict.used == 3
    assert "hold" in verdict.reason.lower() or "day trade" in verdict.reason.lower()


def test_the_same_fourth_day_trade_is_only_flagged_on_book_a(tmp_path):
    guard = guard_for("A")
    assert guard.pdt.hard_limit is False
    counter = pdt_mod.DayTradeCounter("A", tmp_path / "pdt_BOOK_A.json")
    _use_up_the_allowance(counter, TUESDAY)
    intent = dataclasses.replace(_fourth_day_trade(counter, TUESDAY), book_id="A")

    verdict = loop.day_trade_check(guard, intent, TUESDAY, counter, opened_on="2026-09-08")

    assert verdict.blocked is False
    assert verdict.would_have_blocked is True
    assert verdict.used == 3


def test_closing_something_opened_another_day_is_not_a_day_trade(tmp_path):
    guard = guard_for("C")
    counter = pdt_mod.DayTradeCounter("C", tmp_path / "pdt_BOOK_C.json")
    _use_up_the_allowance(counter, TUESDAY)
    intent = gr.OrderIntent(symbol="ZZZ", side="SELL", qty=10, limit_price=50.0,
                            purpose="exit", book_id="C")

    verdict = loop.day_trade_check(guard, intent, TUESDAY, counter,
                                   opened_on="2026-08-01")

    assert verdict.blocked is False
    assert verdict.is_day_trade is False


def test_with_no_counter_a_day_trade_is_written_down_and_let_through():
    """Refusing to close a position because a counter file is missing is worse."""
    guard = guard_for("C")
    intent = gr.OrderIntent(symbol="ZZZ", side="SELL", qty=10, limit_price=50.0,
                            purpose="exit", book_id="C")
    verdict = loop.day_trade_check(guard, intent, TUESDAY, None,
                                   opened_on="2026-09-08")
    assert verdict.is_day_trade is True
    assert verdict.blocked is False


# ---------------------------------------------------------------------------
# The ways out of a position
# ---------------------------------------------------------------------------


def _position(**changes) -> bs.Position:
    base = dict(symbol="AAPL", qty=100, avg_cost=100.0, opened_on="2026-09-08",
                entry=100.0, stop=98.5, target=103.0, side="long",
                trailing_high_or_low=100.0)
    base.update(changes)
    return bs.Position(**base)


def test_the_stop_the_target_and_the_fade_each_close_a_long():
    plan = plan_for("A")
    guard = guard_for("A")
    assert loop.exit_reason_for(_position(), plan, guard, TUESDAY, 98.0, None)[0] == "stop"
    assert loop.exit_reason_for(_position(), plan, guard, TUESDAY, 103.5,
                                None)[0] == "target"
    # A fade needs risk.vwap_fade_closes closes in a row the wrong side of VWAP,
    # which is 2 for this book, so one close below is still a hold.
    assert loop.exit_reason_for(_position(), plan, guard, TUESDAY, 100.5, 101.0,
                                closes_through_vwap=1)[0] is None
    assert loop.exit_reason_for(_position(), plan, guard, TUESDAY, 100.5, 101.0,
                                closes_through_vwap=2)[0] == "fade_observed"
    assert loop.exit_reason_for(_position(), plan, guard, TUESDAY, 100.5,
                                100.0)[0] is None


def test_a_short_is_the_mirror_image():
    plan = plan_for("A")
    guard = guard_for("A")
    short = _position(qty=-100, side="short", entry=100.0, stop=101.5, target=97.0)
    assert loop.exit_reason_for(short, plan, guard, TUESDAY, 102.0, None)[0] == "stop"
    assert loop.exit_reason_for(short, plan, guard, TUESDAY, 96.5, None)[0] == "target"
    # For a short, being back above the vwap is the fade, and it still takes
    # risk.vwap_fade_closes of them in a row.
    assert loop.exit_reason_for(short, plan, guard, TUESDAY, 99.0, 98.0,
                                closes_through_vwap=1)[0] is None
    assert loop.exit_reason_for(short, plan, guard, TUESDAY, 99.0, 98.0,
                                closes_through_vwap=2)[0] == "fade_observed"


def test_the_insider_book_has_a_time_stop_and_no_fade():
    plan = plan_for("C")
    guard = guard_for("C")
    assert guard.risk.time_stop_trading_days == 30
    old = _position(opened_on="2026-06-01", stop=90.0, target=130.0,
                    trailing_high_or_low=100.0)
    assert loop.exit_reason_for(old, plan, guard, TUESDAY, 100.0, None)[0] == "time"
    # A fresh one with the price in the middle is held, and the vwap is ignored
    # because this book does not trade the opening push.
    fresh = _position(opened_on="2026-09-05", stop=90.0, target=130.0,
                      trailing_high_or_low=100.0)
    assert loop.exit_reason_for(fresh, plan, guard, TUESDAY, 100.0, 105.0)[0] is None


def test_the_trailing_stop_follows_the_best_price():
    plan = plan_for("C")
    guard = guard_for("C")
    assert guard.risk.trailing_stop_pct == 10
    assert guard.risk.trailing_activation_pct == 8
    # Up 20 percent at its best, so the trailing stop sits 10 percent under 120.
    winner = _position(opened_on="2026-09-05", entry=100.0, avg_cost=100.0,
                       stop=90.0, target=500.0, trailing_high_or_low=120.0)
    trigger, why = loop.exit_reason_for(winner, plan, guard, TUESDAY, 107.0, None)
    assert trigger == "trailing"
    assert "108.00" in why


# ---------------------------------------------------------------------------
# The book files, and the account state the guardrails see
# ---------------------------------------------------------------------------


def test_each_book_gets_its_own_file_named_after_its_tag(sandbox):
    state = bs.load_state("C", "BOOK_C", TUESDAY, capital=100000)
    path = bs.save_state(state)
    assert path.name == "state_BOOK_C_2026-09-08.json"
    assert path.parent == sandbox / "output"
    again = bs.load_state("C", "BOOK_C", TUESDAY, capital=100000)
    assert again.book_id == "C" and again.capital == 100000


def test_a_books_account_state_is_its_own_money_not_the_accounts(sandbox):
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(_position(qty=100, avg_cost=100.0))
    state.entries_opened_today = 2
    broker_positions = {"AAPL": {"symbol": "AAPL", "position": 400.0,
                                 "marketPrice": 110.0, "marketValue": 44000.0}}

    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False,
                                         broker_positions)

    # The account holds 400 shares across the five books. This book holds 100.
    assert account_state.open_positions["AAPL"].qty == 100
    assert account_state.book_id == "A"
    assert account_state.entries_opened_today == 2
    assert account_state.gross_exposure == pytest.approx(11000.0)
    assert account_state.equity == pytest.approx(101000.0)


def test_positions_carry_over_to_the_next_day(sandbox):
    monday = bs.load_state("C", "BOOK_C", date(2026, 9, 7), capital=100000)
    monday.put_position(_position(symbol="XYZ", qty=50, opened_on="2026-09-07"))
    monday.cash = 95000.0
    bs.save_state(monday)

    tuesday = bs.load_state("C", "BOOK_C", TUESDAY, capital=100000)
    assert "XYZ" in tuesday.all_positions()
    assert tuesday.cash == 95000.0
    assert tuesday.halted is False


# ---------------------------------------------------------------------------
# The shortlists the three strategies read
# ---------------------------------------------------------------------------


def test_a_sweep_row_keyed_by_ticker_is_read_as_a_symbol():
    row = loop.normalise_candidate({"ticker": "aapl", "issuer_name": "Apple Inc",
                                    "cluster_count": 3})
    assert row["symbol"] == "AAPL"
    assert row["company"] == "Apple Inc"
    assert row["cluster_size"] == 3


def test_each_strategy_reads_its_own_shortlist_file(sandbox):
    assert loop.shortlist_path(plan_for("A"), TUESDAY).name == "shortlist_2026-09-08.json"
    assert loop.shortlist_path(plan_for("C"), TUESDAY).name == \
        "insider_shortlist_2026-09-08.json"
    assert loop.shortlist_path(plan_for("D"), TUESDAY).name == \
        "congress_shortlist_2026-09-08.json"


def test_a_missing_shortlist_is_not_an_error(sandbox):
    rows, message = loop.read_shortlist(sandbox / "output" / "nothing_here.json")
    assert rows == []
    assert "nothing to pick from" in message


# ---------------------------------------------------------------------------
# What the broker says about borrowing, which today is nothing
# ---------------------------------------------------------------------------


def test_the_live_servers_snapshot_says_nothing_about_borrowing():
    """The exact shape the MCP server returned on 2026-09-06, borrow fields and all."""
    row = {"conId": 756733, "symbol": "SPY", "secType": "STK", "bid": -1.0,
           "ask": -1.0, "last": 769.45, "close": 773.17, "marketPrice": 769.45,
           "delta": None, "gamma": None}
    terms = broker_mod.borrow_terms(row)
    assert terms.shortable is False
    assert terms.level is None
    assert terms.fee_pct_annual is None
    assert terms.shares_available is None
    assert "has not confirmed" in terms.note


def test_borrow_terms_are_read_the_day_the_server_reports_them():
    terms = broker_mod.borrow_terms({"symbol": "AAPL", "shortable": 3.0,
                                     "shortableShares": 2500000, "feeRate": 0.25})
    assert terms.shortable is True
    assert terms.level == 3.0
    assert terms.shares_available == 2500000
    assert terms.fee_pct_annual == 0.25
    assert "2,500,000" in terms.note


def test_a_short_with_no_borrow_confirmed_is_refused(sandbox):
    """The guardrails, not the loop, are what stop it. This checks the wiring."""
    guard = guard_for("A")
    assert guard.universe.require_shortable is True
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    account_state = bs.account_state_for(state, gr, at(9, 40), "DUT077572", False, {})

    borrow = broker_mod.borrow_terms(None)
    intent = loop._entry_intent("TSLA", short=True, quantity=10, price=250.0,
                                book_id="A", borrow=borrow)

    assert intent.side == "SELL"
    assert intent.shortable is False
    assert intent.shortable_level is None
    assert intent.borrow_fee_pct_annual is None
    assert intent.shares_available_to_borrow is None
    decision = gr.check_order(guard, account_state, intent)
    assert decision.allowed is False
    assert "shortable_required" in decision.rule_ids


def test_a_long_carries_no_borrow_fields_at_all():
    borrow = broker_mod.borrow_terms({"symbol": "AAPL", "shortable": 3.0,
                                      "shortableShares": 100, "feeRate": 0.25})
    intent = loop._entry_intent("AAPL", short=False, quantity=10, price=100.0,
                                book_id="A", borrow=borrow)
    assert intent.side == "BUY"
    assert intent.shortable is False
    assert intent.shortable_level is None
    assert intent.borrow_fee_pct_annual is None
    assert intent.shares_available_to_borrow is None


# ---------------------------------------------------------------------------
# A whole tick, all five books, nothing sent
# ---------------------------------------------------------------------------


def test_one_tick_runs_every_enabled_book_and_sends_nothing(sandbox):
    write_shortlist(sandbox, "shortlist_2026-09-08.json", _momentum_shortlist())
    broker = CountingBroker(price=100.0)

    assert loop.main(["--now", "2026-09-08 09:40"], broker=broker) == 0

    written = sorted(p.name for p in (sandbox / "output").glob("state_BOOK_*.json"))
    assert written == ["state_BOOK_A_2026-09-08.json", "state_BOOK_B_2026-09-08.json",
                       "state_BOOK_C_2026-09-08.json", "state_BOOK_D_2026-09-08.json",
                       "state_BOOK_E_2026-09-08.json"]
    assert broker.order_calls == []
    log = (sandbox / "output" / "loop.log").read_text()
    for book_id in "ABCDE":
        assert f"book={book_id}" in log
    assert "sent=0" in log


def test_one_book_can_be_run_on_its_own(sandbox):
    broker = CountingBroker()
    assert loop.main(["--now", "2026-09-08 09:40", "--book", "C"], broker=broker) == 0
    written = sorted(p.name for p in (sandbox / "output").glob("state_BOOK_*.json"))
    assert written == ["state_BOOK_C_2026-09-08.json"]
    assert broker.order_calls == []


def test_an_unknown_book_is_refused(sandbox):
    assert loop.main(["--book", "Z"], broker=CountingBroker()) == 2


# ---------------------------------------------------------------------------
# Market holidays: a closed day for every book, backlog item 9
# ---------------------------------------------------------------------------

#: Monday 2026-09-07 is Labor Day and the US market is shut. It is one of the
#: three dates in schedule.holidays in config/guardrails.yaml, along with
#: Thanksgiving and Christmas.
LABOR_DAY = date(2026, 9, 7)

#: Every phase helper the loop can hand a book's turn to. On a closed day none
#: of them may be reached, so the holiday tests replace all of them with
#: something that fails the test loudly rather than quietly doing the work.
ACTING_HELPERS = ("do_preopen", "do_sweep", "do_scan", "do_pick", "do_manage",
                  "do_flatten", "write_daily")


@pytest.fixture
def helpers_called(monkeypatch) -> list[str]:
    """Every phase helper replaced by one that writes its name down and returns.

    Recorded rather than raised on purpose. run_book() catches Exception around
    the phase it dispatches to, so a helper that raised would be swallowed into
    a note, the phase would still read closed, and a test that asserted on the
    raise would pass whether or not the sweep had run. The list is the evidence.
    """
    seen: list[str] = []

    def recorder(name):
        def helper(*args, **kwargs):
            seen.append(name)
        return helper

    for name in ACTING_HELPERS:
        monkeypatch.setattr(loop, name, recorder(name))
    return seen


def test_the_plans_carry_the_holidays_from_the_shipped_settings():
    for book_id in "ABCDE":
        holidays = plan_for(book_id).holidays
        assert LABOR_DAY in holidays, f"book {book_id} does not know about Labor Day"
        assert date(2026, 11, 26) in holidays and date(2026, 12, 25) in holidays


def test_every_book_is_closed_all_day_on_a_holiday():
    """Not idle, not sweeping, not picking. Closed, and the reason names the day.

    07:31 is inside book D's 07:30 Congress sweep window and 09:36 is the
    momentum pick. Both of those really ran on the morning of 2026-09-07,
    against a market that was shut, which is the bug this closes.
    """
    for book_id in "ABCDE":
        plan = plan_for(book_id)
        for hour, minute in ((6, 30), (7, 0), (7, 31), (9, 0), (9, 31), (9, 36),
                             (12, 0), (15, 46), (15, 56), (16, 5)):
            phase, why = loop.phase_for(at(hour, minute, LABOR_DAY), plan)
            assert phase == loop.CLOSED, \
                f"book {book_id} at {hour:02d}:{minute:02d} on Labor Day said {phase}"
            assert "2026-09-07" in why and "holiday" in why, why


def test_the_same_minutes_on_the_tuesday_are_untouched():
    """The control. Take the holiday away and every phase is what it always was."""
    assert loop.phase_for(at(7, 31), plan_for("D"))[0] == loop.SWEEP
    assert loop.phase_for(at(7, 0), plan_for("C"))[0] == loop.SWEEP
    assert loop.phase_for(at(9, 0), plan_for("A"))[0] == loop.PREOPEN
    assert loop.phase_for(at(9, 31), plan_for("A"))[0] == loop.SCAN
    assert loop.phase_for(at(9, 36), plan_for("A"))[0] == loop.PICK


def test_a_holiday_is_a_closed_day_even_with_a_sweep_not_yet_run():
    """The holiday is checked before the sweeps, so a holiday morning sweeps nothing.

    There is nothing for a sweep to feed on a holiday: the pick it gathers for
    cannot happen either.
    """
    plan = plan_for("D")
    assert loop.sweep_due(at(7, 31, LABOR_DAY), plan, {}) == "07:30", \
        "the slot really is due, so the closed phase is the holiday and not the clock"
    assert loop.phase_for(at(7, 31, LABOR_DAY), plan, swept_at={})[0] == loop.CLOSED


@pytest.mark.parametrize("when", ["2026-09-07 09:36", "2026-09-07 07:31"])
def test_a_whole_tick_on_a_holiday_is_still_a_tick(sandbox, helpers_called, when):
    """Nothing is decided and nothing moves, but the tick still counts as a tick.

    The dead man's handle in agent/deadman.py flattens the account when the
    heartbeat goes stale, so a holiday that withheld the heartbeat would be far
    worse than one that traded.
    """
    broker = CountingBroker(price=100.0)

    assert loop.main(["--now", when], broker=broker) == 0

    assert helpers_called == [], \
        f"the market is shut and these ran anyway: {sorted(set(helpers_called))}"
    written = sorted(p.name for p in (sandbox / "output").glob("state_BOOK_*.json"))
    assert written == [f"state_BOOK_{book_id}_2026-09-07.json" for book_id in "ABCDE"]
    assert (sandbox / "output" / "heartbeat").exists()
    assert broker.order_calls == []

    log = (sandbox / "output" / "loop.log").read_text()
    lines = [line for line in log.splitlines() if line.strip()]
    assert len(lines) == 5, "one line per book, however shut the market is"
    for book_id, line in zip("ABCDE", lines):
        assert f"book={book_id}" in line
        assert "phase=closed" in line
        assert "2026-09-07 is a US market holiday" in line
        assert "sent=0" in line


def test_the_same_tick_on_the_tuesday_still_sweeps(sandbox, helpers_called):
    """The control for the test above, and what makes its empty list mean something.

    07:31 on 2026-09-08 is inside book D's 07:30 Congress sweep window, so the
    sweep really is reached on an ordinary Tuesday. If this stopped recording
    anything, the holiday test would be passing because nothing ever runs at
    07:31 rather than because the holiday stopped it.
    """
    assert loop.main(["--now", "2026-09-08 07:31"], broker=CountingBroker()) == 0
    assert "do_sweep" in helpers_called
    log = (sandbox / "output" / "loop.log").read_text()
    assert "phase=sweep" in log
    assert "holiday" not in log


def test_a_holiday_writes_no_end_of_day_and_the_next_trading_day_does(sandbox,
                                                                     monkeypatch):
    """The write up belongs to a day that traded, so 16:05 on a holiday skips it."""
    calls: list[str] = []
    monkeypatch.setattr(loop, "write_daily",
                        lambda tick, state: calls.append(tick.book.book_id))

    assert loop.main(["--now", "2026-09-07 16:05"], broker=CountingBroker()) == 0
    assert calls == [], "nothing to write up on a day the market never opened"

    assert loop.main(["--now", "2026-09-08 16:05"], broker=CountingBroker()) == 0
    assert calls == list("ABCDE")
