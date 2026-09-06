# Paper trading ledger

The one-month test is scored in one Google Sheet, owned by mtalib.personal@gmail.com:

https://docs.google.com/spreadsheets/d/18_lzOTkoiJn1tc_WCHE5MheigyfhNc2dQcaZJjUBiP8/edit

Its id and URL also live in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/ledger.json`, which is what the agent reads.

## The five books

The eval runs five strategies side by side inside the one paper account. Each one is called a book, and each is scored as if it started with its own $100,000.

| Book | Strategy | Model |
|---|---|---|
| A | Opening momentum | Claude Fable 5.1 |
| B | Opening momentum | none, rules only |
| C | Insider buying | Claude Fable 5.1 |
| D | Congress trades | Claude Fable 5.1 |
| E | Opening momentum | GPT-6 Astra |

Book A against book B is the question "does the model add anything over the plain rules". Book A against book E is "does it matter which model". Neither question can be answered unless every single row in the ledger says which book it came from, which is what the Book column is for.

## Tabs

- **Trades**: one row per fill. Who, what, how many, at what price, the commission, which signal fired and why, and realised P&L when a position closes. Then four columns on the end: Book (A to E), Model (the model that decided this trade, or "none" for book B), Model Cost USD (what that model call cost) and Prompt Hash (a fingerprint of the prompt the model was given).
- **Daily**: one row per trading day, plus a Day 0 row first. Day 0 is the last trading day before the test starts: Starting Equity and Ending Equity both equal the chosen starting balance, SPY Close is that day's close, Trades Count is 0. This gives SPY the same starting line as the account, so the cumulative and alpha columns compare like with like. The agent fills Date, Starting Equity, Ending Equity, SPY Close, Trades Count and the new Model Cost USD column on the end, which is the day's total model spend across all five books. Everything else is a formula: daily and cumulative P&L, SPY daily and cumulative return, and Alpha (our cumulative return minus SPY's). SPY Close is typed in by the agent rather than pulled with GOOGLEFINANCE, so the benchmark uses the same price source as the trades. There is no Book column here on purpose, because the Daily tab tracks the one real paper account that all five books share.
- **Summary**: total return, SPY return, alpha, max drawdown, win rate, average win and loss, trade count, and an annualised Sharpe ratio. All formulas over Daily and Trades, so it updates as rows arrive. These figures are for the whole account, all books together.
- **Rules Log**: two kinds of row. Every judgement the model made, including "do nothing", tagged with the word "decision". And every time a guardrail fired (daily loss cap, position cap, kill switch), what it saw and what it did. Same four columns on the end as the Trades tab: Book, Model, Model Cost USD and Prompt Hash. Most of the month's model spend lands here rather than on Trades, because the model gets asked on every tick and only some ticks end in a fill.
- **Books**: one row per book, five rows, A to E. This is the tab to read at the end of the month.
- **Config**: starting equity, position cap, daily loss cap, universe, cadence. Blank until Mo decides them.

## The Books tab

Fourteen columns: Book, Strategy, Model, Capital, Equity, Return %, SPY %, Alpha, Max DD, Trades, Commissions, Model Cost USD, Rule Triggers, Missed Ticks.

Book, Strategy, Model and Capital are typed in. Capital is $100,000 for every book. The rest are either live formulas or deliberately blank:

| Column | Where the number comes from |
|---|---|
| Return % | `=IF(OR($E2="",$D2="",$D2=0),"",$E2/$D2-1)` on row 2, this book's Equity against its Capital |
| SPY % | `=IF(Summary!$B$7="","",Summary!$B$7)`, the same benchmark for all five books |
| Alpha | `=IF(OR($F2="",$G2=""),"",$F2-$G2)`, this book's return minus SPY's |
| Trades | `=COUNTIFS(Trades!$O$2:$O,$A2)`, fills logged against this book |
| Commissions | `=SUMIFS(Trades!$H$2:$H,Trades!$O$2:$O,$A2)` |
| Model Cost USD | `=SUMIFS(Trades!$Q$2:$Q,Trades!$O$2:$O,$A2)+SUMIFS('Rules Log'!$G$2:$G,'Rules Log'!$E$2:$E,$A2)`, cost from both tabs added together |
| Rule Triggers | `=COUNTIFS('Rules Log'!$E$2:$E,$A2,'Rules Log'!$B$2:$B,"<>decision")`, guardrails that actually fired, so the decision rows are left out |

Equity, Max DD and Missed Ticks are blank. Nothing in this sheet can work them out, because the Daily tab follows one running account rather than five separate equity curves, and a tick that never ran leaves no row anywhere. The agent has to write those three in. Return % and Alpha are written as live formulas anyway, so the moment an Equity figure appears they start working on their own.

## Model cost, and why a blank is not a zero

OpenRouter reports the real dollar cost of a call a few seconds after it answers. In the reply itself the cost usually comes back as 0. So the ledger treats 0 as "nobody knows yet" and writes an empty cell instead. An empty cell still adds up as nothing inside the Books tab totals, so no figure anywhere is thrown off, and the month-end cost comparison never claims a call was free when it was not.

## Writing to the ledger

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/ledger_writer.py` is the only thing that writes to the sheet. Four ways in:

```python
log_trade(row, book_id=None, model=None, model_cost_usd=None,
          prompt_hash=None, dry_run=False)

log_decision(timestamp, symbol, decision, rationale, mode="dry-run",
             book_id=None, model=None, model_cost_usd=None,
             prompt_hash=None, dry_run=False)

log_rule(timestamp, rule_id, detail, action, book_id=None, model=None,
         model_cost_usd=None, prompt_hash=None, dry_run=False)

upsert_daily(date, starting_equity=None, ending_equity=None, spy_close=None,
             trades_count=None, rules_triggered=None, notes=None,
             model_cost_usd=None, dry_run=False)
```

The four extras mean:

- `book_id`: which book this row belongs to, "A" to "E".
- `model`: the model that made the call. Book B passes "none".
- `model_cost_usd`: what that one call cost in dollars. Leave it out, or pass None, when it is not known yet.
- `prompt_hash`: the sha256 of the rendered system prompt as a hex string. It exists so that a prompt edited halfway through the month shows up in the ledger instead of quietly changing the experiment underneath everyone.

Everything after the required arguments has a default, so older calls that never heard of books keep working and just leave those cells empty. `upsert_daily` takes no book, since a day is a day for the whole account.

`log_trade` will also take the book and the model inside its dictionary, under `book`, `book_id`, `model`, `model_cost_usd` or `prompt_hash`. If the same thing is given both ways, the separate argument wins.

Two promises every one of them keeps. It never raises, so a broken wifi connection cannot stop the trading loop. And `dry_run=True` prints the row it would have written and touches nothing.

Self test, writes nothing:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/ledger_writer.py --dry-run
```

## Rebuild

If the sheet is ever lost, run:

```
source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/bin/activate
python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/create_ledger_sheet.py
```

It makes a fresh copy, with all six tabs and all the columns above, and overwrites `config/ledger.json` with the new id. Auth is the token symlinked at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/token_personal_drive.json` (Google account mtalib.personal@gmail.com, Drive file scope, never committed).
