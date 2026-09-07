"""Native OCA brackets, and the facts the loop has to gather for the guardrails.

Every rule in agent/guardrails.py reads facts off an OrderIntent or an
AccountState, and a rule whose facts nobody fills in is a rule that never fires.
That is the quietest way for a safety net to stop working: it looks present, it
is tested on its own, and in production nothing ever reaches it. So this file
tests the WIRING rather than the rules. For each fact it asks two questions: does
the loop go and get it, and does an unknown answer come through as unknown rather
than as all clear.

It also covers the bracket itself. A momentum entry now goes out as a native
IBKR bracket, a limit parent and a stop-limit child in one one-cancels-the-other
group, transmitted together, with a market backstop if the stop fires and the
limit will not fill.

Nothing here touches a broker or a network. The fake below is twenty lines and
its order methods raise, so a test that ever tried to send something fails
loudly rather than passing quietly.

The flatten tests at the bottom are the exception, and they have to be: watching
an order actually get cancelled needs the live path open. They use a second fake
that writes every cancel and every order into one list instead of sending it, so
the order the two happen in can be read back, and they all catch their alerts
rather than letting agent/alerts.py text a real phone.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_wiring.py -q
"""
from __future__ import annotations

import dataclasses
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REAL_ROOT = Path(__file__).resolve().parent.parent
if str(REAL_ROOT) not in sys.path:
    sys.path.insert(0, str(REAL_ROOT))

from agent import book_state as bs               # noqa: E402
from agent import broker as broker_mod           # noqa: E402
from agent import guardrails as gr               # noqa: E402
from agent import loop                           # noqa: E402
from agent import paths                          # noqa: E402

BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")
TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int, second: int = 0, day: date = TUESDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second,
                    tzinfo=NEW_YORK)


# ---------------------------------------------------------------------------
# A broker that answers reads and refuses to trade
# ---------------------------------------------------------------------------


class QuoteBroker:
    """Answers snapshots and open orders. Any order method is a test failure."""

    def __init__(self, quotes: list[dict] | None = None,
                 orders: list[dict] | None = None):
        self.quotes = quotes if quotes is not None else []
        self.orders = orders or []
        self.snapshot_calls: list[list[dict]] = []

    def account_summary(self, account=None):
        return {"items": [{"tag": "NetLiquidation", "value": "1000000"}]}

    def portfolio(self, account=None, include_pnl=True):
        return {"positions": []}

    def open_orders(self, account=None, include_all=True):
        return {"orders": list(self.orders)}

    def executions(self, account=None, **kwargs):
        return {"executions": []}

    def snapshot(self, contracts, market_data_type=3):
        self.snapshot_calls.append(contracts)
        return {"snapshots": list(self.quotes)}

    def historical_bars(self, contract, duration, bar_size, **kwargs):
        return {"bars": []}

    def place_order(self, *args, **kwargs):
        raise AssertionError("a test must never place an order")

    def bracket_order(self, *args, **kwargs):
        raise AssertionError("a test must never place a bracket")

    def cancel_order(self, *args, **kwargs):
        raise AssertionError("a test must never cancel an order")

    def global_cancel(self, *args, **kwargs):
        raise AssertionError("a test must never cancel everything")


class BrokenBroker(QuoteBroker):
    """A broker that cannot answer. Unknown has to come through as unknown."""

    def snapshot(self, contracts, market_data_type=3):
        raise RuntimeError("the gateway is not answering")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway project root, so nothing here writes into the real output/."""
    for name in ("config", "strategies", "agent", "venv312"):
        (tmp_path / name).symlink_to(REAL_ROOT / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv("AGENTIC_TRADING_LIVE_ORDERS", raising=False)
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    """Every alert this test raises, caught instead of sent.

    agent/alerts.py really does text a phone, message Slack and put a banner on
    this screen, so a test that alerts without this fixture alerts Mo. Tests
    that expect no alert take it too and assert the list is empty, which is the
    only way an accidental one gets caught rather than delivered.
    """
    caught: list[tuple[str, str, str]] = []

    class Caught:
        @staticmethod
        def alert(level, title, body):
            caught.append((level, title, body))
            return ["captured"]

    monkeypatch.setattr(loop, "alerts_mod", Caught)
    return caught


def guard_for(book_id: str = "A") -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(9, 40), "testhash", write_ledger=False,
                         quiet=True)


# ---------------------------------------------------------------------------
# The project root comes from agent/paths.py and nowhere else
# ---------------------------------------------------------------------------


def test_the_loop_asks_paths_where_the_project_is():
    """One answer, in one file, so a second machine needs no edit at all."""
    assert loop.project_root() == paths.project_root()
    assert loop.ROOT_ENV_VAR == paths.ROOT_ENV_VAR


def test_no_path_to_this_mac_is_written_into_the_loops_code():
    """A path in the code is a path that has to be edited on every new machine.

    Docstrings and comments may name it, and they do, because a person reading
    the file wants to know where it runs today. What must not exist is a string
    the CODE uses, which is what this walks the parsed module looking for.
    """
    import ast                                   # noqa: PLC0415

    source = (REAL_ROOT / "agent" / "loop.py").read_text(encoding="utf-8")
    assert "DEFAULT_ROOT" not in source

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            found = ast.get_docstring(node, clean=False)
            if found:
                docstrings.add(found)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "/Users/" in node.value and node.value not in docstrings:
                raise AssertionError(
                    f"a path to one Mac inside the code, on line {node.lineno}: "
                    f"{node.value[:80]}")


def test_the_root_still_follows_the_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    assert loop.project_root() == tmp_path


# ---------------------------------------------------------------------------
# The bracket: a limit parent and a stop-limit child in one OCA group
# ---------------------------------------------------------------------------


def test_the_stop_child_is_a_stop_limit_with_half_a_percent_of_room():
    """A plain stop fills wherever the book happens to be in a thin gap down."""
    child = broker_mod.stop_limit_child(
        {"action": "SELL", "totalQuantity": 100, "orderType": "STP",
         "auxPrice": 100.0, "tif": "DAY"})
    assert child["orderType"] == "STP LMT"
    assert child["auxPrice"] == 100.0, "the trigger does not move"
    assert child["lmtPrice"] == 99.50, "half a percent below, because it is a sell"


def test_a_short_stop_limit_sits_above_its_trigger():
    child = broker_mod.stop_limit_child(
        {"action": "BUY", "totalQuantity": 100, "orderType": "STP",
         "auxPrice": 100.0, "tif": "DAY"})
    assert child["lmtPrice"] == 100.50


def test_a_limit_price_already_worked_out_is_not_overruled():
    child = broker_mod.stop_limit_child(
        {"action": "SELL", "totalQuantity": 100, "orderType": "STP",
         "auxPrice": 100.0, "lmtPrice": 99.0})
    assert child["lmtPrice"] == 99.0


def test_the_offset_is_a_named_number_rather_than_a_magic_one():
    assert broker_mod.STOP_LIMIT_OFFSET_PCT == 0.5
    assert broker_mod.OCA_CANCEL_REMAINING == 1


def test_an_oca_group_name_says_which_book_and_which_name_it_belongs_to():
    group = broker_mod.oca_group_name("BOOK_A", "AAPL")
    assert group.startswith("BOOK_A-AAPL-")
    assert group != broker_mod.oca_group_name("BOOK_B", "AAPL")


def test_the_bracket_path_refuses_to_run_without_the_environment_variable():
    """The second lock, behind the four in the loop."""
    broker = broker_mod.McpBroker.__new__(broker_mod.McpBroker)
    with pytest.raises(broker_mod.BrokerError, match="AGENTIC_TRADING_LIVE_ORDERS"):
        broker.bracket_order({"symbol": "AAPL"}, {"lmtPrice": 100.0},
                             {"auxPrice": 99.0}, None, "BOOK_A")


def test_a_dry_run_shows_two_legs_for_a_momentum_book():
    """No target leg since item A2, so a momentum bracket is parent and stop."""
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=100, limit_price=100.0,
                            purpose="entry", book_id="A", sector="Technology")
    lines = loop.bracket_lines(intent, 99.80, 0.0, "BOOK_A")
    assert len(lines) == 2
    assert "parent" in lines[0]
    assert "OCA group" in lines[1]
    assert "stop 99.80" in lines[1] and "limit 99.30" in lines[1]


# ---------------------------------------------------------------------------
# The market backstop behind the stop-limit
# ---------------------------------------------------------------------------


def test_a_stop_that_has_not_triggered_is_left_alone():
    order = {"symbol": "AAPL", "purpose": "stop"}
    assert loop.stop_backstop_due(order, at(9, 40)) is False


def test_a_stop_that_triggered_a_moment_ago_is_given_its_minute():
    order = {"symbol": "AAPL", "purpose": "stop",
             "triggered_at": at(9, 40, 30).isoformat()}
    assert loop.stop_backstop_due(order, at(9, 40, 59)) is False


def test_a_stop_still_unfilled_after_a_minute_is_marketed_out():
    order = {"symbol": "AAPL", "purpose": "stop",
             "triggered_at": at(9, 40, 0).isoformat()}
    assert loop.stop_backstop_due(order, at(9, 41, 0)) is True
    assert loop.STOP_BACKSTOP_SECONDS == 60


def test_the_backstop_only_ever_looks_at_stop_orders():
    order = {"symbol": "AAPL", "purpose": "entry",
             "triggered_at": at(9, 30, 0).isoformat()}
    assert loop.stop_backstop_due(order, at(9, 41, 0)) is False


def test_the_moment_a_stop_triggers_is_written_into_the_book_file(sandbox):
    """Nothing else on this Mac remembers between ticks, so the file has to."""
    tick = tick_for("A", at(9, 41))
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.working_orders["501"] = {"symbol": "AAPL", "purpose": "stop",
                                   "price": 99.8, "is_child": True}
    broker = QuoteBroker(orders=[{"orderId": 501, "symbol": "AAPL",
                                  "status": "triggered"}])

    loop.note_stop_triggers(tick, state, broker)
    assert state.working_orders["501"]["triggered_at"].startswith("2026-09-08T09:41")


def test_a_stop_already_marked_as_triggered_is_not_restamped(sandbox):
    """Restamping it would reset the minute every tick and the backstop would
    never fire."""
    tick = tick_for("A", at(9, 45))
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    first = at(9, 41).isoformat()
    state.working_orders["501"] = {"symbol": "AAPL", "purpose": "stop",
                                   "triggered_at": first}
    broker = QuoteBroker(orders=[{"orderId": 501, "symbol": "AAPL",
                                  "triggered": True}])

    loop.note_stop_triggers(tick, state, broker)
    assert state.working_orders["501"]["triggered_at"] == first


def test_the_backstop_closes_the_position_and_drops_the_dead_stop(sandbox):
    tick = tick_for("A", at(9, 42))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, stop=99.8, side="long",
                                   opened_on="2026-09-08", market_value=9980.0))
    state.working_orders["501"] = {"symbol": "AAPL", "purpose": "stop",
                                   "triggered_at": at(9, 40).isoformat()}
    guard = guard_for("A")
    account_state = bs.account_state_for(state, gr, at(9, 42), "DUT077572", False)

    loop.market_out_unfilled_stops(tick, state, guard, QuoteBroker(), account_state,
                                   loop.read_guards())

    assert "501" not in state.working_orders, "the dead stop was left behind"
    placed = [row["decision"] for row in state.decisions]
    assert any("SELL 100 AAPL" in row for row in placed)
    assert any("market backstop" in row["rationale"] or "market backstop" in row["decision"]
               for row in state.decisions)


def test_the_backstop_does_nothing_when_the_position_is_already_gone(sandbox):
    """The stop filled after all. Marketing out would sell shares we do not have."""
    tick = tick_for("A", at(9, 42))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.working_orders["501"] = {"symbol": "AAPL", "purpose": "stop",
                                   "triggered_at": at(9, 40).isoformat()}
    account_state = bs.account_state_for(state, gr, at(9, 42), "DUT077572", False)

    loop.market_out_unfilled_stops(tick, state, guard_for("A"), QuoteBroker(),
                                   account_state, loop.read_guards())

    assert "501" not in state.working_orders
    assert tick.would_be_orders == 0


# ---------------------------------------------------------------------------
# The halt facts, read off IBKR's tick 49 and its limit band
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ({"halted": 0}, False),
    ({"halted": 1}, True),
    ({"halted": 2}, True),
    ({"halted": True}, True),
    ({"tick49": 1}, True),
    ({}, None),
    ({"halted": "nonsense"}, None),
    (None, None),
])
def test_the_halted_tick_is_read_and_an_unknown_stays_unknown(raw, expected):
    assert loop.halted_from(raw) is expected


def test_a_price_at_the_top_of_its_band_is_a_limit_state():
    assert loop.limit_state_from(
        {"last": 10.0, "limitUpPrice": 10.0, "limitDownPrice": 8.0}) is True


def test_a_price_at_the_bottom_of_its_band_is_a_limit_state():
    assert loop.limit_state_from(
        {"last": 8.0, "limitUpPrice": 10.0, "limitDownPrice": 8.0}) is True


def test_a_price_inside_its_band_is_fine():
    assert loop.limit_state_from(
        {"last": 9.0, "limitUpPrice": 10.0, "limitDownPrice": 8.0}) is False


def test_a_quote_with_no_band_at_all_is_unknown_rather_than_fine():
    assert loop.limit_state_from({"last": 9.0}) is None


def test_the_loop_asks_the_broker_for_both_facts():
    broker = QuoteBroker(quotes=[{"symbol": "AAPL", "last": 9.0, "halted": 0,
                                  "limitUpPrice": 10.0, "limitDownPrice": 8.0}])
    halted, limit_state = loop.tradeable_now(broker, {"symbol": "AAPL"}, [])
    assert halted is False
    assert limit_state is False
    assert broker.snapshot_calls, "the loop never actually asked"


def test_a_broker_that_cannot_answer_gives_unknown_and_says_so():
    """An unknown halt status stops an entry, which is the designed answer."""
    notes: list[str] = []
    halted, limit_state = loop.tradeable_now(BrokenBroker(), {"symbol": "AAPL"}, notes)
    assert halted is None and limit_state is None
    assert notes and "halt status could not be read" in notes[0]


def test_an_unknown_halt_status_really_does_stop_the_entry():
    """The wiring and the rule, checked together rather than one at a time."""
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=100.0,
                            purpose="entry", book_id="A", sector="Technology",
                            halted=None, limit_state=None)
    state = gr.AccountState(
        equity=100000.0, day_start_equity=100000.0, realized_pnl_today=0.0,
        unrealized_pnl=0.0, open_positions={}, pending_order_notional=0.0,
        now=at(9, 40), kill_switch_present=False, account_id="DUT077572",
        book_id="A")
    decision = gr.check_order(guard_for("A"), state, intent)
    assert "halted" in decision.rule_ids


# ---------------------------------------------------------------------------
# What all five books hold, which only the loop can see
# ---------------------------------------------------------------------------


def _write_state(root: Path, order_ref: str, book_id: str, positions: dict,
                 working: dict | None = None) -> None:
    state = bs.BookState(book_id=book_id, order_ref=order_ref, date="2026-09-08",
                         capital=100000.0, cash=100000.0, day_start_equity=100000.0)
    for symbol, (qty, price) in positions.items():
        state.put_position(bs.Position(symbol=symbol, qty=qty, avg_cost=price,
                                       entry=price, side="long",
                                       opened_on="2026-09-08",
                                       market_value=qty * price))
    state.working_orders = working or {}
    bs.save_state(state, root=root)


def test_the_loop_can_see_which_book_already_has_a_name(sandbox):
    books = gr.load_books(BOOKS_YAML).enabled_books()
    _write_state(sandbox, "BOOK_A", "A", {"AAPL": (100, 100.0)})
    _write_state(sandbox, "BOOK_E", "E", {"MSFT": (50, 200.0)})

    wide = loop.read_account_wide(books, at(9, 40))
    assert wide.owners["AAPL"] == "A"
    assert wide.owners["MSFT"] == "E"
    assert wide.without("A") == {"MSFT": "E"}, "a book is never shut out of its own"


def test_a_working_entry_order_claims_a_name_too(sandbox):
    """A book with an order resting at the broker is as committed as one holding."""
    books = gr.load_books(BOOKS_YAML).enabled_books()
    _write_state(sandbox, "BOOK_A", "A", {}, working={
        "77": {"symbol": "TSLA", "purpose": "entry", "remaining": 10,
               "limit_price": 300.0}})

    wide = loop.read_account_wide(books, at(9, 40))
    assert wide.owners["TSLA"] == "A"
    assert wide.exposure["TSLA"] == 3000.0


def test_a_tie_goes_to_whichever_book_comes_first_in_the_register(sandbox):
    """First come, first served, settled by the order in config/books.yaml."""
    books = gr.load_books(BOOKS_YAML).enabled_books()
    assert [book.book_id for book in books][:2] == ["A", "B"]
    _write_state(sandbox, "BOOK_A", "A", {"AAPL": (100, 100.0)})
    _write_state(sandbox, "BOOK_B", "B", {"AAPL": (100, 100.0)})

    wide = loop.read_account_wide(books, at(9, 40))
    assert wide.owners["AAPL"] == "A"
    assert wide.exposure["AAPL"] == 20000.0, "both books' money counts towards it"
    assert gr.SYMBOL_TIE_BREAK == "first_come_first_served"


def test_the_five_books_equity_is_added_up_for_the_account_level_cap(sandbox):
    books = gr.load_books(BOOKS_YAML).enabled_books()
    for book in books:
        _write_state(sandbox, book.order_ref, book.book_id, {})
    wide = loop.read_account_wide(books, at(9, 40))
    assert wide.equity == pytest.approx(500000.0)


def test_the_facts_reach_the_snapshot_the_guardrails_check(sandbox):
    books = gr.load_books(BOOKS_YAML).enabled_books()
    _write_state(sandbox, "BOOK_E", "E", {"MSFT": (50, 200.0)})
    wide = loop.read_account_wide(books, at(9, 40))

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    account_state = bs.account_state_for(state, gr, at(9, 40), "DUT077572", False)
    book = gr.load_book(BOOKS_YAML, "A")
    loop.fill_v2_state(account_state, state, book, at(9, 40), wide)

    assert account_state.symbols_held_elsewhere == {"MSFT": "E"}
    assert account_state.symbol_exposure_all_books["MSFT"] == 10000.0
    assert account_state.account_equity == pytest.approx(wide.equity)


def test_a_book_sees_what_the_book_before_it_did_in_the_same_tick(sandbox):
    """One ticker, one book has to be a rule about now, not about this morning.

    This is the hole absorb() closes. The account wide view used to be read once
    at the top of the tick and left alone while all five books took their turns,
    so book A could open AAPL at 09:35 and book B, four lines later in the same
    tick, would still be told nobody was in it.
    """
    books = gr.load_books(BOOKS_YAML).enabled_books()
    for book in books:
        _write_state(sandbox, book.order_ref, book.book_id, {})
    wide = loop.read_account_wide(books, at(9, 35))
    assert wide.owners == {}, "nobody holds anything at the top of the tick"

    # Book A opens AAPL part way through the tick, in memory, not on disk yet.
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long",
                                   opened_on="2026-09-08", market_value=10000.0))
    wide.absorb("A", state)

    assert wide.owners["AAPL"] == "A"
    assert wide.without("B") == {"AAPL": "A"}, "book B has to be told"
    assert wide.without("A") == {}, "book A is never shut out of its own name"
    assert wide.exposure["AAPL"] == 10000.0


def test_absorbing_a_book_twice_does_not_count_its_money_twice(sandbox):
    """absorb() replaces that book's row. Adding to it would double the exposure."""
    books = gr.load_books(BOOKS_YAML).enabled_books()
    _write_state(sandbox, "BOOK_A", "A", {"AAPL": (100, 100.0)})
    for book in books[1:]:
        _write_state(sandbox, book.order_ref, book.book_id, {})

    wide = loop.read_account_wide(books, at(9, 40))
    assert wide.exposure["AAPL"] == 10000.0

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    wide.absorb("A", state)
    assert wide.exposure["AAPL"] == 10000.0, "the same position, counted once"


def test_a_working_entry_order_placed_this_tick_claims_the_name_too(sandbox):
    """An order resting at the broker is as committed as a position."""
    books = gr.load_books(BOOKS_YAML).enabled_books()
    for book in books:
        _write_state(sandbox, book.order_ref, book.book_id, {})
    wide = loop.read_account_wide(books, at(9, 35))

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.working_orders["99"] = {"symbol": "TSLA", "purpose": "entry",
                                  "remaining": 10, "limit_price": 300.0}
    wide.absorb("A", state)

    assert wide.owners["TSLA"] == "A"
    assert wide.exposure["TSLA"] == 3000.0


# ---------------------------------------------------------------------------
# Two rows for one name, and neither of them lost
# ---------------------------------------------------------------------------


def test_a_position_is_identified_by_its_symbol_and_its_account():
    row = {"symbol": "aapl", "account": "du123", "position": 100}
    assert loop.position_key(row) == ("AAPL", "DU123")
    assert loop.position_key({"symbol": "AAPL", "position": 1}, "DUT077572") \
        == ("AAPL", "DUT077572")
    for key in ("acctId", "accountId", "account_id"):
        assert loop.position_key({"symbol": "AAPL", key: "DU9"}) == ("AAPL", "DU9")


def test_two_accounts_holding_one_name_are_two_rows_and_one_netted_line():
    holdings = {"positions": [
        {"symbol": "AAPL", "account": "DU1", "position": 100, "avgCost": 100.0,
         "marketValue": 10000.0},
        {"symbol": "AAPL", "account": "DU2", "position": 40, "avgCost": 150.0,
         "marketValue": 6000.0},
    ]}
    rows = loop.positions_by_key(holdings)
    assert set(rows) == {("AAPL", "DU1"), ("AAPL", "DU2")}, (
        "keyed by symbol alone, the second row would have eaten the first")

    netted = loop.net_by_symbol(rows)
    assert netted["AAPL"]["position"] == 140
    assert netted["AAPL"]["marketValue"] == 16000.0
    # 100 shares at 100 and 40 at 150 average out at 114.2857.
    assert netted["AAPL"]["avgCost"] == pytest.approx(114.2857, abs=0.0001)


def test_one_account_reporting_a_name_twice_keeps_both_halves():
    """The replay gate's phantom position fault makes exactly this shape."""
    holdings = {"positions": [
        {"symbol": "OWNED", "position": 100, "avgCost": 100.0, "marketValue": 10000.0},
        {"symbol": "OWNED", "position": 50, "avgCost": 100.0, "marketValue": 5000.0},
    ]}
    rows = loop.positions_by_key(holdings, "DUT077572")
    assert list(rows) == [("OWNED", "DUT077572")]
    assert rows[("OWNED", "DUT077572")]["position"] == 150, (
        "the two rows are added, not one thrown away")
    assert loop.net_by_symbol(rows)["OWNED"]["position"] == 150


def test_a_flat_row_is_dropped_and_a_short_one_is_not():
    holdings = {"positions": [
        {"symbol": "GONE", "position": 0},
        {"symbol": "SHORT", "position": -30, "avgCost": 20.0},
        {"symbol": "", "position": 10},
        {"symbol": "NETSOUT", "account": "DU1", "position": 10},
        {"symbol": "NETSOUT", "account": "DU2", "position": -10},
    ]}
    rows = loop.positions_by_key(holdings, "DUT077572")
    assert ("GONE", "DUT077572") not in rows
    assert rows[("SHORT", "DUT077572")]["position"] == -30
    assert not [key for key in rows if not key[0]], "a row with no symbol is not a row"

    netted = loop.net_by_symbol(rows)
    assert "NETSOUT" not in netted, "long ten and short ten is flat"
    assert netted["SHORT"]["position"] == -30


def test_the_order_refs_on_two_rows_for_one_name_are_kept_together():
    holdings = {"positions": [
        {"symbol": "AAPL", "account": "DU1", "position": 10, "order_refs": ["BOOK_A"]},
        {"symbol": "AAPL", "account": "DU2", "position": 10, "order_refs": ["BOOK_C"]},
    ]}
    netted = loop.net_by_symbol(loop.positions_by_key(holdings))
    assert netted["AAPL"]["order_refs"] == ["BOOK_A", "BOOK_C"]


def test_read_broker_facts_hands_back_both_views(sandbox):
    class TwoAccounts(QuoteBroker):
        def portfolio(self, account=None, include_pnl=True):
            return {"positions": [
                {"symbol": "AAPL", "account": "DU1", "position": 100,
                 "avgCost": 100.0, "marketValue": 10000.0},
                {"symbol": "AAPL", "account": "DU2", "position": 40,
                 "avgCost": 100.0, "marketValue": 4000.0}]}

    facts = loop.read_broker_facts(TwoAccounts(), "DUT077572")
    assert facts.problems == []
    assert len(facts.rows) == 2
    assert facts.positions["AAPL"]["position"] == 140
    assert facts.values["NetLiquidation"] == "1000000"


# ---------------------------------------------------------------------------
# One ticker, one book: a switch, and the loop stops re-asking when it is on
# ---------------------------------------------------------------------------


def test_a_pick_refused_for_a_settled_reason_is_put_down_for_the_day(sandbox):
    """A refusal that cannot change again must not be worked out every tick.

    The first gate run found one rule refusing fifty seven orders in a day,
    which is what a stopped machine looks like rather than a guardrail doing its
    job. A name another book owns is gone for the day, so the pick is put down.
    """
    tick = tick_for("A", at(9, 40))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.triggered["AAPL"] = {"at": "2026-09-08T09:35", "price": 100.0,
                               "allowed": False, "sent": False}
    decision = gr.Decision(allowed=False)
    decision.add("symbol_exclusive", "Book B is already in it.")

    loop.put_the_pick_down(tick, state, "AAPL", decision)

    assert state.triggered["AAPL"]["skipped"] == "symbol_exclusive"
    assert any("cannot change again today" in note for note in tick.notes)


def test_a_pick_refused_for_want_of_room_gets_another_look(sandbox):
    """Closing something changes the answer, so these are deliberately not settled."""
    tick = tick_for("A", at(9, 40))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.triggered["AAPL"] = {"at": "2026-09-08T09:35", "price": 100.0,
                               "allowed": False, "sent": False}
    for rule_id in ("sector_cap", "max_open_positions", "gross_exposure_cap",
                    "max_position_pct", "daily_loss_cap"):
        decision = gr.Decision(allowed=False)
        decision.add(rule_id, "No room right now.")
        loop.put_the_pick_down(tick, state, "AAPL", decision)
        assert "skipped" not in state.triggered["AAPL"], rule_id


def test_the_settled_list_only_holds_rules_the_guardrails_actually_emit():
    """A typo here would silently stop putting a pick down and nobody would know."""
    import re                                          # noqa: PLC0415

    source = (REAL_ROOT / "agent" / "guardrails.py").read_text(encoding="utf-8")
    pattern = 'decision' + r'\.add\(\s*\n?\s*' + '"([a-z_]+)"'
    emitted = set(re.findall(pattern, source))
    assert set(loop.SETTLED_FOR_THE_DAY) <= emitted, (
        f"{sorted(set(loop.SETTLED_FOR_THE_DAY) - emitted)} is not a rule id "
        "agent/guardrails.py can refuse on")


def test_without_the_account_wide_read_the_fields_stay_empty(sandbox):
    """And the account level cap then falls back to this book's own equity."""
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    account_state = bs.account_state_for(state, gr, at(9, 40), "DUT077572", False)
    book = gr.load_book(BOOKS_YAML, "A")
    loop.fill_v2_state(account_state, state, book, at(9, 40))

    assert account_state.symbols_held_elsewhere == {}
    assert account_state.account_equity is None


# ---------------------------------------------------------------------------
# The sector, which the sector cap counts against
# ---------------------------------------------------------------------------


def test_the_sector_is_read_off_the_shortlist_row():
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.shortlist = [{"symbol": "AAPL", "sector": "Technology"}]
    assert loop.sector_for(state, "AAPL") == "Technology"


def test_a_row_with_no_industry_gives_none_rather_than_a_guess():
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.shortlist = [{"symbol": "AAPL", "sector": ""}]
    assert loop.sector_for(state, "AAPL") is None


def test_the_books_money_is_added_up_by_industry():
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.shortlist = [{"symbol": "AAPL", "sector": "Technology"},
                       {"symbol": "MSFT", "sector": "Technology"},
                       {"symbol": "JNJ", "sector": "Health Care"}]
    for symbol, value in (("AAPL", 5000.0), ("MSFT", 3000.0), ("JNJ", 2000.0)):
        state.put_position(bs.Position(symbol=symbol, qty=10, avg_cost=value / 10,
                                       side="long", market_value=value))

    assert loop.sector_exposure_for(state) == {"Technology": 8000.0,
                                               "Health Care": 2000.0}


def test_a_position_with_no_industry_is_counted_on_its_own():
    """Never quietly making room for another name in a sector it might be in."""
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.put_position(bs.Position(symbol="ZZZZ", qty=10, avg_cost=100.0,
                                   side="long", market_value=1000.0))
    assert loop.sector_exposure_for(state) == {"": 1000.0}


# ---------------------------------------------------------------------------
# The heartbeat
# ---------------------------------------------------------------------------


def test_a_finished_tick_touches_the_heartbeat(sandbox):
    path = loop.touch_heartbeat(at(9, 40))
    assert path == sandbox / "output" / "heartbeat"
    assert "2026-09-08T09:40" in path.read_text()


def test_the_dead_mans_handle_prefers_that_file(sandbox):
    from agent import deadman                    # noqa: PLC0415

    loop.touch_heartbeat(at(9, 40))
    beat = deadman.heartbeat(sandbox)
    assert beat.source == "output/heartbeat"


# ---------------------------------------------------------------------------
# After a kill switch, reconcile rather than halt forever
# ---------------------------------------------------------------------------


def test_a_plain_stop_file_somebody_touched_is_not_a_flatten(sandbox):
    (sandbox / "output" / "STOP").write_text("")
    assert loop.kill_switch_flattened(sandbox) is False


def test_a_stop_file_that_says_it_flattened_is_a_flatten(sandbox):
    (sandbox / "output" / "STOP").write_text(
        "2026-09-08 09:50 the kill switch flattened every position\n")
    assert loop.kill_switch_flattened(sandbox) is True


def test_the_marker_file_says_so_on_its_own(sandbox):
    (sandbox / "output" / loop.KILL_SWITCH_FLATTENED_FILE).write_text("done\n")
    assert loop.kill_switch_flattened(sandbox) is True


def test_a_position_the_broker_no_longer_has_is_marked_closed_not_mismatched(sandbox):
    """Nothing went wrong. Somebody pulled the handle and it worked."""
    tick = tick_for("A", at(9, 50))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long", last_close=101.0,
                                   opened_on="2026-09-08", market_value=10100.0))

    closed = loop.close_positions_flattened_by_the_kill_switch(tick, state, {})

    assert closed == 1
    assert state.position("AAPL") is None
    assert state.realized_pnl_today == 100.0, "the profit it was closed at is kept"
    assert any(row["decision"] == "closed by the kill switch"
               for row in state.decisions)


def test_a_position_the_broker_still_holds_is_left_to_the_reconciliation(sandbox):
    """That one really is a mismatch, and a mismatch still halts the book."""
    tick = tick_for("A", at(9, 50))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long", opened_on="2026-09-08"))

    closed = loop.close_positions_flattened_by_the_kill_switch(
        tick, state, {"AAPL": {"position": 100}})

    assert closed == 0
    assert state.position("AAPL") is not None


def test_the_working_orders_for_a_flattened_name_go_too(sandbox):
    tick = tick_for("A", at(9, 50))
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long", opened_on="2026-09-08"))
    state.working_orders["501"] = {"symbol": "AAPL", "purpose": "stop"}
    state.working_orders["502"] = {"symbol": "MSFT", "purpose": "stop"}

    loop.close_positions_flattened_by_the_kill_switch(tick, state, {})

    assert "501" not in state.working_orders
    assert "502" in state.working_orders, "another name's stop is nothing to do with it"


# ---------------------------------------------------------------------------
# The flatten: nothing this book has resting survives it, and the quotes it
# closes on have to say what they are
# ---------------------------------------------------------------------------
#
# Two findings, both from the replay gate rather than from reading the code.
#
# An entry goes out as a bracket, a limit parent and a resting stop-limit child,
# and until 2026-09-06 nothing cancelled either at the close. cancel_order was
# reachable from exactly two places, moving a stop and the sixty second stop
# backstop, and neither of them runs at 15:45. Live that is a stop resting for a
# position that no longer exists, plus an unfilled entry that can fill on the
# next open into a book that believes it is flat.
#
# And the flatten read its quotes through snapshot_by_symbol(), which returned
# the prices and dropped everything the feed said about itself into a list the
# caller threw away. So from 15:45 a competing session (IBKR code 10197) and a
# subscription that had lapsed to delayed data were both handled exactly like a
# quote that did not arrive: no log line, no alert, no halt.

#: The paper account. The live order path refuses any id not starting with DU.
PAPER_ACCOUNT = "DUT077572"

#: A live quote with both sides of the spread on it, so a limit flatten has a
#: bid to sit on. marketDataType 1 is the "this price is current" answer
#: read_quotes asks for, and a fake that leaves it out looks exactly like a
#: subscription that has lapsed.
LIVE_QUOTE = {"symbol": "AAPL", "last": 100.0, "close": 100.0, "bid": 99.90,
              "ask": 100.10, "marketDataType": loop.MARKET_DATA_LIVE}


class FlattenBroker(QuoteBroker):
    """Takes cancels and closing orders, sends none of them, remembers the order.

    One list for both kinds of call, because the order they happen in is the
    point rather than a detail: a stop still live while a closing order fills
    sells stock the book has already sold.
    """

    def __init__(self, quotes: list[dict] | None = None, cancels: bool = True):
        super().__init__([LIVE_QUOTE] if quotes is None else quotes)
        self.did: list[str] = []
        self.cancels = cancels
        self._next_id = 900

    def cancel_order(self, order_id):
        self.did.append(f"cancel {order_id}")
        return {"order_id": order_id, "cancelled": self.cancels,
                "error": None if self.cancels else "it filled a moment ago"}

    def place_order(self, contract, order, order_ref=""):
        self._next_id += 1
        self.did.append(f"place {order.get('action')} {contract.get('symbol')} "
                        f"{order.get('orderType')}")
        return {"sent": True, "order_id": self._next_id, "working": True,
                "filled_qty": 0.0, "avg_fill_price": None, "error": None,
                "confirmed_by": "open_orders"}


class RefusingBroker(FlattenBroker):
    """A broker that raises on a cancel instead of answering it."""

    def cancel_order(self, order_id):
        self.did.append(f"cancel {order_id}")
        raise RuntimeError("the gateway went away mid cancel")


class DelayedBroker(FlattenBroker):
    """Quotes that came back fifteen minutes old when live was asked for."""

    def snapshot(self, contracts, market_data_type=3):
        self.snapshot_calls.append(contracts)
        return {"snapshots": [dict(LIVE_QUOTE,
                                   marketDataType=loop.MARKET_DATA_DELAYED)],
                "market_data_type": loop.MARKET_DATA_DELAYED}


class MuteBroker(FlattenBroker):
    """A snapshot that failed with no IBKR code and no data type on it at all."""

    def snapshot(self, contracts, market_data_type=3):
        raise RuntimeError("the quote request timed out")


class TakenDataLine(RuntimeError):
    """What a broker raises when another session holds the market data line.

    The number is on the exception and not in the words, exactly as
    agent/replay/fake_broker.py raises it, so a passing test proves the code was
    read off the object rather than scraped out of a sentence.
    """

    def __init__(self):
        super().__init__("market data is not available because another session "
                         "is using this account")
        self.code = loop.COMPETING_SESSION_CODE


class CompetingBroker(FlattenBroker):
    """Another session has taken the market data line, so no quote arrives."""

    def snapshot(self, contracts, market_data_type=3):
        raise TakenDataLine()


def flatten_parts(sandbox: Path, now: datetime, holding: tuple = (),
                  book_id: str = "A"):
    """Everything do_flatten needs, on a book in full mode.

    Full mode opens one of the four live locks and each test opens the others,
    which is the only way to watch a cancel actually happen. Nothing can reach a
    broker from here: every fake in this file either records the call or raises.

    holding is what the book has open, as (symbol, shares, price) triples, and
    it goes in BEFORE the account state is worked out. That order matters: the
    guardrails read what is held off the account snapshot, so a position added
    afterwards is a position they cannot see, and the closing order then reads
    as a naked short sale and is refused by the no_shorts rule.
    """
    book = dataclasses.replace(gr.load_books(BOOKS_YAML).get(book_id), mode="full")
    guard = guard_for(book_id)
    state = bs.load_state(book_id, f"BOOK_{book_id}", TUESDAY, capital=100000,
                          root=sandbox)
    for symbol, qty, price in holding:
        state.put_position(bs.Position(
            symbol=symbol, qty=qty, avg_cost=price, entry=price, side="long",
            opened_on=f"{TUESDAY:%Y-%m-%d}", stop=round(price * 0.985, 2),
            market_value=qty * price))
    tick = loop.BookTick(book, now, "testhash", write_ledger=False, quiet=True)
    account_state = bs.account_state_for(state, gr, now, PAPER_ACCOUNT, False)
    return (tick, state, loop.plan_for(book, guard), guard, account_state,
            loop.read_guards(sandbox))


#: One long position in AAPL, a hundred shares bought at a hundred dollars.
HELD_AAPL = (("AAPL", 100, 100.0),)


def cancels(broker: FlattenBroker) -> list[str]:
    return [call for call in broker.did if call.startswith("cancel")]


def test_the_flatten_pulls_the_resting_stop_and_the_unfilled_entry(
        sandbox, sent, monkeypatch):
    """Both legs of the bracket, and the position closed after them.

    The entry in REST never filled and the stop in AAPL is the bracket's child.
    Neither has anything to do with the closing order, and both used to sit
    there through the close.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)
    state.working_orders = {
        "501": {"symbol": "REST", "purpose": "entry", "remaining": 100,
                "limit_price": 99.5},
        "502": {"symbol": "AAPL", "purpose": "stop", "price": 98.5,
                "is_child": True}}

    broker = FlattenBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert sorted(cancels(broker)) == ["cancel 501", "cancel 502"]
    assert "501" not in state.working_orders
    assert "502" not in state.working_orders
    assert [o.get("purpose") for o in state.working_orders.values()] == ["flatten"], (
        "the only order left resting after the flatten is the flatten itself")
    assert sent == []


def test_the_cancel_goes_out_before_the_closing_order(sandbox, sent, monkeypatch):
    """The order of the two is the whole point.

    Closing first would leave a live stop able to fill against a position that
    is already gone, and the book would end up short a name it never sold.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)
    state.working_orders = {"502": {"symbol": "AAPL", "purpose": "stop",
                                    "price": 98.5, "is_child": True}}

    broker = FlattenBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert broker.did == ["cancel 502", "place SELL AAPL LMT"]
    written = [row["decision"] for row in state.decisions]
    assert written.index("cancelled order 502") < next(
        i for i, decision in enumerate(written) if decision.startswith("placed ")), (
        "the book file has to say the same thing in the same order")


def test_a_flatten_with_nothing_resting_pulls_nothing_and_raises_nothing(
        sandbox, sent, monkeypatch):
    """The ordinary case. A book flat at 15:45 with no orders out."""
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(sandbox, at(15, 46))

    broker = FlattenBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert broker.did == []
    assert tick.notes == []
    assert state.working_orders == {}
    assert sent == []


def test_an_order_the_broker_will_not_cancel_is_left_and_said_to_be_still_live(
        sandbox, sent, monkeypatch):
    """It stays in the book file, so the next tick tries it again."""
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry",
                                    "remaining": 100, "limit_price": 99.5}}

    broker = FlattenBroker(cancels=False)
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert "501" in state.working_orders
    assert any("still resting at the broker" in note for note in tick.notes)
    assert "place SELL AAPL LMT" in broker.did, (
        "one order that would not come off does not stop the book getting out")


def test_a_cancel_that_raises_does_not_stop_the_flatten(sandbox, sent, monkeypatch):
    """A broker that goes away mid cancel is a note, never an exception.

    The flatten is the last thing this book does all day. Something raising out
    of it would leave the position open overnight, which is the one outcome the
    whole 15:45 rule exists to prevent.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry",
                                    "remaining": 100, "limit_price": 99.5}}

    broker = RefusingBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert any("would not cancel" in note for note in tick.notes)
    assert "501" in state.working_orders
    assert "place SELL AAPL LMT" in broker.did


def test_cancelling_twice_in_one_day_pulls_each_order_once(sandbox, sent, monkeypatch):
    """15:45 and the 15:55 backstop both come through here, so it runs twice."""
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, _plan, _guard, account, guards = flatten_parts(sandbox, at(15, 46))
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry",
                                    "remaining": 100}}

    broker = FlattenBroker()
    first = loop.cancel_working_orders(tick, state, broker, guards, account,
                                       "this book is flattening")
    second = loop.cancel_working_orders(tick, state, broker, guards, account,
                                        "this book is flattening")

    assert (first, second) == (1, 0)
    assert broker.did == ["cancel 501"]


def test_the_market_backstop_pulls_the_limit_flatten_the_last_tick_left(
        sandbox, sent, monkeypatch):
    """15:55. The 15:45 limit did not fill, so it comes off and a market order goes.

    This is the second cancel the day asks for, and it is why the helper has to
    be safe to call again: the thing it pulls at 15:55 is what it placed at
    15:45.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 56), holding=HELD_AAPL)
    state.working_orders = {"901": {"symbol": "AAPL", "purpose": "flatten",
                                    "side": "SELL", "qty": 100, "remaining": 100,
                                    "limit_price": 99.90}}

    broker = FlattenBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert broker.did == ["cancel 901", "place SELL AAPL MKT"]


def test_a_dry_run_cancels_nothing_and_says_what_it_would_have_done(
        sandbox, sent, capsys):
    """Every book is in dry run today, so this is the path that actually runs."""
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    state.working_orders = {"501": {"symbol": "REST", "purpose": "entry",
                                    "remaining": 100}}
    tick = loop.BookTick(gr.load_book(BOOKS_YAML, "A"), at(15, 46), "testhash",
                         write_ledger=False)
    account = bs.account_state_for(state, gr, at(15, 46), PAPER_ACCOUNT, False)

    broker = FlattenBroker()
    pulled = loop.cancel_working_orders(tick, state, broker, loop.read_guards(sandbox),
                                        account, "this book is flattening at 15:45")

    assert pulled == 0
    assert broker.did == []
    assert "501" in state.working_orders
    printed = capsys.readouterr().out
    assert "would cancel order 501" in printed
    assert "because this book is flattening at 15:45" in printed


# ---------------------------------------------------------------------------
# A snapshot failure at the flatten is not a note nobody reads
# ---------------------------------------------------------------------------


def test_a_taken_data_line_at_the_flatten_halts_the_book_and_tells_mo(
        sandbox, sent, monkeypatch):
    """IBKR code 10197, which used to vanish into a list do_flatten threw away.

    Prices nobody can trust are worse than no prices, so the book is halted. A
    halt stops it OPENING anything and leaves the closing path alone, and the
    position still goes out, at market, because no bid or ask arrived to sit a
    limit order on.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)

    broker = CompetingBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert state.halted is True
    assert bs.HALT_MARKET_DATA in state.halt_causes()
    assert str(loop.COMPETING_SESSION_CODE) in tick.data_block
    assert [title for _level, title, _body in sent] == [
        "Another session has taken the market data line"]
    assert "place SELL AAPL MKT" in broker.did, (
        "an exit is never blocked by the state of the feed")


def test_a_delayed_feed_at_the_flatten_stops_an_entry_and_lets_the_exit_out(
        sandbox, sent, monkeypatch):
    """Market data type 3 during the session means the live subscription lapsed.

    A price about fifteen minutes old is fine for deciding whether to get out of
    something and is not fine for deciding what to pay for it, which is exactly
    the split this asserts.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)

    broker = DelayedBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    blocked = loop.entries_blocked_reason(guards, state, tick)
    assert blocked and "delayed" in blocked
    assert state.halted is True
    assert [level for level, _title, _body in sent] == ["warn"]
    assert "place SELL AAPL LMT" in broker.did, (
        "the price that did arrive is good enough to get out on")


def test_one_name_whose_quote_did_not_arrive_is_only_a_note(sandbox, sent,
                                                            monkeypatch):
    """Two positions, one quote. An unreadable name is not a reason to stop.

    The fake answers about AAPL and says nothing at all about MSFT, which is
    what a single name nobody could price looks like. MSFT goes out at market
    and the book is not halted.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=(("AAPL", 100, 100.0), ("MSFT", 50, 200.0)))

    broker = FlattenBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert state.halted is False
    assert sent == []
    assert any("MSFT" in note and "no bid or ask" in note for note in tick.notes)
    assert "place SELL AAPL LMT" in broker.did
    assert "place SELL MSFT MKT" in broker.did


def test_a_snapshot_that_simply_failed_is_a_note_and_not_a_halt(sandbox, sent,
                                                                monkeypatch):
    """No IBKR code and no market data type: nothing here says the feed is bad.

    A Gateway that has gone away is somebody else's job, in read_broker_facts
    and broker_unavailable_tick. Halting the book on a timed out quote request
    would stop the day over the one failure that is most often a single slow
    reply.
    """
    monkeypatch.setenv(loop.LIVE_ENV_VAR, "yes")
    tick, state, plan, guard, account, guards = flatten_parts(
        sandbox, at(15, 46), holding=HELD_AAPL)

    broker = MuteBroker()
    loop.do_flatten(tick, state, plan, guard, broker, account, guards)

    assert state.halted is False
    assert sent == []
    assert any("no quotes came back" in note for note in tick.notes)
    assert "place SELL AAPL MKT" in broker.did


def test_a_caller_with_no_book_to_halt_still_gets_the_reason_in_writing(sandbox):
    """snapshot_by_symbol used to return the prices and drop all of this.

    Without a tick there is no book to halt and nobody to tell, so the verdict
    goes into notes. That is the difference between a caller that can act on it
    and the silence there used to be.
    """
    taken: list[str] = []
    loop.snapshot_by_symbol(CompetingBroker(), [{"symbol": "AAPL"}], taken)
    assert any(str(loop.COMPETING_SESSION_CODE) in note for note in taken)

    delayed: list[str] = []
    loop.snapshot_by_symbol(DelayedBroker(), [{"symbol": "AAPL"}], delayed)
    assert any("delayed" in note for note in delayed)

    live: list[str] = []
    quotes = loop.snapshot_by_symbol(FlattenBroker(), [{"symbol": "AAPL"}], live)
    assert live == [], "a live feed has nothing to say about itself"
    assert quotes["AAPL"]["bid"] == 99.90
