"""Fills come back off the broker, and they get there exactly once.

The most important thing the first replay gate run found. agent/loop.py recorded
a fill in exactly one place, from whatever place_order() handed straight back.
Nothing anywhere read executions(), and nothing turned a resting order into a
position later. Against a live market a marketable order comes back already
filled, so that mostly worked. Against a limit order that fills at 10:20 it did
not: the position existed at the broker and the book file had never heard of it,
the next reconciliation called it an orphan, and the day fell apart. The gate's
fake broker filled nineteen orders on a clean day and not one book file knew.

There is now exactly one path from a fill into a book file, and the exec id is
what stops it being walked twice. Both of those are what this file tests.

Nothing here touches a broker or a network.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_fills.py -q
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


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 8, hour, minute, tzinfo=NEW_YORK)


def execution(exec_id: str, symbol: str = "AAPL", side: str = "BUY",
              shares: int = 100, price: float = 100.0, order_id: str = "7",
              ref: str = "BOOK_A", when: str = "2026-09-08T09:38:00-04:00",
              commission: float = 1.0) -> dict:
    """One fill in the shape agent/replay/fake_broker.py writes them."""
    return {"execId": exec_id, "orderId": order_id, "orderRef": ref,
            "order_ref": ref, "symbol": symbol, "side": side, "shares": shares,
            "price": price, "time": when, "commission": commission}


class Filler:
    """A broker that has some executions and some working orders."""

    def __init__(self, fills: list[dict] | None = None,
                 orders: list[dict] | None = None):
        self.fills = fills or []
        self.orders = orders or []
        self.asked: list[str] = []

    def executions(self, account=None, symbol=None, sec_type=None, exchange=None,
                   side=None, time=None, order_ref=None):
        self.asked.append(str(order_ref or ""))
        return {"fills": list(self.fills), "executions": list(self.fills)}

    def open_orders(self, account=None, include_all=True):
        return {"orders": list(self.orders)}


class NoRefFilter(Filler):
    """The real broker's executions() takes no order reference at all."""

    def executions(self, account=None, symbol=None, sec_type=None, exchange=None,
                   side=None, time=None):
        self.asked.append("no order_ref argument")
        return {"executions": list(self.fills)}


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
    monkeypatch.setattr(loop.ledger_writer, "log_trade", lambda *a, **k: True)
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    monkeypatch.setattr(loop.ledger_writer, "log_decision", lambda *a, **k: True)
    loop._DB_TROUBLE.clear()
    return tmp_path


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(9, 40), "testhash", write_ledger=False,
                         quiet=True)


def guard_for(book_id: str = "A") -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def fresh_state() -> bs.BookState:
    return bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08",
                        capital=100000.0, cash=100000.0, day_start_equity=100000.0)


def with_a_resting_entry() -> bs.BookState:
    state = fresh_state()
    state.working_orders["7"] = {
        "symbol": "AAPL", "side": "BUY", "qty": 100, "remaining": 100,
        "limit_price": 100.0, "purpose": "entry",
        "placed_at": at(9, 35).isoformat(), "order_ref": "BOOK_A"}
    state.triggered["AAPL"] = {"at": at(9, 35).isoformat(), "price": 100.0,
                               "stop": 98.5, "target": 0.0, "qty": 100,
                               "side": "long"}
    return state


# ---------------------------------------------------------------------------
# Reading a fill, whatever it was called
# ---------------------------------------------------------------------------


def test_a_fill_is_read_however_the_broker_spells_it():
    row = loop.normalise_execution({
        "exec_id": "e1", "order_id": "9", "order_ref": "book_a", "symbol": "aapl",
        "action": "BOT", "qty": "50", "avgPrice": "101.25", "timestamp": "x"})
    assert row["exec_id"] == "e1"
    assert row["order_id"] == "9"
    assert row["order_ref"] == "BOOK_A"
    assert row["symbol"] == "AAPL"
    assert row["side"] == "BUY"
    assert row["shares"] == 50.0
    assert row["price"] == 101.25


def test_a_sale_is_read_as_a_sale():
    for word in ("SELL", "SLD", "sell"):
        assert loop.normalise_execution({"side": word})["side"] == "SELL"


def test_a_negative_share_count_is_still_a_share_count():
    """The side says the direction. A quantity is a quantity."""
    assert loop.normalise_execution({"shares": -100})["shares"] == 100.0


def test_only_this_books_fills_come_back(sandbox):
    broker = Filler([execution("e1", ref="BOOK_A"),
                     execution("e2", ref="BOOK_C", symbol="TSLA")])
    rows = loop.read_executions(broker, "BOOK_A", [])
    assert [row["exec_id"] for row in rows] == ["e1"]
    assert broker.asked == ["BOOK_A"], "the filter is asked for when it exists"


def test_a_broker_that_cannot_filter_is_filtered_here(sandbox):
    broker = NoRefFilter([execution("e1", ref="BOOK_A"),
                          execution("e2", ref="BOOK_C", symbol="TSLA")])
    rows = loop.read_executions(broker, "BOOK_A", [])
    assert [row["exec_id"] for row in rows] == ["e1"], (
        "a fill attributed to the wrong book is worse than one nobody noticed")


def test_a_broker_that_will_not_answer_is_a_note_not_a_crash(sandbox):
    class Broken:
        def executions(self, **kwargs):
            raise RuntimeError("the gateway went away")

    notes: list[str] = []
    assert loop.read_executions(Broken(), "BOOK_A", notes) == []
    assert notes and "could not be read" in notes[0]


def test_fills_come_back_oldest_first(sandbox):
    broker = Filler([
        execution("e2", when="2026-09-08T10:00:00-04:00"),
        execution("e1", when="2026-09-08T09:38:00-04:00"),
    ])
    assert [row["exec_id"] for row in loop.read_executions(broker, "BOOK_A", [])] \
        == ["e1", "e2"]


# ---------------------------------------------------------------------------
# A resting order that fills later
# ---------------------------------------------------------------------------


def test_a_fill_that_arrives_after_the_order_call_reaches_the_book(sandbox):
    """The whole point. This is the position that used to exist nowhere."""
    tick = tick_for("A", at(9, 40))
    state = with_a_resting_entry()
    broker = Filler([execution("e1")], orders=[])

    fresh = loop.ingest_fills(tick, state, guard_for("A"), broker)

    assert len(fresh) == 1
    held = state.position("AAPL")
    assert held is not None
    assert held.qty == 100
    assert held.avg_cost == 100.0
    assert held.stop > 0, "and it comes with a stop on it, not a zero"
    assert state.entries_opened_today == 1
    assert state.cash == pytest.approx(100000.0 - 10000.0)


def test_the_working_order_is_marked_filled_and_taken_out(sandbox):
    tick = tick_for("A", at(9, 40))
    state = with_a_resting_entry()
    loop.ingest_fills(tick, state, guard_for("A"), Filler([execution("e1")]))
    assert state.working_orders == {}, (
        "a book waiting on an order that has already filled counts its money twice")


def test_a_partial_fill_leaves_the_rest_working(sandbox):
    tick = tick_for("A", at(9, 40))
    state = with_a_resting_entry()
    loop.ingest_fills(tick, state, guard_for("A"),
                      Filler([execution("e1", shares=40)]))

    assert state.position("AAPL").qty == 40
    assert state.working_orders["7"]["remaining"] == 60
    assert state.working_orders["7"]["status"] == "partially_filled"


def test_the_rest_of_a_partial_fill_finishes_it(sandbox):
    state = with_a_resting_entry()
    guard = guard_for("A")
    loop.ingest_fills(tick_for("A", at(9, 40)), state, guard,
                      Filler([execution("e1", shares=40)]))
    loop.ingest_fills(tick_for("A", at(9, 45)), state, guard,
                      Filler([execution("e1", shares=40),
                              execution("e2", shares=60, price=100.5)]))

    held = state.position("AAPL")
    assert held.qty == 100
    # 40 at 100.00 and 60 at 100.50 average out at 100.30.
    assert held.avg_cost == pytest.approx(100.30, abs=0.001)
    assert state.working_orders == {}


def test_a_closing_fill_realises_the_money_and_drops_the_position(sandbox):
    state = fresh_state()
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long", stop=98.5,
                                   opened_on="2026-09-08"))
    loop.ingest_fills(tick_for("A", at(11, 0)), state, guard_for("A"),
                      Filler([execution("e9", side="SELL", price=102.0,
                                        order_id="none")]))

    assert state.position("AAPL") is None
    assert state.realized_pnl_today == pytest.approx(200.0)
    assert state.entries_opened_today == 0, "closing something opens nothing"


def test_a_fill_in_a_name_the_book_holds_the_other_way_is_read_as_an_exit(sandbox):
    """A stop resting at the broker has no working order in the book after a restart."""
    state = fresh_state()
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   side="long", opened_on="2026-09-08"))
    row = loop.normalise_execution(execution("e1", side="SELL"))
    assert loop.purpose_of_fill(state, row, None) == "exit"

    buying = loop.normalise_execution(execution("e2", side="BUY"))
    assert loop.purpose_of_fill(state, buying, None) == "entry"


def test_the_order_says_what_it_was_for_when_the_book_remembers_it():
    state = fresh_state()
    row = loop.normalise_execution(execution("e1", side="SELL"))
    assert loop.purpose_of_fill(state, row, {"purpose": "flatten"}) == "flatten"
    assert loop.purpose_of_fill(state, row, {"purpose": "nonsense"}) == "entry"


# ---------------------------------------------------------------------------
# Once, and only once
# ---------------------------------------------------------------------------


def test_the_same_execution_is_never_applied_twice(sandbox):
    state = with_a_resting_entry()
    guard = guard_for("A")
    broker = Filler([execution("e1")])

    loop.ingest_fills(tick_for("A", at(9, 40)), state, guard, broker)
    loop.ingest_fills(tick_for("A", at(9, 45)), state, guard, broker)
    loop.ingest_fills(tick_for("A", at(9, 50)), state, guard, broker)

    assert state.position("AAPL").qty == 100, (
        "three ticks reading the same fill is three chances to double a position")
    assert state.entries_opened_today == 1
    assert state.fills_seen == ["e1"]


def test_the_execution_ids_survive_a_restart(sandbox):
    state = with_a_resting_entry()
    guard = guard_for("A")
    broker = Filler([execution("e1")])
    loop.ingest_fills(tick_for("A", at(9, 40)), state, guard, broker)
    bs.save_state(state, root=sandbox)

    # A brand new process, reading the book file back off disk.
    again = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert again.fills_seen == ["e1"]
    loop.ingest_fills(tick_for("A", at(9, 45)), again, guard, broker)
    assert again.position("AAPL").qty == 100


def test_a_fill_with_no_execution_id_is_still_applied(sandbox):
    """Better a position the book knows about than one it does not."""
    tick = tick_for("A", at(9, 40))
    state = with_a_resting_entry()
    loop.ingest_fills(tick, state, guard_for("A"),
                      Filler([execution("", order_id="7")]))
    assert state.position("AAPL").qty == 100
    assert state.fills_seen == []


def test_a_new_day_starts_with_no_execution_ids(sandbox):
    """Today's fills are all new. Yesterday's are not in today's list."""
    state = with_a_resting_entry()
    loop.ingest_fills(tick_for("A", at(9, 40)), state, guard_for("A"),
                      Filler([execution("e1")]))
    bs.save_state(state, root=sandbox)

    tomorrow = bs.load_state("A", "BOOK_A", date(2026, 9, 9), capital=100000,
                             root=sandbox)
    assert tomorrow.fills_seen == []
    assert tomorrow.position("AAPL").qty == 100, "what it holds carries over"


# ---------------------------------------------------------------------------
# Orders the broker no longer has
# ---------------------------------------------------------------------------


def test_an_order_the_broker_has_forgotten_stops_being_waited_on(sandbox):
    tick = tick_for("A", at(9, 45))
    state = with_a_resting_entry()

    loop.ingest_fills(tick, state, guard_for("A"), Filler([]), broker_orders=[])

    assert state.working_orders == {}
    assert any("no longer working" in note for note in tick.notes)


def test_an_order_the_broker_still_has_is_left_alone(sandbox):
    tick = tick_for("A", at(9, 45))
    state = with_a_resting_entry()

    loop.ingest_fills(tick, state, guard_for("A"), Filler([]),
                      broker_orders=[{"orderId": 7, "symbol": "AAPL"}])

    assert "7" in state.working_orders


def test_an_order_placed_this_very_tick_is_not_called_cancelled(sandbox):
    """The list was read at the top of the tick, before the order was sent."""
    tick = tick_for("A", at(9, 35))
    state = with_a_resting_entry()          # placed_at is 09:35, the same tick

    loop.ingest_fills(tick, state, guard_for("A"), Filler([]), broker_orders=[])

    assert "7" in state.working_orders, (
        "calling a live order cancelled would throw away its id")


def test_nothing_is_judged_when_the_open_orders_were_not_read(sandbox):
    tick = tick_for("A", at(9, 45))
    state = with_a_resting_entry()
    loop.ingest_fills(tick, state, guard_for("A"), Filler([]), broker_orders=None)
    assert "7" in state.working_orders


# ---------------------------------------------------------------------------
# The whole tick, in order
# ---------------------------------------------------------------------------


def test_the_fills_are_read_before_reconciliation_runs(sandbox, capsys):
    """The ordering that caused eight problems across three books on a clean day.

    A book that sent a limit order at 09:35 and had it filled at 09:38 looks, to
    a reconciliation that runs first, like a book waiting on an order the broker
    has lost and holding a position it never bought. That is a mismatch, and a
    mismatch is a halt.
    """
    state = with_a_resting_entry()
    bs.save_state(state, root=sandbox)

    class Account:
        def account_summary(self, account=None):
            return {"items": [{"tag": "NetLiquidation", "value": "500000"}]}

        def portfolio(self, account=None, include_pnl=True):
            return {"positions": [{"symbol": "AAPL", "position": 100,
                                   "avgCost": 100.0, "marketPrice": 100.0,
                                   "marketValue": 10000.0}]}

        def open_orders(self, account=None, include_all=True):
            return {"orders": []}

        def executions(self, account=None, order_ref=None, **kwargs):
            return {"fills": [execution("e1")] if order_ref == "BOOK_A" else []}

        def snapshot(self, contracts, market_data_type=3):
            return {"market_data_type": market_data_type,
                    "snapshots": [{"symbol": c.get("symbol"), "last": 100.0,
                                   "marketDataType": market_data_type}
                                  for c in contracts]}

        def historical_bars(self, contract, duration, bar_size, **kwargs):
            return {"bars": []}

    assert loop.main(["--now", "2026-09-08 09:40", "--book", "A"],
                     broker=Account()) == 0

    printed = capsys.readouterr().out
    assert "Reconciliation: everything matched" in printed, printed[-2000:]

    after = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert after.position("AAPL").qty == 100
    assert after.halted is False, "the fill was read before anybody compared anything"
    assert after.working_orders == {}
