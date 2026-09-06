"""Tests for the kill switch's order building.

This is the one part of the project that can trade, so the piece that decides
which side and how many shares gets checked here in isolation. Nothing in this
file connects to anything: it hands closing_order() a position and reads back
the order it would have built.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_kill_switch.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import kill_switch as ks  # noqa: E402

LONG_SPY = {"symbol": "SPY", "secType": "STK", "exchange": "ARCA", "currency": "USD",
            "conId": 756733, "position": 1.0, "marketValue": 769.42}
SHORT_DELL = {"symbol": "DELL", "secType": "STK", "exchange": "NYSE", "currency": "USD",
              "conId": 346218218, "position": -25.0, "marketValue": -11869.25}


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


def test_only_paper_accounts_are_allowed():
    assert ks.PAPER_PREFIX == "DU", (
        "the guard in main() refuses any account id that does not start with this")
