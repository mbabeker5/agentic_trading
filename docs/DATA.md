# Where everything is written down

Status: written 2026-09-06, the day Mo decided the project needed a real record.

Everything the agent does now goes into one file:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/data/trading.sqlite
```

That file is the record. The Google Sheet is a picture of it, redrawn once a
night after the close.

## Why this exists

Before this, the day was scattered across half a dozen shapes. Book state in
`output/state_BOOK_A_2026-09-08.json`, the shortlist in another JSON, the day
trade count in a third, the watchdog in a fourth, alerts in a text log, and the
score in a Google Sheet on the other end of a wifi connection. None of it could
be asked a question. "How often did the daily loss cap actually bite in
September" meant opening twenty files by hand.

Worse, the Sheet was both the record and a thing that could fail. A row written
at 09:35 while the market was moving is a network call inside the trading loop,
and a network call inside a loop that holds the risk limits is a bad idea on the
morning it goes wrong.

So the arrangement is now the other way round.

**SQLite is the system of record.** Every tick, scan, decision, order, fill,
alert and check is written there, locally, with no network involved. If the wifi
is off, nothing is lost.

**The Google Sheet is a nightly human view.** It is rewritten from the database
at 16:35 New York by
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/sync_sheet.py`.
If it is ever wrong, or somebody deletes a row, or the whole spreadsheet goes
missing, that is not a loss. Rebuild it and run the sync again.

## Setting it up

One command, safe to run as many times as you like:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/migrate_db.py
```

The second run does nothing and says so.

To see what is in there without any chance of breaking it:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/db.py
```

That prints where the file is, which migrations have been applied, and how many
rows are in each table. It writes nothing.

## The files

| File | What it is |
|---|---|
| `data/trading.sqlite` | The database. Gitignored, because it is state, not source. |
| `data/schema.sql` | Every table in one readable piece, with the reason each one exists. In git. Does not run. |
| `data/migrations/0001_initial.sql` | What actually runs to build the database. In git. |
| `data/backups/` | One copy a night, thirty days kept. Gitignored. |
| `agent/db.py` | The only thing that writes to the database. Every helper is here. |
| `scripts/migrate_db.py` | Builds it, or brings it up to date. |
| `scripts/backup_db.sh` | The nightly copy. |
| `ledger/sync_sheet.py` | Rewrites the Google Sheet from the database. |

All of those are under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/`.

`data/schema.sql` and `data/migrations/` say the same thing twice on purpose.
The migrations are what runs; the schema file is what a person reads when they
want the whole picture without piecing several migrations together in their
head. They cannot quietly drift apart:
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_db.py`
builds a database each way and fails if the two do not match. So when you add a
migration, paste its statements into `data/schema.sql` as well.

## The tables

Thirteen tables and a fourteenth for bookkeeping. Times are stored as New York
local time, written `2026-09-08 09:35:11`, which is the same shape the Google
Sheet displays, so a row goes straight from one to the other with no conversion
and no timezone argument to have.

**ticks.** One row every time the loop wakes up, for every book, whether or not
anything happened. This is the attendance register, and the gaps are the point:
a tick with no row is a tick that never ran, and nothing else in the project can
tell you that. Holds the phase (idle, sweep, scan, pick, manage, flatten,
closed), the book's mode (dry_run, tiny, full), the git hash of the rules it ran
under, and how long it took.

**scans.** One row per run of a scanner, whether that is the momentum scanner,
the insider sweep or the congress sweep. Keeps the counts at each filter stage,
which is the thing to read when a scan comes back empty and nobody knows which
filter ate everything, plus the raw diagnostics IBKR sent back and whether the
quotes were live or delayed.

**shortlist_entries.** The names one scan produced, one row each, in the order
the scanner ranked them. Each carries its score, relative volume, dollar volume,
the scan codes that flagged it, and the plain English reasons. The `traded`
column is filled in later, once it is known whether anything was actually bought
off the back of that line.

**decisions.** Every judgement call, including every skip and every decision to
do nothing. That is the strategy's own rule, and it is what makes a month
readable afterwards: the interesting question at the end is usually why a name
was passed over, not why one was bought. Each row says which book, which model
(or none, for book B), the fingerprint of the prompt the model was shown, what
it decided, the entry, stop and target, its confidence, its reason in words, how
long it took, how many tokens it used and what it cost. A call that was made and
then refused is marked `rejected` with the guardrail's own name in
`reject_reason`, which is what the month end count of "which limit actually bit"
is built from.

**orders.** One row per order sent, and also the ones that were only worked out
and never sent. All five books are on dry run today, so the orders they did not
send are the entire result so far. Each row carries the book's own tag, BOOK_A
to BOOK_E, which is what makes a fill traceable back to the book that asked for
it once five books share one account, plus the parent order and OCA group that
hold a bracket together.

**fills.** One row per execution. IBKR's own execution id is unique in this
table, which is what stops the same fill being counted twice when the reconciler
reads the day's executions again after a restart. Slippage in dollars and in
basis points is worked out at write time, by the same arithmetic the Google
Sheet uses in columns U and V, so the two can never disagree about a number Mo
is going to read in both places.

**position_snapshots.** What each book was holding at one moment: quantity,
average cost, market price, unrealised profit, and the stop and target resting
at the broker. Written every tick and at the close, so a day can be replayed
afterwards rather than guessed at from the fills. Recording the stop here is
what would make a stop that quietly went missing visible in the history.

**alerts.** Every alert raised and which channels it actually reached, from
iMessage, Slack, the macOS banner and the log. An alert that reached nobody is
recorded too, because "we tried to shout and nothing got through" is exactly the
thing nobody finds out about otherwise.

**preflight_results.** One row per morning check per day: gateway login, market
data, scanner, scanner filters, reconcile, day trades, day trade regime. Running
the pre-flight twice in a morning updates the row rather than adding a second
opinion.

**watchdog_checks.** One row every time the watchdog looks at something. Unlike
the pre-flight these pile up all day on purpose, because the question worth
asking of the watchdog is almost always "when did this start failing", and that
needs every check rather than the most recent verdict. Records what it did about
it, including a Gateway restart.

**day_trade_counters.** Where each book stands against the pattern day trader
limit, one row per book per day: how many day trades it has used in the rolling
five business days, how many trades the rule stopped, and which regime was in
force. The count of stopped trades is the figure that says whether the limit is
actually costing this experiment anything.

**regime_flags.** Which margin regime the account was in on a given day, old
PDT or the new intraday margin rules or unknown, with the raw IBKR tags the
decision was based on. So a regime that flips unexpectedly can be argued with
rather than just believed.

**daily_book_summaries.** The scoreboard: one row per book per trading day, with
its opening and closing equity, profit in dollars and percent, SPY's close, its
trades, commissions, model spend, rule triggers, missed ticks and worst
drawdown. This is the table to read at the end of the month, and the one both
the Daily and Books tabs of the Google Sheet are built from.

It exists because the spreadsheet cannot work these out. The Sheet's Daily tab
follows the one paper account that all five books share, so it has no way to
give each book its own equity curve, its own drawdown, or a count of the ticks
it missed. Those three are exactly the columns that sit blank on the Books tab
today. Here they are just columns.

**schema_version.** Which migration files have already been applied. That is the
whole of how running the migration again does nothing.

## How a caller switches from ledger_writer to db

Nothing has been switched over yet. `agent/loop.py`, `agent/watchdog.py`,
`agent/preflight.py` and the rest still write where they always did, and wiring
them up is the next job. This is what it looks like when they are.

Today, in `agent/loop.py`:

```python
import ledger_writer

ledger_writer.log_decision(
    self.now, symbol, decision, f"{rationale} [rules {self.rules}]",
    mode=str(self.book.mode), book_id=self.book.book_id,
    model=self.book.model or "none", model_cost_usd=cost,
    prompt_hash=prompt_hash, dry_run=not self.write_ledger)
```

After:

```python
import db

db.record_decision(
    ts=self.now, book_id=self.book.book_id, shape=self.phase,
    model=self.book.model or "none", prompt_hash=prompt_hash,
    rules_commit=self.rules, symbol=symbol, action=decision,
    rationale=rationale, cost_usd=cost)
```

Four things change, and all four are the point.

There is no `dry_run` any more. The database is written to always, in every
mode. A dry run is a rehearsal and a rehearsal nobody wrote down is worthless,
so `mode` moves onto the `ticks` row where it belongs, saying which of dry_run,
tiny or full the book was in. Nothing reaches the broker in dry run either way.

There is no network call. `ledger_writer` posts to Google over the wifi and
takes up to thirty seconds to find out it cannot. `db.record_decision` writes to
a file on the same disk and returns in under a millisecond.

The reason no longer has `[rules 41d734d]` stapled to the end of it.
`rules_commit` is its own column, so you can filter on it instead of searching
for it inside a sentence.

`db.record_decision` never raises, exactly like `ledger_writer` never raises. If
something is wrong it complains to stderr and hands back `None`. Recording what
happened must never be the thing that stops the loop, because the loop is what
holds the risk limits.

Every helper works the same way. One short transaction each, opened and closed
inside the call, so nothing ever holds a database lock while waiting on IBKR or
on Google. The full list is at the top of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/db.py`:
`record_tick`, `record_scan`, `record_decision`, `record_decision_result`,
`record_order`, `update_order_status`, `record_fill`, `snapshot_positions`,
`record_alert`, `record_preflight`, `record_watchdog`,
`record_day_trade_counter`, `record_regime` and `upsert_daily_summary`.

One of those is worth calling out. `record_decision_result` takes a whole
`DecisionResult` from `agent/decide.py` and writes one row per name in it: a row
for each pick, each skip, each exit and each rejection. The cost, the token
counts and the latency go on the first row only and the rest carry nothing. That
is deliberate. One model call has one price, and writing it on every row would
multiply the month's spend by however many names the model happened to mention,
which would make the whole cost comparison meaningless.

## Two writers at the same time

The loop wakes up every five minutes and the watchdog wakes up every five
minutes, so sooner or later they overlap. Three settings, applied on every
connection, make that a non event:

- **WAL journal mode.** A reader never blocks a writer and a writer never blocks
  a reader, so the nightly sync can read a month while the watchdog is mid write.
- **A five second busy timeout.** If the other process is mid write, wait rather
  than failing straight away. Every write here is milliseconds, so five seconds
  is an eternity and hitting it means something is genuinely wrong.
- **Foreign keys on.** SQLite has them off by default, per connection. A fill
  pointing at an order that does not exist is a bug worth hearing about at once.

There is a test for it. Two threads writing at once, each opening its own
connection for every single row, which is exactly what the helpers do in real
life.

## Backups, and how long things are kept

One copy a night at 17:00, into
`data/backups/trading_YYYY-MM-DD.sqlite`, written by
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/backup_db.sh`.
Anything older than thirty days is deleted. One line goes into
`output/backup_db.log` saying what happened.

It uses SQLite's own online backup rather than copying the file, for a reason
worth knowing. The database runs in WAL mode, so the newest writes may still be
sitting in a separate `trading.sqlite-wal` file rather than in the database
itself. A plain `cp` would quietly miss them, and a `cp` taken while the loop was
mid write would produce a file that looks fine and is actually torn. The backup
command takes a consistent snapshot of a database that is being written to at
the time, then the script opens the copy and checks it before deleting anything
old.

Nothing inside the database is ever pruned. A month of five books is a few
hundred thousand rows at most, which is a few tens of megabytes, and the whole
point of keeping every tick and every skipped name is being able to ask a
question in November that nobody thought of in September.

**Neither of the two new launchd jobs is loaded**, exactly like every other job
in this project. They are definitions sitting in the repo at
`config/launchd/templates/sheet_sync.plist.tmpl` and
`config/launchd/templates/backup_db.plist.tmpl`, waiting for somebody to load
them by hand. Each file says at the top how. Until then, run both by hand.

## Moving it to the Mac Mini

One file. Copy `data/trading.sqlite` across, or more simply copy the newest file
out of `data/backups/`, which is already a clean snapshot and does not need the
old machine to be idle.

If the old machine has never traded, do not copy anything. Run
`scripts/migrate_db.py` on the new one and you get an empty database with the
right shape.

Do not copy `trading.sqlite-wal` or `trading.sqlite-shm` on their own, and do
not copy `trading.sqlite` while the loop is running. A backup file has neither
problem, which is the reason to prefer it.

The rest of the move is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/MIGRATION.md`.

## What the Google Sheet still owns

The sync rewrites the Trades, Daily, Rules Log, Books and Config tabs from the
database, clearing and rewriting only the columns the agent owns. It never
touches a formula. That is not politeness: a blank sent to Trades column U
deletes that row's slippage formula for good, and the loss shows up as an empty
cell rather than an error, so it could run for a fortnight before anybody
noticed.

Two things on that sheet do not come from the database, and should not.

**The Summary tab** is entirely formulas over Daily and Trades. Total return,
alpha, max drawdown, win rate, Sharpe. The sync writes nothing to it and says so
in its output, because a tab silently skipped is a tab nobody checks.

**The Config tab** holds settings, not results. Starting equity, position cap,
daily loss cap, universe and cadence live in `config/guardrails.yaml` and
`config/books.yaml`, which is where they are edited and where the code reads
them. The sync reads them from there. Putting them in the database would mean
two copies of the same number and one of them going stale.

To see what the sync would do without it doing anything:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/sync_sheet.py --dry-run
```

That prints every row and reads the live sheet to check the column headings
still line up. If a column has been inserted by hand, it stops and says which
one, rather than shifting every value one cell to the left. Add `--write` when
you mean it.
