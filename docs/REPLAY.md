# The replay harness

## Why it exists

Five books are about to start trading. Every one of them is on `dry_run` today,
which means it works out the order it would have sent and writes it down. Moving
a book to `tiny` or `full`, where it actually sends orders to the paper account,
is a hand edit to
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`
that Mo makes one book at a time.

The question this harness answers is what has to be true before Mo makes that
edit.

The honest answer is not "the strategy made money". A month is far too short to
know that, and `docs/STRATEGY.md` already says so. The answer is that the machine
works: that the loop runs a whole day without a person touching it, that every
guardrail fires when it should, and that nothing surprising happens when the
plumbing breaks. None of that can be tested against the live market, because the
live market will not kill your Gateway at 11:07 on a Tuesday just because you
asked it to.

So the harness replays a recorded day instead. Real bars, real quotes, real
scanner output, and a pretend broker that fills orders and can be told to break
in five specific ways. The loop cannot tell the difference, because the fake
broker offers exactly the same read methods as
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py`.

## The three pieces

| File | What it does |
|---|---|
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/fetch_history.py` | Pulls past bars out of IB Gateway, read only |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/record_day.py` | Records one live trading day as it happens, read only |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/fake_broker.py` | Replays what those two recorded, and fills orders against it |

Shared plumbing lives in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/common.py`.

The first two connect to IB Gateway with `readonly=True` and call nothing but
quotes and historical bars. There is no order code in either file. That is not a
gap waiting to be filled: the whole point of a replay harness is that the loop
can be exercised end to end without a live order existing anywhere.

## What gets recorded

### The past, from `fetch_history.py`

For each symbol, three kinds of bar:

- **Five minute bars** for the last 10 trading days, regular hours only. These
  are what orders fill against.
- **One minute bars covering 09:30 to 09:40** of each of those days, so the
  opening range the strategy trades off is a real one rather than something
  inferred from a five minute bar.
- **Daily bars for 40 sessions**, which is where the 20 million dollar average
  daily dollar volume floor in `docs/STRATEGY.md` gets checked.

One JSONL file per symbol under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/history/`,
plus a `manifest.json` listing every symbol, every session asked for, the bar
counts, and every gap with a plain reason next to it. `output/` is gitignored, so
recordings never reach git.

IB Gateway rations historical data requests at roughly sixty in any ten minute
window, counted across every client on the connection. Go over and it starts
refusing requests for everyone, and the refusals outlast the window. Both scripts
share one pacer in `common.py` that keeps a timestamp for every request it
granted and waits out the sliding window rather than sleeping a fixed amount
between calls. At the defaults each symbol costs twelve requests, so the full
universe is a job that takes a while, not one that runs in a minute.

### One live day, from `record_day.py`

Every five minutes from 09:25 to 16:05 Eastern:

- A **snapshot** for SPY, QQQ and every symbol on that day's shortlist: bid, ask,
  last, volume, and which market data type Gateway actually served. The type
  matters and is recorded rather than assumed, because the paper account's data
  entitlement is not something the code gets to decide. As of 2026-09-06 the
  account is refused live data outright (errors 10168 and 10089) and everything
  comes back delayed, so the recorder asks for live, takes what it is given, and
  writes down which it got.
- The **latest five minute bar** for each of those symbols.
- At 09:35 and 09:40 only, the **scanner's own JSON output**, produced by running
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`
  as a separate process. Separate on purpose: the scanner talks to IBKR's scanner
  service and can hang, and it should not be able to take the recorder with it.

One JSONL file per kind of data under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/YYYY-MM-DD/`,
plus a manifest rewritten after every tick. The manifest is the file a person
reads to decide whether a recording is usable: which slots ran, which were
missed, how late each one was, how many times the Gateway connection had to be
rebuilt, and which market data types turned up during the day.

**Mind the data ration.** At the default cap of 25 symbols the recorder asks for
25 historical bars every five minutes, which is 50 in any rolling ten minutes
against Gateway's ceiling of about 60. That is very little slack for the whole
machine. Finish any history fetch before 09:25, or run the day with
`--max-symbols 15`. Nothing crashes if the budget runs out, the pacer just
inserts waits, ticks run long, and long ticks make the next slot late.

A recorded day is not fragile. A tick that throws gets written down and the run
carries on. A Gateway restart is reconnected to with backoff. A `SIGTERM` from
launchd writes a final manifest and exits cleanly. And because every tick under
launchd is its own process, the recorder reads `ticks.jsonl` back at startup and
rebuilds the day's totals from it, so the manifest describes the whole day rather
than whichever tick happened to write it last. That also means the recorder can
be killed at noon and restarted without losing the morning.

The launchd template is at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.recorder.plist`.
**It is not loaded.** It wakes the recorder with `--once` every five minutes
rather than letting the script run its own six and a half hour loop, for the same
reason the trading loop works that way: a script that loops all day is one crash
away from losing the rest of the day, and a Mac that sleeps at noon wakes up with
a loop that still thinks it is 11:55. One wake up per tick means a tick that dies
costs one tick.

### Three things the first runs taught us, all of which bite

**The account only gets delayed data.** Asking Gateway for live quotes on
2026-09-06 was refused with errors 10168 and 10089. Everything the recorder gets
is market data type 3. That means `delayed_data` is not only a fault to inject,
it is the normal state of this account today, and any scenario that assumes live
prices is testing something the real loop will not have. If Mo ever adds the
10 dollar a month snapshot bundle mentioned in `docs/STRATEGY.md`, this changes
and the harness should be re-run.

**With the market shut, there is no bid and no ask.** IBKR returned -1 for both
on the Sunday test run, which is its way of saying there is no book, and the
recorder writes that as null. `last` and the previous `close` came back fine. A
recording with no spread in it cannot tell the fake broker what a market order
should pay, so the broker falls back to the flat 0.02 half spread. **Check the
Tuesday recording for real bid and ask before trusting any slippage number that
comes out of it.** The manifest says so in plain words when the quotes came back
empty.

**The delayed feed's volume field is garbage.** Delayed SPY reported
34,054,225,730,979 shares traded, and QQQ about the same, while price, high, low
and previous close were all sensible. The recorder now writes any volume above a
hundred billion shares as null and keeps the original in `volume_raw`. Volume in
`bars_5m.jsonl` is correct (SPY traded 2,239,384 shares on the 15:55 bar), so
anything that needs a real volume number should read the bars and not the
snapshot. Worth rechecking on Tuesday with the market open.

### Two IBKR quirks that were silently producing wrong data

Both were found while building this, both are fixed, and both are the kind of
thing that would have gone unnoticed for weeks.

**`endDateTime` has two spellings and mixing them fails.** IBKR takes
`YYYYMMDD HH:MM:SS US/Eastern` with a space and a named zone, or
`YYYYMMDD-HH:MM:SS` with a hyphen in UTC and no zone at all. A hyphen with a time
zone after it is rejected with error 10314 and no useful explanation. The first
history fetch lost every one of its twenty opening range requests to this.

**IBKR counts a duration in trading time, not clock time.** A 900 second window
ending at 09:40 does not stop at the opening bell. It walks back 900 seconds of
*trading*, straight over the overnight gap, and hands back the previous
afternoon's last five minutes along with this morning's ten. Verified against
Gateway on 2026-09-06. Left alone, yesterday's close would have been filed as
today's opening range and the fake broker would have taken entry triggers from
the wrong session. The same arithmetic applies to `40 D` of daily bars: it means
forty sessions, not forty days on a calendar, and reading it as calendar time
returns thirty bars when the strategy's liquidity test asked for forty.

**A bar recorded at a tick is not necessarily from that tick.** Before the bell,
Gateway hands back the previous session's last bar, because that is genuinely the
latest one there is. Every bar keeps its own timestamp, so the replay places it
correctly in time, but anything comparing a bar to "now" has to check the bar's
own time rather than the tick it arrived on.

## How fills are modelled

Copied from what IBKR's paper simulator actually does. Every rule below is
covered by a test in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_replay_fake_broker.py`
with the arithmetic written out by hand.

**Market order.** Fills at the next bar's open, plus half the recorded bid to ask
spread if a quote was recorded near that moment, and 0.02 if none was. Buying
pays up and selling gets hit, so the adjustment always costs money.

**Limit buy.** Fills when that bar's low reaches the limit or better. The fill is
at the limit, unless the bar opened below the limit already, in which case it
fills at the open, which is better than asked for.

**Limit sell.** The mirror image. Fills when the bar's high reaches the limit, at
the limit, or at the open when the open was already above it.

**Stop.** Triggers on the bar that trades through the stop, then fills on the
**next** bar exactly like a market order. So a stop always costs at least one bar
of slippage. That is the honest version: a stop is a market order the moment it
fires.

**Quantities.** Whole shares only. An order for a fraction of a share is refused.

**Commission.** IBKR Pro fixed tier: half a cent a share, never less than a
dollar an order, never more than one percent of what the order was worth. The
ceiling beats the floor when they disagree, which is what happens on a small
order in a cheap stock. Twenty shares of a two dollar stock is forty dollars of
stock, so the most it can cost is forty cents even though the floor says a
dollar.

**Every fill carries its `order_ref`.** An order with no `order_ref` is refused
outright, because a fill nobody can trace back to a book cannot be reconciled.

Two knobs are off by default and exist to make life harder on purpose:
`slippage_bps` adds a fixed cost to every market fill, and
`partial_fill_probability` makes orders fill in pieces so the loop has to cope
with a half filled position.

## Where this is wrong on purpose, and where it is just wrong

The fill model is copied from IBKR's simulator, and IBKR's simulator is not the
market. Four differences matter enough to name.

**The simulator is optimistic on limit orders.** It fills a limit buy the moment
the printed low touches the limit. In the real market, price trading at your
limit does not mean you were filled at it. You are behind everyone who was
already resting there, and on a fast move the size at that price can be gone
before your order arrives. A backtest that assumes every touched limit filled
will show entries the real account never got, and those missed entries are not
randomly distributed: the ones you miss are disproportionately the good ones,
because price moved away from your limit fast for a reason. `docs/STRATEGY.md`
already flags this for the month one results, and it applies with full force
here.

**The real market gaps through stops.** A stop here triggers on the bar that
trades through it and fills at the next bar's open, which is a fair model of a
normal day. It is not a model of a bad one. When a stock halts on news and
reopens 8 percent lower, the stop does not fill near the stop, it fills wherever
the reopening auction lands. A 1.5 percent stop is a 1.5 percent loss in this
harness and can be a 9 percent loss in real life. The harness will never show you
that, so do not read a clean drawdown number here as evidence the stop works.

**Borrow may not exist.** Shorting in this harness always works, because a
recorded bar has no opinion about whether the shares could be borrowed. In the
real account, the three easy to borrow tests in `docs/STRATEGY.md` have to pass
at the moment of entry, and on exactly the small hard moving names this strategy
finds, they often will not. Every short the harness fills is a short the real
account might simply have been refused.

**Partial fills are the normal case, not the exception.** Here they are off by
default and, when turned on, are a coin flip with a fixed fraction. In real life
a thousand share order in a thin name comes back in pieces at several prices over
several seconds, and the loop has to handle holding 340 shares of something it
thinks it holds 1,000 of. Turn `partial_fill_probability` on for at least one
full scenario run before promoting anything.

One smaller difference worth knowing. Nothing fills at the moment `place_order`
is called here. Fills happen when `advance_to` produces the next bar. On the real
paper account a market order sent into a live market comes back already filled,
and the MCP server has a bug where an instant fill is reported as an error even
though it filled (see the known gaps section of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/MCP_SERVER.md`).
The harness cannot reproduce that, so the rule stands regardless: confirm every
order against `executions()` and `open_orders()`, never against what the order
call said.

## What the harness must pass before any book is promoted

All of these against a recorded day, with the fake broker, with no person
touching the keyboard during the run. A book that has not passed every one of
them stays on `dry_run`.

### The day runs at all

1. A full recorded day, 09:25 to 16:05, runs end to end with no manual restart.
2. Every fill and every decision, including every "do nothing", reaches the
   ledger with a reason attached.
3. What the loop believes it holds matches what the broker reports, at every
   tick, all day. No phantom positions and none missing.

### Every guardrail refuses something

Each rule id in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py`
needs a scenario where it blocks an order, and the block has to show up in the
ledger with that rule id on it. A guardrail that never fires during the whole
harness has not been tested, it has just not been reached.

`paper_only`, `wrong_account`, `wrong_book`, `kill_switch`, `sec_type`,
`currency`, `blacklist`, `whitelist`, `no_shorts`, `short_price_floor`,
`shortable_required`, `entry_window`, `outside_market_hours`, `flatten_time`,
`daily_loss_cap`, `max_order_notional`, `max_position_pct`,
`max_open_positions`, `gross_exposure_cap`, `entries_per_day`.

### The named scenarios

4. **Daily loss cap trips.** Drive a book into a 2 percent loss on the day. New
   trades must halt, open positions must close, and `daily_loss_cap` must appear
   in the ledger. Then check the obvious failure mode: the halt must not block
   the closing orders themselves.
5. **The 3:55 flatten happens.** Every momentum book is flat by 15:55 with market
   orders. Check it with positions still open at 15:50, and check it again when a
   position is already flat, because a flatten that sends an order for zero shares
   is a bug.
6. **Reconciliation halts the day on a phantom position.** Inject
   `phantom_position` mid morning. The loop must notice that the account holds
   something no book claims, halt, and alert. It must not carry on trading around
   it and it must not try to close it, because a position nobody understands is
   not one to act on blind.
7. **The kill switch bites.** Create the stop file at
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/STOP`
   mid day. No new entries, no new resting stop orders, and closing an existing
   position still allowed. That asymmetry is deliberate and is the thing to check.
8. **The day trade counter counts.** Books C and D are held to three day trades
   per five business days. Drive book C to four round trips and confirm the fourth
   is refused. Confirm the momentum books are not blocked but that every trade the
   pattern day trader rule would have blocked is logged, so the live money cost of
   the rule is measured rather than guessed.
9. **Gateway goes down mid day.** Inject `gateway_down` at 11:00 and clear it at
   11:20. The loop must survive four dead ticks, must not conclude it holds
   nothing just because it cannot read the account, must not double up on orders
   when the connection comes back, and must reconcile before it trades again.
10. **A competing session appears.** Inject `competing_session`, which raises with
    IBKR code 10197. This is what happens when someone logs into TWS on another
    machine with the same login. The loop must halt and alert rather than trade on
    stale numbers.
11. **Data goes delayed.** Inject `delayed_data` so every snapshot reports market
    data type 3. The loop must notice the data is delayed and either refuse to
    open new positions or record loudly that it opened them on delayed prices.
    Quietly trading on delayed quotes is the failure.
12. **An order comes back rejected.** Inject `reject_next_order`. The loop must
    not treat a rejection as a fill, and must not retry it in a loop.

## What replay cannot catch

This is the section to read before trusting a green run.

**Fill quality.** Covered above, and it is the big one. Every limit fill in this
harness is a fill the real account might not have got, and the ones it misses are
the good ones. Treat any return number the harness produces as an upper bound
with an unknown gap beneath it, not as an estimate.

**Anything that depends on being first.** The strategy buys a break above the
opening range high on rising volume. Whether that fill is available depends on
where you are in a queue that a five minute bar cannot see. A bar tells you the
price traded there. It does not tell you there was size left when your order
arrived.

**Real latency.** Here, a tick's work happens instantly between two bars. In real
life the scanner takes time, the model takes time, Gateway takes time, and the
price the decision was made on is not the price the order arrives at. The harness
cannot show you what that costs.

**Bad data that looks like good data.** A recording is a recording. If Gateway
served a stale quote or a bad print on Tuesday, that stale quote is now baked into
every replay of Tuesday, and it will be replayed identically forever. Consistency
is not correctness.

**One day is one day.** A single recorded Tuesday has one market regime in it.
Everything the harness proves is conditional on that day. It says nothing about
how the loop behaves on a gap down open, a Fed afternoon, a half day, an expiry,
or a day when one of the shortlist names halts.

**Halts, auctions and the open itself.** Regular hours five minute bars quietly
skip the messiest moments. A halt appears as a gap between bars, not as an event
the loop has to handle. The opening auction is a single print the harness treats
like any other.

**Corporate actions.** A split, a dividend or a symbol change in a recorded name
will not be adjusted for and will look like a price move.

**Anything about real money.** The paper account is exempt from the pattern day
trader rule and this harness is exempt from everything. Borrow costs nothing,
short availability is infinite, margin is never called, and no order is ever
refused by a real exchange. Month one on paper says the machine works. It does
not say the strategy survives contact with a real account, and passing the
harness does not either.

**Its own bugs.** The harness is code, and it was written by the same kind of
process that wrote the loop. If the fake broker's arithmetic is wrong, every
scenario it passes is worthless. That is why every fill rule has a test with the
price worked out by hand rather than by running the code and pasting the answer.

## The interface the loop codes against

`FakeBroker` is a drop in for the read half of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py`,
plus the order half that file deliberately leaves out.

Reads, identical in name and shape to the real client:

```python
account_summary(account=None) -> dict          # {"account", "items": [{"tag","value"}], "notes"}
account_values(account=None) -> dict[str, str] # the same thing as {tag: value}
portfolio(account=None, include_pnl=True, order_ref=None) -> dict
open_orders(account=None, include_all=True, order_ref=None) -> dict
executions(account=None, symbol=None, sec_type=None, exchange=None,
           side=None, time=None, order_ref=None) -> dict
snapshot(contracts: list[dict], market_data_type: int = 3) -> dict
historical_bars(contract, duration, bar_size, what="TRADES",
                use_rth=True, end_date_time="") -> dict
bars_5m_today(contract) -> list[dict]
is_up() -> bool
```

`order_ref` is the one addition, and it is optional everywhere. Leave it off and
you get the netted account, which is all IBKR would ever show you. Pass it and
you get one book's own view, which is the half IBKR cannot give us and the whole
reason this class keeps five sets of books.

Orders:

```python
place_order(contract: dict, order: dict, order_ref: str) -> dict
cancel_order(order_id: int) -> dict
global_cancel() -> dict
```

`contract` and `order` are IBKR's own plain dictionaries, exactly as
`docs/MCP_SERVER.md` describes them:

```python
contract = {"symbol": "SPY", "secType": "STK", "exchange": "SMART", "currency": "USD"}
order    = {"action": "BUY", "totalQuantity": 100, "orderType": "LMT",
            "lmtPrice": 700.0, "tif": "DAY"}
```

`orderType` is `MKT`, `LMT` or `STP`. A stop takes `auxPrice`. `order_ref` is
required and an empty one raises.

The clock and the harness controls:

```python
advance_to(timestamp) -> dict   # steps through recorded bars, fills what fills
inject_fault(kind, **options) -> dict
clear_fault(kind) -> None
clear_faults() -> None
active_faults() -> list[str]
reconcile() -> dict             # {"ok": bool, "differences": [...]}
book_summary(order_ref) -> dict
book_positions(order_ref) -> dict[str, BookPosition]
day_trade_count(order_ref, within_days=5, as_of=None) -> int
state() -> dict                 # everything at a glance, for the run log
```

`advance_to` takes a datetime or an ISO string and returns
`{"from", "to", "bars_processed", "fills": [...]}`. It only moves forward. Asking
it to go backwards raises, because a replay that can rewind can see the future by
accident, and then every number it produces is worthless.

The five fault kinds:

| Kind | What breaks |
|---|---|
| `gateway_down` | Every broker call raises `ConnectionError` until cleared. `advance_to` is deliberately exempt, because the market does not stop while your Gateway is down and the harness has to model exactly that. |
| `delayed_data` | Every snapshot reports market data type 3. |
| `competing_session` | Every snapshot raises `FakeBrokerError` carrying IBKR's code 10197. |
| `phantom_position` | A position appears that no book placed an order for, so `reconcile()` fails. Takes `symbol`, `quantity`, `avg_cost`. |
| `reject_next_order` | The next `place_order` comes back with `rejected=True` and error code 201, then the fault clears itself. |

An unknown fault kind raises rather than doing nothing, because a harness that
quietly fails to inject a fault reports a pass that never happened.

Building one:

```python
from agent.replay.fake_broker import FakeBroker

broker = FakeBroker.from_recording("2026-09-08")        # one recorded day
broker = FakeBroker.from_history(["SPY", "QQQ"])        # the fetched past
broker = FakeBroker(bars={"SPY": [...]}, quotes={...})  # bars written by hand, for tests
```

Useful keyword arguments: `starting_cash`, `book_capital` (a dict of order_ref to
starting cash), `slippage_bps`, `partial_fill_probability`, `default_half_spread`
and `seed`. The random draw for partial fills is seeded, so two runs of the same
scenario produce the same fills.

## Running it

```bash
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading

# Fetch the past for a few names. Read only, no orders, ever.
./venv312/bin/python agent/replay/fetch_history.py --symbols SPY,QQQ

# One recorder tick, for testing, at any time of day. --date keeps a test
# tick out of a real recording's folder.
./venv312/bin/python agent/replay/record_day.py --once --symbols SPY,QQQ --date 2026-09-06

# The real thing on the day, if you would rather watch it than use launchd.
# Add --max-symbols 15 if anything else is using Gateway's data ration.
./venv312/bin/python agent/replay/record_day.py

# The fake broker's own tests
./venv312/bin/python -m pytest -q tests/test_replay_fake_broker.py
```
