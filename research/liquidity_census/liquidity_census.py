"""
Liquidity census of US-listed common stocks and ETFs.

Universe:  Nasdaq stock screener + Nasdaq ETF screener (both free, no key)
           https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25000&download=true
           https://api.nasdaq.com/api/screener/etf?tableonly=true&limit=5000&download=true
Volume:    yfinance daily bars, mean volume over the last 30 trading sessions,
           and the last close from the same bars.

Written by the LiquidityCensus agent, 2026-09-06.
Lives at /private/tmp/claude-501/-Users-mtalib-workspace-repos/36eef68c-82f0-4a97-bc07-730cc91bf900/scratchpad/liquidity_census.py
"""
import json, re, sys, os
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))

EXCLUDE = re.compile(
    r"warrant|\bright\b|\brights\b|\bunit[s]?\b|preferred|depositary share|"
    r"\bnotes?\b|debenture|subordinated|\bbond\b|contingent value",
    re.I,
)

def universe():
    rows = json.load(open(f"{HERE}/nasdaq_stocks.json"))["data"]["rows"]
    stocks = []
    for r in rows:
        sym = r["symbol"].strip()
        if "^" in sym:                      # preferred series
            continue
        if EXCLUDE.search(r["name"]):
            continue
        stocks.append((sym.replace("/", "-"), "stock"))
    etfs = []
    for r in json.load(open(f"{HERE}/nasdaq_etf.json"))["data"]["data"]["rows"]:
        sym = r["symbol"].strip()
        if "^" in sym:
            continue
        etfs.append((sym.replace("/", "-"), "etf"))
    seen, out = set(), []
    for sym, kind in stocks + etfs:
        if sym and sym not in seen:
            seen.add(sym)
            out.append((sym, kind))
    return out

def fetch(chunk):
    try:
        df = yf.download(chunk, period="3mo", interval="1d", group_by="ticker",
                         auto_adjust=False, threads=False, progress=False,
                         timeout=45)
    except Exception as exc:
        print("chunk failed:", exc, file=sys.stderr)
        return []
    res = []
    for sym in chunk:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub.dropna(subset=["Close", "Volume"]).tail(30)
            if len(sub) < 15:               # needs a real trading history
                continue
            res.append((sym, float(sub["Close"].iloc[-1]),
                        float(sub["Volume"].mean()), int(len(sub))))
        except Exception:
            continue
    return res

def main():
    uni = universe()
    kind = dict(uni)
    syms = [s for s, _ in uni]
    print(f"universe: {len(syms)} symbols "
          f"({sum(1 for k in kind.values() if k=='stock')} stocks, "
          f"{sum(1 for k in kind.values() if k=='etf')} ETFs)")
    chunks = [syms[i:i + 100] for i in range(0, len(syms), 100)]
    rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, res in enumerate(ex.map(fetch, chunks), 1):
            rows.extend(res)
            if i % 10 == 0:
                print(f"  {i}/{len(chunks)} chunks, {len(rows)} resolved", flush=True)
    df = pd.DataFrame(rows, columns=["symbol", "close", "avg_vol_30d", "sessions"])
    df["kind"] = df["symbol"].map(kind)
    df["dollar_vol"] = df["close"] * df["avg_vol_30d"]
    df.to_csv(f"{HERE}/liquidity_census.csv", index=False)

    print(f"\nresolved {len(df)} of {len(syms)} symbols")
    above5 = df[df["close"] > 5]
    print(f"priced above $5: {len(above5)}  "
          f"(stocks {(above5.kind=='stock').sum()}, ETFs {(above5.kind=='etf').sum()})")
    print("\n30-day average share volume, among names above $5")
    print(f"{'threshold':>12} {'all':>7} {'stocks':>7} {'ETFs':>6} {'% of >$5':>9}")
    for t in [250_000, 500_000, 1_000_000, 2_000_000, 5_000_000]:
        m = above5[above5.avg_vol_30d >= t]
        print(f"{t:>12,} {len(m):>7} {(m.kind=='stock').sum():>7} "
              f"{(m.kind=='etf').sum():>6} {100*len(m)/len(above5):>8.1f}%")
    print("\n30-day average DOLLAR volume, among names above $5")
    for t in [5e6, 10e6, 20e6, 50e6, 100e6]:
        m = above5[above5.dollar_vol >= t]
        print(f"{'$'+format(int(t/1e6),',')+'M':>12} {len(m):>7} "
              f"{(m.kind=='stock').sum():>7} {(m.kind=='etf').sum():>6} "
              f"{100*len(m)/len(above5):>8.1f}%")
    print("\nmedian price of names clearing 1M shares:",
          round(above5[above5.avg_vol_30d >= 1e6]["close"].median(), 2))
    print("median dollar volume of names clearing 1M shares: $%.1fM" %
          (above5[above5.avg_vol_30d >= 1e6]["dollar_vol"].median() / 1e6))

if __name__ == "__main__":
    main()
