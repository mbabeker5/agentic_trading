"""Tests for the kill switch: the order building, the live account gate, and
the whole cancel-then-flatten run against a pretend broker.

This is the one part of the project that can trade, so it gets tested three
ways. The small functions get their arithmetic checked in isolation. The gate
that stops a live account being flattened gets a test for every way it can be
half satisfied. And the whole run happens end to end against
agent/replay/fake_broker.py, which holds two books' positions and two books'
resting orders, so "cancel everything, then close everything, then read it back
until it is flat" is proved rather than assumed.

Nothing here reaches the network, IB Gateway, the MCP server or a real account.
Every alert channel is replaced, and every file the kill switch writes goes to a
throwaway folder through AGENTIC_TRADING_ROOT.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_kill_switch.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import alerts  # noqa: E402
import broker as broker_mod  # noqa: E402
import kill_switch as ks  # noqa: E402

from agent.replay.fake_broker import FakeBroker  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

LONG_SPY = {"symbol": "SPY", "secType": "STK", "exchange": "ARCA", "currency": "USD",
            "conId": 756733, "position": 1.0, "marketValue": 769.42}
SHORT_DELL = {"symbol": "DELL", "secType": "STK", "exchange": "NYSE", "currency": "USD",
              "conId": 346218218, "position": -25.0, "marketValue": -11869.25}


# --------------------------------------------------------- building the orders

def test_a_long_is_closed_by_selling():
    assert ks.side_to_close(1.0) == "SELL"
    assert ks.side_to_close(1000.0) == "SELL"


def test_a_short_is_closed_by_buying():
    assert ks.side_to_close(-1.0) == "BUY"
    assert ks.side_to_close(-25.0) == "BUY"


def test_closing_a_long_sells_the_whole_position_at_the_market():
    contract, order = ks.closing_order(LONG_SPY, "DUT077572")
    assert order == {"action": "SELL", "totalQuantity": 1, "orderType": "MKT",
                     "tif": "DAY", "account": "DUT077572"}
    assert contract["symbol"] == "SPY"
    assert contract["conId"] == 756733
    assert contract["exchange"] == "SMART", "route through IBKR's own router"


def test_closing_a_short_buys_back_a_positive_number_of_shares():
    _, order = ks.closing_order(SHORT_DELL, "DUT077572")
    assert order["action"] == "BUY"
    assert order["totalQuantity"] == 25, "a positive quantity, never a negative one"


def test_a_whole_number_of_shares_stays_a_whole_number():
    _, order = ks.closing_order({**LONG_SPY, "position": 400.0}, None)
    assert order["totalQuantity"] == 400
    assert isinstance(order["totalQuantity"], int)


def test_a_fractional_position_keeps_its_fraction():
    _, order = ks.closing_order({**LONG_SPY, "position": 0.5}, None)
    assert order["totalQuantity"] == 0.5


def test_a_position_without_a_contract_id_still_builds_an_order():
    contract, order = ks.closing_order({"symbol": "SPY", "position": 2.0}, None)
    assert "conId" not in contract
    assert contract["secType"] == "STK" and contract["currency"] == "USD"
    assert order["action"] == "SELL" and order["totalQuantity"] == 2


def test_no_account_means_no_account_field_on_the_order():
    _, order = ks.closing_order(LONG_SPY, None)
    assert "account" not in order


def test_flat_positions_are_left_out():
    portfolio = {"positions": [LONG_SPY, {"symbol": "AAPL", "position": 0.0},
                               {"symbol": "MSFT", "position": None}]}
    assert [p["symbol"] for p in ks.open_positions(portfolio)] == ["SPY"]


def test_an_empty_or_missing_portfolio_has_nothing_to_close():
    assert ks.open_positions({}) == []
    assert ks.open_positions({"positions": []}) == []
    assert ks.open_positions(None) == []


def test_the_description_names_the_side_and_the_size():
    text = ks.describe(SHORT_DELL)
    assert "DELL" in text and "BUY 25" in text


def test_an_order_id_is_found_under_whichever_name_it_arrived_as():
    assert ks.order_id_of({"orderId": 4}) == 4
    assert ks.order_id_of({"order_id": 7}) == 7
    assert ks.order_id_of({"nothing": "useful"}) is None


def test_working_orders_copes_with_an_empty_or_odd_reply():
    assert ks.working_orders({"orders": [{"orderId": 1}]}) == [{"orderId": 1}]
    assert ks.working_orders({}) == []
    assert ks.working_orders(None) == []
    assert ks.working_orders({"orders": [None, "nonsense"]}) == []


def test_only_paper_accounts_are_allowed_without_saying_so_twice():
    assert ks.PAPER_PREFIX == "DU"
    assert ks.is_paper_account("DUT077572")
    assert not ks.is_paper_account("U1234567")
    assert not ks.is_paper_account("")


# ------------------------------------------------------------- the test broker

def at(hour: int, minute: int) -> datetime:
    """One moment on the test day, Tuesday 2026-09-08."""
    return datetime(2026, 9, 8, hour, minute, tzinfo=EASTERN)


def bars_from(price: float, count: int = 25) -> list[dict]:
    """Five minute bars from 09:30, drifting up a dime a bar. Easy to read."""
    rows = []
    for step in range(count):
        moment = at(9, 30) + timedelta(minutes=5 * step)
        level = round(price + step * 0.10, 2)
        rows.append({"time": moment.isoformat(), "open": level, "high": level + 0.50,
                     "low": level - 0.50, "close": level, "volume": 100_000,
                     "average": level, "barCount": 50})
    return rows


def contract(symbol: str) -> dict:
    return {"symbol": symbol, "secType": "STK", "exchange": "SMART", "currency": "USD"}


def two_book_broker(account_id: str = "DUT077572") -> FakeBroker:
    """A broker holding two books' positions and two books' resting orders.

    BOOK_A is long 10 SPY, BOOK_C is long 20 DELL, and each has a sell limit
    resting miles above the market so it never fills. That is the shape the kill
    switch is for: things to cancel and things to close, belonging to more than
    one book.
    """
    broker = FakeBroker(bars={"SPY": bars_from(700.0), "DELL": bars_from(100.0)},
                        account_id=account_id, now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 10, "orderType": "MKT"},
                       "BOOK_A")
    broker.place_order(contract("DELL"),
                       {"action": "BUY", "totalQuantity": 20, "orderType": "MKT"},
                       "BOOK_C")
    broker.advance_to(at(9, 40))
    broker.place_order(contract("SPY"),
                       {"action": "SELL", "totalQuantity": 10, "orderType": "LMT",
                        "lmtPrice": 9_999.0}, "BOOK_A")
    broker.place_order(contract("DELL"),
                       {"action": "SELL", "totalQuantity": 20, "orderType": "LMT",
                        "lmtPrice": 9_999.0}, "BOOK_C")
    return broker


def clock_runner(broker: FakeBroker, start: datetime = at(9, 40)):
    """A stand in for time.sleep that moves the replay clock instead of waiting.

    The kill switch reads the account back five times with a wait between each.
    In real life the wait is what lets a market order fill. Here the fill comes
    from the next recorded bar, so the wait becomes a five minute step forward
    and the whole test runs in milliseconds.
    """
    state = {"at": start}

    def sleep(_seconds: float) -> None:
        state["at"] = state["at"] + timedelta(minutes=5)
        broker.advance_to(state["at"])

    return sleep


@pytest.fixture
def quiet(monkeypatch, tmp_path):
    """No alert leaves the machine, and every file lands in a temporary folder."""
    sent: list[tuple] = []
    monkeypatch.setattr(alerts, "alert",
                        lambda level, title, body: sent.append((level, title, body))
                        or ["log"])
    monkeypatch.setenv("AGENTIC_TRADING_ROOT", str(tmp_path))
    monkeypatch.delenv(ks.LIVE_KILL_ENV_VAR, raising=False)
    monkeypatch.delenv(broker_mod.LIVE_ENV_VAR, raising=False)
    return sent


def brakes(tmp_path: Path) -> tuple[bool, bool]:
    return ((tmp_path / "output" / "STOP").exists(),
            (tmp_path / "output" / "LOOP_DISABLED").exists())


# ------------------------------------------------------- the live account gate

def test_a_live_account_is_refused_when_neither_the_flag_nor_the_variable_is_there(
        quiet, tmp_path):
    broker = two_book_broker(account_id="U1234567")
    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))

    assert status == 2
    assert "does not start with DU" in result.refused
    assert result.live_account is True
    assert broker.positions["SPY"] == 10, "nothing was closed"
    assert len(ks.working_orders(broker.open_orders())) == 2, "nothing was cancelled"
    assert brakes(tmp_path) == (True, True), "the loop is stopped either way"
    assert quiet and "refused" in quiet[-1][1].lower()


def test_a_live_account_is_refused_with_the_flag_but_no_environment_variable(
        quiet, tmp_path):
    broker = two_book_broker(account_id="U1234567")
    status, result = ks.pull(broker, really=True, live_account_ok=True,
                             sleep=clock_runner(broker))

    assert status == 2
    assert ks.LIVE_KILL_ENV_VAR in result.refused
    assert broker.positions["SPY"] == 10
    assert brakes(tmp_path) == (True, True)


def test_a_live_account_is_refused_with_the_environment_variable_but_no_flag(
        quiet, tmp_path, monkeypatch):
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "yes")
    broker = two_book_broker(account_id="U1234567")
    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))

    assert status == 2
    assert "--live-account-ok" in result.refused
    assert broker.positions["SPY"] == 10


def test_a_live_account_is_flattened_with_both_and_the_alert_says_it_was_live(
        quiet, monkeypatch):
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "yes")
    broker = two_book_broker(account_id="U1234567")
    status, result = ks.pull(broker, really=True, live_account_ok=True,
                             sleep=clock_runner(broker))

    assert status == 0 and result.flat is True
    assert result.live_account is True
    assert broker.positions["SPY"] == 0 and broker.positions["DELL"] == 0
    level, title, body = quiet[-1]
    assert "LIVE account U1234567" in title
    assert "THIS WAS A LIVE ACCOUNT" in body


def test_the_variable_has_to_say_exactly_yes(monkeypatch):
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "YES")
    assert not ks.live_kill_allowed()
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "true")
    assert not ks.live_kill_allowed()
    monkeypatch.setenv(ks.LIVE_KILL_ENV_VAR, "yes")
    assert ks.live_kill_allowed()


# ------------------------------------------------------ cancel, then flatten

def test_cancel_then_flatten_against_two_books(quiet, tmp_path):
    broker = two_book_broker()
    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))

    assert status == 0, "the account came back flat"
    assert result.flat is True
    assert result.account == "DUT077572"
    assert len(result.before_positions) == 2
    assert len(result.before_orders) == 2

    assert broker.positions["SPY"] == 0, "book A's ten shares are gone"
    assert broker.positions["DELL"] == 0, "book C's twenty shares are gone"
    assert ks.working_orders(broker.open_orders()) == [], "nothing is still working"

    closing = [order for order in broker.all_orders()
               if order["orderRef"] == ks.KILL_ORDER_REF]
    assert len(closing) == 2, "one closing order per position"
    assert {order["action"] for order in closing} == {"SELL"}
    assert all(order["orderType"] == "MKT" for order in closing)

    assert brakes(tmp_path) == (True, True)
    assert result.record_path and Path(result.record_path).exists()
    assert quiet[-1][1] == "Kill switch fired on account DUT077572"


def test_the_closing_orders_are_not_tagged_as_a_book(quiet):
    """The dead man's handle tells a book's position from an orphan by the tag,
    so a closing order must never look like a book's own order."""
    broker = two_book_broker()
    ks.pull(broker, really=True, sleep=clock_runner(broker))
    assert not ks.KILL_ORDER_REF.startswith("BOOK_")


def test_a_short_is_bought_back_rather_than_sold_again(quiet):
    broker = FakeBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                        now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "SELL", "totalQuantity": 5, "orderType": "MKT"},
                       "BOOK_B")
    broker.advance_to(at(9, 40))
    assert broker.positions["SPY"] == -5

    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))
    assert status == 0 and result.flat
    assert broker.positions["SPY"] == 0
    closing = [o for o in broker.all_orders() if o["orderRef"] == ks.KILL_ORDER_REF]
    assert [o["action"] for o in closing] == ["BUY"]


def test_stragglers_are_cancelled_one_at_a_time_when_the_global_cancel_does_nothing(
        quiet):
    """IBKR ignores a global cancel often enough that the second pass matters."""

    class DeafBroker(FakeBroker):
        """A broker whose global cancel says yes and does nothing at all."""

        def global_cancel(self) -> dict:
            return {"cancelled": [], "count": 0, "note": "ignored, on purpose"}

    broker = DeafBroker(bars={"SPY": bars_from(700.0), "DELL": bars_from(100.0)},
                        account_id="DUT077572", now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 10, "orderType": "MKT"},
                       "BOOK_A")
    broker.advance_to(at(9, 40))
    broker.place_order(contract("SPY"),
                       {"action": "SELL", "totalQuantity": 10, "orderType": "LMT",
                        "lmtPrice": 9_999.0}, "BOOK_A")
    broker.place_order(contract("DELL"),
                       {"action": "BUY", "totalQuantity": 5, "orderType": "LMT",
                        "lmtPrice": 0.01}, "BOOK_C")

    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))

    assert status == 0 and result.flat is True
    assert ks.working_orders(broker.open_orders()) == []
    one_by_one = [line for line in result.did if "on its own" in line]
    assert len(one_by_one) == 2, "both stragglers were chased individually"


def test_a_failed_global_cancel_does_not_stop_the_flatten(quiet):
    class AngryBroker(FakeBroker):
        def global_cancel(self) -> dict:
            raise RuntimeError("the gateway dropped the connection")

    broker = AngryBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                         now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 10, "orderType": "MKT"},
                       "BOOK_A")
    broker.advance_to(at(9, 40))

    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))
    assert status == 0 and result.flat is True
    assert broker.positions["SPY"] == 0
    assert any("global cancel reported an error" in line for line in result.did)


def test_it_reports_what_is_left_when_the_account_will_not_go_flat(quiet):
    """A market order that never fills is the after hours case, and it must be
    reported as not flat rather than assumed away."""
    broker = FakeBroker(bars={"SPY": bars_from(700.0, count=3)},
                        account_id="DUT077572", now=at(9, 30))
    broker.place_order(contract("SPY"),
                       {"action": "BUY", "totalQuantity": 10, "orderType": "MKT"},
                       "BOOK_A")
    broker.advance_to(at(9, 40))

    # The clock runs past the last recorded bar, so nothing can fill after this.
    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker, at(11, 0)))

    assert status == 1, "acted, but the account is not flat"
    assert result.flat is False
    assert [p["symbol"] for p in result.after_positions] == ["SPY"]
    assert any("still not flat after 5 reads" in line for line in result.did)
    assert "NOT flat yet" in quiet[-1][2]


def test_a_broker_that_cannot_be_read_stops_it_but_still_stops_the_loop(quiet, tmp_path):
    broker = two_book_broker()
    broker.inject_fault("gateway_down")

    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))

    assert status == 2
    assert "could not read the account" in result.refused
    assert brakes(tmp_path) == (True, True)
    assert "could not read the account" in quiet[-1][1]


# ------------------------------------------------------------- the rehearsal

def test_the_rehearsal_sends_nothing_but_still_writes_the_brakes(quiet, tmp_path, capsys):
    broker = two_book_broker()
    status, result = ks.pull(broker, really=False)

    assert status == 0
    assert broker.positions["SPY"] == 10, "nothing was closed"
    assert len(ks.working_orders(broker.open_orders())) == 2, "nothing was cancelled"
    assert quiet == [], "no alert left the machine"
    assert brakes(tmp_path) == (True, True), "the brakes are written even in a rehearsal"

    printed = capsys.readouterr().out
    assert "REHEARSAL over" in printed
    assert "SELL 10 SPY at the market" in printed


def test_the_rehearsal_of_a_live_account_still_refuses(quiet, capsys):
    broker = two_book_broker(account_id="U1234567")
    status, result = ks.pull(broker, really=False)
    assert status == 2 and result.live_account
    assert quiet == [], "a rehearsal never alerts, not even when it refuses"


def test_an_empty_account_has_nothing_to_do(quiet):
    broker = FakeBroker(bars={"SPY": bars_from(700.0)}, account_id="DUT077572",
                        now=at(9, 30))
    status, result = ks.pull(broker, really=True, sleep=clock_runner(broker))
    assert status == 0 and result.did == []
    assert quiet == [], "nothing happened, so nobody is told"


# ---------------------------------------------------------------- the locks

def test_the_order_lock_is_lifted_only_for_as_long_as_the_orders_take(quiet):
    broker = two_book_broker()
    assert not broker_mod.live_orders_enabled()
    ks.pull(broker, really=True, sleep=clock_runner(broker))
    assert not broker_mod.live_orders_enabled(), (
        "the lock in agent/broker.py has to be back on afterwards")
    assert broker_mod.LIVE_ENV_VAR not in os.environ


def test_a_lock_that_was_already_set_is_left_as_it_was(monkeypatch):
    monkeypatch.setenv(broker_mod.LIVE_ENV_VAR, "no")
    with ks.order_lock_lifted():
        assert broker_mod.live_orders_enabled()
    assert os.environ[broker_mod.LIVE_ENV_VAR] == "no"


def test_the_brake_files_say_who_wrote_them_and_how_to_undo_it(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIC_TRADING_ROOT", str(tmp_path))
    written = ks.write_brakes(at(10, 15))
    assert [path.name for path in written] == ["STOP", "LOOP_DISABLED"]
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert "kill_switch.py" in text
        assert "reenable.sh" in text
