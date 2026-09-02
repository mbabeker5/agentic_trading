"""Login smoke test for IB Gateway (paper).

Run after IB Gateway is up and logged into the paper account:

    source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/bin/activate
    python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/smoke_test.py

It connects to the paper API port, prints the account id, net liquidation,
cash, open positions, and a live SPY quote, then disconnects. It places no orders.
"""
import sys
from ib_async import IB, Stock

HOST = "127.0.0.1"
PORT = 4002          # IB Gateway paper. Live is 4001.
CLIENT_ID = 99       # anything not used by the trading agent


def main() -> int:
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not connect to IB Gateway on {HOST}:{PORT}: {exc}")
        print("Is Gateway running and logged in? Is the API enabled on port 4002?")
        return 1

    accounts = ib.managedAccounts()
    print(f"connected. accounts: {accounts}")
    if not accounts:
        print("FAIL: no managed accounts returned")
        return 1
    acct = accounts[0]
    if not acct.startswith("DU"):
        print(f"WARNING: account {acct} does not look like a paper account (paper ids start with DU)")

    summary = {v.tag: v.value for v in ib.accountSummary(acct)
               if v.tag in ("NetLiquidation", "TotalCashValue", "BuyingPower", "AccountType")}
    for k in ("AccountType", "NetLiquidation", "TotalCashValue", "BuyingPower"):
        print(f"  {k}: {summary.get(k)}")

    positions = ib.positions(acct)
    print(f"  open positions: {len(positions)}")
    for p in positions:
        print(f"    {p.contract.symbol} {p.position} @ {p.avgCost:.2f}")

    spy = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(spy)
    ib.reqMarketDataType(1)  # 1 = live. Falls back with an error if not entitled.
    t = ib.reqMktData(spy, "", False, False)
    ib.sleep(3)
    print(f"  SPY bid/ask/last: {t.bid} / {t.ask} / {t.last}")
    if t.bid is None or t.bid != t.bid:  # None or NaN
        print("WARNING: no live quote. Check the market data subscription and that "
              "'share real-time data with paper account' is ticked in Client Portal.")
    ib.cancelMktData(spy)
    ib.disconnect()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
