# The trading loop, across all five books

One run of `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py` is one tick. A tick is not one book, it is all five: A, B, C, D and E, in the order they appear in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`.

There is no `while` loop anywhere in it, and that is on purpose. launchd wakes the script, it looks at the clock, does the one thing that belongs to that minute for each book, writes down what it saw, and exits. Everything a book has to carry from one tick to the next lives in a file on disk. So a tick that crashes, or a Mac that was asleep, costs one tick and not the day.

Nothing is ordered today. Not on paper, not through a preview, not through the broker's own dry-run flag. Every order the loop works out is printed as `DRY RUN BOOK_A would place ...`, written to the ledger as a decision, and that is where it stops. The four locks that keep it that way are near the bottom of this page.

---

## The files

| What | Where |
|---|---|
| The loop | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py` |
| The one door to a broker | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py` |
| What each book remembers | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/book_state.py` |
| The register of books | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml` |
| The limits every book starts from | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml` |
| Each book's own numbers | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/<folder>/strategy.yaml` |
| The wrapper launchd calls | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh` |
| The launchd job | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist` |
| The tests | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_loop_books.py` |

The project folder is read from the environment variable `AGENTIC_TRADING_ROOT`, and falls back to `/Users/mtalib/workspace_repos/personal_repo/agentic_trading` when that is not set. Nothing has to be configured for the normal case.

---

## The five books, and what each one does when

Five books share one IBKR paper account, `DUT077572`. What tells them apart is the tag on every order: book A tags its orders `BOOK_A`, book C tags its `BOOK_C`, and so on. That tag is the only thing that says which book owns a position, which is why the reconciliation check below matters so much.

| Book | Strategy | Model | Clock | Sold at the close |
|---|---|---|---|---|
| A | Opening momentum | Claude Fable | every 5 minutes | yes, 15:55 |
| B | Opening momentum | none, rules only | every 5 minutes | yes, 15:55 |
| C | Insider buying | Claude Fable | every 30 minutes | no, holds for weeks |
| D | Congress trades | Claude Fable | every 30 minutes | no, holds for weeks |
| E | Opening momentum | GPT-6 Astra | every 5 minutes | yes, 15:55 |

All times are New York time, and every one of them is read from the book's own `strategy.yaml` rather than written into the code. Change a time in that file and the loop changes.

### The three momentum books, A, B and E

```
09:25            the first tick, five minutes early, checks the plumbing is up
09:30 to 09:35   the scanner runs and writes the shortlist
09:35            the pick: the model, or the rules alone for book B
09:35 to 11:00   entries may be opened
09:35 to 15:55   positions are watched every five minutes
15:55            everything still open is sold
16:00 onwards    the day is written up
```

The three of them share one scanner run. Whichever ticks first pays for it, and the other two read the file it wrote, because running the scanner three times in one minute would spend three times the data budget on three copies of the same answer.

### The insider book, C

```
07:00            sweep SEC Form 4 filings
09:45            the pick
09:45 to 15:50   positions are watched every thirty minutes, entries allowed
16:30            sweep again, for tomorrow morning
```

Nothing is sold at the close. Its positions live for days to weeks and most of them will still be open when the month ends, which is expected.

### The Congress book, D

```
07:30            sweep the House and Senate disclosures
09:45            the pick
09:45 to 15:50   positions are watched every thirty minutes, entries allowed
```

Also never sold at the close.

A book on a thirty minute clock works out whether it is due from when it last looked, not from the minute hand. So a tick missed because the Mac was asleep does not push the whole day out of step.

---

## What happens inside one tick

1. The guard files are read first. If `output/LOOP_DISABLED` exists the loop prints one line and exits, having touched nothing.
2. The rules hash is taken with `git rev-parse --short HEAD`, once, at the top. Every log line and every ledger row carries it, so a month later a decision can be read against the exact limits it was made under.
3. The account is read once, not once per book. Five books asking IB Gateway the same three questions in the same second is how a data pacing violation happens.
4. Reconciliation runs before anything else. See below.
5. Each book takes its turn, in register order: work out the phase, do that one thing, save its file. A book that falls over is caught, written down, and the other four still get their tick.
6. At the close, each book writes its own end of day line to the Rules Log, and one account level line goes to the Daily tab.

Everything a book decides is written twice: into its own state file, and to the Rules Log tab of the ledger, tagged with the book id, the model, what the model cost and the rules hash. A decision to do nothing is still a decision and still gets a written reason. That is the strategy's own rule, not a preference: a decision with no reason cannot be reviewed at the end of the month.

---

## Reconciliation, and why a mismatch halts a book

Five books share one account. IBKR reports the account netted together, so it can tell you the account holds 400 shares of AAPL and it cannot tell you which book owns which hundred. Only the book files can, and only because the order that opened each position carried a tag.

So before anything else, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reconcile.py` compares what the five books believe against what the broker actually has. If they disagree, nobody knows who owns what, and sizing the next order would be guesswork. A mismatch halts the book it belongs to, and only that book.

A halted book:

- opens nothing for the rest of the day, and
- may still close positions, because refusing to close is its own kind of risk.

If `agent/reconcile.py` cannot be imported at all, every book is halted for that tick and the line `reconciliation unavailable, halting all books` goes in the log. That is deliberate: a missing referee means the answer is no.

### Positions nobody claims

The paper account holds one share of SPY from the manual test on 2026-09-02, and there is a working order id 4 with no tag on it from the same session. Neither belongs to a book, so neither halts one, but both are reported on every tick. To stop that noise once someone has looked at them, write `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/expected_orphans.json` as either

```json
["SPY"]
```

which forgives any quantity of that symbol, or

```json
{"SPY": 1}
```

which forgives exactly one share and complains again if the number changes. That file does not exist today, on purpose: the orphan is real and somebody should deal with it rather than silence it.

---

## The day trade counter

A day trade is buying and selling the same name on the same day. `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/pdt.py` counts them, one small file per book, and the loop asks it before every closing order.

Whether going over the line refuses the order or merely notes it is `pdt.hard_limit` in each book's own `strategy.yaml`:

- Books C and D set `hard_limit: true`. They are meant to hold for weeks, so a same day round trip in one of them is a mistake rather than a strategy. A fourth day trade in five business days is refused.
- Books A, B and E set `hard_limit: false`. Day trading is the whole strategy. A fourth day trade is allowed and written down, with a note saying it would have been blocked in a live account under 25,000 dollars. That way the cost of the rule is measured rather than guessed.

This is the only check in the project that can refuse an order which closes a position, and that is why it is narrow.

If `agent/pdt.py` cannot be imported, the loop still knows from the book file whether a position was opened today, so it still says whether something is a day trade. What it cannot know is how many came before it. In that case it writes the note and lets the order through, because refusing to close a position on the strength of a missing counter is the more dangerous mistake.

---

## The three files that stop it

All three live in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`.

| File | What it does | How to set it | How to clear it |
|---|---|---|---|
| `LOOP_DISABLED` | Nothing runs at all. `run_tick.sh` exits before it even checks the Gateway, and the loop exits before it reads a book. | `agent/kill_switch.sh` | `agent/reenable.sh`, or `rm output/LOOP_DISABLED` |
| `STOP` | Positions may be closed. Nothing may be opened, in any book. | `touch output/STOP` | `rm output/STOP` |
| `NO_TRADE_TODAY` | No book opens anything today. Exits still work. Written by the pre-flight check when something is wrong. | written automatically, or `touch output/NO_TRADE_TODAY` | `rm output/NO_TRADE_TODAY` |

`STOP` and `NO_TRADE_TODAY` do the same thing from the loop's point of view and are kept separate because they mean different things: `STOP` is a person deciding to stop, `NO_TRADE_TODAY` is the machine finding something wrong before the open. Both are also handed to the guardrails as the kill switch, so even an order that somehow got past the loop would be refused a second time.

---

## The four locks on the live path

The code that sends an order exists, in `submit()` in `agent/loop.py` and in `McpBroker.place_order` in `agent/broker.py`. It is shut behind four locks, and all four have to be open at once:

1. The book's mode in `config/books.yaml` is `tiny` or `full`. All five say `dry_run`.
2. The environment variable `AGENTIC_TRADING_LIVE_ORDERS` is set to `yes`. It is not set, and `run_tick.sh` unsets it before every tick.
3. The account id starts with `DU`, which is how IBKR names paper accounts.
4. None of `output/STOP`, `output/LOOP_DISABLED` or `output/NO_TRADE_TODAY` exist.

Every one of these is tested on its own in `tests/test_loop_books.py`, because a safety net tested only as a whole tells you nothing about which strand is holding.

Behind all four there is one more: `McpBroker`'s three order methods check `AGENTIC_TRADING_LIVE_ORDERS` themselves and refuse loudly. That is a second lock on the same door, not a replacement for the first.

---

## Promotion: how a book earns the right to send an order

Promotion is never automatic. No code anywhere moves a book from `dry_run` to `tiny`, or from `tiny` to `full`. Nothing watches a book's results and decides it has earned it.

A promotion is Mo editing `config/books.yaml` by hand, one book at a time, after the hub has approved that book. Two fields get stamped on the book at the same moment as the mode changes:

- `promoted_on`, the date the hub approved it
- `rules_commit`, the git hash of the rules it was approved against

A book set to `tiny` or `full` without both of them filled in refuses to load, so a mode change on its own cannot quietly start sending orders.

The three modes:

- `dry_run` works the order out, writes it down, and stops. Sizing still uses the book's full `capital_usd`, because a rehearsal that sizes differently from the real thing is not a rehearsal.
- `tiny` sends real orders in the paper account, sized against `tiny_capital_usd`, which is 2,000 dollars. A bug is cheap.
- `full` sends real orders in the paper account against the book's whole capital.

---

## Running it by hand

Everything below is safe. None of it can send an order.

```bash
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading

# one tick, all five books, right now
venv312/bin/python agent/loop.py

# one book only
venv312/bin/python agent/loop.py --book C

# pretend it is a particular minute, to see a phase after hours
venv312/bin/python agent/loop.py --now "2026-09-08 09:36"

# one book at a pretend time
venv312/bin/python agent/loop.py --book D --now "2026-09-08 09:46"

# write the decisions to the real Google Sheet instead of printing them
venv312/bin/python agent/loop.py --write-ledger
```

`--now` takes `"2026-09-08 09:36"`, or just `"09:36"` for today. The market being shut does not stop it: the shortlists come back empty and the loop says so, which is the right answer rather than a failure.

To run the whole thing the way launchd does, with the Gateway and MCP server checks in front of it:

```bash
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh
tail -f /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/tick_$(date +%Y-%m-%d).log
```

The tests:

```bash
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading
venv312/bin/python -m pytest -q
```

---

## What a tick leaves behind

All in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`.

| File | What it is |
|---|---|
| `state_BOOK_A_2026-09-08.json` | one book's memory for one day: positions, working orders, the shortlist, the picks, how many names it opened, what it realised, whether it is halted and why, and every decision it made with the reason |
| `packet_BOOK_A_2026-09-08_0936_pick.json` | exactly what was known at the moment of a decision, written before the decision is made, so a pick can be reviewed rather than guessed at |
| `shortlist_2026-09-08.json` | the momentum scanner's shortlist, shared by A, B and E |
| `insider_shortlist_2026-09-08.json` | book C's sweep |
| `congress_shortlist_2026-09-08.json` | book D's sweep |
| `loop.log` | one line per book per tick, with the rules hash on every one |
| `pdt_BOOK_A.json` | one book's rolling day trade count |

Delete a book's state file and that book starts its day over. Do not do that while it is holding something: the file is the only record of which book owns which position.

State carries over between days. The insider and Congress books hold for weeks, so what a day ended holding is what the next day starts with, stops and all. Without that, every morning those two books would think they were flat and their stops would vanish.

---

## Where the stop lives, and why it goes to the broker

Every position is opened with two numbers on it: a stop and, usually, a target. They are set at the moment of the fill by `record_fill` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`, taken from the trigger record the pick wrote, and re-measured against the price actually paid rather than the price that was planned.

The model proposes both numbers and does not get the final say on either:

- **The stop is clamped.** `guardrails.stop_price_for` works out the rule stop, 1.5 percent from entry or the opening range level when that is nearer. The model's stop is used only when it sits inside that, so a model may move a stop closer to entry and can never move one further away. For a long the nearer stop is the higher of the two, for a short the lower.
- **A stop on the wrong side of entry throws the pick away.** A long stopping out above where it bought would close the instant it opened. That is not a widening, it is nonsense, so the pick is refused with a `decision_rejected` row naming the two prices.
- **A target on the wrong side is dropped, not fatal.** The position still has a stop, so it is still safe. It runs to the trailing stop, the time stop or the close instead, and the drop is written down.

That covers the file. The other half is the account.

### The stop rests at the broker

An entry does not go out as one order. It goes out as a bracket: a limit parent, a stop child on the other side, and a limit target child when the pick has a usable target. All three carry the book's `orderRef`, so a child order can be traced back to the book that owns it exactly like its parent.

The reason is simple. If the stop existed only in this Mac's memory, then a Mac that sleeps, a crashed tick or a dropped network connection would leave a live position with nothing protecting it, and nobody would know until the next tick woke up. A stop resting at IBKR works whether or not this code is running.

`McpBroker.bracket_order` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py` calls the server's `ibkr_bracket_order` tool. That tool does not take three order dictionaries. It takes the entry's action, quantity and limit price plus a `takeProfitPrice` and a `stopLossPrice`, and builds the three IBKR orders itself with both children hung off the parent's id. Anything that has to be on every leg goes in `orderOptions`, which the server copies onto all three, and that is where `orderRef` and `account` go. Its `takeProfitPrice` is not optional, so a pick whose target was dropped takes a second path instead: the parent, then the stop, as two ordinary orders. The stop still rests at the broker. What is lost is the one-cancels-the-other link between the two children, and with no target there is nothing for the stop to be cancelled against.

### Moving a stop

There is no "edit this order" on this path, so tightening a stop is two steps: cancel the resting child, then place a new one for the same shares at the new price under the same tag. Cancel first and place second, deliberately. A moment with no stop is bad; a moment with two stops would be worse, because both could fill and the book would end up short a position it never opened. If the cancel fails, no replacement is sent and the old stop stays live.

The child order ids are written into the book's state file as `working_orders` entries marked `is_child`, because an order that has to be cancelled later is an order whose id has to survive the tick that placed it.

Today this is all rehearsal. A dry run prints the three legs it would have sent, one line each, under the order it would have placed:

```
DRY RUN BOOK_A would place BUY 1000 ABC limit 9.38 (purpose: entry)
    leg: entry  BUY 1000 ABC limit 9.38 (purpose: entry) tagged BOOK_A
    leg: stop   SELL 1000 ABC stop 9.24 tagged BOOK_A
    leg: target SELL 1000 ABC limit 9.66 tagged BOOK_A
```

### When the model does not give a usable answer

Two rows to know in the Rules Log, because they mean opposite things:

| Row | What happened | What the book did |
|---|---|---|
| `model_unavailable` | No usable reply arrived: the provider was down, refused the connection, or took longer than the 60 second budget. Each call gets a 45 second timeout and no retries. | The book's own rules answered instead. Written down so a rules answer is never counted later as a model answer. |
| `decision_rejected` | A reply did arrive and could not be trusted: not JSON, the wrong shape, a pick with an unknown side, a missing confidence, or a confidence outside 0 to 1. | Nothing. That row, or that whole reply, is thrown away and no rules answer stands in for it, because standing in would quietly turn a broken model into a working book. |

A single bad row inside a reply that otherwise parsed only costs that row. A reply that cannot be read at all costs the whole tick, and the book opens nothing until the next one.

---

## The pluggable broker

The loop never talks to IBKR directly. It is handed a `Broker` and calls methods on it. `agent/broker.py` defines the protocol: six read methods (`account_summary`, `portfolio`, `open_orders`, `executions`, `snapshot`, `historical_bars`) and four that act (`place_order`, `bracket_order`, `cancel_order`, `global_cancel`).

That single change is what lets the same loop run three ways without knowing which:

- `McpBroker`, the real thing, talking to IB Gateway through the local MCP server.
- `FakeBroker` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/fake_broker.py`, which feeds the loop a recorded day so a month can be replayed in a minute. `agent/broker.py` deliberately does not import it: the protocol is the contract between them, and an import would tie the live path to the test path.
- a twenty line test double in `tests/test_loop_books.py`, whose three order methods raise, so a loop that ever tried to send something in a test fails loudly rather than passing quietly.

One thing about the real broker is worth knowing. `docs/MCP_SERVER.md` records a bug seen for real on 2026-09-02: a market order that fills straight away comes back from `ibkr_place_order` with `isError=true`, because the server's own reply fails its own validation on the way out. The order filled. The error is about the reply, not the trade. So `McpBroker.place_order` never trusts what the order call said. Whatever comes back, success or failure, it re-reads executions and open orders afterwards and reports what the broker actually holds.

---

## Known gaps, written down rather than left to be discovered

### The broker will not say whether a name can be borrowed

Checked against the live MCP server on 2026-09-06: the snapshot it returns holds `conId`, `symbol`, `secType`, `exchange`, `currency`, `bid`, `ask`, `last`, `close`, `marketPrice` and the option greeks, and nothing at all about borrowing. `ibkr_get_contract_details` has nothing either. The momentum books set `require_shortable`, so every short is refused today, with the four reasons written out in the log. That is the designed answer and not a gap being papered over. `broker.borrow_terms()` already reads the three field names IBKR uses for those ticks elsewhere, so the day the server passes them through, shorts start working with no other change.

### The Daily tab has no book column

It tracks the one paper account all five books share, so a day is a day and not a day per book. Each book's own end of day figures go to the Rules Log, which does have a book column and which the Books tab slices on. The one account level line is written once, after every book has had its turn.

### Holidays are known to the day trade counter and to nothing else

`schedule.holidays` in `config/guardrails.yaml` is read by `agent/pdt.py` to work out what a business day is. The order checks in `agent/guardrails.py` still know about weekends only. The loop will happily decide it is a trading day on Thanksgiving; the shortlist will be empty and nothing will happen, but the log will say `manage` rather than `closed`.
