"""The one door between the trading loop and a broker.

The loop never talks to IBKR directly. It is handed a Broker and calls methods
on it. That single change is what lets the same loop run three ways without the
loop knowing which:

    McpBroker      the real thing, talking to IB Gateway through the local MCP
                   server. Reads work today. The order methods exist and are
                   locked shut, see below.
    FakeBroker     agent/replay/fake_broker.py, written by another agent, which
                   feeds the loop a recorded day so a month can be replayed in
                   a minute. This file deliberately does not import it.
    a test double  tests/test_loop_books.py has a twenty line one that counts
                   the calls it gets. That is the whole point of the protocol.

NOTHING HERE PLACES AN ORDER TODAY, and that is not a matter of nobody calling
it. McpBroker.place_order, cancel_order and global_cancel each check the
environment variable AGENTIC_TRADING_LIVE_ORDERS before they do anything, and
refuse loudly when it is not set to yes. That is a second lock, behind the ones
in agent/loop.py, not a replacement for them. Do not set that variable. Setting
it is a decision for Mo, after he has read the strategy numbers and said yes.

The instant fill trap
---------------------
docs/MCP_SERVER.md records a bug that was seen for real on 2026-09-02: a market
order that fills straight away comes back from ibkr_place_order with
isError=true, because the server's own reply fails its own validation on the way
out. The order filled. The error is about the reply, not the trade.

So place_order below never trusts what the order call said. Whatever comes back,
success or failure, it re-reads executions and open orders afterwards and
reports what the broker actually holds. A caller reading "error" and assuming
nothing happened is exactly the mistake that costs money.

Read only self test, places nothing:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import mcp_client as mcp  # noqa: E402

#: Has to be exactly "yes" before McpBroker will touch an order tool.
LIVE_ENV_VAR = "AGENTIC_TRADING_LIVE_ORDERS"

#: IBKR paper account ids all start with this. A live one does not.
PAPER_ACCOUNT_PREFIX = "DU"

#: IBKR's one-cancels-the-other type 1: when one order in the group fills, every
#: other order in it is cancelled, and the remaining quantity is reduced with a
#: block. That is what makes an entry and its stop one bracket rather than two
#: orders that happen to be about the same shares.
OCA_CANCEL_REMAINING = 1

#: How far below the stop trigger the stop-limit's limit price sits, for a long,
#: and above it for a short. Half a percent (Momentum v2, 2026-09-06).
#:
#: A plain stop becomes a market order the moment it is touched and fills
#: wherever the book happens to be, which in a thin gap down is a long way from
#: the stop. A stop-limit will not fill below this price. Half a percent is
#: enough room for an ordinary fill and not enough to give the position away.
#: The cost of a limit is that a price gapping straight through it leaves the
#: order triggered and unfilled, which is what the loop's sixty second market
#: backstop exists to catch.
STOP_LIMIT_OFFSET_PCT = 0.5


class BrokerError(RuntimeError):
    """Something went wrong at the broker, in words that read well in a log."""


@runtime_checkable
class Broker(Protocol):
    """What the trading loop needs from a broker, and nothing more.

    Six of these read and three of them act. Anything implementing all nine can
    drive the loop: the real MCP client, the replay harness's recorded day, or a
    fake in a test.

    Two things the loop wants often are deliberately not in here, because they
    can be built out of the methods below and every extra method is one more
    thing a replay or a test has to implement: a plain {tag: value} view of the
    account summary, and today's five minute bars. Both live at the bottom of
    this file as plain functions that take a Broker.
    """

    # ------------------------------------------------------------- reading

    def account_summary(self, account: str | None = None) -> dict:
        """Account values: NetLiquidation, TotalCashValue, BuyingPower and so on."""

    def portfolio(self, account: str | None = None, include_pnl: bool = True) -> dict:
        """Open positions with market value and profit so far."""

    def open_orders(self, account: str | None = None, include_all: bool = True) -> dict:
        """Orders that are still working, as {"orders": [...]}."""

    def executions(self, account: str | None = None, symbol: str | None = None,
                   sec_type: str | None = None, exchange: str | None = None,
                   side: str | None = None, time: str | None = None) -> dict:
        """Fills. The honest answer to what we actually own."""

    def snapshot(self, contracts: list[dict], market_data_type: int = 3) -> dict:
        """One shot quotes for a list of contracts."""

    def historical_bars(self, contract: dict, duration: str, bar_size: str,
                        what: str = "TRADES", use_rth: bool = True,
                        end_date_time: str = "") -> dict:
        """Price history for one contract, as {"bars": [...]}."""

    # -------------------------------------------------------------- acting

    def place_order(self, contract: dict, order: dict, order_ref: str) -> dict:
        """Send one order, tagged with order_ref so the fill can be traced to a book.

        Returns a dictionary. The keys every implementation promises are:

            sent            bool, whether the order went to the broker at all
            order_id        the broker's id for it, or None
            filled_qty      shares filled by the time we looked
            avg_fill_price  what they filled at, or None
            working         True when the order is still resting unfilled
            error           a sentence, or None
            raw             whatever the broker's own answer was
            confirmed_by    how we know: "executions", "open_orders" or "neither"
        """

    def bracket_order(self, contract: dict, entry: dict, stop: dict,
                      target: dict | None, order_ref: str) -> dict:
        """Send an entry with its protective orders attached to it.

        This is how a stop actually protects a position. place_order above
        leaves the loop holding shares and nothing else: if the Mac sleeps, the
        network drops or a tick crashes, nothing at the broker knows where the
        stop was. A bracket leaves the stop resting at IBKR, where it works
        whether or not this code is running.

        The legs are plain IBKR order dictionaries, the same shape place_order
        takes:

            entry   the parent, a limit order in the direction of the trade
            stop    a child on the other side, with auxPrice at the stop. The
                    real broker turns it into a stop-limit; see McpBroker's own
                    bracket_order below for why.
            target  a LMT child on the other side, or None. Momentum v2 (item
                    A2, Mo 2026-09-06) took the profit target away from the
                    three momentum books entirely, so it is None for them and a
                    momentum bracket is a parent and a stop and nothing else.
                    The insider and Congress books still pass one.

        Every leg goes out in ONE one-cancels-the-other group and the children
        hang off the parent's id, so a fill on any of them cancels the rest and
        nothing reaches the market until the whole bracket is assembled.

        Every leg carries order_ref, because a child order nobody can trace back
        to a book cannot be reconciled.

        Returns the same keys place_order does, describing the parent, plus:

            legs        one dict per leg: purpose, order_id, and what was sent
            bracketed   True when the protective children really went out
        """

    def cancel_order(self, order_id: Any) -> dict:
        """Cancel one working order by its broker id."""

    def global_cancel(self) -> dict:
        """Cancel every working order on the account. The emergency handle."""


def live_orders_enabled() -> bool:
    """True only when the environment variable is set to exactly yes."""
    return os.environ.get(LIVE_ENV_VAR) == "yes"


def _refuse(what: str) -> BrokerError:
    return BrokerError(
        f"refusing to {what}: {LIVE_ENV_VAR} is not set to yes. Every strategy "
        "number in this project is still provisional, so no order may leave this "
        "machine, on paper or otherwise. Setting that variable is a decision for "
        "Mo after he has read docs/STRATEGY.md, not a step in a script."
    )


class McpBroker:
    """A Broker that talks to IB Gateway through the local MCP server.

    Reads pass straight through to agent/mcp_client.py. The three order methods
    call the server's order tools, and each one is locked behind
    AGENTIC_TRADING_LIVE_ORDERS.
    """

    def __init__(self, client: mcp.McpClient | None = None,
                 account: str | None = None) -> None:
        self.client = client or mcp.McpClient(account=account)
        self.account = account or getattr(self.client, "account", None)

    # ------------------------------------------------------------- reading

    def account_summary(self, account: str | None = None) -> dict:
        return self.client.account_summary(account or self.account)

    def portfolio(self, account: str | None = None, include_pnl: bool = True) -> dict:
        return self.client.portfolio(account or self.account, include_pnl=include_pnl)

    def open_orders(self, account: str | None = None, include_all: bool = True) -> dict:
        return self.client.open_orders(account or self.account, include_all=include_all)

    def executions(self, account: str | None = None, symbol: str | None = None,
                   sec_type: str | None = None, exchange: str | None = None,
                   side: str | None = None, time: str | None = None) -> dict:
        return self.client.executions(account or self.account, symbol=symbol,
                                      sec_type=sec_type, exchange=exchange,
                                      side=side, time=time)

    def snapshot(self, contracts: list[dict], market_data_type: int = 3) -> dict:
        return self.client.snapshot(contracts, market_data_type=market_data_type)

    def historical_bars(self, contract: dict, duration: str, bar_size: str,
                        what: str = "TRADES", use_rth: bool = True,
                        end_date_time: str = "") -> dict:
        return self.client.historical_bars(contract, duration, bar_size, what=what,
                                           use_rth=use_rth, end_date_time=end_date_time)

    # -------------------------------------------------------------- acting

    def place_order(self, contract: dict, order: dict, order_ref: str) -> dict:
        """Send one order and then go and check what actually happened.

        The order dictionary handed in is copied, not edited, and two fields are
        written onto the copy: orderRef, which is the book's tag and is how a
        fill is traced back to one of the five books, and account, so the order
        cannot land anywhere else.

        confirm=true, dry_run=false and transmit=true are all passed on purpose.
        The server defaults to dry_run=true and transmit=false, which parks an
        order in Gateway waiting for a human click, and an order parked forever
        is worse than no order at all: the loop would think it was working.
        """
        if not live_orders_enabled():
            raise _refuse(f"place a {order.get('action', '?')} order in "
                          f"{contract.get('symbol', '?')}")

        payload = dict(order)
        payload["orderRef"] = str(order_ref)
        if self.account:
            payload["account"] = self.account

        raw: Any = None
        error: str | None = None
        try:
            raw = self.client.call("ibkr_place_order", {
                "contract": contract,
                "order": payload,
                "confirm": True,
                "dry_run": False,
                "transmit": True,
            })
        except mcp.McpError as exc:
            # This is the known bug from docs/MCP_SERVER.md as often as it is a
            # real failure, so it is recorded and then ignored in favour of what
            # executions and open orders say below.
            error = str(exc)

        return self._confirm(contract, payload, order_ref, raw, error)

    def _confirm(self, contract: dict, order: dict, order_ref: str,
                 raw: Any, error: str | None) -> dict:
        """Ask the broker what it actually did, rather than believing the reply.

        Executions first, because a fill is the fact that matters. Open orders
        second, because an order that is resting unfilled is a real state too and
        it is not a failure.
        """
        symbol = str(contract.get("symbol") or "")
        result: dict[str, Any] = {
            "sent": True,
            "order_id": _order_id_from(raw),
            "filled_qty": 0.0,
            "avg_fill_price": None,
            "working": False,
            "error": error,
            "raw": raw,
            "confirmed_by": "neither",
            "order_ref": order_ref,
            "symbol": symbol,
        }

        fills: list[dict] = []
        try:
            answer = self.executions(symbol=symbol) or {}
            fills = [row for row in (answer.get("executions") or answer.get("fills")
                                     or answer.get("trades") or [])
                     if isinstance(row, dict) and _matches_ref(row, order_ref)]
        except mcp.McpError as exc:
            result["error"] = _join(result["error"],
                                    f"could not read the fills back: {exc}")

        if fills:
            quantity = sum(float(row.get("shares") or row.get("qty") or 0.0) for row in fills)
            paid = sum(float(row.get("shares") or row.get("qty") or 0.0)
                       * float(row.get("price") or row.get("avgPrice") or 0.0)
                       for row in fills)
            result["filled_qty"] = quantity
            result["avg_fill_price"] = round(paid / quantity, 4) if quantity else None
            result["confirmed_by"] = "executions"
            result["order_id"] = result["order_id"] or fills[-1].get("orderId")

        try:
            working = [row for row in ((self.open_orders() or {}).get("orders") or [])
                       if isinstance(row, dict) and _matches_ref(row, order_ref)]
        except mcp.McpError as exc:
            working = []
            result["error"] = _join(result["error"],
                                    f"could not read the open orders back: {exc}")
        if working:
            result["working"] = True
            result["order_id"] = result["order_id"] or working[-1].get("orderId")
            if result["confirmed_by"] == "neither":
                result["confirmed_by"] = "open_orders"

        if result["confirmed_by"] == "neither" and error:
            # Nothing filled, nothing is resting, and the call complained. Now
            # the error is worth believing.
            result["sent"] = False
        return result

    def bracket_order(self, contract: dict, entry: dict, stop: dict,
                      target: dict | None = None, order_ref: str = "") -> dict:
        """Send an entry and the stop that protects it, as ONE native IBKR bracket.

        WHY THIS DOES NOT USE THE SERVER'S OWN ibkr_bracket_order TOOL. That tool
        takes an entry action, a quantity, a limit price, a takeProfitPrice and a
        stopLossPrice, and it builds the three IBKR orders itself. Its
        takeProfitPrice is not optional, checked by reading the pinned server's
        source on 2026-09-06 (the commit is in requirements-312.txt, and the
        argument has no default in _ibkr_bracket_order_sync). Momentum v2 took
        the profit target away entirely (item A2, Mo 2026-09-06), so a momentum
        entry has no take profit price to give it and that tool cannot be used
        at all.

        So the bracket is built here out of the server's plain order tool, which
        is what IBKR itself does underneath:

            parent   a limit order, sent with transmit=false so it rests in
                     Gateway and does not go to the market on its own
            child    a stop-limit on the other side, carrying parentId set to
                     the parent's order id, sent with transmit=true, which is
                     what releases BOTH orders to the market together

        Both legs carry the same ocaGroup and ocaType=1, so a fill on one
        cancels the other, and both carry the book's orderRef and the account.
        Checked against the same pinned server: order_from_input passes every
        field of ib_async's Order straight through, and parentId, ocaType and
        ocaGroup are all fields of it, so nothing here needs the server to learn
        a new trick. The one field the server does NOT read off the order
        dictionary is transmit, which it overwrites from its own argument
        (server.py line 2331), so transmit is passed as an argument on each call
        and never inside the order.

        THE STOP CHILD IS A STOP-LIMIT, NOT A PLAIN STOP. A plain stop becomes a
        market order the moment it is touched, and in a thin gap down that fills
        wherever the book happens to be. The stop-limit triggers at the stop and
        then works a limit STOP_LIMIT_OFFSET_PCT below it for a long, above it
        for a short, which is half a percent of room. That is enough for an
        ordinary fill and not enough to give the position away.

        The risk in a stop-limit is the other way round: a price that gaps
        straight through the limit leaves the order triggered and unfilled, and
        the position unprotected. That is what the loop's backstop is for. It
        markets the position out when the stop has triggered and the child is
        still unfilled sixty seconds later. See stop_backstop_due in
        agent/loop.py.

        target is accepted and ignored on any book that has no profit target,
        which is all three momentum books. A book that still takes one, which is
        the insider and Congress books, gets a third leg in the same OCA group.

        Returns the same keys place_order does, describing the parent, plus:

            legs        one dict per leg: purpose, order_id, price, order_ref
            bracketed   True when the protective child really went out
            oca_group   the group name both legs went out under
        """
        if not live_orders_enabled():
            raise _refuse(f"place a bracket in {contract.get('symbol', '?')}")

        ref = str(order_ref)
        symbol = str(contract.get("symbol") or "")
        stop_price = stop.get("auxPrice", stop.get("stopPrice"))
        if entry.get("lmtPrice") is None or stop_price is None:
            raise BrokerError(
                "a bracket needs a limit price on the entry and a stop price on the "
                f"stop leg, and it was given {entry.get('lmtPrice')!r} and "
                f"{stop_price!r}.")

        group = oca_group_name(ref, symbol)
        parent = dict(entry)
        parent["ocaGroup"] = group
        parent["ocaType"] = OCA_CANCEL_REMAINING

        # The parent goes out untransmitted, so it sits in Gateway until the
        # child is attached to it. An entry that reached the market with nothing
        # protecting it is the exact hole this whole path exists to close.
        parent_result = self._send(contract, parent, ref, transmit=False)
        parent_id = parent_result.get("order_id")
        if parent_id is None:
            parent_result["bracketed"] = False
            parent_result["legs"] = [
                {"purpose": "entry", "order_id": None, "order_ref": ref,
                 "price": entry.get("lmtPrice")}]
            parent_result["error"] = _join(
                parent_result.get("error"),
                "the parent order came back with no order id, so no stop could be "
                "hung off it and nothing was transmitted")
            return parent_result

        legs = [{"purpose": "entry", "order_id": parent_id, "order_ref": ref,
                 "price": entry.get("lmtPrice")}]
        children = self._child_legs(contract, stop, target, ref, group, parent_id)
        legs.extend(children)

        parent_result["legs"] = legs
        parent_result["oca_group"] = group
        parent_result["bracketed"] = any(
            leg["purpose"] == "stop" and leg.get("order_id") is not None
            for leg in legs)
        if not parent_result["bracketed"]:
            parent_result["error"] = _join(
                parent_result.get("error"),
                "the stop child did not go out, so the parent is still sitting "
                "untransmitted in Gateway and no shares have been bought")
        return parent_result

    def _child_legs(self, contract: dict, stop: dict, target: dict | None,
                    ref: str, group: str, parent_id: Any) -> list[dict]:
        """The protective legs, hung off the parent and transmitted last.

        The LAST child sent carries transmit=true, and that one call is what
        releases the parent and every child to the market at once. So the order
        of these matters: the stop is always last, because a bracket that went
        out with a target and no stop would be worse than one that never went.
        """
        wanted: list[tuple[str, dict]] = []
        if target is not None and target.get("lmtPrice") is not None:
            wanted.append(("target", dict(target)))
        wanted.append(("stop", stop_limit_child(stop)))

        legs: list[dict] = []
        for index, (purpose, order) in enumerate(wanted):
            order["ocaGroup"] = group
            order["ocaType"] = OCA_CANCEL_REMAINING
            order["parentId"] = int(parent_id)
            last = index == len(wanted) - 1
            answer = self._send(contract, order, ref, transmit=last)
            legs.append({
                "purpose": purpose, "order_id": answer.get("order_id"),
                "order_ref": ref,
                "price": (order.get("lmtPrice") if purpose == "target"
                          else order.get("auxPrice")),
                "limit_price": order.get("lmtPrice") if purpose == "stop" else None,
                "error": answer.get("error"),
            })
        return legs

    def _send(self, contract: dict, order: dict, order_ref: str,
              transmit: bool) -> dict:
        """One order tool call, with the book's tag and the account written on.

        transmit is an ARGUMENT rather than a field on the order because the
        pinned server overwrites order.transmit from its own argument. Passing
        it any other way looks like it works and does nothing.
        """
        payload = dict(order)
        payload["orderRef"] = str(order_ref)
        if self.account:
            payload["account"] = self.account

        raw: Any = None
        error: str | None = None
        try:
            raw = self.client.call("ibkr_place_order", {
                "contract": contract,
                "order": payload,
                "confirm": True,
                "dry_run": False,
                "transmit": bool(transmit),
            })
        except mcp.McpError as exc:
            # The known instant fill bug from docs/MCP_SERVER.md as often as it
            # is a real failure, so it is recorded and then checked against what
            # the broker actually holds.
            error = str(exc)
        return self._confirm(contract, payload, order_ref, raw, error)

    def cancel_order(self, order_id: Any) -> dict:
        if not live_orders_enabled():
            raise _refuse(f"cancel order {order_id}")
        try:
            raw = self.client.call("ibkr_cancel_order",
                                   {"orderId": int(order_id), "confirm": True})
            error = None
        except (mcp.McpError, ValueError, TypeError) as exc:
            raw, error = None, str(exc)
        still_working = []
        try:
            still_working = [row for row in ((self.open_orders() or {}).get("orders") or [])
                             if isinstance(row, dict)
                             and str(row.get("orderId")) == str(order_id)]
        except mcp.McpError:
            pass
        return {"order_id": order_id, "cancelled": not still_working,
                "still_working": bool(still_working), "error": error, "raw": raw}

    def global_cancel(self) -> dict:
        if not live_orders_enabled():
            raise _refuse("cancel every working order")
        try:
            raw = self.client.call("ibkr_global_cancel", {"confirm": True})
            error = None
        except mcp.McpError as exc:
            raw, error = None, str(exc)
        left = []
        try:
            left = (self.open_orders() or {}).get("orders") or []
        except mcp.McpError:
            pass
        return {"cancelled_all": not left, "still_working": len(left),
                "error": error, "raw": raw}


# ------------------------------------------------------------ small helpers

def oca_group_name(order_ref: str, symbol: str) -> str:
    """The name both legs of one bracket go out under.

    It carries the book's tag and the symbol so a group seen in Gateway can be
    read back to the book and the name that made it, and a clock reading so two
    brackets in the same name on the same day are never accidentally the same
    group. Kept short, because IBKR truncates a long one.
    """
    stamp = datetime.now().strftime("%H%M%S")
    return f"{str(order_ref).strip().upper()}-{str(symbol).strip().upper()}-{stamp}"


def stop_limit_child(stop: dict) -> dict:
    """The stop leg as a stop-limit, with its limit STOP_LIMIT_OFFSET_PCT away.

    Takes the plain STP order the loop works out and turns it into a STP LMT:
    auxPrice stays where it is, because that is the price that triggers the
    order, and lmtPrice is set half a percent beyond it in the direction the
    position is being closed. Selling to close a long, the limit sits BELOW the
    trigger. Buying to close a short, it sits ABOVE.

    An order that already carries a limit price is left as it is, so a caller
    that has worked out its own is not overruled.
    """
    child = dict(stop)
    trigger = child.get("auxPrice", child.get("stopPrice"))
    if trigger is None:
        return child
    child["orderType"] = "STP LMT"
    child["auxPrice"] = round(float(trigger), 2)
    if child.get("lmtPrice") is None:
        selling = str(child.get("action") or "").strip().upper() == "SELL"
        factor = (1.0 - STOP_LIMIT_OFFSET_PCT / 100.0) if selling else (
            1.0 + STOP_LIMIT_OFFSET_PCT / 100.0)
        child["lmtPrice"] = round(float(trigger) * factor, 2)
    return child


def _order_id_from(raw: Any) -> Any:
    """Dig the broker's order id out of whatever shape the reply came back in."""
    if not isinstance(raw, dict):
        return None
    for key in ("orderId", "order_id", "id"):
        if raw.get(key) is not None:
            return raw[key]
    for nest in ("order", "trade", "result"):
        inner = raw.get(nest)
        if isinstance(inner, dict):
            found = _order_id_from(inner)
            if found is not None:
                return found
    return None


def _matches_ref(row: dict, order_ref: str) -> bool:
    """True when this fill or order carries our book's tag.

    A row with no tag at all counts as ours only when we asked for nothing in
    particular, which never happens here, so it does not.
    """
    for key in ("orderRef", "order_ref", "ref"):
        if str(row.get(key) or "") == str(order_ref):
            return True
    order = row.get("order")
    if isinstance(order, dict):
        return _matches_ref(order, order_ref)
    return False


def _join(first: str | None, second: str) -> str:
    return f"{first}; {second}" if first else second


def account_values(broker: Broker, account: str | None = None) -> dict[str, str]:
    """The account summary as a plain {tag: value} lookup.

    Built on top of account_summary rather than being its own protocol method,
    so a replay or a test only has to implement the nine methods above.
    """
    try:
        summary = broker.account_summary(account) or {}
    except Exception:                            # noqa: BLE001
        return {}
    items = summary.get("items") if isinstance(summary, dict) else None
    if not isinstance(items, list):
        return {}
    return {str(item.get("tag")): item.get("value") for item in items
            if isinstance(item, dict) and item.get("tag")}


def bars_5m_today(broker: Broker, contract: dict) -> list[dict]:
    """Today's five minute bars for one contract, regular hours only."""
    answer = broker.historical_bars(contract, "1 D", "5 mins") or {}
    bars = answer.get("bars") if isinstance(answer, dict) else None
    return bars or []


def session_vwap(bars: list[dict]) -> float | None:
    """The day's volume weighted average price. Re-exported so the loop has one import."""
    return mcp.session_vwap(bars)


@dataclass(frozen=True)
class BorrowTerms:
    """What the broker says about borrowing one name, and a sentence saying how we know.

    The four fields line up one for one with the borrow fields on
    agent/guardrails.py's OrderIntent, so the loop can hand them straight over.

        shortable         can it be borrowed at all
        level             IBKR's own shortable indicator, 0 to 3, where anything
                          above 2.5 is what it calls easy to borrow
        fee_pct_annual    what the borrow costs, as a percentage a year
        shares_available  how many shares can be borrowed right now
    """

    shortable: bool = False
    level: float | None = None
    fee_pct_annual: float | None = None
    shares_available: int | None = None
    note: str = ""


def borrow_terms(row: dict | None) -> BorrowTerms:
    """Read the borrow terms out of one snapshot row.

    Checked against the live MCP server on 2026-09-06: the snapshot it returns
    holds conId, symbol, secType, exchange, currency, bid, ask, last, close,
    marketPrice and the option greeks, and nothing about borrowing at all.
    ibkr_get_contract_details has nothing either. So the honest answer today is
    "we do not know", which comes back as shortable False and three Nones.

    That is the safe direction and it is the designed behaviour, not a gap being
    papered over: the momentum books set require_shortable, so the borrow rules
    in agent/guardrails.py refuse every short until the broker can actually
    answer. The field names below are the ones IBKR uses elsewhere for these
    three ticks, so the day the server starts passing them through, this starts
    working with no other change.
    """
    if not isinstance(row, dict):
        return BorrowTerms(note="no quote came back for this name, so nothing is "
                                "known about borrowing it")

    level = _first_number(row, ("shortable", "shortableLevel", "shortable_level"))
    shares = _first_number(row, ("shortableShares", "shortable_shares",
                                 "sharesAvailable", "shares_available_to_borrow"))
    fee = _first_number(row, ("feeRate", "fee_rate", "borrowFee",
                              "borrow_fee_pct_annual"))

    # A bare true or false is the older shape, and it is still worth reading.
    flag = row.get("shortable")
    plain = flag if isinstance(flag, bool) else None

    known = [name for name, value in
             (("a shortable level of " + _fmt(level), level),
              (_fmt(shares) + " shares available to borrow", shares),
              ("a borrow fee of " + _fmt(fee) + " percent a year", fee)) if value is not None]
    if plain is not None:
        known.append(f"a shortable flag of {plain}")

    if not known:
        return BorrowTerms(note="the MCP snapshot carries no shortable level, borrow "
                                "fee or share availability, so the broker has not "
                                "confirmed this name can be borrowed")

    shortable = bool(plain) if plain is not None else False
    if level is not None:
        shortable = level > 2.5
    elif shares is not None:
        shortable = shares > 0

    return BorrowTerms(
        shortable=shortable, level=level, fee_pct_annual=fee,
        shares_available=int(shares) if shares is not None else None,
        note="the broker reported " + ", ".join(known))


def _first_number(row: dict, keys: tuple[str, ...]) -> float | None:
    """The first of these keys that holds a real number, or None."""
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number or number < 0:      # a NaN, or IBKR's -1 for unknown
            continue
        return number
    return None


def _fmt(value: float | None) -> str:
    """A number a person can read. No scientific notation, ever, in a log line."""
    if value is None:
        return "?"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _self_test() -> int:
    """Read a few things through the broker and print them. Places nothing."""
    broker = McpBroker()
    if not isinstance(broker, Broker):
        print("FAIL: McpBroker does not satisfy the Broker protocol")
        return 1
    print("McpBroker satisfies the Broker protocol")
    print(f"live orders: {'ENABLED, which is wrong today' if live_orders_enabled() else 'locked'}")
    try:
        values = account_values(broker)
        print(f"net liquidation {values.get('NetLiquidation')}, "
              f"cash {values.get('TotalCashValue')}")
        holdings = broker.portfolio() or {}
        print(f"account {holdings.get('account')}, "
              f"{len(holdings.get('positions') or [])} positions open")
        print(f"open orders {len((broker.open_orders() or {}).get('orders') or [])}")
    except mcp.McpError as exc:
        print(f"could not reach the broker: {exc}")
        return 1
    print("OK, read only, nothing was ordered")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
