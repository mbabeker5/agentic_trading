"""The stop and the target: set at the fill, clamped by the rules, and they fire.

Why this file exists. Until 2026-09-06 record_fill in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py built
a Position with no stop and no target on it, so both were 0.0. exit_reason_for
in the same file skipped a zero stop, and guardrails.stop_price_for was never
called from the loop at all. The whole chain was there and none of it was
connected: live, neither the hard 1.5 percent stop nor the target could ever
have fired. Everything below is that chain, one link at a time.

Nothing here talks to IB Gateway, the MCP server or any account. The only
broker is the tiny recording fake at the top of this file, and its three order
methods keep a list instead of sending anything, so a test can read back exactly
which legs would have gone out.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_stops.py -q
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent import book_state as bs
from agent import guardrails as gr
from agent import loop

REAL_ROOT = Path(__file__).resolve().parent.parent
BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")

TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int, day: date = TUESDAY) -> datetime:
    return datetime.combine(day, clock_time(hour, minute), tzinfo=NEW_YORK)


# ---------------------------------------------------------------------------
# A broker that writes down every leg instead of sending it
# ---------------------------------------------------------------------------


class RecordingBroker:
    """Enough of the Broker protocol to take orders, and it sends none of them.

    place_order and bracket_order append to `placed` and `brackets` and hand
    back a plausible answer. Nothing leaves this object.
    """

    def __init__(self, price: float = 100.0):
        self._price = price
        self.placed: list[dict] = []
        self.brackets: list[dict] = []
        self.cancelled: list = []
        self._next_id = 500

    # -- reading ----------------------------------------------------------

    def account_summary(self, account=None) -> dict:
        return {"account": account or "DUT077572",
                "items": [{"tag": "NetLiquidation", "value": "1000000"}]}

    def portfolio(self, account=None, include_pnl=True) -> dict:
        return {"positions": [], "totals": {}, "notes": []}

    def open_orders(self, account=None, include_all=True) -> dict:
        return {"orders": [], "notes": []}

    def executions(self, account=None, symbol=None, sec_type=None, exchange=None,
                   side=None, time=None) -> dict:
        return {"executions": [], "notes": []}

    def snapshot(self, contracts, market_data_type=3) -> dict:
        return {"snapshots": [{"symbol": c.get("symbol"), "last": self._price,
                               "close": self._price} for c in contracts], "notes": []}

    def historical_bars(self, contract, duration, bar_size, what="TRADES",
                        use_rth=True, end_date_time="") -> dict:
        return {"bars": [], "notes": []}

    # -- acting -----------------------------------------------------------

    def place_order(self, contract, order, order_ref) -> dict:
        self._next_id += 1
        self.placed.append({"contract": contract, "order": dict(order),
                            "order_ref": order_ref, "order_id": self._next_id})
        return {"sent": True, "order_id": self._next_id, "filled_qty": 0.0,
                "avg_fill_price": None, "working": True, "error": None, "raw": {},
                "confirmed_by": "open_orders"}

    def bracket_order(self, contract, entry, stop, target=None, order_ref="") -> dict:
        legs = [{"purpose": "entry", "order_id": self._next_id + 1,
                 "order_ref": order_ref, "price": entry.get("lmtPrice")}]
        self._next_id += 1
        if target is not None:
            self._next_id += 1
            legs.append({"purpose": "target", "order_id": self._next_id,
                         "order_ref": order_ref, "price": target.get("lmtPrice")})
        self._next_id += 1
        legs.append({"purpose": "stop", "order_id": self._next_id,
                     "order_ref": order_ref, "price": stop.get("auxPrice")})
        answer = {"sent": True, "order_id": legs[0]["order_id"], "filled_qty": 0.0,
                  "avg_fill_price": None, "working": True, "error": None, "raw": {},
                  "confirmed_by": "open_orders", "legs": legs, "bracketed": True}
        self.brackets.append({"contract": contract, "entry": dict(entry),
                              "stop": dict(stop),
                              "target": dict(target) if target else None,
                              "order_ref": order_ref, "legs": legs})
        return answer

    def cancel_order(self, order_id) -> dict:
        self.cancelled.append(order_id)
        return {"order_id": order_id, "cancelled": True, "still_working": False,
                "error": None}

    def global_cancel(self) -> dict:
        raise AssertionError("no test here cancels everything")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A project root of its own so no test reads another one's state files."""
    for name in ("config", "strategies", "agent", "venv312"):
        (tmp_path / name).symlink_to(REAL_ROOT / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(loop.LIVE_ENV_VAR, raising=False)
    return tmp_path


def guard_for(book_id: str = "A") -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def book_for(book_id: str = "A", mode: str = "dry_run") -> gr.BookConfig:
    registry = gr.load_books(BOOKS_YAML)
    return dataclasses.replace(registry.get(book_id), mode=mode)


def fresh_state(root: Path, book_id: str = "A") -> bs.BookState:
    return bs.load_state(book_id, f"BOOK_{book_id}", TUESDAY, capital=100000,
                         root=root)


def long_position(stop: float = 98.5, target: float = 103.0,
                  entry: float = 100.0) -> bs.Position:
    return bs.Position(symbol="AAPL", qty=100, avg_cost=entry, entry=entry,
                       opened_on=f"{TUESDAY:%Y-%m-%d}", side="long", stop=stop,
                       target=target, trailing_high_or_low=entry)


def short_position(stop: float = 101.5, target: float = 97.0,
                   entry: float = 100.0) -> bs.Position:
    return bs.Position(symbol="AAPL", qty=-100, avg_cost=entry, entry=entry,
                       opened_on=f"{TUESDAY:%Y-%m-%d}", side="short", stop=stop,
                       target=target, trailing_high_or_low=entry)


# ---------------------------------------------------------------------------
# 1. The clamp: a model may tighten a stop and may never widen one
# ---------------------------------------------------------------------------


def test_a_long_stop_wider_than_the_rules_is_pulled_back_to_the_rule_stop():
    guard = guard_for("A")
    # The rule stop for a 100.00 long is 1.5 percent below, so 98.50. The model
    # asked for 95.00, which is more than three times the loss.
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=95.0, model_target=104.0)
    assert levels.reject is None
    assert levels.stop == 98.5
    assert any("never widen" in note for note in levels.notes)


def test_a_long_stop_tighter_than_the_rules_is_kept():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=99.4, model_target=104.0)
    assert levels.stop == 99.4
    # Item A2: this book takes no profit target, so the one that came in is
    # dropped and the reason is written down rather than swallowed.
    assert levels.target == 0.0
    assert any("no profit target at all" in note for note in levels.notes)


def test_a_momentum_book_drops_every_target_it_is_given():
    """Item A2, approved by Mo on 2026-09-06. A position leaves on its stop or at
    the close, and a target on the right side of entry is dropped exactly like
    one on the wrong side."""
    guard = guard_for("A")
    assert guard.risk.use_profit_target is False
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=99.4, model_target=110.0)
    assert levels.target == 0.0
    assert any("no profit target at all" in note for note in levels.notes)


def test_a_book_that_still_takes_a_target_keeps_a_good_one():
    """The insider book has not changed, so its target survives untouched."""
    guard = guard_for("C")
    assert guard.risk.use_profit_target is True
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=95.0, model_target=110.0)
    assert levels.target == 110.0


def test_a_short_stop_wider_than_the_rules_is_pulled_back():
    guard = guard_for("A")
    # Mirrored: the rule stop for a 100.00 short is 1.5 percent above, 101.50.
    levels = loop.protective_levels(guard, entry=100.0, short=True,
                                    model_stop=108.0, model_target=96.0)
    assert levels.stop == 101.5
    assert any("never widen" in note for note in levels.notes)


def test_a_short_stop_tighter_than_the_rules_is_kept():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=True,
                                    model_stop=100.6, model_target=96.0)
    assert levels.stop == 100.6


def test_a_pick_with_no_stop_at_all_gets_the_rule_stop():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=0.0, model_target=104.0)
    assert levels.stop == 98.5
    assert any("carried no stop" in note for note in levels.notes)


def test_a_long_stop_above_entry_is_rejected():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=101.0, model_target=104.0)
    assert levels.reject is not None
    assert "wrong side" in levels.reject
    assert levels.stop == 0.0


def test_a_short_stop_below_entry_is_rejected():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=True,
                                    model_stop=99.0, model_target=96.0)
    assert levels.reject is not None
    assert "wrong side" in levels.reject


def test_a_target_on_the_wrong_side_is_dropped_and_the_stop_survives():
    """On a book that still takes targets. The momentum books drop them all."""
    guard = guard_for("C")
    levels = loop.protective_levels(guard, entry=100.0, short=False,
                                    model_stop=99.0, model_target=97.0)
    assert levels.reject is None
    assert levels.stop == 99.0
    assert levels.target == 0.0
    assert any("wrong side" in note for note in levels.notes)


def test_a_short_target_above_entry_is_dropped():
    guard = guard_for("A")
    levels = loop.protective_levels(guard, entry=100.0, short=True,
                                    model_stop=101.0, model_target=103.0)
    assert levels.target == 0.0
    assert levels.stop == 101.0


def test_the_opening_range_low_wins_when_it_is_nearer_than_the_percent_stop():
    guard = guard_for("A")
    # 99.20 is nearer to a 100.00 entry than the 98.50 percent stop, so it wins,
    # and a model stop wider than that is pulled all the way back to it.
    levels = loop.protective_levels(guard, entry=100.0, short=False, model_stop=97.0,
                                    model_target=104.0, opening_range_low=99.2)
    assert levels.stop == 99.2


# ---------------------------------------------------------------------------
# 2. The fill: a position is never opened without a stop on it
# ---------------------------------------------------------------------------


def test_a_fill_takes_its_stop_and_target_from_the_trigger_record(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 98.5, "target": 103.0, "side": "long"}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")

    loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)

    held = state.position("AAPL")
    assert held is not None
    assert held.stop == 98.5
    assert held.target == 0.0, "item A2, this book takes no profit target"
    assert held.entry == 100.0
    assert held.side == "long"


def test_a_fill_clamps_a_widened_stop_against_the_price_actually_paid(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 90.0, "target": 106.0, "side": "long"}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")

    notes = loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)

    assert state.position("AAPL").stop == 98.5
    assert any("never widen" in note for note in notes)


def test_a_short_fill_gets_a_stop_above_the_price_it_sold_at(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 101.0, "target": 96.0, "side": "short"}
    intent = gr.OrderIntent(symbol="AAPL", side="SELL", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")

    loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)

    held = state.position("AAPL")
    assert held.side == "short"
    assert held.qty == -100
    assert held.stop == 101.0
    assert held.stop > held.entry
    assert held.target == 0.0, "item A2, this book takes no profit target"


def test_a_fill_with_a_nonsense_stop_still_gets_the_rule_stop(sandbox):
    """The shares are already ours, so refusing is not on the table."""
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 120.0, "target": 103.0, "side": "long"}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")

    notes = loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)

    held = state.position("AAPL")
    assert held.stop == 98.5
    assert held.target == 0.0
    assert any("wrong side" in note for note in notes)


def test_a_fill_with_no_trigger_record_at_all_still_gets_a_stop(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")

    loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)

    assert state.position("AAPL").stop == 98.5


def test_the_stop_survives_a_round_trip_through_the_book_file(sandbox):
    """A stop that is lost on save is a stop that vanishes overnight."""
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 98.5, "target": 103.0, "side": "long"}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")
    loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)
    bs.save_state(state, root=sandbox)

    reloaded = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert reloaded.position("AAPL").stop == 98.5
    assert reloaded.position("AAPL").target == 0.0


def test_adding_to_a_position_does_not_wipe_its_stop(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    state.triggered["AAPL"] = {"stop": 98.5, "target": 103.0, "side": "long"}
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A")
    loop.record_fill(state, intent, 100, 100.0, at(9, 40), guard)
    loop.record_fill(state, intent, 50, 101.0, at(9, 45), guard)

    held = state.position("AAPL")
    assert held.qty == 150
    assert held.stop == 98.5


# ---------------------------------------------------------------------------
# 3. exit_reason_for fires on the stored stop and the stored target
# ---------------------------------------------------------------------------


def plan() -> loop.BookPlan:
    registry = gr.load_books(BOOKS_YAML)
    return loop.plan_for(registry.get("A"), guard_for("A"))


def test_a_long_stops_out_when_the_close_goes_through_the_stop():
    trigger, why = loop.exit_reason_for(long_position(), plan(), guard_for("A"),
                                        TUESDAY, 98.4, vwap=None)
    assert trigger == "stop"
    assert "98.50" in why


def test_a_long_takes_its_target_when_the_close_reaches_it():
    trigger, why = loop.exit_reason_for(long_position(), plan(), guard_for("A"),
                                        TUESDAY, 103.1, vwap=None)
    assert trigger == "target"
    assert "103.00" in why


def test_a_long_between_its_stop_and_its_target_is_held():
    position = long_position()
    position.trailing_high_or_low = 100.0
    trigger, _ = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                      100.5, vwap=None)
    assert trigger is None


def test_a_short_stops_out_when_the_close_goes_up_through_the_stop():
    trigger, why = loop.exit_reason_for(short_position(), plan(), guard_for("A"),
                                        TUESDAY, 101.6, vwap=None)
    assert trigger == "stop"
    assert "101.50" in why


def test_a_short_takes_its_target_when_the_close_falls_to_it():
    trigger, why = loop.exit_reason_for(short_position(), plan(), guard_for("A"),
                                        TUESDAY, 96.9, vwap=None)
    assert trigger == "target"
    assert "97.00" in why


def test_a_short_between_its_stop_and_its_target_is_held():
    position = short_position()
    position.trailing_high_or_low = 100.0
    trigger, _ = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                      99.5, vwap=None)
    assert trigger is None


def test_the_stop_is_checked_before_the_target_when_both_would_fire():
    """A bar that spans both is a loss, not a win. The stop wins."""
    position = bs.Position(symbol="AAPL", qty=100, avg_cost=100.0, entry=100.0,
                           opened_on=f"{TUESDAY:%Y-%m-%d}", side="long",
                           stop=98.5, target=98.0, trailing_high_or_low=100.0)
    trigger, _ = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                      98.4, vwap=None)
    assert trigger == "stop"


def test_a_position_carried_over_with_no_stop_still_gets_one():
    """The old bug's shape: a state file written before the stop was stored."""
    position = bs.Position(symbol="AAPL", qty=100, avg_cost=100.0, entry=100.0,
                           opened_on=f"{TUESDAY:%Y-%m-%d}", side="long",
                           stop=0.0, target=0.0, trailing_high_or_low=100.0)
    trigger, why = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                        98.0, vwap=None)
    assert trigger == "stop"
    assert "98.50" in why


# ---------------------------------------------------------------------------
# The bracket: the stop rests at the broker, not only in this Mac's memory
# ---------------------------------------------------------------------------


def entry_intent(qty: int = 100, price: float = 100.0,
                 side: str = "BUY") -> gr.OrderIntent:
    return gr.OrderIntent(symbol="AAPL", side=side, qty=qty, limit_price=price,
                          purpose="entry", book_id="A")


def test_the_children_of_a_long_are_both_sells():
    stop, target = loop.child_orders(entry_intent(), 98.5, 103.0)
    assert stop["action"] == "SELL"
    assert stop["orderType"] == "STP"
    assert stop["auxPrice"] == 98.5
    assert stop["totalQuantity"] == 100
    assert target["action"] == "SELL"
    assert target["orderType"] == "LMT"
    assert target["lmtPrice"] == 103.0


def test_the_children_of_a_short_are_both_buys():
    stop, target = loop.child_orders(entry_intent(side="SELL"), 101.5, 97.0)
    assert stop["action"] == "BUY"
    assert stop["auxPrice"] == 101.5
    assert target["action"] == "BUY"
    assert target["lmtPrice"] == 97.0


def test_a_pick_with_no_target_still_gets_a_stop_child():
    stop, target = loop.child_orders(entry_intent(), 98.5, 0.0)
    assert stop is not None
    assert target is None


def test_an_entry_goes_out_as_a_bracket_with_every_leg_tagged(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    book = book_for("A", "full")
    tick = loop.BookTick(book, at(9, 40), "testhash", write_ledger=False, quiet=True)
    broker = RecordingBroker()

    loop.submit(tick, state, entry_intent(), broker, guard, stop=98.5, target=103.0)

    assert len(broker.brackets) == 1
    assert broker.placed == []
    sent = broker.brackets[0]
    assert sent["entry"]["orderType"] == "LMT"
    assert sent["stop"]["auxPrice"] == 98.5
    assert sent["target"]["lmtPrice"] == 103.0
    assert sent["order_ref"] == guard.order_ref
    assert all(leg["order_ref"] == guard.order_ref for leg in sent["legs"])


# ---------------------------------------------------------------------------
# Nothing this book has resting survives the flatten
# ---------------------------------------------------------------------------


def _live(book_id: str = "A", now=None, monkeypatch=None):
    """A tick with all four live locks open, and the account state to match."""
    book = book_for(book_id, "full")
    return loop.BookTick(book, now or at(15, 46), "testhash", write_ledger=False,
                         quiet=True)


def test_the_flatten_pulls_every_order_this_book_has_resting(sandbox, monkeypatch):
    """Found by the replay gate: cancel_order was called in exactly one place.

    An entry that never filled and the stop and target children that went out
    with it were all left resting through the close. A momentum book meant to be
    flat by 15:55 could be filled into a fresh position on the way out, and its
    children could then sell stock it does not own.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    state = fresh_state(sandbox)
    state.working_orders = {
        "501": {"symbol": "REST", "purpose": "entry", "remaining": 100,
                "limit_price": 99.5},
        "502": {"symbol": "AAPL", "purpose": "stop", "price": 98.5, "is_child": True},
        "503": {"symbol": "AAPL", "purpose": "target", "price": 103.0,
                "is_child": True},
    }
    guard = guard_for("A")
    tick = _live("A")
    broker = RecordingBroker()
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    cancelled = loop.cancel_working_orders(
        tick, state, broker, loop.read_guards(sandbox), account_state,
        "this book is flattening at 15:45")

    assert cancelled == 3
    assert sorted(broker.cancelled) == ["501", "502", "503"]
    assert state.working_orders == {}


def test_a_dry_run_cancels_nothing_and_says_what_it_would_have(sandbox):
    state = fresh_state(sandbox)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry"}}
    tick = loop.BookTick(book_for("A", "dry_run"), at(15, 46), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    assert loop.cancel_working_orders(
        tick, state, broker, loop.read_guards(sandbox), account_state,
        "this book is flattening") == 0
    assert broker.cancelled == []
    assert state.working_orders, "nothing was sent, so nothing was pulled"


def test_an_order_that_will_not_cancel_stays_in_the_book_file(sandbox, monkeypatch):
    """So the next tick tries again rather than forgetting the order exists."""
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")

    class Stubborn(RecordingBroker):
        def cancel_order(self, order_id):
            self.cancelled.append(order_id)
            return {"order_id": order_id, "cancelled": False,
                    "error": "it filled a moment ago"}

    state = fresh_state(sandbox)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry"}}
    tick = _live("A")
    broker = Stubborn()
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    assert loop.cancel_working_orders(
        tick, state, broker, loop.read_guards(sandbox), account_state,
        "this book is flattening") == 0
    assert "501" in state.working_orders
    assert any("would not cancel" in note for note in tick.notes)


def test_a_broker_that_raises_on_cancel_does_not_stop_the_flatten(sandbox,
                                                                  monkeypatch):
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")

    class Broken(RecordingBroker):
        def cancel_order(self, order_id):
            raise RuntimeError("the gateway went away mid cancel")

    state = fresh_state(sandbox)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry"}}
    tick = _live("A")
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    assert loop.cancel_working_orders(
        tick, state, Broken(), loop.read_guards(sandbox), account_state,
        "this book is flattening") == 0
    assert "501" in state.working_orders


def test_a_book_with_nothing_resting_cancels_nothing(sandbox, monkeypatch):
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    state = fresh_state(sandbox)
    broker = RecordingBroker()
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    assert loop.cancel_working_orders(
        tick := _live("A"), state, broker, loop.read_guards(sandbox), account_state,
        "this book is flattening") == 0
    assert broker.cancelled == []
    assert tick.notes == []


def test_a_flatten_with_nothing_held_still_pulls_the_resting_entry(sandbox,
                                                                   monkeypatch):
    """The exact shape the gate found: an entry resting, no position, the close."""
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    state = fresh_state(sandbox)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry",
                                    "remaining": 100, "limit_price": 99.5}}
    guard = guard_for("A")
    plan = loop.plan_for(book_for("A", "full"), guard)
    tick = _live("A")
    broker = RecordingBroker()
    account_state = bs.account_state_for(state, gr, at(15, 46), "DUT077572", False)

    loop.do_flatten(tick, state, plan, guard, broker, account_state,
                    loop.read_guards(sandbox))

    assert broker.cancelled == ["501"]
    assert state.working_orders == {}
    assert broker.placed == [], "there was nothing to close, only something to pull"


def test_the_child_order_ids_are_written_into_the_book_file(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    tick = loop.BookTick(book_for("A", "full"), at(9, 40), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()

    loop.submit(tick, state, entry_intent(), broker, guard, stop=98.5, target=103.0)

    children = [row for row in state.working_orders.values()
                if isinstance(row, dict) and row.get("is_child")]
    assert {row["purpose"] for row in children} == {"stop", "target"}
    assert loop.resting_stop_id(state, "AAPL") is not None


def test_an_exit_is_one_plain_order_and_never_a_bracket(sandbox):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    tick = loop.BookTick(book_for("A", "full"), at(9, 40), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()
    intent = gr.OrderIntent(symbol="AAPL", side="SELL", qty=100, limit_price=99.0,
                            purpose="exit", book_id="A")

    loop.submit(tick, state, intent, broker, guard, stop=98.5, target=103.0)

    assert broker.brackets == []
    assert len(broker.placed) == 1


def test_a_dry_run_prints_every_leg_it_would_send():
    """The stop is last, because that is the leg that transmits the bracket."""
    lines = loop.bracket_lines(entry_intent(), 98.5, 103.0, "BOOK_A")
    assert len(lines) == 3
    assert lines[0].startswith("entry")
    assert "103.00" in lines[1] and "BOOK_A" in lines[1]
    assert lines[2].startswith("stop")
    assert "98.50" in lines[2] and "BOOK_A" in lines[2]


def test_a_dry_run_shows_the_stops_own_limit_price():
    """A rehearsal has to show the stop-limit, not a summary of it."""
    lines = loop.bracket_lines(entry_intent(), 98.5, 0.0, "BOOK_A")
    assert len(lines) == 2, "a momentum book has no target leg (item A2)"
    # Half a percent below the 98.50 trigger, because this one closes a long.
    assert "stop 98.50" in lines[1]
    assert "limit 98.01" in lines[1]


def test_a_short_stop_limit_sits_above_its_trigger():
    lines = loop.bracket_lines(entry_intent(side="SELL"), 101.5, 0.0, "BOOK_A")
    assert "stop 101.50" in lines[1]
    assert "limit 102.01" in lines[1]


# ---------------------------------------------------------------------------
# Tightening a stop cancels the child and places a new one
# ---------------------------------------------------------------------------


def trailing_guard() -> gr.Guardrails:
    """Book A with a trailing rule switched on, which its yaml leaves empty."""
    guard = guard_for("A")
    risk = dataclasses.replace(guard.risk, trailing_stop_pct=1.0,
                               trailing_activation_pct=2.0)
    return dataclasses.replace(guard, risk=risk)


def test_no_trailing_numbers_means_the_stop_never_moves():
    position = long_position()
    position.trailing_high_or_low = 110.0
    assert loop.tighter_stop_for(position, guard_for("A")) is None


def test_the_stop_follows_a_winner_up():
    position = long_position()
    position.trailing_high_or_low = 105.0
    nearer = loop.tighter_stop_for(position, trailing_guard())
    assert nearer == pytest.approx(103.95)
    assert nearer > position.stop


def test_the_stop_never_loosens():
    """Up two percent, then most of the way back: the stop stays where it got to."""
    position = long_position(stop=103.95)
    position.trailing_high_or_low = 105.0
    position.stop = 104.5
    assert loop.tighter_stop_for(position, trailing_guard()) is None


def test_a_short_stop_follows_the_price_down():
    position = short_position()
    position.trailing_high_or_low = 95.0
    nearer = loop.tighter_stop_for(position, trailing_guard())
    assert nearer == pytest.approx(95.95)
    assert nearer < position.stop


def test_moving_a_stop_cancels_the_old_child_and_places_a_new_one(sandbox):
    state = fresh_state(sandbox)
    guard = trailing_guard()
    tick = loop.BookTick(book_for("A", "full"), at(10, 5), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()
    state.working_orders["901"] = {"symbol": "AAPL", "purpose": "stop",
                                   "price": 98.5, "order_ref": "BOOK_A",
                                   "is_child": True}
    position = long_position()
    account_state = bs.account_state_for(state, gr, at(10, 5), "DUT077572", False, {})

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(loop.LIVE_ENV_VAR, "yes")
        loop.move_resting_stop(tick, state, position, 103.95, broker, guard,
                               loop.read_guards(), account_state)

    assert broker.cancelled == ["901"]
    assert len(broker.placed) == 1
    replacement = broker.placed[0]["order"]
    assert replacement["orderType"] == "STP"
    assert replacement["auxPrice"] == 103.95
    assert replacement["action"] == "SELL"
    assert broker.placed[0]["order_ref"] == guard.order_ref
    assert "901" not in state.working_orders
    assert loop.resting_stop_id(state, "AAPL") is not None


def test_a_dry_run_book_moves_no_stop_at_the_broker(sandbox):
    state = fresh_state(sandbox)
    tick = loop.BookTick(book_for("A", "dry_run"), at(10, 5), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()
    state.working_orders["901"] = {"symbol": "AAPL", "purpose": "stop",
                                   "price": 98.5, "order_ref": "BOOK_A",
                                   "is_child": True}
    account_state = bs.account_state_for(state, gr, at(10, 5), "DUT077572", False, {})

    loop.move_resting_stop(tick, state, long_position(), 103.95, broker,
                           trailing_guard(), loop.read_guards(), account_state)

    assert broker.cancelled == []
    assert broker.placed == []
    assert state.working_orders["901"]["price"] == 98.5


def test_a_stop_that_will_not_cancel_leaves_the_old_one_alone(sandbox):
    """Two live stops would be worse than one stale one, so nothing new is placed."""
    state = fresh_state(sandbox)
    tick = loop.BookTick(book_for("A", "full"), at(10, 5), "testhash",
                         write_ledger=False, quiet=True)
    broker = RecordingBroker()
    broker.cancel_order = lambda order_id: {"order_id": order_id, "cancelled": False,
                                            "still_working": True,
                                            "error": "the broker said no"}
    state.working_orders["901"] = {"symbol": "AAPL", "purpose": "stop",
                                   "price": 98.5, "order_ref": "BOOK_A",
                                   "is_child": True}
    account_state = bs.account_state_for(state, gr, at(10, 5), "DUT077572", False, {})

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(loop.LIVE_ENV_VAR, "yes")
        loop.move_resting_stop(tick, state, long_position(), 103.95, broker,
                               trailing_guard(), loop.read_guards(), account_state)

    assert broker.placed == []


# ---------------------------------------------------------------------------
# The fake broker in the replay harness speaks the same bracket
# ---------------------------------------------------------------------------


def test_the_replay_fake_broker_places_every_leg():
    from agent.replay import fake_broker as fb

    broker = fb.FakeBroker(bars={"AAPL": []}, now=at(9, 35))
    contract = {"symbol": "AAPL", "secType": "STK", "exchange": "SMART",
                "currency": "USD"}
    answer = broker.bracket_order(
        contract,
        {"action": "BUY", "totalQuantity": 100, "orderType": "LMT",
         "lmtPrice": 100.0, "tif": "DAY"},
        {"action": "SELL", "totalQuantity": 100, "orderType": "STP",
         "auxPrice": 98.5, "tif": "DAY"},
        {"action": "SELL", "totalQuantity": 100, "orderType": "LMT",
         "lmtPrice": 103.0, "tif": "DAY"},
        "BOOK_A")

    assert answer["bracketed"] is True
    assert [leg["purpose"] for leg in answer["legs"]] == ["entry", "target", "stop"]
    assert all(leg["order_ref"] == "BOOK_A" for leg in answer["legs"])
    assert len(broker.orders) == 3


# ---------------------------------------------------------------------------
# The VWAP fade: one number in the yaml, and the code fires on exactly it
# ---------------------------------------------------------------------------


def test_every_momentum_book_reads_its_fade_count_from_its_own_yaml():
    for book_id in ("A", "B", "E"):
        registry = gr.load_books(BOOKS_YAML)
        made = loop.plan_for(registry.get(book_id), guard_for(book_id))
        assert made.family == loop.MOMENTUM
        assert made.vwap_fade_closes == 2, (
            f"book {book_id} has no risk.vwap_fade_closes in its strategy.yaml")


def test_a_book_that_does_not_trade_the_opening_push_has_no_fade_rule():
    registry = gr.load_books(BOOKS_YAML)
    for book_id in ("C", "D"):
        made = loop.plan_for(registry.get(book_id), guard_for(book_id))
        assert made.vwap_fade_closes == 0


def test_one_close_below_vwap_is_not_a_fade():
    position = long_position()
    position.trailing_high_or_low = 100.0
    trigger, _ = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                      100.4, vwap=101.0, closes_through_vwap=1)
    assert trigger is None


def test_the_fade_fires_on_exactly_the_count_the_yaml_names():
    position = long_position()
    position.trailing_high_or_low = 100.0
    trigger, why = loop.exit_reason_for(position, plan(), guard_for("A"), TUESDAY,
                                        100.4, vwap=101.0, closes_through_vwap=2)
    assert trigger == "fade_observed", (
        "item D2: in month one a fade is written down and closes nothing")
    assert "2 five minute closes in a row" in why
    assert "calls a fade at 2" in why


def test_the_fade_count_climbs_and_resets(sandbox):
    state = fresh_state(sandbox)
    position = long_position()

    assert loop.count_vwap_closes(state, "AAPL", position, 100.4, 101.0) == 1
    assert loop.count_vwap_closes(state, "AAPL", position, 100.2, 101.0) == 2
    # One close back above VWAP puts it to zero. It counts a run, not a total.
    assert loop.count_vwap_closes(state, "AAPL", position, 101.5, 101.0) == 0
    assert loop.count_vwap_closes(state, "AAPL", position, 100.1, 101.0) == 1


def test_a_tick_with_no_price_leaves_the_fade_count_alone(sandbox):
    state = fresh_state(sandbox)
    position = long_position()
    loop.count_vwap_closes(state, "AAPL", position, 100.4, 101.0)
    assert loop.count_vwap_closes(state, "AAPL", position, None, None) == 1
    assert loop.count_vwap_closes(state, "AAPL", position, None, 101.0) == 1


def test_the_short_fade_counts_closes_above_vwap(sandbox):
    state = fresh_state(sandbox)
    position = short_position()
    assert loop.count_vwap_closes(state, "AAPL", position, 101.5, 101.0) == 1
    assert loop.count_vwap_closes(state, "AAPL", position, 100.4, 101.0) == 0


def test_the_fade_count_survives_a_round_trip_through_the_book_file(sandbox):
    state = fresh_state(sandbox)
    loop.count_vwap_closes(state, "AAPL", long_position(), 100.4, 101.0)
    bs.save_state(state, root=sandbox)

    reloaded = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert loop.count_vwap_closes(reloaded, "AAPL", long_position(), 100.2,
                                  101.0) == 2


def test_the_prompt_renders_the_same_fade_count_the_code_fires_on():
    """The whole point of the yaml key: one number, two readers, no drift."""
    from agent import decide as decide_mod

    strategy_dir = REAL_ROOT / "strategies" / "momentum_hybrid"
    params, _ = decide_mod.load_params(strategy_dir)
    rendered = decide_mod.render_prompt(strategy_dir, "manage", params)

    plan_count = loop.plan_for(gr.load_books(BOOKS_YAML).get("A"),
                               guard_for("A")).vwap_fade_closes
    assert "{{vwap_fade_closes}}" not in rendered
    assert f"{plan_count} closes in a row the wrong side of VWAP" in rendered


# ---------------------------------------------------------------------------
# The model's "fade" answer closes a position, the same as "exit"
# ---------------------------------------------------------------------------


class StubDecision:
    """What decide() hands back, with whatever exits a test wants in it."""

    def __init__(self, exits):
        self.picks: list = []
        self.skips: list = []
        self.exits = list(exits)
        self.notes: list = []
        self.ok = True
        self.error = None
        self.model = "stub"
        self.cost_usd = 0.0
        self.prompt_hash = "stubhash"


def manage_once(sandbox, monkeypatch, exits, price=100.5, vwap=100.0,
                position=None):
    """One manage tick over one open position, with the model's answer stubbed."""
    state = fresh_state(sandbox)
    guard = guard_for("A")
    book = book_for("A", "dry_run")
    tick = loop.BookTick(book, at(10, 5), "testhash", write_ledger=False, quiet=True)
    state.put_position(position or long_position())
    broker = RecordingBroker(price=price)
    account_state = bs.account_state_for(state, gr, at(10, 5), "DUT077572", False, {})

    monkeypatch.setattr(loop.decide_mod, "decide",
                        lambda *a, **k: StubDecision(exits))
    monkeypatch.setattr(loop.broker_mod, "bars_5m_today",
                        lambda *a, **k: [{"time": "2026-09-08 10:05:00",
                                          "close": price, "high": price,
                                          "low": price, "open": price,
                                          "volume": 1000}])
    monkeypatch.setattr(loop.broker_mod, "session_vwap", lambda bars: vwap)
    monkeypatch.setattr(loop.ledger_writer, "log_decision", lambda *a, **k: None)
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: None)

    loop.do_manage(tick, state, plan(), guard, broker, account_state,
                   loop.read_guards())
    return state, tick


def decisions_about(state, symbol="AAPL"):
    return [row for row in state.decisions
            if str(row.get("symbol") or "") == symbol]


def test_a_model_fade_is_written_down_and_closes_nothing(sandbox, monkeypatch):
    """Item D2, approved by Mo on 2026-09-06.

    In month one a fade is an observation. The row goes into the ledger with the
    model's own words on it, and the position is held, so at the end of the month
    Mo can read what every fade would have cost or saved. Set
    risk.vwap_fade_action to `exit` in the book's strategy.yaml and the old
    behaviour comes back in one edit.
    """
    state, _ = manage_once(sandbox, monkeypatch, [
        {"symbol": "AAPL", "action": "fade",
         "rationale": "two bars of nothing on dying volume"}])

    closing = [row for row in decisions_about(state)
               if "would place SELL" in str(row["decision"])]
    assert closing == [], "a fade must not close anything in month one"

    observed = [row for row in decisions_about(state)
                if "fade observed" in str(row["decision"])]
    assert observed, "the fade was not written down"
    assert "called the momentum gone" in observed[-1]["rationale"]
    assert "dying volume" in observed[-1]["rationale"]
    assert state.position("AAPL") is not None, "the position should still be held"


def test_a_model_exit_closes_the_position(sandbox, monkeypatch):
    state, _ = manage_once(sandbox, monkeypatch, [
        {"symbol": "AAPL", "action": "exit", "rationale": "get out now"}])

    closing = [row for row in decisions_about(state)
               if "would place SELL" in str(row["decision"])]
    assert closing
    assert "asked to close it now" in closing[-1]["decision"]


def test_a_model_hold_closes_nothing(sandbox, monkeypatch):
    state, _ = manage_once(sandbox, monkeypatch, [
        {"symbol": "AAPL", "action": "hold", "rationale": "still working"}])

    assert not [row for row in decisions_about(state)
                if "would place" in str(row["decision"])]
    assert any(row["decision"] == "hold" for row in decisions_about(state))


def test_a_rule_that_already_fired_keeps_its_own_reason(sandbox, monkeypatch):
    """A stop out is a stop out, even when the model called it a fade."""
    state, _ = manage_once(sandbox, monkeypatch, [
        {"symbol": "AAPL", "action": "fade", "rationale": "momentum gone"}],
        price=98.0, vwap=99.0)

    closing = [row for row in decisions_about(state)
               if "would place SELL" in str(row["decision"])]
    assert "went through the stop" in closing[-1]["decision"]
    assert "momentum gone" in closing[-1]["decision"]


def test_a_model_fade_still_sends_nothing_in_a_dry_run(sandbox, monkeypatch):
    _, tick = manage_once(sandbox, monkeypatch, [
        {"symbol": "AAPL", "action": "fade", "rationale": "gone"}])
    assert tick.sent == 0


# ---------------------------------------------------------------------------
# Headline and news are out of the momentum packet, not just out of the message
# ---------------------------------------------------------------------------


def test_a_momentum_candidate_carries_no_headline_and_no_news(sandbox, monkeypatch):
    state = fresh_state(sandbox)
    guard = guard_for("A")
    tick = loop.BookTick(book_for("A"), at(9, 36), "testhash", write_ledger=False,
                         quiet=True)
    broker = RecordingBroker()
    monkeypatch.setattr(loop.broker_mod, "bars_5m_today", lambda *a, **k: [])

    packet = loop.build_pick_packet(tick, state, plan(), guard, broker, [
        {"symbol": "AAPL", "opening_range_high": 101.0, "opening_range_low": 99.0,
         "headline": "a headline nobody checked", "news": "and some news",
         "score": 9.0}])

    candidate = packet["candidates"][0]
    assert "headline" not in candidate
    assert "news" not in candidate


def test_the_momentum_keys_no_longer_offer_a_headline():
    from agent import decide as decide_mod

    assert "headline" not in decide_mod.MOMENTUM_CANDIDATE_KEYS
    assert "news" not in decide_mod.MOMENTUM_CANDIDATE_KEYS
    # The filings books keep both, because their sweeps read real text.
    assert "headline" in decide_mod.SLOW_CANDIDATE_KEYS
    assert "news" in decide_mod.SLOW_CANDIDATE_KEYS


def test_the_momentum_prompt_no_longer_asks_for_a_catalyst():
    from agent import decide as decide_mod

    strategy_dir = REAL_ROOT / "strategies" / "momentum_hybrid"
    params, _ = decide_mod.load_params(strategy_dir)
    rendered = decide_mod.render_prompt(strategy_dir, "pick", params)
    assert "carry no" in rendered and "headline and no news" in rendered
    assert "A gap with a headline behind it beats a gap with none" not in rendered
