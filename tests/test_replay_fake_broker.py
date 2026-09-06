"""Tests for the pretend broker the replay harness fills orders against.

The point of these is narrow and important: the fake broker is the thing that
decides whether the whole five book loop "worked" before any real paper order is
allowed. If its arithmetic is wrong, every scenario it passes is worthless. So
every fill rule gets a test with the price written out by hand, and every fault
gets a test that it actually breaks what it claims to break.

Nothing here touches the network, IB Gateway, an account, or a recording on
disk. Every bar is written into the test.

Dates are all Tuesday 2026-09-08, which is the day the recorder is scheduled to
run for real.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest -q tests/test_replay_fake_broker.py
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent.replay.fake_broker import (
    COMPETING_SESSION_CODE,
    FakeBroker,
    FakeBrokerError,
    commission_for,
)

EASTERN = ZoneInfo("America/New_York")
DAY = "2026-09-08"


def at(hour: int, minute: int) -> str:
    """One moment on the test day, as the ISO string the broker takes."""
    return datetime(2026, 9, 8, hour, minute, tzinfo=EASTERN).isoformat()


def bar(hour: int, minute: int, open_: float, high: float, low: float,
        close: float, volume: float = 100_000) -> dict:
    """One five minute bar, in the shape agent/replay/common.bar_to_dict makes."""
    return {
        "time": datetime(2026, 9, 8, hour, minute, tzinfo=EASTERN).isoformat(),
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume, "average": round((high + low + close) / 3.0, 2),
        "barCount": 50,
    }


# SPY through the first twenty minutes: up, then a sharp reversal down. Chosen so
# every fill rule has a bar that exercises it and the numbers are easy to check
# on paper.
SPY_BARS = [
    bar(9, 30, 100.00, 101.00, 99.50, 100.50),
    bar(9, 35, 100.60, 102.00, 100.00, 101.50),
    bar(9, 40, 101.60, 101.90, 99.00, 99.20),
    bar(9, 45, 99.10, 99.60, 98.00, 98.40),
]

# A second name, so the ordering test has two symbols to interleave.
QQQ_BARS = [
    bar(9, 30, 500.00, 502.00, 499.00, 501.00),
    bar(9, 35, 501.20, 503.00, 500.50, 502.50),
    bar(9, 40, 502.60, 503.50, 501.00, 501.20),
    bar(9, 45, 501.30, 501.80, 499.00, 499.40),
]

# A cheap stock, so the one percent commission cap can actually bite.
PENNY_BARS = [
    bar(9, 30, 2.00, 2.10, 1.95, 2.05),
    bar(9, 35, 2.05, 2.15, 2.00, 2.10),
    bar(9, 40, 2.00, 2.08, 1.90, 1.95),
    bar(9, 45, 1.95, 1.99, 1.88, 1.90),
]

# A name that falls off a cliff, so a stop-limit can trigger and then have the
# price run away from its limit before it can fill. Kept out of the shared broker
# below on purpose, because adding a fourth name would change every bar count the
# tests further down assert on.
GAP_BARS = [
    bar(9, 30, 100.00, 100.50, 99.80, 100.20),
    bar(9, 35, 100.10, 100.30, 99.00, 99.20),
    bar(9, 40, 95.00, 95.20, 94.00, 94.50),
    bar(9, 45, 94.40, 94.80, 93.50, 93.80),
]

SPY = {"symbol": "SPY", "secType": "STK", "exchange": "SMART", "currency": "USD"}
QQQ = {"symbol": "QQQ", "secType": "STK", "exchange": "SMART", "currency": "USD"}
PENNY = {"symbol": "PENNY", "secType": "STK", "exchange": "SMART", "currency": "USD"}
GAPPY = {"symbol": "GAPPY", "secType": "STK", "exchange": "SMART", "currency": "USD"}


def broker(**options) -> FakeBroker:
    """A broker holding the three test names, clock parked just before the open."""
    options.setdefault("starting_cash", 100_000.0)
    return FakeBroker(
        bars={"SPY": list(SPY_BARS), "QQQ": list(QQQ_BARS), "PENNY": list(PENNY_BARS)},
        **options,
    )


def market(action: str, shares: int) -> dict:
    return {"action": action, "totalQuantity": shares, "orderType": "MKT", "tif": "DAY"}


def limit(action: str, shares: int, price: float) -> dict:
    return {"action": action, "totalQuantity": shares, "orderType": "LMT",
            "lmtPrice": price, "tif": "DAY"}


def stop(action: str, shares: int, price: float) -> dict:
    return {"action": action, "totalQuantity": shares, "orderType": "STP",
            "auxPrice": price, "tif": "DAY"}


def stop_limit(action: str, shares: int, trigger: float, limit_price: float) -> dict:
    """A stop-limit: auxPrice wakes it up, lmtPrice is the worst price it takes."""
    return {"action": action, "totalQuantity": shares, "orderType": "STP LMT",
            "auxPrice": trigger, "lmtPrice": limit_price, "tif": "DAY"}


def order_row(b: FakeBroker, order_id) -> dict:
    """The broker's own record of one order, however that order has ended up."""
    return [row for row in b.all_orders() if row["orderId"] == order_id][0]


# ---------------------------------------------------------------- market fills

def test_market_buy_fills_at_the_next_bar_open_plus_half_the_spread():
    """The rule, written out: next bar's open 101.60, plus 0.02 because no quote
    was recorded, is 101.62. Commission on 100 shares is the one dollar minimum.
    """
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    result = b.advance_to(at(9, 40))

    assert len(result["fills"]) == 1
    fill = result["fills"][0]
    assert fill["symbol"] == "SPY"
    assert fill["side"] == "BUY"
    assert fill["shares"] == 100
    assert fill["price"] == pytest.approx(101.62)
    assert fill["commission"] == pytest.approx(1.00)
    assert fill["order_ref"] == "BOOK_A"
    # Cash out is the stock plus the commission, nothing else.
    assert b.cash == pytest.approx(100_000.0 - 100 * 101.62 - 1.00)


def test_market_sell_pays_away_half_the_spread_the_other_way():
    """Selling gets hit rather than paid up: 101.60 minus 0.02 is 101.58."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("SELL", 50), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(101.58)
    # A sell with nothing held is a short, and the broker holds it as one.
    assert b.positions["SPY"] == -50


def test_market_order_does_not_fill_on_the_bar_it_was_placed_in():
    """Placed at 09:35, when the 09:35 bar has already printed. It waits."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 10), order_ref="BOOK_A")
    assert b.executions()["executions"] == []
    assert len(b.open_orders()["orders"]) == 1


def test_recorded_spread_beats_the_default_when_there_is_one():
    """A recorded bid and ask of 101.50 and 101.70 is a 0.20 spread, so a market
    buy pays the open plus 0.10 rather than the default 0.02."""
    quotes = {"SPY": [{"time": at(9, 35), "bid": 101.50, "ask": 101.70,
                       "last": 101.60, "volume": 1_000_000}]}
    b = FakeBroker(bars={"SPY": list(SPY_BARS)}, quotes=quotes)
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(101.70)


def test_slippage_in_basis_points_is_off_by_default_and_costs_money_when_on():
    plain = broker()
    plain.advance_to(at(9, 35))
    plain.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    plain_price = plain.advance_to(at(9, 40))["fills"][0]["price"]

    slipping = broker(slippage_bps=10.0)      # ten basis points, a tenth of a percent
    slipping.advance_to(at(9, 35))
    slipping.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    slipped_price = slipping.advance_to(at(9, 40))["fills"][0]["price"]

    assert plain_price == pytest.approx(101.62)
    assert slipped_price == pytest.approx(101.62 + 101.60 * 0.0010)
    assert slipped_price > plain_price


# ----------------------------------------------------------------- limit orders

def test_limit_buy_fills_at_the_limit_when_the_bar_low_reaches_it():
    """The 09:40 bar dips to 99.00, so a 99.50 buy fills at 99.50 and not lower."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("BUY", 100, 99.50), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 1
    assert fills[0]["price"] == pytest.approx(99.50)


def test_limit_buy_fills_at_the_open_when_the_bar_opened_below_the_limit():
    """Asked to pay up to 102.00, the bar opened at 101.60, so we pay 101.60."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("BUY", 100, 102.00), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(101.60)


def test_limit_buy_does_not_fill_when_the_price_never_gets_there():
    """The lowest print in the whole replay is 98.00, so a 97.00 bid sits there."""
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.place_order(SPY, limit("BUY", 100, 97.00), order_ref="BOOK_A")
    b.advance_to(at(9, 45))
    assert b.executions()["executions"] == []
    still_open = b.open_orders()["orders"]
    assert len(still_open) == 1
    assert still_open[0]["orderId"] == answer["orderId"]
    assert still_open[0]["remaining"] == 100
    assert b.positions.get("SPY", 0) == 0


def test_limit_sell_fills_at_the_limit_when_the_bar_high_reaches_it():
    """The 09:40 bar tops out at 101.90, so a 101.90 offer is exactly filled."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("SELL", 100, 101.90), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(101.90)


def test_limit_sell_fills_at_the_open_when_the_open_is_already_above_it():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("SELL", 100, 101.00), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(101.60)


def test_limit_sell_does_not_fill_when_the_price_never_gets_there():
    b = broker()
    b.advance_to(at(9, 40))
    b.place_order(SPY, limit("SELL", 100, 110.00), order_ref="BOOK_A")
    b.advance_to(at(9, 45))
    assert b.executions()["executions"] == []


# ------------------------------------------------------------------ stop orders

def test_stop_triggers_on_the_bar_that_trades_through_it_and_fills_on_the_next():
    """A sell stop at 99.50. The 09:40 bar trades down to 99.00, which sets it
    off, but it cannot fill until the 09:45 bar, whose open is 99.10. Minus the
    0.02 half spread that is 99.08. Costing a whole bar is the honest version:
    a stop is a market order once it fires.
    """
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.place_order(SPY, stop("SELL", 100, 99.50), order_ref="BOOK_A")

    on_the_trigger_bar = b.advance_to(at(9, 40))
    assert on_the_trigger_bar["fills"] == []
    order = [o for o in b.all_orders() if o["orderId"] == answer["orderId"]][0]
    assert order["status"] == "Triggered"

    after = b.advance_to(at(9, 45))
    assert len(after["fills"]) == 1
    assert after["fills"][0]["price"] == pytest.approx(99.08)
    assert "stop triggered" in after["fills"][0]["reason"]


def test_a_stop_that_is_never_traded_through_never_fires():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, stop("SELL", 100, 90.00), order_ref="BOOK_A")
    b.advance_to(at(9, 45))
    assert b.executions()["executions"] == []
    assert b.open_orders()["orders"][0]["status"] == "Submitted"


def test_buy_stop_triggers_on_the_way_up():
    """A buy stop at 101.80. The 09:35 bar reaches 102.00, so it fires there and
    fills on the 09:40 open of 101.60 plus the half spread."""
    b = broker()
    b.advance_to(at(9, 30))
    b.place_order(SPY, stop("BUY", 100, 101.80), order_ref="BOOK_A")
    assert b.advance_to(at(9, 35))["fills"] == []
    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 1
    assert fills[0]["price"] == pytest.approx(101.62)



# ------------------------------------------------------------ stop-limit orders

def test_a_stop_limit_sits_still_until_the_price_touches_its_trigger():
    """A sell stop-limit protecting a long: trigger 99.50, limit 99.00.

    Three things in order. The 09:35 bar never gets below 100.00, so nothing
    happens at all. The 09:40 bar trades down to 99.00, which touches the
    trigger and wakes the order up, but like a plain stop it does not get to fill
    on the bar that set it off. The 09:45 bar opens at 99.10, which is above the
    99.00 limit, so it fills there.
    """
    b = broker()
    b.advance_to(at(9, 30))
    answer = b.place_order(SPY, stop_limit("SELL", 100, 99.50, 99.00),
                           order_ref="BOOK_A")

    assert b.advance_to(at(9, 35))["fills"] == []
    asleep = order_row(b, answer["orderId"])
    assert asleep["status"] == "Submitted"
    assert asleep["triggered"] is False
    assert asleep["triggered_at"] is None

    assert b.advance_to(at(9, 40))["fills"] == []
    awake = order_row(b, answer["orderId"])
    assert awake["status"] == "Triggered"
    assert awake["triggered"] is True
    assert awake["triggered_at"] == at(9, 40)

    fills = b.advance_to(at(9, 45))["fills"]
    assert len(fills) == 1
    assert fills[0]["price"] == pytest.approx(99.10)
    assert "stop-limit triggered" in fills[0]["reason"]


def test_a_stop_limit_that_gaps_through_its_limit_stays_triggered_and_unfilled():
    """The whole risk of a stop-limit, and the reason the loop needs a backstop.

    The trigger at 99.50 is touched on the 09:35 bar. The next bar opens at 95.00
    and never trades as high as the 99.00 limit again, so the order is awake,
    live, and cannot fill. The position it was meant to protect is now
    unprotected, and this broker says so plainly rather than quietly filling at a
    price that was never there.
    """
    b = FakeBroker(bars={"GAPPY": list(GAP_BARS)})
    b.advance_to(at(9, 30))
    answer = b.place_order(GAPPY, stop_limit("SELL", 100, 99.50, 99.00),
                           order_ref="BOOK_A")
    b.advance_to(at(9, 45))

    assert b.executions()["executions"] == []
    stranded = order_row(b, answer["orderId"])
    assert stranded["status"] == "Triggered"
    assert stranded["triggered"] is True
    assert stranded["remaining"] == 100
    # Still working, because it is: it is a live limit order nobody will hit.
    assert [row["orderId"] for row in b.open_orders()["orders"]] == [answer["orderId"]]


def test_a_buy_stop_limit_protects_a_short_the_other_way_round():
    """Closing a short, so the trigger is above and the limit is above that.

    Trigger 101.80 is touched by the 09:35 bar's high of 102.00. The 09:40 bar
    opens at 101.60, which is below the 102.20 limit, so the buy fills at the
    open and pays less than it was willing to.
    """
    b = broker()
    b.advance_to(at(9, 30))
    b.place_order(SPY, stop_limit("BUY", 100, 101.80, 102.20), order_ref="BOOK_A")
    assert b.advance_to(at(9, 35))["fills"] == []
    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 1
    assert fills[0]["price"] == pytest.approx(101.60)


def test_a_stop_limit_needs_both_a_trigger_and_a_limit():
    b = broker()
    b.advance_to(at(9, 35))
    no_limit = {"action": "SELL", "totalQuantity": 100, "orderType": "STP LMT",
                "auxPrice": 99.50, "tif": "DAY"}
    with pytest.raises(FakeBrokerError, match="lmtPrice"):
        b.place_order(SPY, no_limit, order_ref="BOOK_A")

    no_trigger = {"action": "SELL", "totalQuantity": 100, "orderType": "STP LMT",
                  "lmtPrice": 99.00, "tif": "DAY"}
    with pytest.raises(FakeBrokerError, match="auxPrice"):
        b.place_order(SPY, no_trigger, order_ref="BOOK_A")


# ----------------------------------------------- one cancels the other, and parents

def test_a_fill_on_one_leg_cancels_the_other_in_the_same_group():
    """Two orders, one group. The buy fills on the 09:40 bar at 99.50.

    The sell at 101.50 would have filled on that very same bar, because it traded
    up to 101.90. It does not, because by the time it is looked at the buy has
    already pulled it, and the note on it says which order did that.
    """
    b = broker()
    b.advance_to(at(9, 35))
    group = "BOOK_A-SPY-093500"
    buy = b.place_order(SPY, dict(limit("BUY", 100, 99.50), ocaGroup=group, ocaType=1),
                        order_ref="BOOK_A")
    sell = b.place_order(SPY, dict(limit("SELL", 100, 101.50), ocaGroup=group,
                                   ocaType=1), order_ref="BOOK_A")

    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 1
    assert fills[0]["side"] == "BUY"
    assert fills[0]["price"] == pytest.approx(99.50)

    pulled = order_row(b, sell["orderId"])
    assert pulled["status"] == "Cancelled"
    assert pulled["remaining"] == 0
    assert pulled["ocaGroup"] == group
    assert f"order {buy['orderId']} filled" in pulled["notes"][-1]
    assert group in pulled["notes"][-1]
    assert b.open_orders()["orders"] == []


def test_an_order_with_no_oca_group_cancels_nothing():
    """The same two orders with no group name. Both fill, and that is right.

    An empty group links to nothing, which is how every plain order in the file
    behaves and why nothing that does not ask for a group has changed.
    """
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("BUY", 100, 99.50), order_ref="BOOK_A")
    sell = b.place_order(SPY, limit("SELL", 100, 101.50), order_ref="BOOK_A")

    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 2
    assert order_row(b, sell["orderId"])["status"] == "Filled"


def test_a_child_cannot_fill_before_its_parent_has():
    """The hole this closes: a stop that fires before there is anything to protect.

    The parent bids 97.00, which is below every print in the recording, so it
    never fills. The child would have sold at 101.50 on the 09:35 bar. Because
    its parent never filled it never becomes an order at all, and the replay does
    not end up short 100 shares nobody bought.
    """
    b = broker()
    b.advance_to(at(9, 30))
    parent = b.place_order(SPY, limit("BUY", 100, 97.00), order_ref="BOOK_A")
    child = b.place_order(SPY, dict(limit("SELL", 100, 101.50),
                                    parentId=parent["orderId"]), order_ref="BOOK_A")
    b.advance_to(at(9, 45))

    assert b.executions()["executions"] == []
    waiting = order_row(b, child["orderId"])
    assert waiting["status"] == "Submitted"
    assert waiting["remaining"] == 100
    assert waiting["parentId"] == parent["orderId"]
    assert b.positions.get("SPY", 0) == 0


def test_a_child_becomes_able_to_fill_once_its_parent_has():
    """The other half of the same rule.

    The child's price is there on the 09:35 bar, which trades up to 102.00, and
    it still must not fill. The parent buys on the 09:40 bar, and from that
    moment the child is a real order. It wakes up on the same bar its parent
    filled on, because the fill machinery walks the orders in the order they were
    placed and the parent was placed first.
    """
    b = broker()
    b.advance_to(at(9, 30))
    parent = b.place_order(SPY, limit("BUY", 100, 99.50), order_ref="BOOK_A")
    b.place_order(SPY, dict(limit("SELL", 100, 101.50), parentId=parent["orderId"]),
                  order_ref="BOOK_A")

    assert b.advance_to(at(9, 35))["fills"] == []
    fills = b.advance_to(at(9, 40))["fills"]
    assert [fill["side"] for fill in fills] == ["BUY", "SELL"]
    assert fills[0]["price"] == pytest.approx(99.50)
    assert fills[1]["price"] == pytest.approx(101.60)
    assert b.positions.get("SPY", 0) == 0


def test_an_untransmitted_order_rests_and_cannot_fill():
    """IBKR holds an untransmitted order in Gateway where nothing can trade on it."""
    b = broker()
    b.advance_to(at(9, 35))
    resting = b.place_order(SPY, limit("BUY", 100, 99.50), order_ref="BOOK_A",
                            transmit=False)
    assert resting["transmitted"] is False
    b.advance_to(at(9, 40))          # the bar trades to 99.00, well through the limit
    assert b.executions()["executions"] == []
    assert order_row(b, resting["orderId"])["remaining"] == 100


def test_a_child_sent_transmitted_releases_the_parent_that_was_waiting():
    """One call puts a whole bracket on the market, which is the point of transmit."""
    b = broker()
    b.advance_to(at(9, 35))
    group = "BOOK_A-SPY-093500"
    parent = b.place_order(SPY, dict(limit("BUY", 100, 99.50), ocaGroup=group),
                           order_ref="BOOK_A", transmit=False)
    assert order_row(b, parent["orderId"])["transmitted"] is False

    b.place_order(SPY, dict(limit("SELL", 100, 110.00), ocaGroup=group,
                            parentId=parent["orderId"]),
                  order_ref="BOOK_A", transmit=True)
    assert order_row(b, parent["orderId"])["transmitted"] is True

    fills = b.advance_to(at(9, 40))["fills"]
    assert len(fills) == 1
    assert fills[0]["price"] == pytest.approx(99.50)


# -------------------------------------------------------------------- brackets

def test_a_bracket_is_an_entry_and_a_stop_limit_in_one_group():
    """What every momentum book sends since the profit target went, on 2026-09-06.

    Two legs and no more. The stop goes out as a stop-limit with its limit half a
    percent below the 99.50 trigger, which is 99.0025 and rounds to 99.00, it
    carries the entry's order id as its parent, and both legs share one group.
    """
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.bracket_order(SPY, limit("BUY", 100, 101.00),
                             stop("SELL", 100, 99.50), None, "BOOK_A")

    assert answer["bracketed"] is True
    assert [leg["purpose"] for leg in answer["legs"]] == ["entry", "stop"]
    group = answer["oca_group"]
    assert group.startswith("BOOK_A-SPY-")

    entry_leg, stop_leg = answer["legs"]
    entry = order_row(b, entry_leg["order_id"])
    child = order_row(b, stop_leg["order_id"])
    assert child["orderType"] == "STP LMT"
    assert child["auxPrice"] == pytest.approx(99.50)
    assert child["lmtPrice"] == pytest.approx(99.00)
    assert stop_leg["price"] == pytest.approx(99.50)
    assert stop_leg["limit_price"] == pytest.approx(99.00)
    assert child["parentId"] == entry["orderId"]
    assert entry["ocaGroup"] == child["ocaGroup"] == group
    # The child went out transmitted, and that released the parent with it.
    assert entry["transmitted"] is True


def test_a_bracket_takes_a_third_leg_when_a_target_is_asked_for():
    """The insider and Congress books still take a profit target, so it still works."""
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.bracket_order(SPY, limit("BUY", 100, 101.00),
                             stop("SELL", 100, 99.50),
                             limit("SELL", 100, 103.00), "BOOK_A")

    assert [leg["purpose"] for leg in answer["legs"]] == ["entry", "target", "stop"]
    rows = [order_row(b, leg["order_id"]) for leg in answer["legs"]]
    assert {row["ocaGroup"] for row in rows} == {answer["oca_group"]}
    assert {row["parentId"] for row in rows[1:]} == {answer["legs"][0]["order_id"]}
    assert answer["legs"][1]["price"] == pytest.approx(103.00)   # the target's limit
    assert answer["legs"][2]["price"] == pytest.approx(99.50)    # the stop's trigger
    assert rows[1]["orderType"] == "LMT"
    assert rows[2]["orderType"] == "STP LMT"


def test_a_whole_bracket_runs_from_the_entry_to_the_stop():
    """End to end, with every price written out.

    The 09:40 bar dips to 99.00, which fills the 101.00 entry at its limit and,
    on the same bar, touches the 99.50 trigger of the stop the entry just woke
    up. The 09:45 bar opens at 99.10, above the 99.00 limit, so the stop gets out
    there and the book is flat again.
    """
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.bracket_order(SPY, limit("BUY", 100, 101.00),
                             stop("SELL", 100, 99.50), None, "BOOK_A")

    bought = b.advance_to(at(9, 40))["fills"]
    assert len(bought) == 1
    assert bought[0]["side"] == "BUY"
    assert bought[0]["price"] == pytest.approx(101.00)
    protection = order_row(b, answer["legs"][1]["order_id"])
    # The entry filling woke the stop rather than cancelling it, even though they
    # share a group. A bracket that pulled its own stop would be worse than none.
    assert protection["status"] == "Triggered"
    assert protection["triggered"] is True

    sold = b.advance_to(at(9, 45))["fills"]
    assert len(sold) == 1
    assert sold[0]["side"] == "SELL"
    assert sold[0]["price"] == pytest.approx(99.10)
    assert b.positions.get("SPY", 0) == 0
    assert b.book_positions("BOOK_A") == {}


def test_a_bracket_whose_entry_never_fills_cannot_short_out_of_thin_air():
    """The bug this whole change exists to close.

    The entry bids 97.00 and never fills. The 09:40 bar would have touched the
    99.50 stop trigger and the 09:45 bar would have filled it at 99.10, selling
    100 shares that were never bought. Hung off its parent, the stop never wakes
    up at all.
    """
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.bracket_order(SPY, limit("BUY", 100, 97.00),
                             stop("SELL", 100, 99.50), None, "BOOK_A")
    b.advance_to(at(9, 45))

    assert b.executions()["executions"] == []
    assert b.positions.get("SPY", 0) == 0
    asleep = order_row(b, answer["legs"][1]["order_id"])
    assert asleep["status"] == "Submitted"
    assert asleep["triggered"] is False


def test_a_bracket_with_no_stop_price_is_refused():
    """No stop leg means nothing would transmit the entry, so it is refused outright."""
    b = broker()
    b.advance_to(at(9, 35))
    with pytest.raises(FakeBrokerError, match="stop price"):
        b.bracket_order(SPY, limit("BUY", 100, 101.00), None, None, "BOOK_A")


# ------------------------------------------------------------------ commission

def test_commission_is_half_a_cent_a_share_in_the_ordinary_case():
    assert commission_for(1000, 100.0) == pytest.approx(5.00)


def test_commission_never_goes_below_the_one_dollar_minimum():
    """Ten shares at half a cent is five cents, and IBKR still charges a dollar."""
    assert commission_for(10, 100.0) == pytest.approx(1.00)


def test_commission_never_goes_above_one_percent_of_the_order():
    """Twenty shares of a two dollar stock is forty dollars of stock. One percent
    of that is forty cents, and the cap beats the one dollar minimum."""
    assert commission_for(20, 2.00) == pytest.approx(0.40)


def test_the_minimum_commission_shows_up_on_a_real_fill():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 10), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["commission"] == pytest.approx(1.00)


def test_the_maximum_commission_shows_up_on_a_real_fill():
    """Twenty shares of the two dollar name. The fill is at 2.00 plus the 0.02
    half spread, so 2.02, forty dollars and forty cents of stock, and one percent
    of that is 40.4 cents."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(PENNY, market("BUY", 20), order_ref="BOOK_A")
    fills = b.advance_to(at(9, 40))["fills"]
    assert fills[0]["price"] == pytest.approx(2.02)
    assert fills[0]["commission"] == pytest.approx(20 * 2.02 * 0.01)
    assert fills[0]["commission"] < 1.00


# ------------------------------------------------------ two books, one account

def test_two_books_trading_the_same_symbol_keep_their_own_positions():
    """The whole reason this class keeps five sets of books. IBKR would show one
    netted position in SPY and nothing else. Here the broker nets to the total
    and each book still knows exactly what is its own.
    """
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.place_order(SPY, market("BUY", 60), order_ref="BOOK_B")
    b.advance_to(at(9, 40))

    assert b.positions["SPY"] == 160
    assert b.book_positions("BOOK_A")["SPY"].qty == 100
    assert b.book_positions("BOOK_B")["SPY"].qty == 60

    netted = b.portfolio()["positions"]
    assert len(netted) == 1
    assert netted[0]["position"] == 160
    assert netted[0]["order_refs"] == ["BOOK_A", "BOOK_B"]

    just_a = b.portfolio(order_ref="BOOK_A")["positions"]
    assert len(just_a) == 1
    assert just_a[0]["position"] == 100
    assert b.reconcile()["ok"] is True


def test_one_book_closing_out_leaves_the_other_book_untouched():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.place_order(SPY, market("BUY", 60), order_ref="BOOK_B")
    b.advance_to(at(9, 40))
    b.place_order(SPY, market("SELL", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 45))

    assert b.positions["SPY"] == 60
    assert b.book_positions("BOOK_A") == {}
    assert b.book_positions("BOOK_B")["SPY"].qty == 60
    assert b.reconcile()["ok"] is True

    # Book A bought at 101.62 and sold at 99.08, losing 2.54 a share on 100
    # shares. Book B has not sold anything, so its realised profit is zero.
    a = b.book_summary("BOOK_A")
    assert a["realized_pnl"] == pytest.approx(-254.00, abs=0.02)
    assert a["commission_paid"] == pytest.approx(2.00)
    assert a["realized_pnl_net"] == pytest.approx(-256.00, abs=0.02)
    assert b.book_summary("BOOK_B")["realized_pnl"] == pytest.approx(0.0)


def test_each_book_carries_its_own_unrealised_profit():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.place_order(SPY, market("BUY", 60), order_ref="BOOK_B")
    b.advance_to(at(9, 45))          # SPY closes the 09:45 bar at 98.40

    a = b.book_summary("BOOK_A")
    second = b.book_summary("BOOK_B")
    assert a["unrealized_pnl"] == pytest.approx((98.40 - 101.62) * 100, abs=0.02)
    assert second["unrealized_pnl"] == pytest.approx((98.40 - 101.62) * 60, abs=0.02)


def test_every_fill_carries_the_order_ref_that_sent_it():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 10), order_ref="BOOK_A")
    b.place_order(QQQ, market("BUY", 10), order_ref="BOOK_D")
    b.advance_to(at(9, 40))
    refs = {fill["order_ref"] for fill in b.executions()["executions"]}
    assert refs == {"BOOK_A", "BOOK_D"}
    assert len(b.executions(order_ref="BOOK_A")["executions"]) == 1


def test_an_order_with_no_order_ref_is_refused():
    """A fill nobody can trace back to a book cannot be reconciled, so the
    broker will not accept the order in the first place."""
    b = broker()
    b.advance_to(at(9, 35))
    with pytest.raises(FakeBrokerError, match="order_ref"):
        b.place_order(SPY, market("BUY", 10), order_ref="")


def test_the_day_trade_counter_counts_round_trips_per_book():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 40))
    assert b.day_trade_count("BOOK_A") == 0
    b.place_order(SPY, market("SELL", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 45))
    assert b.day_trade_count("BOOK_A") == 1
    assert b.day_trade_count("BOOK_B") == 0


# ---------------------------------------------------------------------- faults

def test_gateway_down_makes_every_broker_call_raise_until_it_is_cleared():
    b = broker()
    b.advance_to(at(9, 35))
    b.inject_fault("gateway_down")

    for call in (b.account_summary, b.portfolio, b.open_orders, b.executions):
        with pytest.raises(ConnectionError):
            call()
    with pytest.raises(ConnectionError):
        b.snapshot([SPY])
    with pytest.raises(ConnectionError):
        b.place_order(SPY, market("BUY", 10), order_ref="BOOK_A")
    with pytest.raises(ConnectionError):
        b.global_cancel()
    assert b.is_up() is False

    # The market does not stop while Gateway is down, so the clock still moves.
    b.advance_to(at(9, 40))

    b.clear_fault("gateway_down")
    assert b.is_up() is True
    assert b.account_summary()["account"] == "DUREPLAY"


def test_delayed_data_makes_every_snapshot_report_market_data_type_three():
    b = broker()
    b.advance_to(at(9, 35))
    assert b.snapshot([SPY], market_data_type=1)["market_data_type"] == 1

    b.inject_fault("delayed_data")
    answer = b.snapshot([SPY], market_data_type=1)
    assert answer["market_data_type"] == 3
    assert answer["market_data_type_label"] == "delayed"
    assert answer["snapshots"][0]["marketDataType"] == 3


def test_competing_session_raises_an_error_carrying_code_10197():
    b = broker()
    b.advance_to(at(9, 35))
    b.inject_fault("competing_session")
    with pytest.raises(FakeBrokerError) as caught:
        b.snapshot([SPY])
    assert caught.value.code == COMPETING_SESSION_CODE == 10197
    b.clear_fault("competing_session")
    assert b.snapshot([SPY])["snapshots"][0]["symbol"] == "SPY"


def test_a_phantom_position_appears_with_no_order_ref_and_breaks_reconciliation():
    """This is the one that has to halt the day. A position turns up at the
    broker that no book placed an order for, so the books and the account no
    longer agree and nothing can be trusted until a person looks."""
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 40))
    assert b.reconcile()["ok"] is True

    b.inject_fault("phantom_position", symbol="QQQ", quantity=250, avg_cost=500.0)
    report = b.reconcile()
    assert report["ok"] is False
    assert len(report["differences"]) == 1
    difference = report["differences"][0]
    assert difference["symbol"] == "QQQ"
    assert difference["broker_qty"] == 250
    assert difference["books_qty"] == 0

    ghost = [row for row in b.portfolio()["positions"] if row["symbol"] == "QQQ"][0]
    assert ghost["order_refs"] == []

    b.clear_fault("phantom_position")
    assert b.reconcile()["ok"] is True


def test_reject_next_order_rejects_exactly_one_order_and_then_stops():
    b = broker()
    b.advance_to(at(9, 35))
    b.inject_fault("reject_next_order")

    refused = b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    assert refused["rejected"] is True
    assert refused["status"] == "Rejected"
    assert refused["error_code"] == 201
    assert b.open_orders()["orders"] == []

    accepted = b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    assert accepted["rejected"] is False
    assert len(b.open_orders()["orders"]) == 1

    b.advance_to(at(9, 40))
    assert b.positions["SPY"] == 100          # only the second order filled


def test_a_fault_nobody_has_heard_of_is_refused_rather_than_ignored():
    b = broker()
    with pytest.raises(FakeBrokerError, match="no fault called"):
        b.inject_fault("gateway_on_fire")


def test_active_faults_lists_what_is_currently_broken():
    b = broker()
    b.inject_fault("delayed_data")
    b.inject_fault("gateway_down")
    assert b.active_faults() == ["delayed_data", "gateway_down"]
    b.clear_faults()
    assert b.active_faults() == []


# ------------------------------------------------------------------ advance_to

def test_advance_to_refuses_to_go_backwards():
    """A replay that can rewind can see the future by accident, and then every
    number it produces is worthless."""
    b = broker()
    b.advance_to(at(9, 40))
    with pytest.raises(FakeBrokerError, match="only moves forward"):
        b.advance_to(at(9, 35))


def test_advance_to_walks_the_bars_in_time_order_across_symbols():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("BUY", 100, 99.50), order_ref="BOOK_A")     # fills 09:40
    b.place_order(QQQ, limit("BUY", 100, 499.50), order_ref="BOOK_B")    # fills 09:45

    result = b.advance_to(at(9, 45))
    times = [fill["time"] for fill in result["fills"]]
    assert times == sorted(times)
    assert [fill["symbol"] for fill in result["fills"]] == ["SPY", "QQQ"]
    assert result["bars_processed"] == 6      # three names, two bars each


def test_advance_to_reports_where_it_went_and_what_it_did():
    b = broker()
    first = b.advance_to(at(9, 35))
    assert first["to"] == at(9, 35)
    assert first["bars_processed"] == 6       # three names, the 09:30 and 09:35 bars
    assert first["fills"] == []
    assert b.now.isoformat() == at(9, 35)


def test_nothing_ever_returns_a_bar_from_after_the_clock():
    """The single most important property of the whole harness."""
    b = broker()
    b.advance_to(at(9, 35))

    today = b.bars_5m_today(SPY)
    assert len(today) == 2
    assert today[-1]["close"] == 101.50

    history = b.historical_bars(SPY, "1 D", "5 mins")["bars"]
    assert len(history) == 2

    # Asking for an end time in the future does not get you the future either.
    later = b.historical_bars(SPY, "1 D", "5 mins", end_date_time=at(9, 45))["bars"]
    assert len(later) == 2

    b.advance_to(at(9, 45))
    assert len(b.bars_5m_today(SPY)) == 4


def test_the_clock_starts_just_before_the_first_bar():
    b = broker()
    assert b.bars_5m_today(SPY) == []
    assert b.advance_to(at(9, 30))["bars_processed"] == 3


# ------------------------------------------------------- the rest of the surface

def test_account_summary_matches_the_shape_the_real_client_returns():
    b = broker()
    b.advance_to(at(9, 35))
    values = b.account_values()
    assert values["NetLiquidation"] == "100000.00"
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 40))
    after = b.account_values()
    # Bought at 101.62, marked at the 09:40 close of 99.20, so the account is
    # down the loss plus the dollar of commission.
    expected = 100_000.0 - 1.00 + (99.20 - 101.62) * 100
    assert float(after["NetLiquidation"]) == pytest.approx(expected, abs=0.02)


def test_cancel_order_pulls_a_resting_order_and_says_so():
    b = broker()
    b.advance_to(at(9, 35))
    answer = b.place_order(SPY, limit("BUY", 100, 97.00), order_ref="BOOK_A")
    cancelled = b.cancel_order(answer["orderId"])
    assert cancelled["cancelled"] is True
    assert cancelled["cancelled_quantity"] == 100
    b.advance_to(at(9, 45))
    assert b.executions()["executions"] == []
    assert b.open_orders()["orders"] == []


def test_global_cancel_pulls_everything_at_once():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, limit("BUY", 100, 97.00), order_ref="BOOK_A")
    b.place_order(QQQ, limit("BUY", 100, 400.00), order_ref="BOOK_B")
    result = b.global_cancel()
    assert result["count"] == 2
    assert b.open_orders()["orders"] == []


def test_partial_fills_are_off_by_default_and_split_an_order_when_turned_on():
    whole = broker()
    whole.advance_to(at(9, 35))
    whole.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    whole.advance_to(at(9, 40))
    assert len(whole.executions()["executions"]) == 1

    split = broker(partial_fill_probability=1.0, partial_fill_fraction=0.5, seed=1)
    split.advance_to(at(9, 35))
    split.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    split.advance_to(at(9, 40))
    first = split.executions()["executions"]
    assert len(first) == 1
    assert first[0]["shares"] == 50
    assert split.open_orders()["orders"][0]["status"] == "PartiallyFilled"
    # The rest keeps trying on the bars that follow.
    split.advance_to(at(9, 45))
    assert split.positions["SPY"] > 50


def test_fractional_and_zero_share_orders_are_refused():
    b = broker()
    b.advance_to(at(9, 35))
    with pytest.raises(FakeBrokerError, match="whole number of shares"):
        b.place_order(SPY, market("BUY", 0), order_ref="BOOK_A")


def test_state_gives_the_harness_one_readable_summary():
    b = broker()
    b.advance_to(at(9, 35))
    b.place_order(SPY, market("BUY", 100), order_ref="BOOK_A")
    b.advance_to(at(9, 40))
    state = b.state()
    assert state["positions"] == {"SPY": 100}
    assert state["fills"] == 1
    assert state["reconciled"] is True
    assert "BOOK_A" in state["books"]
