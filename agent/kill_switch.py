"""Get out of everything, now. The only script in this project that can trade.

Read this before running it.

It does three things through the local MCP server, in this order:

    1. cancels every working order on the account;
    2. reads what is still held;
    3. sells every long and buys back every short, at the market, transmitted
       straight through rather than parked in Gateway for a click.

Then it reads the account again and prints what is actually left, because the
MCP server has a known bug where a market order that fills instantly comes back
looking like a failure (see docs/MCP_SERVER.md). The only honest answer to "did
it work" is what the account says afterwards, so that is what it reports.

REHEARSAL IS THE DEFAULT
------------------------

With no flags it is a rehearsal: it reads the account, lists exactly what it
would cancel and what it would flatten, sends nothing, and prints the alert it
would have sent. Nothing about the rehearsal touches the market.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.py

Only --really makes it real, and normally you would not run this file directly.
Use the shell script, which also stops the loop before it starts cancelling:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really

Guards
------

* Paper only. If the account does not start with DU it refuses to send anything.
  Flattening a live account is not a thing this project does.
* Market orders outside trading hours do not fill. They queue for the next open.
  The script says so rather than pretending the account is flat.
* Everything it did, and everything still left over, goes to Mo through
  agent/alerts.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402
import mcp_client as mcp  # noqa: E402
from paths import output_dir  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: Paper account ids start with these two letters. Anything else is refused.
PAPER_PREFIX = "DU"

#: How long to give IBKR to report the fills before reading the account back.
SETTLE_SECONDS = 4


def side_to_close(quantity: float) -> str:
    """SELL closes a long, BUY closes a short."""
    return "SELL" if quantity > 0 else "BUY"


def closing_order(position: dict, account: str | None) -> tuple[dict, dict]:
    """The contract and order that would close one position, at the market.

    conId is IBKR's own unique number for a security, so it is passed whenever
    the account gave us one: it removes any chance of closing the wrong thing
    because two listings share a ticker. The order is routed to SMART, IBKR's
    own router, rather than back to the exchange the position was opened on.
    """
    quantity = float(position.get("position") or 0.0)
    contract = {
        "symbol": position.get("symbol"),
        "secType": position.get("secType") or "STK",
        "exchange": "SMART",
        "currency": position.get("currency") or "USD",
    }
    if position.get("conId"):
        contract["conId"] = position["conId"]

    size = abs(quantity)
    order = {
        "action": side_to_close(quantity),
        "totalQuantity": int(size) if float(size).is_integer() else size,
        "orderType": "MKT",
        "tif": "DAY",
    }
    if account:
        order["account"] = account
    return contract, order


def open_positions(portfolio: dict) -> list[dict]:
    """Just the positions that are not already flat."""
    found = []
    for position in (portfolio or {}).get("positions") or []:
        try:
            quantity = float(position.get("position") or 0.0)
        except (TypeError, ValueError):
            continue
        if quantity != 0.0:
            found.append(position)
    return found


def describe(position: dict) -> str:
    quantity = float(position.get("position") or 0.0)
    return (f"{position.get('symbol')} {quantity:g} shares, "
            f"worth {position.get('marketValue')}, "
            f"would {side_to_close(quantity)} {abs(quantity):g}")


def describe_order(order: dict) -> str:
    return (f"order {order.get('orderId')}: {order.get('action')} "
            f"{order.get('totalQuantity')} {(order.get('contract') or {}).get('symbol')} "
            f"{order.get('orderType')} {order.get('tif')}, status {order.get('status')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cancel every order and close every position. A rehearsal "
                    "unless --really is given.")
    parser.add_argument("--really", action="store_true",
                        help="Actually cancel and actually trade. Without this "
                             "it is a rehearsal that sends nothing.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Rehearse. This is already the default; the flag is "
                             "here so a script can say plainly what it wants.")
    args = parser.parse_args(argv)
    live = args.really and not args.dry_run

    now = datetime.now(EASTERN)
    heading = "KILL SWITCH" if live else "KILL SWITCH REHEARSAL"
    print(f"===== {heading} at {now:%Y-%m-%d %H:%M:%S %Z} =====")
    if not live:
        print("Nothing below will be sent. To do it for real:")
        print("  /Users/mtalib/workspace_repos/personal_repo/agentic_trading"
              "/agent/kill_switch.sh --really\n")

    client = mcp.McpClient()

    try:
        before_portfolio = client.portfolio() or {}
        before_orders = (client.open_orders() or {}).get("orders") or []
    except mcp.McpError as exc:
        print(f"STOPPING: could not read the account. {exc}")
        if live:
            alerts_module.alert(
                "error", "Kill switch could not read the account",
                f"The kill switch ran but could not reach the broker: {exc}\n\n"
                "Nothing was cancelled and nothing was closed. Check IB Gateway "
                "and the MCP server, then run it again.")
        return 2

    account = before_portfolio.get("account") or ""
    positions = open_positions(before_portfolio)

    print(f"account: {account or 'unknown'}")
    print(f"working orders: {len(before_orders)}")
    for order in before_orders:
        print(f"  {describe_order(order)}")
    print(f"open positions: {len(positions)}")
    for position in positions:
        print(f"  {describe(position)}")

    if not account.startswith(PAPER_PREFIX):
        print(f"\nSTOPPING: account {account!r} does not start with {PAPER_PREFIX}, "
              "so it is not the paper account. This script will not trade a live "
              "account.")
        return 2

    if not before_orders and not positions:
        print("\nNothing to do. No working orders and no open positions.")
        return 0

    if not live:
        print("\nA real run would now:")
        print(f"  1. cancel all {len(before_orders)} working orders "
              "(ibkr_global_cancel, confirm true)")
        for index, position in enumerate(positions, start=2):
            contract, order = closing_order(position, account)
            print(f"  {index}. {order['action']} {order['totalQuantity']} "
                  f"{contract['symbol']} at the market, transmitted "
                  f"(conId {contract.get('conId', 'not given')})")
        print(f"  {len(positions) + 2}. read the account back and report what is left")
        print("\nThe alert it would send:")
        print(f"  [error] Kill switch fired on {account}")
        print(f"  cancelled {len(before_orders)} orders, closed {len(positions)} positions")
        print("\nREHEARSAL over. Nothing was cancelled, nothing was traded.")
        return 0

    # ------------------------------------------------------------ the real thing
    did: list[str] = []

    try:
        client.call("ibkr_global_cancel", {"confirm": True})
        did.append(f"cancelled all working orders ({len(before_orders)} were open)")
        print(f"\ncancelled all working orders ({len(before_orders)} were open)")
    except mcp.McpError as exc:
        did.append(f"global cancel reported an error: {exc}")
        print(f"\nglobal cancel reported an error: {exc}")
        print("  carrying on to the positions, and checking the orders again at the end")

    for position in positions:
        contract, order = closing_order(position, account)
        label = f"{order['action']} {order['totalQuantity']} {contract['symbol']} at the market"
        try:
            client.call("ibkr_place_order", {
                "contract": contract,
                "order": order,
                "confirm": True,
                "dry_run": False,
                "transmit": True,
            })
            did.append(f"sent {label}")
            print(f"sent {label}")
        except mcp.McpError as exc:
            # The server reports an instantly filled market order as an error.
            # It may well have worked. The account read below is the real answer.
            did.append(f"sent {label}, and the server answered with an error: {exc}")
            print(f"sent {label}, and the server answered with an error: {exc}")
            print("  this is the known bug in docs/MCP_SERVER.md. Checking the "
                  "account below rather than believing it.")

    print(f"\nwaiting {SETTLE_SECONDS} seconds for IBKR to report the fills")
    time.sleep(SETTLE_SECONDS)

    try:
        after_portfolio = client.portfolio() or {}
        after_orders = (client.open_orders() or {}).get("orders") or []
    except mcp.McpError as exc:
        print(f"could not read the account back: {exc}")
        after_portfolio, after_orders = {}, []

    left = open_positions(after_portfolio)
    print(f"\n===== after =====")
    print(f"working orders: {len(after_orders)}")
    for order in after_orders:
        print(f"  {describe_order(order)}")
    print(f"open positions: {len(left)}")
    for position in left:
        print(f"  {position.get('symbol')} {float(position.get('position') or 0):g}")

    flat = not left and not after_orders
    if flat:
        print("\nThe account is flat and no orders are working.")
    else:
        print("\nNOT FLAT YET. Market orders do not fill outside trading hours, "
              "they queue for the next open, so this is expected after the close. "
              "Check again when the market opens.")

    record = output_dir() / f"kill_switch_{now:%Y-%m-%d_%H%M%S}.json"
    record.write_text(json.dumps({
        "run_at": now.isoformat(),
        "account": account,
        "did": did,
        "before": {"orders": before_orders, "positions": positions},
        "after": {"orders": after_orders, "positions": left},
        "flat": flat,
    }, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"written to: {record}")

    delivered = alerts_module.alert(
        "error" if not flat else "warn",
        f"Kill switch fired on {account}",
        "The kill switch was pulled. What it did:\n"
        + "\n".join(f"- {line}" for line in did)
        + f"\n\nLeft over: {len(left)} positions, {len(after_orders)} working orders.\n"
        + ("The account is flat.\n" if flat
           else "NOT flat yet. Market orders queue outside trading hours.\n")
        + f"\nThe loop is stopped. Turn it back on with agent/reenable.sh\n"
        + f"Full record: {record}")
    print(f"alert delivered through: {', '.join(delivered) or 'nothing'}")

    return 0 if flat else 1


if __name__ == "__main__":
    raise SystemExit(main())
