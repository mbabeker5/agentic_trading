# Paper trading ledger

The one-month test is scored in one Google Sheet, owned by mtalib.personal@gmail.com:

https://docs.google.com/spreadsheets/d/18_lzOTkoiJn1tc_WCHE5MheigyfhNc2dQcaZJjUBiP8/edit

Its id and URL also live in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/ledger.json`, which is what the agent reads.

## Tabs

- **Trades**: one row per fill. Who, what, how many, at what price, the commission, which signal fired and why, and realised P&L when a position closes.
- **Daily**: one row per trading day, plus a Day 0 row first. Day 0 is the last trading day before the test starts: Starting Equity and Ending Equity both equal the chosen starting balance, SPY Close is that day's close, Trades Count is 0. This gives SPY the same starting line as the account, so the cumulative and alpha columns compare like with like. The agent fills Date, Starting Equity, Ending Equity, SPY Close and Trades Count. Everything else is a formula: daily and cumulative P&L, SPY daily and cumulative return, and Alpha (our cumulative return minus SPY's). SPY Close is typed in by the agent rather than pulled with GOOGLEFINANCE, so the benchmark uses the same price source as the trades.
- **Summary**: total return, SPY return, alpha, max drawdown, win rate, average win and loss, trade count, and an annualised Sharpe ratio. All formulas over Daily and Trades, so it updates as rows arrive.
- **Rules Log**: every time a guardrail fires (daily loss cap, position cap, kill switch), what it saw and what it did.
- **Config**: starting equity, position cap, daily loss cap, universe, cadence. Blank until Mo decides them.

## Rebuild

If the sheet is ever lost, run:

```
source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/bin/activate
python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/create_ledger_sheet.py
```

It makes a fresh copy and overwrites `config/ledger.json` with the new id. Auth is the token symlinked at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/token_personal_drive.json` (Google account mtalib.personal@gmail.com, Drive file scope, never committed).
