"""The loop never sends an order it already has resting at the broker.

Found by running the replay gate rather than by reading the code, which is the
whole reason the gate exists. A book short a name whose price rises all day gets
a fade exit on every manage tick, and every tick sent a fresh limit order to
cover the whole position. Seventy two identical cover orders were resting at the
broker by the close.

On a paper replay that is a curiosity. In a live account it is the position
committed once for every five minutes of the day, and all of it filling together
on the first dip: a book meant to be short a hundred shares ends up long six
thousand of them in the wrong direction.

Nothing here touches a broker or a network.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_no_resend.py -q
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


class Recorder:
    """Enough of a broker to take orders, and it sends none of them."""

    def __init__(self):
        self.placed: list[dict] = []
        self.next_id = 900

    def account_summary(self, account=None):
        return {"items": [{"tag": "NetLiquidation", "value": "500000"}]}

    def portfolio(self, account=None, include_pnl=True):
        return {"positions": []}

    def open_orders(self, account=None, include_all=True):
        return {"orders": []}

    def executions(self, account=None, **kwargs):
        return {"fills": []}

    def snapshot(self, contracts, market_data_type=3):
        return {"market_data_type": market_data_type, "snapshots": []}

    def historical_bars(self, contract, duration, bar_size, **kwargs):
        return {"bars": []}

    def place_order(self, contract, order, order_ref):
        self.next_id += 1
        self.placed.append({"contract": contract, "order": order,
                            "order_ref": order_ref})
        return {"sent": True, "order_id": self.next_id, "filled_qty": 0,
                "avg_fill_price": None, "working": True, "error": None,
                "confirmed_by": "open_orders"}

    def bracket_order(self, contract, entry, stop, target=None, order_ref=""):
        answer = self.place_order(contract, entry, order_ref)
        answer["legs"] = []
        answer["bracketed"] = True
        return answer

    def cancel_order(self, order_id):
        return {"order_id": order_id, "cancelled": True}

    def global_cancel(self):
        raise AssertionError("no test here cancels everything")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("config", "strategies"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "not wanted in this test")
    monkeypatch.setattr(loop, "alerts_mod", None)
    monkeypatch.setattr(loop, "ALERTS_ERROR", "not wanted in this test")
    monkeypatch.setattr(loop.ledger_writer, "log_trade", lambda *a, **k: True)
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    monkeypatch.setattr(loop.ledger_writer, "log_decision", lambda *a, **k: True)
    loop._DB_TROUBLE.clear()
    return tmp_path


def guard_for(book_id: str = "B") -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def live_tick(book_id: str = "B", now: datetime | None = None) -> loop.BookTick:
    import dataclasses                           # noqa: PLC0415

    book = dataclasses.replace(gr.load_books(BOOKS_YAML).get(book_id), mode="full")
    return loop.BookTick(book, now or at(10, 0), "testhash", write_ledger=False,
                         quiet=True)


def short_book(root: Path) -> bs.BookState:
    """Book B, short a hundred shares of a name that is climbing all day."""
    state = bs.load_state("B", "BOOK_B", TUESDAY, capital=100000, root=root)
    state.put_position(bs.Position(
        symbol="RISER", qty=-100, avg_cost=100.0, entry=100.0, side="short",
        opened_on="2026-09-08", stop=101.5, trailing_high_or_low=100.0,
        last_close=104.0, market_value=-10400.0))
    return state


def cover(qty: int = 100, price: float = 104.0,
          purpose: str = "exit") -> gr.OrderIntent:
    return gr.OrderIntent(symbol="RISER", side="BUY", qty=qty, limit_price=price,
                          purpose=purpose, book_id="B")


# ---------------------------------------------------------------------------
# The rising short, which is the case that found this
# ---------------------------------------------------------------------------


def test_the_second_cover_order_is_not_sent(sandbox):
    """The fade fires again five minutes later and nothing new goes out."""
    state = short_book(sandbox)
    guard = guard_for("B")
    broker = Recorder()
    guards = loop.read_guards(sandbox)
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    first = loop.consider(live_tick("B", at(10, 0)), state, guard, account_state,
                          cover(), broker, guards)
    assert first.allowed is True
    assert len(broker.placed) == 1
    assert state.working_orders, "the first one is resting now"

    tick = live_tick("B", at(10, 5))
    second = loop.consider(tick, state, guard, account_state, cover(), broker,
                           guards)

    assert second.allowed is False
    assert "duplicate_order" in second.rule_ids
    assert len(broker.placed) == 1, (
        "seventy two of these were resting at the broker by the close")
    assert any("already has order" in reason for reason in second.reasons)


def test_seventy_two_ticks_of_the_same_fade_send_one_order(sandbox):
    """The shape of the original bug, run out to its full length."""
    state = short_book(sandbox)
    guard = guard_for("B")
    broker = Recorder()
    guards = loop.read_guards(sandbox)
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    for minute in range(0, 360, 5):
        hour, mins = 10 + minute // 60, minute % 60
        loop.consider(live_tick("B", at(hour, mins)), state, guard, account_state,
                      cover(price=104.0 + minute / 100.0), broker, guards)

    assert len(broker.placed) == 1


def test_a_cheaper_cover_order_is_still_the_same_shares_twice(sandbox):
    """Never matched on the price. A second cover a cent better is still a double."""
    state = short_book(sandbox)
    guard = guard_for("B")
    broker = Recorder()
    guards = loop.read_guards(sandbox)
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    loop.consider(live_tick("B"), state, guard, account_state, cover(price=104.0),
                  broker, guards)
    again = loop.consider(live_tick("B"), state, guard, account_state,
                          cover(price=103.5), broker, guards)
    assert again.allowed is False
    assert len(broker.placed) == 1


def test_an_exit_a_stop_and_a_flatten_are_all_the_same_kind_of_thing(sandbox):
    """Three words for getting out. Two of them resting at once is one mistake."""
    state = short_book(sandbox)
    guard = guard_for("B")
    broker = Recorder()
    guards = loop.read_guards(sandbox)
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    loop.consider(live_tick("B"), state, guard, account_state,
                  cover(purpose="exit"), broker, guards)
    for purpose in ("stop", "flatten", "exit"):
        answer = loop.consider(live_tick("B"), state, guard, account_state,
                               cover(purpose=purpose), broker, guards)
        assert answer.allowed is False, purpose
    assert len(broker.placed) == 1


def test_the_families_are_what_they_look_like():
    assert loop.order_family("entry") == "opening"
    for word in ("exit", "stop", "flatten"):
        assert loop.order_family(word) == "closing"
    assert loop.order_family(None) == "opening"


# ---------------------------------------------------------------------------
# What is not a duplicate
# ---------------------------------------------------------------------------


def test_an_order_in_a_different_name_goes_out(sandbox):
    state = short_book(sandbox)
    guard = guard_for("B")
    broker = Recorder()
    guards = loop.read_guards(sandbox)
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    loop.consider(live_tick("B"), state, guard, account_state, cover(), broker,
                  guards)
    other = gr.OrderIntent(symbol="OTHER", side="BUY", qty=10, limit_price=50.0,
                           purpose="exit", book_id="B")
    answer = loop.consider(live_tick("B"), state, guard, account_state, other,
                           broker, guards)
    assert "duplicate_order" not in answer.rule_ids
    assert len(broker.placed) == 2


def test_an_order_the_other_way_round_is_not_a_duplicate(sandbox):
    """A resting BUY does not stop a SELL. They are not the same shares twice."""
    state = short_book(sandbox)
    guard = guard_for("B")
    guards = loop.read_guards(sandbox)
    broker = Recorder()
    account_state = bs.account_state_for(state, gr, at(10, 0), "DUT077572", False)

    loop.consider(live_tick("B"), state, guard, account_state, cover(), broker,
                  guards)
    selling = gr.OrderIntent(symbol="RISER", side="SELL", qty=10, limit_price=104.0,
                             purpose="exit", book_id="B")
    answer = loop.consider(live_tick("B"), state, guard, account_state, selling,
                           broker, guards)
    assert "duplicate_order" not in answer.rule_ids


def test_an_order_that_has_already_filled_does_not_block_the_next_one(sandbox):
    state = short_book(sandbox)
    state.working_orders["55"] = {"symbol": "RISER", "side": "BUY", "qty": 100,
                                  "remaining": 0, "purpose": "exit"}
    guards = loop.read_guards(sandbox)
    tick = live_tick("B")
    assert loop.duplicate_order_reason(tick, state, guard_for("B"), cover()) is None


def test_a_stop_child_does_not_stop_the_entry_that_owns_it(sandbox):
    """A bracket's own stop is the other side of the entry, not a copy of it."""
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    state.working_orders["81"] = {"symbol": "AAPL", "purpose": "stop",
                                  "price": 98.5, "is_child": True}
    entry = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                           purpose="entry", book_id="A")
    tick = live_tick("A")
    assert loop.duplicate_order_reason(tick, state, guard_for("A"), entry) is None


# ---------------------------------------------------------------------------
# The order the book has forgotten, which the broker still has
# ---------------------------------------------------------------------------


def test_an_order_the_broker_has_and_the_book_has_forgotten_still_blocks(sandbox):
    """Which is exactly what a restart leaves behind."""
    state = short_book(sandbox)
    assert not state.working_orders

    tick = live_tick("B")
    tick.broker_orders = [{"orderId": 44, "symbol": "RISER", "action": "BUY",
                           "orderRef": "BOOK_B", "totalQuantity": 100}]
    reason = loop.duplicate_order_reason(tick, state, guard_for("B"), cover())
    assert reason and "the broker already has order 44" in reason
    assert "forgotten" in reason


def test_another_books_order_at_the_broker_is_not_this_books_duplicate(sandbox):
    state = short_book(sandbox)
    tick = live_tick("B")
    tick.broker_orders = [{"orderId": 44, "symbol": "RISER", "action": "BUY",
                           "orderRef": "BOOK_A", "totalQuantity": 100}]
    assert loop.duplicate_order_reason(tick, state, guard_for("B"), cover()) is None


def test_an_untagged_order_at_the_broker_is_nobodys_duplicate(sandbox):
    """The paper account has carried an untagged order since 2026-09-02."""
    state = short_book(sandbox)
    tick = live_tick("B")
    tick.broker_orders = [{"orderId": 4, "symbol": "RISER", "action": "BUY"}]
    assert loop.duplicate_order_reason(tick, state, guard_for("B"), cover()) is None


# ---------------------------------------------------------------------------
# A dry run rehearses the refusal too
# ---------------------------------------------------------------------------


def test_a_dry_run_says_it_would_not_send_the_second_one(sandbox, monkeypatch):
    """A rehearsal that stacks orders the real thing would not is not a rehearsal."""
    monkeypatch.delenv(loop.LIVE_ENV_VAR, raising=False)
    state = short_book(sandbox)
    state.working_orders["55"] = {"symbol": "RISER", "side": "BUY", "qty": 100,
                                  "remaining": 100, "purpose": "exit"}
    book = gr.load_books(BOOKS_YAML).get("B")
    assert book.mode == "dry_run"
    tick = loop.BookTick(book, at(10, 5), "testhash", write_ledger=False, quiet=True)

    answer = loop.consider(tick, state, guard_for("B"),
                           bs.account_state_for(state, gr, at(10, 5), "DUT077572",
                                                False),
                           cover(), Recorder(), loop.read_guards(sandbox))

    assert answer.allowed is False
    assert "duplicate_order" in answer.rule_ids
    assert tick.refused == 1


# ---------------------------------------------------------------------------
# An order this tick has already cancelled is not a duplicate (item 16)
# ---------------------------------------------------------------------------
#
# main() reads the account's working orders once for the whole tick and hands
# the same list to all five books, on purpose: five books each asking IB
# Gateway the same question in the same second is how a data pacing violation
# happens, and the fifth book's call really did time out at 45 seconds the first
# time this ran end to end. The cost of reading once was that the duplicate
# check could not see a cancel made after that read, so the 15:45 flatten
# cancelled the resting stop and then had its own closing order refused, naming
# the order it had just pulled. The position closed on the next look, five
# minutes later in the replay gate and thirty seconds later in production, so
# nothing was ever left open overnight; what it cost was a flatten one tick
# slower than it reads.
#
# The read is still once a tick. A cancel now edits the list this tick already
# holds instead of asking for it again.


def test_a_cancelled_order_comes_out_of_this_ticks_view_of_the_broker(sandbox):
    """The whole of item 16, with no broker in it at all."""
    state = short_book(sandbox)
    tick = live_tick("B")
    tick.broker_orders = [{"orderId": 44, "symbol": "RISER", "action": "BUY",
                           "orderRef": "BOOK_B", "totalQuantity": 100}]
    assert loop.duplicate_order_reason(tick, state, guard_for("B"), cover())

    assert tick.forget_order(44) == 1
    assert loop.duplicate_order_reason(tick, state, guard_for("B"), cover()) is None
    assert tick.forget_order(44) == 0, (
        "an order this tick's read never saw is not an error, it is an order "
        "placed and cancelled inside the same tick")


def test_the_flatten_gets_out_on_the_same_tick_it_cancels_the_stop(sandbox):
    """A long with a real stop resting at the broker goes flat in one look.

    The broker here is the replay FakeBroker rather than one of the hand written
    fakes above, because the bug was about what the ACCOUNT looks like before and
    after a cancel. A fake that has to be told what its own order book holds
    could be told the answer the test wanted; this one keeps the order, gives it
    an id, cancels it and reports it as cancelled on its own.

    Exactly one cancel and exactly one closing order, in that order. Cancel
    first is not a detail: a live stop and a live closing order in the same name
    at the same moment can both fill, and then the book is short a position it
    never opened.
    """
    from agent.replay.fake_broker import FakeBroker      # noqa: PLC0415

    def bar(hour: int, minute: int, price: float = 100.0) -> dict:
        return {"time": at(hour, minute).isoformat(), "open": price, "high": price,
                "low": price, "close": price, "volume": 100_000, "average": price,
                "barCount": 50}

    broker = FakeBroker(bars={"AAPL": [bar(15, 40), bar(15, 45)]},
                        account_id="DUT077572", now=at(15, 46).isoformat())

    # The stop that a morning bracket left resting, as a real order at the
    # broker with an id of its own.
    resting = broker.place_order(
        {"symbol": "AAPL", "secType": "STK", "exchange": "SMART", "currency": "USD"},
        {"action": "SELL", "totalQuantity": 100, "orderType": "STP",
         "auxPrice": 98.5, "tif": "DAY"}, "BOOK_A")
    stop_id = str(resting["order_id"])

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    state.put_position(bs.Position(
        symbol="AAPL", qty=100, avg_cost=100.0, entry=100.0, side="long",
        opened_on="2026-09-08", stop=98.5, trailing_high_or_low=100.0,
        last_close=100.0, market_value=10000.0))
    state.working_orders[stop_id] = {
        "symbol": "AAPL", "purpose": "stop", "price": 98.5, "order_ref": "BOOK_A",
        "placed_at": at(15, 40).isoformat(), "is_child": True}

    guard = guard_for("A")
    tick = live_tick("A", at(15, 46))
    # THE ONCE A TICK READ, exactly as main() does it, taken before the cancel.
    tick.broker_orders = broker.open_orders()["orders"]
    assert any(str(row["orderId"]) == stop_id for row in tick.broker_orders)

    calls: list[str] = []
    real_cancel, real_place = broker.cancel_order, broker.place_order

    def counted_cancel(order_id):
        calls.append(f"cancel {order_id}")
        return real_cancel(order_id)

    def counted_place(contract, order, order_ref):
        calls.append(f"place {order.get('action')} {order.get('totalQuantity')} "
                     f"{contract.get('symbol')} {order.get('orderType')}")
        return real_place(contract, order, order_ref)

    broker.cancel_order = counted_cancel
    broker.place_order = counted_place

    loop.do_flatten(tick, state, loop.plan_for(tick.book, guard), guard, broker,
                    bs.account_state_for(state, gr, at(15, 46), "DUT077572", False),
                    loop.read_guards(sandbox))

    assert calls == [f"cancel {stop_id}", "place SELL 100 AAPL LMT"], (
        "one cancel and one closing order, on this tick, the cancel first")
    assert tick.refused == 0, (
        "the closing order used to be refused as a duplicate of the stop the "
        "same tick had just cancelled")
    assert tick.sent == 1
    assert stop_id not in state.working_orders
    assert not any(str(row.get("orderId")) == stop_id
                   for row in broker.open_orders()["orders"]), (
        "the stop is really gone from the broker, not just from the book file")
