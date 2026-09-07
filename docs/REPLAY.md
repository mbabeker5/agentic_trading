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

## The six pieces

| File | What it does |
|---|---|
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/fetch_history.py` | Pulls past bars out of IB Gateway, read only |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/record_day.py` | Records one live trading day as it happens, read only |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/fake_broker.py` | Replays what those two recorded, and fills orders against it |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/stub_decider.py` | Stands in for `agent/decide.py`, so no model is called and the gate is free |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/harness.py` | Steps the real loop through a whole day against the fake broker, and reports |
| `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/scenarios.py` | The twelve things the gate proves, one `Scenario` each |

Shared plumbing lives in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/common.py`.
The gate has its own tests at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_replay_gate.py`.

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

The list of rule ids is not written down here any more, because it moved three
times on 2026-09-06 alone: twenty at breakfast, twenty two after commit
`e653508`, twenty seven by the afternoon. `GUARDRAIL_RULE_IDS` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/scenarios.py`
holds the current list, and
`test_the_gate_covers_every_rule_id_the_guardrails_can_emit` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_replay_gate.py`
reads the `decision.add(...)` calls straight out of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py`
and goes red when the two disagree. A rule the gate does not know about is a
rule the gate would otherwise report as covered.

**A rule the loop can only reach with help is worth less than one it reaches on
its own, and one it cannot reach at all is worth nothing.** The gate sorts every
rule into those three piles and says which is which.

Reached on its own means the loop's own order flow got there during the day.
Reached by a probe means the gate pushed a crafted order at it through
`agent/loop.py`'s own `consider()`, with the real guardrails, the real book
state and the real ledger writing. Some of those are backstops behind a door the
loop keeps shut, which is fine: it will not build an entry outside the entry
window, it will not build one while the stop file is there, and it sizes every
entry through `max_shares_for` so it cannot ask for more than the caps allow.

The third pile is the one to read. The list below was seven rules when it was
written; `symbol_exclusive` left it when the hub stopped it refusing anything,
and it is back in `GUARDRAIL_RULE_IDS` now that `universe.symbol_exclusive` in
`config/guardrails.yaml` decides whether it refuses or reports. Six others read
a fact somebody has to go and get, and until the evening of 2026-09-06 nothing
went and got any of them, so every one of the six sat at the value that means
all clear. They are filled now, and this is what fills each one:

| Rule | Reads | Filled by |
|---|---|---|
| `halted` | `OrderIntent.halted`, `OrderIntent.limit_state` | `tradeable_now()`, off IBKR's tick type 49 and the limit-up limit-down band |
| `weekly_loss_cap` | `AccountState.week_pnl` | `loss_history()`, out of the book's own earlier state files |
| `monthly_loss_cap` | `AccountState.month_pnl` | `loss_history()`, the same way |
| `losing_streak_pause` | `AccountState.consecutive_losing_days` | `loss_history()`, the same way |
| `sector_cap` | `OrderIntent.sector`, `AccountState.sector_exposure` | `sector_for()` off the shortlist row, and `sector_exposure_for()` across the book |
| `account_symbol_cap` | `AccountState.symbol_exposure_all_books`, `account_equity` | `read_account_wide()`, reading all five book files once a tick |

Every one of those is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`, and
`test_the_facts_behind_the_rules_are_still_gathered` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_replay_gate.py`
reads that file for each of them rather than trusting this table, so a line here
that stops being true goes red instead of going unnoticed.

A probe still reaches five of the six, and that is a much smaller complaint than
the one it replaced. The loop gathers the fact; the recorded day simply did not
produce the condition. A book that is not four percent down this week cannot
trip the weekly cap however well wired it is. What it used to mean was that what
looked like twenty seven guardrails was twenty one, and that one of the six was
worse than dormant: `sector_cap` refuses any entry whose industry it was not
told, so with nothing setting `OrderIntent.sector` it refused every entry every
momentum book worked out. The clean day scenario reports any rule that refused
ten or more orders as a stopped machine rather than a guardrail doing its job,
which is how that turned up.

### Which scenario is which

Each numbered requirement above is one scenario in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/scenarios.py`,
named by a key you can hand to `--scenario`.

| Key | Bars | What it covers |
|---|---|---|
| `clean_day` | recorded | Requirements 1 to 3: the day runs, everything reaches the ledger, the books and the broker agree |
| `clean_day_no_fill_bridge` | recorded | The same day with the harness fill bridge off, which measures what the loop can do on its own |
| `every_guardrail` | recorded | Every rule id blocks an order and is written down |
| `daily_loss_cap` | crafted | Requirement 4 |
| `flatten_at_close` | crafted | Requirement 5, both halves: a position open at 15:50, and a book with nothing to sell |
| `phantom_position` | crafted | Requirement 6, in both its shapes: a mismatch with a book's name on it, and an orphan with nobody's |
| `kill_switch` | crafted | Requirement 7, running the real `agent/kill_switch.py` against the fake broker |
| `day_trade_counter` | crafted | Requirement 8 |
| `gateway_down` | crafted | Requirement 9 |
| `competing_session_delayed_data` | crafted | Requirements 10 and 11 |
| `rejected_order` | recorded | Requirement 12 |
| `two_books_one_symbol` | crafted | Two books in one ticker, told apart by the order reference, and their positions adding up to the broker's netted line. Sharing a name has been allowed since 2026-09-06 |

Where the table says crafted, the bars were written by hand because a recorded
session will not fall through a stop, hold a position to 15:50 or put two books
in one name on request. Those scenarios prove the loop's arithmetic and its
decisions. They prove nothing about the market. The scenarios marked recorded
run on the real five minute bars of a real session.

## Running the gate

```bash
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading

# The whole thing. Twelve scenarios, about twenty seconds, no network at all.
./venv312/bin/python -m agent.replay.harness --all

# What it would run, and what each one proves.
./venv312/bin/python -m agent.replay.harness --list

# One scenario, repeatable, when you are chasing a single failure.
./venv312/bin/python -m agent.replay.harness --scenario kill_switch

# Skip the three slow ones, which is what the tests do.
./venv312/bin/python -m agent.replay.harness --all --fast

# A different recorded session.
./venv312/bin/python -m agent.replay.harness --all --day 2026-09-03

# The gate's own tests: the safety locks plus the nine fast scenarios, 15 seconds.
./venv312/bin/python -m pytest -q tests/test_replay_gate.py
```

It writes two things. A plain language summary to the terminal, one block per
scenario with its evidence and its failures written as sentences. And a JSON
report at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/replay_gate_YYYY-MM-DD.json`
holding the same thing plus the per book end of day state, the rule ids that
fired, the alerts that were captured, the day trade counts and the number of
ledger rows. **The exit code is 0 only when every scenario passed.** Anything
else is a 1, and a 1 means no book is promoted.

Each scenario builds its own project root under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/replay_sandbox/<scenario>/`
and everything the loop writes goes in there: the book state files, the decision
packets, the day trade counters, the guard files, the tick log. Nothing a gate
run does touches the real `output/` folder except the report at the end. The
sandboxes are left behind on purpose, because the first thing you want after a
failure is the state file and the packet the loop was looking at.

### Why the gate can open the live order path and still be safe

The gate does two things that would be alarming anywhere else. It writes `full`
into the mode of every book in its sandbox copy of the register, with
`promoted_on` and `rules_commit` stamped so the register will load. And it sets
`AGENTIC_TRADING_LIVE_ORDERS=yes` in its own process for the length of the run.

Both are on purpose. Those are two of `agent/loop.py`'s four locks on the live
order path, and a gate that left them shut would be exercising the dry run
branch and proving nothing about the branch that will actually send orders in
October.

What makes it safe is not a lock at all but an object: the broker on the other
end is a `FakeBroker`, and a `FakeBroker` cannot reach IB Gateway. That is
checked rather than assumed, twice, before a single tick runs and again inside
the adapter, and a run handed anything else stops dead with a message saying so. `agent/broker.py`'s `McpBroker` is replaced for the length of the run
with a class whose constructor raises, so nothing the loop imports can quietly
build a real one. The environment variable is put back in a `finally` block. The
MCP order tools are never imported. And the sandbox holds no `agent/` folder and
no `venv312`, so `run_helper()` cannot shell out to the scanner or a sweep,
which are the only two things in a tick that would otherwise reach IBKR or the
SEC.

`tests/test_replay_gate.py` tests each of those rather than trusting them.

## What a pass means, and what it does not

A passing scenario means one thing: on this recorded day, with these bars, the
loop did what the strategy documents say it must, and the evidence is written
out underneath it in words you can check.

What it does not mean is that the strategy works, or that the numbers in it are
right, or that tomorrow will go the same way. Read the next section before
treating a green run as permission for anything.

**Evidence is not decoration.** Every scenario prints the specific fact it
checked, not "ok". If a line reads `daily_loss_cap was logged against book A`
you can go and find that row. A scenario with no evidence line for the thing it
claims to prove has not proved it.

**A failure is a finding, not a broken test.** All twelve scenarios pass as of
the evening of 2026-09-06, and the way they got there is the point. Five of them
were failing that morning, every one on something real: the loop had no
`cancel_order` call at the flatten, no `alert()` call anywhere, no way to tell a
Gateway that is down from an account that is empty, no reading of the market data
type off a quote, and no path from a broker fill back into a book file. Each of
those was a bug in `agent/loop.py`, found here rather than on a Tuesday, and
each was fixed rather than worked around in the scenario. A scenario that goes
red again is a regression, and its failure lines say what changed and where, in
full sentences.

**The gate marks its own weak spots.** Where a scenario runs on bars written by
hand rather than recorded, it says so. Where a rule was only reached by pushing a
crafted order at it, the report separates that from the rules the loop reached
on its own. Where the harness stood in for something the loop cannot do, the
report says which and the clean day is run a second time with that stand in
switched off so the gap is on the record.

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

**What the harness stands in for.** `agent/loop.py` records a fill in one place
only, from what `place_order()` hands straight back. There is no code in it that
reads `executions()` or turns a resting order into a position later. Against a
live market a marketable order comes back already filled, so that mostly works.
Against a limit order that fills at 10:20 it does not, and the position exists
at the broker while the book file has never heard of it. The harness carries a
fill bridge that reads the broker's own executions after every tick and applies
them with the loop's own `record_fill()`, and it tells the day trade counter
about them too, because the loop only does that for an order that came back
filled. **Every scenario downstream of a fill is running on that bridge.** The
`clean_day_no_fill_bridge` scenario runs the same day with it switched off, so
the size of the gap is measured rather than argued about. If that scenario ever
reports the gap has closed, delete the bridge.

**A bracket's children are not one cancels the other here.** IBKR hangs the stop
and the target off the parent's id, activates them when the parent fills, and
pulls one when the other fills. `agent/replay/fake_broker.py` says plainly that
it does none of that: both children are live from the moment they are placed and
neither cancels the other. That is harder than the real thing rather than
easier, which is the right direction, but it means an entry limit resting well
below the market has a target child that will sell stock the book does not own.
Read any short position that appears in a gate run against that before believing
it.

**A resting stop is outside every rule the loop enforces.** Since the bracket
work landed, a position's stop sits at the broker, which is the point of it. It
also means the stop fires without asking anything. The day trade scenario shows
book C's fourth round trip refused by `pdt_limit` and then happening anyway,
because the stop was already resting. Any rule that works by refusing the loop's
own closing order is weaker than it reads.

**Nothing stops the loop sending the same order twice.** Found by running the
gate rather than by reading the code. A book short a name whose price rises all
day gets a fade exit on every manage tick, and every tick sends a fresh limit
order to cover. Nothing in `agent/loop.py` reads `open_orders()` before sending,
and nothing cancels, so seventy two identical orders for the whole position were
resting at the broker by the close. On a paper replay that is a curiosity. In a
live account it is the position committed once for every five minutes of the
day, and all of it filling together on the first dip. The `_stacked_orders`
check in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/scenarios.py`
watches for it now, but only in the scenarios that call it.

**Nothing here proves the scanner works.** The gate builds its shortlist out of
the recorded bars, ranked by the size of the move and what traded, because the
real scanner talks to IBKR's scanner service and a replay cannot. That is the
scanner's idea in miniature, not a copy of it. A green gate says the loop does
something sensible with a shortlist. It says nothing at all about whether the
shortlist would have held those names.

## The promotion checklist

Nothing here is automatic. Promotion is Mo editing
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`
by hand, one book at a time. This is the list to work down before making that
edit, and every line of it is a thing to check rather than a thing to assume.

**Before the gate**

1. `./venv312/bin/python -m pytest -q` passes on the whole repository.
2. The recording being replayed is real and usable: open its `manifest.json` and
   check the sessions are complete, the gaps list is empty, and the quotes have
   real bids and asks in them rather than the nulls a shut market returns.
3. `git status` is clean, so the hash the gate reports is the hash that ran.

**The gate**

4. `./venv312/bin/python -m agent.replay.harness --all` exits 0. Not "mostly
   passed". Zero.
5. Read the summary rather than the exit code. Every scenario's evidence lines
   say what was actually checked, and a scenario that passed with nothing
   underneath it has proved nothing.
6. Check that every rule id turns up in the report's `rule_ids_fired` list. A
   guardrail that did not fire has not been tested, it has only not been
   reached.
7. Check how many rule ids were reached by the loop's own order flow rather than
   by a probe, and be honest about the difference.
8. Run it again on a second recorded session, `--day`, and read the differences.
   One day is one day.
9. Run one full scenario with `partial_fill_probability` turned on, because
   partial fills are the normal case in a real account and they are off by
   default here.

**Beyond the gate, which the gate cannot tell you**

10. The strategy numbers in the book's `strategy.yaml` are approved, not
    provisional. Every one of them still says `status: provisional` today.
11. The hub has approved this specific book, and the date and the rules hash go
    into `promoted_on` and `rules_commit` at the same moment the mode changes.
    A book set to `tiny` or `full` without both refuses to load, which is the
    last mechanical check between a typo and a live order.
12. The book goes to `tiny` first, never straight to `full`. `tiny` risks
    `money.tiny_capital_usd`, which is 2,000 dollars.
13. One book at a time. Watch it for a week before the next one.
14. The kill switch has been pulled by hand, for real, against the paper
    account, and the account was empty afterwards. Rehearsing it in a replay is
    not the same as knowing the button works on the day.
15. Alerts reach a human. `agent/loop.py` raises them now (a halt, a cap, an
    orphan, a competing session, delayed data), rate limited so one problem is
    one message rather than eighty. What is not proved is delivery: the gate
    captures alerts instead of sending them, so send one to yourself by hand and
    check it arrives before a book sends a real order.

## The interface the loop codes against

`FakeBroker` is a drop in for the read half of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py`,
plus the order half that file deliberately leaves out.

It also satisfies the `Broker` protocol in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py`,
checked with `isinstance` and by comparing every method signature one at a time.
The only differences are additive: `portfolio`, `open_orders` and `executions`
take one extra optional `order_ref`. So the loop can be handed a `FakeBroker`
wherever it expects an `McpBroker` and needs no other change, and
`account_values`, `bars_5m_today` and `session_vwap` from that module all work
against it unaltered.

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

# The gate itself. See "Running the gate" above for the rest.
./venv312/bin/python -m agent.replay.harness --all
./venv312/bin/python -m pytest -q tests/test_replay_gate.py
```
