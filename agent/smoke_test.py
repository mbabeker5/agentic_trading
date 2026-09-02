"""Login smoke test for IB Gateway (paper).

Run after IB Gateway is up and logged into the paper account:

    source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/activate
    python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/smoke_test.py

It connects to the paper API port, prints the account id, cash, open positions,
a SPY quote (live if subscribed, otherwise delayed), and one historical bar,
then disconnects. It places no orders. Every request has its own timeout so the
script always finishes, even when the paper account is still being provisioned.
"""
import asyncio
import math
import sys

from ib_async import IB, Stock

HOST = "127.0.0.1"
PORT = 4002          # IB Gateway paper. Live is 4001.
CLIENT_ID = 99       # anything not used by the trading agent
NOISE = {2104, 2106, 2107, 2108, 2158}   # "data farm connection is OK" style messages


def timed(ib, coro, seconds):
    return ib.run(asyncio.wait_for(coro, seconds))


def main() -> int:
    ib = IB()
    errors = []
    ib.errorEvent += lambda reqId, code, msg, *a: (
        errors.append((code, msg)) if code not in NOISE else None)

    try:
        # readonly=True skips the slow account sync, which hangs for 20s on a
        # brand new paper account. We ask for the account data explicitly below.
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not connect to IB Gateway on {HOST}:{PORT}: {exc}")
        print("Is Gateway running and logged in? Is the API enabled on port 4002?")
        return 1

    accounts = ib.managedAccounts()
    print(f"connected. accounts: {accounts}, server version {ib.client.serverVersion()}")
    if not accounts:
        print("FAIL: no managed accounts returned")
        return 1
    acct = accounts[0]
    if not acct.startswith("DU"):
        print(f"STOP: account {acct} is not a paper account (paper ids start with DU). "
              "Do not run the agent against this Gateway.")
        return 2

    try:
        vals = timed(ib, ib.reqAccountSummaryAsync(), 15)
        summary = {v.tag: v.value for v in vals
                   if v.tag in ("NetLiquidation", "TotalCashValue", "BuyingPower")}
        if summary:
            for k, v in summary.items():
                print(f"  {k}: {v}")
        else:
            print("  account summary: EMPTY. Normal on the day the paper account is created, "
                  "IBKR provisions it overnight. Re-run tomorrow.")
    except Exception as exc:  # noqa: BLE001
        print(f"  account summary failed: {exc!r}")

    try:
        positions = timed(ib, ib.reqPositionsAsync(), 15)
        print(f"  open positions: {len(positions)}")
        for p in positions:
            print(f"    {p.contract.symbol} {p.position} @ {p.avgCost:.2f}")
    except Exception as exc:  # noqa: BLE001
        print(f"  positions failed: {exc!r}")

    spy = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(spy)
    ib.reqMarketDataType(1)
    t = ib.reqMktData(spy, "", True, False)
    ib.sleep(4)
    if t.bid is not None and not math.isnan(t.bid):
        print(f"  SPY LIVE bid/ask/last: {t.bid} / {t.ask} / {t.last}")
    else:
        ib.cancelMktData(spy)
        ib.reqMarketDataType(3)
        t = ib.reqMktData(spy, "", True, False)
        ib.sleep(4)
        print(f"  SPY DELAYED bid/ask/last: {t.bid} / {t.ask} / {t.last}")
        print("  WARNING: no live quote. Subscribe to 'US Securities Snapshot and Futures "
              "Value Bundle' on the live login and tick 'share real-time market data with "
              "paper trading account' in Client Portal.")
    ib.cancelMktData(spy)

    try:
        bars = timed(ib, ib.reqHistoricalDataAsync(
            spy, "", "1 D", "1 hour", "TRADES", useRTH=True), 20)
        print(f"  historical bars today: {len(bars)}, last close {bars[-1].close if bars else None}")
    except Exception as exc:  # noqa: BLE001
        print(f"  historical bars failed: {exc!r}")

    relevant = [(c, m[:100]) for c, m in errors if c not in (300, 10167, 354)]
    if relevant:
        print("  other Gateway messages:", relevant)
    ib.disconnect()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
