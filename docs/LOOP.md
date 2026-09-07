# The trading loop, across all five books

One run of `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py` is one tick. A tick is not one book, it is all five: A, B, C, D and E, in the order they appear in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`.

There is no `while` loop anywhere in it, and that is on purpose. launchd wakes the script, it looks at the clock, does the one thing that belongs to that minute for each book, writes down what it saw, and exits. Everything a book has to carry from one tick to the next lives in a file on disk. So a tick that crashes, or a Mac that was asleep, costs one tick and not the day. The wrapper may call the loop several times in a row when a book has asked to be looked at sooner, which is the cadence section below, but each of those calls is still one whole tick that starts and finishes on its own.

Nothing is ordered today. Not on paper, not through a preview, not through the broker's own dry-run flag. Every order the loop works out is printed as `DRY RUN BOOK_A would place ...`, written to the ledger as a decision, and that is where it stops. The four locks that keep it that way are near the bottom of this page.

---

## The files

| What | Where |
|---|---|
| The loop | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py` |
| The one door to a broker | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py` |
| What each book remembers | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/book_state.py` |
| The pre-open run, from 09:00 | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py` |
| The register of books | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml` |
| The limits every book starts from | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml` |
| Each book's own numbers | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/<folder>/strategy.yaml` |
| The wrapper launchd calls | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh` |
| The launchd job | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist` |
| The tests | `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_loop_books.py` |

The project folder comes from `AGENTIC_TRADING_ROOT` when that is set, and otherwise `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/paths.py` works it out from where it sits on disk, which means a plain `git clone` anywhere on any Mac finds itself. Nothing has to be configured for the normal case, and there is no path to one particular Mac written into the code any more.

---

## The five books, and what each one does when

Five books share one IBKR paper account, `DUT077572`. What tells them apart is the tag on every order: book A tags its orders `BOOK_A`, book C tags its `BOOK_C`, and so on. That tag is the only thing that says which book owns a position, which is why the reconciliation check below matters so much.

| Book | Strategy | Model | Clock | Sold at the close |
|---|---|---|---|---|
| A | Opening momentum | Claude Fable | 30 seconds when busy, 5 minutes when not | yes, from 15:45 |
| B | Opening momentum | none, rules only | 30 seconds when busy, 5 minutes when not | yes, from 15:45 |
| C | Insider buying | Claude Fable | every 30 minutes | no, holds for weeks |
| D | Congress trades | Claude Fable | every 30 minutes | no, holds for weeks |
| E | Opening momentum | GPT-6 Astra | 30 seconds when busy, 5 minutes when not | yes, from 15:45 |

All times are New York time, and every one of them is read from the book's own `strategy.yaml` rather than written into the code. Change a time in that file and the loop changes. The momentum clock changed on 2026-09-06 with Momentum v2 and now depends on what the book is doing rather than on the minute hand, which is the next section but one.

### The three momentum books, A, B and E

```
09:00            the pre-open run starts: the gap scan and the paced history pulls
09:30 to 09:35   the opening range builds
09:35            the pick: the model, or the rules alone for book B
09:35 to 10:15   entries may be opened
09:35 to 15:45   positions are watched
15:45            flattening begins, with limit orders at the bid or the ask
15:55            anything still open goes out at market, as the backstop
16:00 onwards    the day is written up
```

Two of those times moved on 2026-09-06. Entries used to run to 11:00 and now stop at 10:15 (item D3), because an entry after 10:15 chases a move that has already been made. And the close used to be one market order at 15:55; it is now two stages, 15:45 with limit orders and 15:55 at market only if something is still open (item A11), because spreads widen and depth thins in the last few minutes and a market order into that pays for the hurry.

The three of them share one scanner run. Whichever ticks first pays for it, and the other two read the file it wrote, because running the scanner three times in one minute would spend three times the data budget on three copies of the same answer.

### Before the open

From 09:00 the momentum books have work to do before the market is even open. `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py` runs the pre-market gap scan every few minutes, keeps a candidate list of up to 100 names, and pulls each new name's history at no more than four requests a minute: the 14 days of five minute bars the relative volume baseline needs, and the daily bars the 14 day average true range needs. The pacing is the point. IBKR allows only about 60 historical requests in any 10 minutes, so spending that budget between 09:00 and 09:26 means it is not being spent in the five minutes around the open when it is scarcest. It is written one tick at a time like everything else here, with `step(now, broker)` looking at the clock and at what is already on disk and doing only what that minute owes. The whole timeline, every step's time budget, what happens to a name that gaps late, and the honest limits of what has actually been built are in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/PREOPEN_FLOW.md`.

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

### How often the loop wakes up, and who decides

Since Momentum v2 the cadence is a number the books work out, not a number in the launchd job (item A14). A momentum book asks to be looked at every 30 seconds between 09:35 and 11:00 while it is holding a position or has a working order, and every 5 minutes the rest of the time. The insider and Congress books have no fast window at all, so they always ask for their own five or thirty minutes. The reason for the fast window is the stop: a stop this tight needs sub-minute resolution, even with the stop itself resting at the broker.

Each book's answer comes from `gr.next_tick_seconds` at the end of its turn, and at the end of the tick the loop writes the smallest number any book asked for into `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/next_tick_seconds`. The file holds one plain whole number of seconds and nothing else, and it is rewritten every tick. The smallest wins because the loop ticks all five books together, so the busiest one sets the pace for everybody.

That file exists because launchd cannot be argued with. It wakes the script on a fixed timetable and there is no way to tell it, at 09:41, to come back in thirty seconds. So the wrapper honours the file instead: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh` reads it after a tick and, when it says less than a minute, runs a short sub-loop inside itself, ticking at that pace until the next launchd wake up is due, and then exits. The 30 second cadence therefore costs no change at all to the launchd job. Both halves are built. The loop writes the file at the end of every tick, and the wrapper reads it, sleeps that long and ticks again, at most nine extra times and never past the next launchd wake up. It checks `output/LOOP_DISABLED` every time round, so pulling the handle does not have to wait out a five minute run, and it only ever enters that sub-loop after a tick that finished cleanly, because a loop that fell over should be looked at rather than run nine more times.

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

The paper account holds one share of SPY from the manual test on 2026-09-02, and there is a working order id 4 with no tag on it from the same session. Neither belongs to a book.

**Neither halts one, and that is a decision rather than a gap.** Halting on an orphan would mean halting all five books on every tick of every day for the rest of the month over a share nobody is managing and nobody is at risk from, and a safety rule that fires every five minutes forever is not a safety rule. What the loop does instead is write a line into the record every tick, so a reader can see it was noticed rather than missed, and tell Mo once per name per day. An orphan named in `output/expected_orphans.json` gets the line and no alert, because somebody has already looked at that one and said so.

This is also why the loop reads `books_agree` rather than reconciliation's own `ok`. The unclaimed SPY share makes `ok` false on every tick of every day and will keep doing so. Reading that as "the books are wrong" would mean no reconciliation halt could ever be lifted, because the condition for lifting one would never be true again.

To stop the alert once someone has looked at them, write `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/expected_orphans.json` as either

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
| `next_tick_seconds` | one whole number of seconds: how soon the busiest book wants looking at again. Rewritten every tick, and read by `agent/run_tick.sh` |

Delete a book's state file and that book starts its day over. Do not do that while it is holding something: the file is the only record of which book owns which position.

State carries over between days. The insider and Congress books hold for weeks, so what a day ended holding is what the next day starts with, stops and all. Without that, every morning those two books would think they were flat and their stops would vanish.

---

## Where the stop lives, and why it goes to the broker

A momentum position is opened with one number on it, and only one: a stop. There is no target at all, and there has not been since Momentum v2 landed on 2026-09-06 (item A2). A position leaves by its stop or at the close, and by nothing else, because two independent studies found that putting a target on this strategy destroys its edge: the handful of trades that run a long way are what pay for all the small losses, and a target cuts exactly those off. The insider and Congress books, C and D, still take targets, and their strategy files still say `use_profit_target: true`.

The stop is set at the moment of the fill by `record_fill` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`, taken from the trigger record the pick wrote, and re-measured against the price actually paid rather than the price that was planned.

The model proposes a stop and does not get the final say on it:

- **The stop is clamped.** `guardrails.stop_price_for` works out the rule stop. On a momentum book that is 10 percent of the name's 14 day average true range away from entry, and then, because it may never sit inside the opening range, it is pushed out to the range low for a long or the range high for a short whenever it would otherwise land inside (item A1). The model's stop is used only when it sits inside that, so a model may move a stop closer to entry and can never move one further away. For a long the nearer stop is the higher of the two, for a short the lower. That clamp is unchanged.
- **1.5 percent is now only a fallback.** It used to be the momentum stop. Today it stands in only for a position whose average true range nobody could work out, which should not happen for a name that passed the volatility filter, and it exists so a position carried in from an older state file still gets a stop rather than none. The insider and Congress books never had an average true range stop, so for them the percentage stop, 8 percent in C and 10 percent in D, is still the real one.
- **A stop on the wrong side of entry throws the pick away.** A long stopping out above where it bought would close the instant it opened. That is not a widening, it is nonsense, so the pick is refused with a `decision_rejected` row naming the two prices.
- **A target on the wrong side is dropped, not fatal.** This one only reaches books C and D now, since the momentum books propose no target to be wrong about. The position still has a stop, so it is still safe. It runs to the trailing stop, the time stop or the close instead, and the drop is written down.

That covers the file. The other half is the account.

### The stop rests at the broker

An entry does not go out as one order. On a momentum book it goes out as two: a limit parent, and a stop child on the other side. That is the whole thing, because there is no target to hang a third leg on. Books C and D, which do take targets, get the full bracket of three. Every leg carries the book's `orderRef`, so a child order can be traced back to the book that owns it exactly like its parent.

The reason is simple. If the stop existed only in this Mac's memory, then a Mac that sleeps, a crashed tick or a dropped network connection would leave a live position with nothing protecting it, and nobody would know until the next tick woke up. A stop resting at IBKR works whether or not this code is running.

`McpBroker.bracket_order` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/broker.py` deliberately does not use the server's own `ibkr_bracket_order` tool any more. That tool takes the entry's action, quantity and limit price plus a `takeProfitPrice` and a `stopLossPrice`, and its `takeProfitPrice` is not optional, checked by reading the pinned server's source on 2026-09-06. A momentum entry has no take profit price to hand it, so the tool cannot be used at all.

Instead the bracket is built here out of the server's plain order tool, which is what IBKR does underneath anyway. The parent limit goes out first with transmit switched off, so it rests inside Gateway and cannot reach the market on its own. Then the stop child goes out carrying the parent's order id and transmit switched on, and that is what releases the two together. Both carry the same one-cancels-the-other group, so a fill on either cancels the other, and both carry the book's `orderRef` and the account. An entry that reached the market with nothing protecting it is the exact hole this path exists to close. The stop child is a stop-limit rather than a plain stop, with half a percent of room below the trigger for a long and above it for a short, because a plain stop turns into a market order the moment it is touched and in a thin gap down that fills wherever the book happens to be. A book that still takes a profit target, which is C and D, gets a third leg in the same group.

### Moving a stop

There is no "edit this order" on this path, so tightening a stop is two steps: cancel the resting child, then place a new one for the same shares at the new price under the same tag. Cancel first and place second, deliberately. A moment with no stop is bad; a moment with two stops would be worse, because both could fill and the book would end up short a position it never opened. If the cancel fails, no replacement is sent and the old stop stays live.

The child order ids are written into the book's state file as `working_orders` entries marked `is_child`, because an order that has to be cancelled later is an order whose id has to survive the tick that placed it.

Today this is all rehearsal. A dry run prints the legs it would have sent, one line each, under the order it would have placed. On a momentum book there are two of them and no more:

```
DRY RUN BOOK_A would place BUY 1000 ABC limit 9.38 (purpose: entry)
    leg: entry  BUY 1000 ABC limit 9.38 (purpose: entry) tagged BOOK_A
    leg: stop   SELL 1000 ABC stop 9.13 tagged BOOK_A
```

It is worth walking that example through, because every number in it came from a rule. ABC has a 14 day average true range of 1.60 dollars, so the stop starts 16 cents from the 9.38 entry, at 9.22. But 9.22 is inside the opening range, whose low is 9.13, so the stop is pushed out to 9.13. The distance is now 25 cents. The book risks 0.25 percent of its 100,000 dollars, which is 250 dollars, and 250 divided by 0.25 is 1,000 shares. Those 1,000 shares are worth 9,380 dollars, which is inside the 10 percent notional cap of 10,000, so the size stands. Had it not been, the order would have been cut to fit the cap and the trade would have risked less than 250 dollars. Being under the risk budget is fine. Being over it is not.

### The VWAP fade closes nothing in month one

The VWAP fade is the rule that says the opening push is over: two five minute closes in a row back through the day's volume-weighted average price. It used to close the position. Since 2026-09-06 it closes nothing at all (item D2).

Both halves of it end up in the same place. The rule fade, and a fade the model called by answering `fade`, both come back as the trigger `fade_observed`, both get written into the Rules Log under the rule id `vwap_fade_observed`, and in both cases the position is held. The loop says so on the tick, in as many words: a fade would have closed this, and in month one it only gets written down.

The reason is that the fade comes from a different published strategy and was never tested on this one, so grafting it on as an exit would have been a guess. Month one measures the pick, and records what every fade would have cost or saved, which is a month of evidence rather than an opinion.

An `exit` from the model still closes the position. That is a different answer from `fade`. It means the model wants out now, rather than noticing that the push has gone, and the manage prompt tells the model exactly that, including a line asking it not to reach for `exit` to force a fade through.

One line puts the old behaviour back: `risk.vwap_fade_action` in a book's `strategy.yaml`. It reads `log_only` today. Set it to `exit` and the fade closes positions again, for the rule and for the model together.

### When the model does not give a usable answer

Two rows to know in the Rules Log, because they mean opposite things:

| Row | What happened | What the book did |
|---|---|---|
| `model_unavailable` | No usable reply arrived: the provider was down, refused the connection, or took longer than the 60 second budget. Each call gets a 45 second timeout and no retries. | The book's own rules answered instead. Written down so a rules answer is never counted later as a model answer. |
| `decision_rejected` | A reply did arrive and could not be trusted: not JSON, the wrong shape, a pick with an unknown side, a missing confidence, or a confidence outside 0 to 1. | Nothing. That row, or that whole reply, is thrown away and no rules answer stands in for it, because standing in would quietly turn a broken model into a working book. |

A single bad row inside a reply that otherwise parsed only costs that row. A reply that cannot be read at all costs the whole tick, and the book opens nothing until the next one.

Two footnotes on that table, both worth knowing before anybody counts these rows at month end. `decision_rejected` is also the row written when a pick's stop comes back on the wrong side of entry, which is nothing to do with a model and can happen on book B, which never calls one. And there is a third id next to these two, `decision_failed`, for the case where the decision fell over before a model was ever reached, such as a prompt that would not render. The loop chooses between them on the spot: if there are rejected rows it is `decision_rejected`, otherwise it is `decision_failed`.

### The other rows Momentum v2 added to the Rules Log

Eight more rows a reader will meet from 2026-09-06. None of them is an error, and the first three are there to be counted at the end of the month rather than acted on during it.

| Row | What it means |
|---|---|
| `entries_cutoff` | An entry the 10:15 cutoff turned away, with the name and the time. Every one of them is written down, so at the end of the month the cutoff can be measured rather than argued about: if the names it refused all went on to run, the cutoff cost money and should move back. |
| `vwap_fade_observed` | A fade that would have closed a position under the old rule. The position was held. See the section above. |
| `same_direction_count` | How many of this book's positions point the same way, and across how many industries, written every tick that the book is holding anything. Ten morning gappers all long is one bet made ten times, and the ledger should say so. Nothing is blocked by it (item A9). |
| `weekly_loss_cap` | The book is down 4 percent or more this calendar week, so it is paused for Mo to look at. Entries only. Closing orders still go through. |
| `monthly_loss_cap` | The same thing over a calendar month, at 6 percent. |
| `losing_streak_pause` | The book has finished down three trading days in a row. Same answer: paused, entries only, exits still allowed. |
| `sector_cap` | An entry that would have put more than a quarter of the book's gross exposure limit into one industry. It is also the row for an entry in a name IBKR would not give an industry for, because a limit that cannot be measured is not a limit, so an unknown industry is refused rather than assumed harmless. |
| `account_symbol_cap` | An entry that would leave more than 15 percent of what all five books are worth riding on a single ticker, counted across every book rather than inside one. |

The three loss limits are worked out by the loop rather than by the guardrails, because only the loop can see a book's earlier days. `loss_history` in `agent/loop.py` reads the book's own state files, adds up this calendar week and this calendar month, counts the run of losing days behind them, and hands all three over on the AccountState as `week_pnl`, `month_pnl` and `consecutive_losing_days`. The guardrails own the limits; the loop owns the arithmetic.

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

### The pre-open wakes every minute now, which it did not until 2026-09-06

`agent/preopen.py` is driven by the loop: 09:00 to 09:30 is a phase of its own, `preopen`, and books A, B and E share the one run exactly as they share the one scanner run. The launchd side was the missing half and is now done. The pacing rule is four historical requests a minute, and a tick is over in a second or two, so a tick can never send more than four. Twenty seven wake ups between 09:00 and 09:26 pay for about a hundred requests, which is what the morning needs. Five minute wake ups paid for about twenty, and most of the candidate list reached 09:35 with nothing behind it.

`every 1 minute from 09:00 to 09:26 on weekdays` is now a line in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/templates/tick.template`, so `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py` writes it into `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist`. The job went from 84 wake ups a day to 110, and from 420 entries to 550: the pre-open half hour adds 26 rather than 27 because 09:25 is already on the five minute grid and the generator drops the duplicate. `test_the_tick_job_wakes_every_minute_through_the_pre_open` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_paths.py` checks every one of those minutes is there on every weekday.

Nothing has been loaded. Writing the file is not the same as running it, and `scripts/gen_launchd.py --install` is still a separate, deliberate step.

### The quotes have to say how old they are, and this account's are delayed

The loop asks IB Gateway for LIVE quotes, market data type 1, and reads back which type it was actually served. Asking for delayed and being given delayed proves nothing; asking for live and being given delayed is the fact that matters. `agent/replay/record_day.py` already worked this way, and until 2026-09-06 the loop did not: nothing anywhere read `marketDataType` off a reply, so a fifteen minute old price and a live one were the same thing to it.

A book whose quotes are not live is halted, cause `market_data`, which means it opens nothing and may still close what it holds. Managing a position on a delayed price is fine. Deciding what to pay for a new one is not, because the whole strategy is a break of a range that happened in the last five minutes. The halt lifts itself the moment a live quote arrives.

**This account is served delayed data every day.** Live data was refused outright on 2026-09-06 with IBKR errors 10168 and 10089. So until the streaming quote subscription is bought, no book will open a position, and that is the honest answer rather than a gap: every book is on `dry_run` anyway, and a rule that quietly let entries through on a stale price would be worse than one that stops them. The alert about it is said once a day rather than every half hour, because it is the same fact all day.

### IBKR code 10197: somebody else has the market data line

10197 means another session is logged in with the same IBKR credentials and has taken the market data line, so this one gets no quotes at all. In plain words: Mo has a live quote screen or an app open somewhere. The loop used to catch it inside `snapshot_by_symbol()`, turn it into a note, and handle it exactly like a quote that did not arrive, so half an hour of no quotes passed without a word.

Now the code is kept, the book is halted for as long as it lasts, and the alert says what it means and what to do about it: close the TWS window or the mobile app and it clears itself on the next tick.

### Holidays are known to the day trade counter and to nothing else

`schedule.holidays` in `config/guardrails.yaml` is read by `agent/pdt.py` to work out what a business day is. The order checks in `agent/guardrails.py` still know about weekends only. The loop will happily decide it is a trading day on Thanksgiving; the shortlist will be empty and nothing will happen, but the log will say `manage` rather than `closed`.
