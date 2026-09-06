"""Get out of everything, now. The only script in this project that can trade.

Read this before running it.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.py

It does five things, in this order, and the order is the whole design:

    1. writes output/STOP and output/LOOP_DISABLED, which stops the loop. This
       happens FIRST, before anything that can be slow or can fail, and it
       happens whether or not you remembered --really;
    2. cancels every working order on the account in one go;
    3. reads the orders back and cancels one by one whatever survived that;
    4. sells every long and buys back every short, at the market;
    5. reads the account again, up to five times over thirty seconds, until it
       is flat and empty or until it can say exactly what is left.

Then it alerts Mo with the result and writes the whole thing to
output/kill_switch_<when>.json.

Step 1 is first on purpose. Writing two small files is fast and cannot fail in
any interesting way. Talking to a broker is neither. If the broker half falls
over, the loop is still stopped.

WHY IT READS THE ACCOUNT BACK RATHER THAN BELIEVING THE REPLIES
---------------------------------------------------------------
The MCP server has a known bug, seen for real on 2026-09-02 and written up in
docs/MCP_SERVER.md: a market order that fills instantly comes back looking like
a failure, because the server's own reply fails its own validation on the way
out. The order filled. The error is about the reply. So the only honest answer
to "did it work" is what the account says afterwards, and that is what this
reports.

IT DOES NOT GO THROUGH THE LOOP
-------------------------------
Everything here is done straight through the Broker protocol in agent/broker.py:
global_cancel, cancel_order and place_order. It never imports agent/loop.py,
never reads a book state file, and never asks the guardrails for permission.
Getting out is always allowed, and a panic button that depends on the thing you
are panicking about is not a panic button. The same protocol is why the tests
can run the whole of this against agent/replay/fake_broker.py.

REHEARSAL IS THE DEFAULT
------------------------
With no flags it is a rehearsal: it reads the account, lists exactly what it
would cancel and what it would flatten, sends nothing, and prints the alert it
would have sent.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.py

A rehearsal still writes the two brake files, because step 1 is unconditional.
Clear them with agent/reenable.sh afterwards.

Only --really makes it real:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really

PAPER ONLY, UNLESS YOU SAY OTHERWISE TWICE
------------------------------------------
IBKR paper account ids start with DU. On any other id this refuses to trade
unless BOTH of these are true:

    the flag  --live-account-ok
    the env   AGENTIC_TRADING_KILL_LIVE=yes

Two of them, deliberately, because they are hard to do by accident together. A
flag alone is one typo. An environment variable alone is something a shell
profile could be carrying without you knowing. When both are there it flattens
the live account and says so in plain words in the alert. When either is
missing it refuses, says why, and the two brake files are still written, so the
loop is stopped either way.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402
import broker as broker_mod  # noqa: E402
from paths import (  # noqa: E402
    loop_disabled_file, output_dir, project_root, stop_file,
)

EASTERN = ZoneInfo("America/New_York")

#: Paper account ids start with these two letters. Anything else needs the flag
#: and the environment variable below before a single order is sent.
PAPER_PREFIX = "DU"

#: Half of what it takes to flatten a live account. The other half is the
#: --live-account-ok flag.
LIVE_KILL_ENV_VAR = "AGENTIC_TRADING_KILL_LIVE"

#: The tag that goes on every closing order. Not BOOK_ anything, on purpose:
#: these orders belong to no book, and agent/deadman.py tells a book's position
#: from an orphan by exactly that prefix.
KILL_ORDER_REF = "KILL_SWITCH"

#: How many times to read the account back, and how long to wait between reads.
#: Five reads six seconds apart is thirty seconds of patience, which is long
#: enough for a market order to fill and report in a live session and short
#: enough that nobody standing over the machine gives up on it.
SETTLE_ATTEMPTS = 5
SETTLE_SECONDS = 6.0


# ------------------------------------------------------- reading what is there

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


def working_orders(answer: dict) -> list[dict]:
    """The orders out of an open_orders() reply, whatever shape it came in."""
    rows = (answer or {}).get("orders")
    return [row for row in (rows or []) if isinstance(row, dict)]


def order_id_of(order: dict) -> Any:
    """The broker's id for one order, under whichever key it arrived."""
    for key in ("orderId", "order_id", "id"):
        if (order or {}).get(key) is not None:
            return order[key]
    return None


def describe(position: dict) -> str:
    quantity = float(position.get("position") or 0.0)
    return (f"{position.get('symbol')} {quantity:g} shares, "
            f"worth {position.get('marketValue')}, "
            f"would {side_to_close(quantity)} {abs(quantity):g}")


def describe_order(order: dict) -> str:
    symbol = order.get("symbol") or (order.get("contract") or {}).get("symbol")
    return (f"order {order_id_of(order)}: {order.get('action')} "
            f"{order.get('totalQuantity')} {symbol} "
            f"{order.get('orderType')} {order.get('tif')}, status {order.get('status')}")


# ------------------------------------------------------------------ the guards

def live_kill_allowed() -> bool:
    """True only when AGENTIC_TRADING_KILL_LIVE is set to exactly yes."""
    return os.environ.get(LIVE_KILL_ENV_VAR) == "yes"


def is_paper_account(account: str | None) -> bool:
    """True for an IBKR paper account id, which always starts with DU."""
    return str(account or "").startswith(PAPER_PREFIX)


@contextmanager
def order_lock_lifted():
    """Let this process send closing orders, then put the lock straight back.

    agent/broker.py refuses every order unless AGENTIC_TRADING_LIVE_ORDERS is
    exactly "yes". That lock exists to stop a strategy order leaving this
    machine before Mo has read the strategy numbers and said yes. It does not
    exist to stop an account being closed out, and refusing to get out is the
    one failure that costs more than the lock ever saves.

    So it is lifted for exactly as long as the closing orders take, and
    whatever was there before is put back, which is normally nothing at all.
    """
    was = os.environ.get(broker_mod.LIVE_ENV_VAR)
    os.environ[broker_mod.LIVE_ENV_VAR] = "yes"
    try:
        yield
    finally:
        if was is None:
            os.environ.pop(broker_mod.LIVE_ENV_VAR, None)
        else:
            os.environ[broker_mod.LIVE_ENV_VAR] = was


def attempt(call: Callable[[], Any]) -> tuple[Any, str | None]:
    """Do one thing at the broker and never raise.

    Three brokers satisfy the protocol and each has its own idea of what to
    raise: BrokerError from agent/broker.py, McpError from the MCP client
    underneath it, ConnectionError and FakeBrokerError in a replay. A kill
    switch that dies on an exception type it did not expect is a kill switch
    that leaves a position open, so everything is caught here and written down.
    """
    try:
        return call(), None
    except Exception as exc:                                      # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- the brakes

def write_brakes(now: datetime) -> list[Path]:
    """Stop the loop. The first thing that happens on every path through here.

    output/STOP           the loop may close positions but must not open any.
    output/LOOP_DISABLED  run_tick.sh will not run a tick at all.

    Both are written whether this is a rehearsal or the real thing, and whether
    or not the broker can be reached. agent/kill_switch.sh writes the same two
    files before it even starts Python, so on the normal path they are written
    twice with the same content. That is deliberate: whichever half of the
    panic button runs, the loop stops.
    """
    stamp = f"{now:%Y-%m-%d %H:%M:%S %Z}"
    root = project_root()
    written = []
    for path, what in (
        (stop_file(), "The loop may close positions but must not open any."),
        (loop_disabled_file(), "run_tick.sh will not run a tick while this file exists."),
    ):
        path.write_text(
            f"Written by kill_switch.py at {stamp}.\n{what}\n"
            f"Clear it with {root}/agent/reenable.sh\n", encoding="utf-8")
        written.append(path)
    return written


# ------------------------------------------------------------- what came of it

@dataclass
class KillResult:
    """What the kill switch found, did, and left behind."""

    account: str = ""
    live_account: bool = False
    did: list = field(default_factory=list)
    before_orders: list = field(default_factory=list)
    before_positions: list = field(default_factory=list)
    after_orders: list = field(default_factory=list)
    after_positions: list = field(default_factory=list)
    flat: bool = False
    refused: str = ""
    brakes: list = field(default_factory=list)
    record_path: str | None = None
    alerted: list = field(default_factory=list)


# ----------------------------------------------------------------- the actions

def cancel_everything(broker, before: list[dict], did: list[str]) -> None:
    """Global cancel, then chase whatever survived it, one order at a time.

    The global cancel is one call and it either works or it does not. What
    matters is the read afterwards: an order still sitting there after a global
    cancel is a straggler, and a straggler is cancelled by its own id. IBKR
    ignores a global cancel for orders placed by another client id often enough
    that this second pass is not theoretical.
    """
    answer, error = attempt(broker.global_cancel)
    if error:
        did.append(f"the global cancel reported an error: {error}")
        print(f"\nthe global cancel reported an error: {error}")
        print("  carrying on, and cancelling what is left one at a time")
    else:
        did.append(f"cancelled all working orders in one go ({len(before)} were open)")
        print(f"\ncancelled all working orders in one go ({len(before)} were open)")

    left, read_error = attempt(broker.open_orders)
    if read_error:
        did.append(f"could not read the orders back after the global cancel: {read_error}")
        print(f"could not read the orders back: {read_error}")
        return

    stragglers = working_orders(left)
    if not stragglers:
        print("nothing is working after the global cancel")
        return

    print(f"{len(stragglers)} order(s) survived the global cancel, cancelling each one")
    for order in stragglers:
        order_id = order_id_of(order)
        if order_id is None:
            did.append(f"a working order came back with no id on it: {order}")
            print(f"  no id on this one, cannot cancel it: {describe_order(order)}")
            continue
        _, one_error = attempt(lambda oid=order_id: broker.cancel_order(oid))
        if one_error:
            did.append(f"cancelling order {order_id} on its own reported: {one_error}")
            print(f"  order {order_id}: {one_error}")
        else:
            did.append(f"cancelled order {order_id} on its own")
            print(f"  cancelled order {order_id}")


def flatten_positions(broker, positions: list[dict], account: str,
                      did: list[str]) -> None:
    """Sell every long and buy back every short, at the market.

    One order per position, in the closing direction, tagged KILL_SWITCH so a
    later reconciliation can see where the fill came from. Nothing here trusts
    what the order call says: the reads afterwards are the answer.
    """
    for position in positions:
        contract, order = closing_order(position, account)
        label = (f"{order['action']} {order['totalQuantity']} "
                 f"{contract['symbol']} at the market")
        answer, error = attempt(
            lambda c=contract, o=order: broker.place_order(c, o, KILL_ORDER_REF))
        if error:
            # As often the known bug in docs/MCP_SERVER.md as a real failure.
            did.append(f"sent {label}, and the broker answered with an error: {error}")
            print(f"sent {label}, and the broker answered with an error: {error}")
            print("  not believing that. The account read below is the answer.")
            continue
        note = ""
        if isinstance(answer, dict) and answer.get("error"):
            note = f", the broker also said: {answer['error']}"
        did.append(f"sent {label}{note}")
        print(f"sent {label}{note}")


def settle(broker, did: list[str], sleep: Callable[[float], Any] = time.sleep,
           attempts: int = SETTLE_ATTEMPTS,
           gap: float = SETTLE_SECONDS) -> tuple[list[dict], list[dict]]:
    """Read the account back until it is flat and empty, or until we run out.

    Five reads six seconds apart. It stops the moment the account is flat with
    nothing working, so the normal case takes six seconds and not thirty.
    Returns whatever the last successful read said, which is the honest answer
    even when it is not the answer anybody wanted.
    """
    orders: list[dict] = []
    positions: list[dict] = []
    for number in range(1, attempts + 1):
        sleep(gap)
        holdings, portfolio_error = attempt(broker.portfolio)
        resting, orders_error = attempt(broker.open_orders)
        if portfolio_error or orders_error:
            problem = portfolio_error or orders_error
            print(f"read {number} of {attempts}: could not read the account back: {problem}")
            did.append(f"read {number} could not reach the broker: {problem}")
            continue
        positions = open_positions(holdings or {})
        orders = working_orders(resting or {})
        print(f"read {number} of {attempts}: {len(positions)} position(s), "
              f"{len(orders)} working order(s)")
        if not positions and not orders:
            did.append(f"the account was flat and empty on read {number}")
            return orders, positions
    did.append(f"still not flat after {attempts} reads over "
               f"{attempts * gap:g} seconds")
    return orders, positions


# ------------------------------------------------------------------- the whole

def pull(broker, *, really: bool = False, live_account_ok: bool = False,
         now: datetime | None = None,
         sleep: Callable[[float], Any] = time.sleep) -> tuple[int, KillResult]:
    """Do the whole thing against one broker. Returns (exit code, what happened).

    really            False rehearses: it reads, it prints what it would do, and
                      it sends nothing.
    live_account_ok   half of the permission to touch a non DU account. The
                      other half is AGENTIC_TRADING_KILL_LIVE=yes.
    sleep             swapped out in the tests, where waiting six real seconds
                      for a pretend broker would be silly.

    Exit codes: 0 done or nothing to do, 1 acted but the account is not flat,
    2 refused or could not read the account.
    """
    now = now or datetime.now(EASTERN)
    result = KillResult()

    heading = "KILL SWITCH" if really else "KILL SWITCH REHEARSAL"
    print(f"===== {heading} at {now:%Y-%m-%d %H:%M:%S %Z} =====")

    # Step one, always, before anything that can be slow or can fail.
    result.brakes = [str(path) for path in write_brakes(now)]
    print("the loop is stopped:")
    for path in result.brakes:
        print(f"  wrote {path}")

    if not really:
        print("\nNothing below will be sent. To do it for real:")
        print(f"  {project_root()}/agent/kill_switch.sh --really")

    holdings, portfolio_error = attempt(broker.portfolio)
    resting, orders_error = attempt(broker.open_orders)
    if portfolio_error or orders_error:
        problem = portfolio_error or orders_error
        result.refused = f"could not read the account: {problem}"
        print(f"\nSTOPPING: could not read the account. {problem}")
        print("The two brake files above are in place, so the loop is stopped either way.")
        if really:
            result.alerted = alerts_module.alert(
                "error", "Kill switch could not read the account",
                f"The kill switch ran but could not reach the broker: {problem}\n\n"
                "Nothing was cancelled and nothing was closed. The loop is "
                "stopped, because output/STOP and output/LOOP_DISABLED were "
                "written first.\n\nCheck IB Gateway and the MCP server, then run "
                "it again.")
        return 2, result

    account = str((holdings or {}).get("account") or "")
    positions = open_positions(holdings or {})
    orders = working_orders(resting or {})
    result.account = account
    result.before_orders = orders
    result.before_positions = positions

    print(f"\naccount: {account or 'unknown'}")
    print(f"working orders: {len(orders)}")
    for order in orders:
        print(f"  {describe_order(order)}")
    print(f"open positions: {len(positions)}")
    for position in positions:
        print(f"  {describe(position)}")

    # ------------------------------------------------------- the live account gate
    if not is_paper_account(account):
        result.live_account = True
        if not (live_account_ok and live_kill_allowed()):
            missing = []
            if not live_account_ok:
                missing.append("the --live-account-ok flag")
            if not live_kill_allowed():
                missing.append(f"{LIVE_KILL_ENV_VAR}=yes in the environment")
            result.refused = (
                f"account {account!r} does not start with {PAPER_PREFIX}, so it is "
                f"not a paper account, and {' and '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} missing")
            print(f"\nSTOPPING: {result.refused}.")
            print("Nothing was cancelled and nothing was traded.")
            print("The loop is stopped anyway: the two brake files above are written.")
            print("\nTo flatten a live account you need both of these, together:")
            print("  --live-account-ok on the command line")
            print(f"  {LIVE_KILL_ENV_VAR}=yes in the environment")
            if really:
                result.alerted = alerts_module.alert(
                    "error", f"Kill switch refused: {account} is not a paper account",
                    f"The kill switch was pulled on account {account}, which does "
                    f"not start with {PAPER_PREFIX}.\n\n"
                    f"It refused, because {result.refused}.\n\n"
                    "Nothing was cancelled and nothing was closed. The loop IS "
                    "stopped: output/STOP and output/LOOP_DISABLED were written "
                    "first, before this check ran.\n\n"
                    "If flattening that account really is what you want, run it "
                    "again with --live-account-ok and "
                    f"{LIVE_KILL_ENV_VAR}=yes set.")
            return 2, result
        print(f"\nTHIS IS A LIVE ACCOUNT. {account} does not start with {PAPER_PREFIX}.")
        print(f"Going ahead because --live-account-ok was given and "
              f"{LIVE_KILL_ENV_VAR} is set to yes.")

    if not orders and not positions:
        print("\nNothing to do at the broker. No working orders and no open positions.")
        print("The loop is stopped. Turn it back on with agent/reenable.sh")
        return 0, result

    # ------------------------------------------------------------- the rehearsal
    if not really:
        print("\nA real run would now:")
        print(f"  1. cancel all {len(orders)} working orders in one go")
        print("  2. read the orders back and cancel one by one anything still there")
        for index, position in enumerate(positions, start=3):
            contract, order = closing_order(position, account)
            print(f"  {index}. {order['action']} {order['totalQuantity']} "
                  f"{contract['symbol']} at the market, tagged {KILL_ORDER_REF} "
                  f"(conId {contract.get('conId', 'not given')})")
        print(f"  {len(positions) + 3}. read the account back up to "
              f"{SETTLE_ATTEMPTS} times over "
              f"{SETTLE_ATTEMPTS * SETTLE_SECONDS:g} seconds, until it is flat")
        print("\nThe alert it would send:")
        which = "LIVE account" if result.live_account else "account"
        print(f"  [error] Kill switch fired on {which} {account}")
        print(f"  cancelled {len(orders)} orders, closed {len(positions)} positions")
        print("\nREHEARSAL over. Nothing was cancelled, nothing was traded.")
        print("The two brake files were written. Clear them with agent/reenable.sh")
        return 0, result

    # ------------------------------------------------------------ the real thing
    did: list[str] = result.did
    with order_lock_lifted():
        cancel_everything(broker, orders, did)
        flatten_positions(broker, positions, account, did)
        print(f"\nreading the account back, up to {SETTLE_ATTEMPTS} times over "
              f"{SETTLE_ATTEMPTS * SETTLE_SECONDS:g} seconds")
        after_orders, after_positions = settle(broker, did, sleep=sleep)

    result.after_orders = after_orders
    result.after_positions = after_positions
    result.flat = not after_orders and not after_positions

    print("\n===== after =====")
    print(f"working orders: {len(after_orders)}")
    for order in after_orders:
        print(f"  {describe_order(order)}")
    print(f"open positions: {len(after_positions)}")
    for position in after_positions:
        print(f"  {position.get('symbol')} {float(position.get('position') or 0):g}")

    if result.flat:
        print("\nThe account is flat and no orders are working.")
    else:
        print("\nNOT FLAT YET. Market orders do not fill outside trading hours, "
              "they queue for the next open, so this is expected after the close. "
              "Check again when the market opens.")

    record = output_dir() / f"kill_switch_{now:%Y-%m-%d_%H%M%S}.json"
    record.write_text(json.dumps({
        "run_at": now.isoformat(),
        "account": account,
        "live_account": result.live_account,
        "did": did,
        "before": {"orders": orders, "positions": positions},
        "after": {"orders": after_orders, "positions": after_positions},
        "flat": result.flat,
    }, indent=2, default=str) + "\n", encoding="utf-8")
    result.record_path = str(record)
    print(f"written to: {record}")

    live_line = ""
    if result.live_account:
        live_line = (f"THIS WAS A LIVE ACCOUNT, not the paper one. {account} was "
                     f"flattened because --live-account-ok was given and "
                     f"{LIVE_KILL_ENV_VAR} was set to yes.\n\n")
    result.alerted = alerts_module.alert(
        "error",
        f"Kill switch fired on {'LIVE account' if result.live_account else 'account'} "
        f"{account}",
        live_line
        + "The kill switch was pulled. What it did:\n"
        + "\n".join(f"- {line}" for line in did)
        + f"\n\nLeft over: {len(after_positions)} positions, "
          f"{len(after_orders)} working orders.\n"
        + ("The account is flat.\n" if result.flat
           else "NOT flat yet. Market orders queue outside trading hours.\n")
        + "\nThe loop is stopped. Turn it back on with agent/reenable.sh\n"
        + f"Full record: {record}")
    print(f"alert delivered through: {', '.join(result.alerted) or 'nothing'}")

    return 0 if result.flat else 1, result


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
    parser.add_argument("--live-account-ok", action="store_true",
                        help="Allow a non paper account to be flattened. Needs "
                             f"{LIVE_KILL_ENV_VAR}=yes in the environment as "
                             "well, and refuses without both.")
    args = parser.parse_args(argv)

    status, _ = pull(broker_mod.McpBroker(), really=args.really and not args.dry_run,
                     live_account_ok=args.live_account_ok)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
