# Changelog: opening momentum, hybrid (books A and E)

This file records every change to this strategy's numbers: what changed, on what date, and the git commit that carried it. The reason it exists is the ledger. A decision written down in the ledger in October has to be readable against the exact rules it was made under, not against whatever the rules became by December. Without a dated commit beside each set of numbers, a good month and a changed stop loss are impossible to tell apart. The strategy file beside this one is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_hybrid/strategy.yaml` and the spec it implements is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`.

## The flatten gets out on the tick it cancels the stop, 2026-09-06 (late night)

Not a change to this strategy's numbers. Every number in `strategy.yaml` is
still exactly as Mo approved it in Momentum v2, and nothing in this entry moved
one.

Commit: 51da883 (moved from b04298a)

One of the two commits in this batch moves a limit, and it is the reason the
stamp moves. `main()` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
reads the account's working orders once for the whole tick and hands the same
list to all five books, so the duplicate check could not see a cancel made after
that read. The 15:45 flatten cancelled the resting stop, correctly and first,
and then had its own closing order refused, naming the very order it had just
pulled. **A rule that said no now says yes**, which is the mirror image of the
last entry's move and just as much what this stamp records. Nothing was ever
left open, because the position closed on the next look, five minutes later in
the replay gate and thirty seconds later in production. What it cost was a
flatten one tick slower than it reads, and on a fast close that is real.

The once a tick read stays exactly as it was, because five books each asking IB
Gateway the same question in the same second is how a data pacing violation
happens and the fifth book's call really did time out at 45 seconds. A cancel now
drops the order it pulled out of the list this tick already holds, from all three
places that cancel: the flatten, the stop move and the market backstop. The same
rule had been silently refusing that market backstop every time it fired, which
is the worse half of it: the backstop exists to get out at market when a
triggered stop-limit will not fill, and a position sitting behind a stop that
fired and did not fill is the worst state one of these books can be in.

The other commit in the batch leaves every limit answering as it did:

- `9f7c04b` closes backlog item 14 by writing the decision behind every order
  row, so a trade can be read back to the model, the cost and the reason that
  produced it. It changes what is recorded and not what any check answers.

Nothing has traded. All five books are still on `dry_run` and `promoted_on` is
still empty on every one of them, so this is still housekeeping rather than a
version.

## The flatten stops trusting a feed it cannot read, 2026-09-06 (night)

Not a change to this strategy's numbers. Every number in `strategy.yaml` is
still exactly as Mo approved it in Momentum v2, and nothing in this entry moved
one.

Commit: b04298a (moved from f840f0f)

One change in the batch moves a limit, and it is the reason the stamp moves.
`snapshot_by_symbol()` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
returned the prices and threw away everything the feed said about itself, so the
15:45 flatten handled a market data line taken by another session (IBKR code
10197) and a subscription lapsed to delayed data exactly like a quote that did
not arrive: no log line, no alert, no halt. It now passes the tick and the book
in, so the feed's verdict reaches the one place that writes a data problem down,
tells Mo and halts the book. **A rule that said yes from 15:45 onwards can now
say no**, which is what this stamp exists to record. The halt stops the book
opening anything and leaves the closing path alone, because a stale price is
fine to get out on and is not fine to get in on.

The four other commits in the batch leave every limit answering as it did:

- `6fc3fd3` widens the launchd generator's template glob, names the three
  hand-made plists it cannot render instead of passing over them in silence, and
  rewrites `--check` to fail three ways. Not one byte of any generated plist
  changes, verified by generating from both versions and diffing.
- `9254702` adds a thirteenth replay scenario, `nothing_left_working`, and
  strengthens `day_trade_counter` to read each book's own counter file. Test
  code and a scenario.
- `c5c92a2` reverts an uncommitted change that would have made an unclaimed
  position halt every book, so the committed answer stands: tell somebody once a
  day, halt nobody. Net zero behaviour change, plus documentation and tests.
  Whether that answer is right is now backlog item 0b, for Mo.
- `5b57b6f` is the backlog and the journal.

Nothing has traded. All five books are still on `dry_run` and `promoted_on` is
still empty on every one of them, so this is still housekeeping rather than a
version.

## Loop and guardrail fixes from the replay gate, 2026-09-06

Not a change to this strategy's numbers. Every number in `strategy.yaml` is
exactly as Mo approved it in Momentum v2. What changed is the machinery those
numbers are enforced by, and the stamp has to follow it, because a decision
written in the ledger tonight was made under these fixes and not under the ones
of this morning.

Commit: f840f0f (moved from 03e5318)

The replay gate found all nine, before any book could trade:

- An unclaimed position at the broker tells somebody once a day and halts nobody
  (`58dfa67`).
- A halt can end, and its reason no longer grows without bound (`c482c91`).
- A Gateway that is not answering is no longer read as an account holding
  nothing, which had been halting every book for the rest of the day
  (`ecd34f8`).
- The loop reads how old its quotes are and refuses to open on a stale one, and
  IBKR code 10197 and a delayed feed are now visible to it (`6166471`).
- Cross-book symbol exclusivity defaults back to refusing, which is the review
  team's instruction, and Mo decides whether it stays that way (`055f289`).
- Fills come back off the broker's own executions and reach the book file
  exactly once, deduplicated on IBKR's execution id (`0590a0c`).
- The loop will not send an order it already has resting at the broker
  (`f840f0f`). The gate had found seventy two identical cover orders in one run.
- Nothing a book has resting survives the 15:45 flatten (`0a2edc5`).
- The loop raises alerts, once per problem rather than once per tick
  (`ec49be0`).

The stamp deliberately does not follow the three commits after `f840f0f`.
`158bc24` corrects the gate's own wording about which facts the loop gathers,
`41a0c51` wires two database writers and records how long a tick took, and
`d11323c` deletes a constant nothing read. None of them changes what an order
check says yes or no to, and the rule at the top of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`
excludes plumbing that leaves every limit answering as it did.

Nothing has traded. All five books are still on `dry_run` and `promoted_on` is
still empty on every one of them, so this is still housekeeping rather than a
version.

## Momentum v2, 2026-09-06

Approved by Mo from the consolidated critique at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md`

Commit: 03e5318

The numbers Mo approved landed in 273e928. The stamp names 03e5318 instead, because two commits after that one changed how the rules behave: `7937e78` wired the facts several guardrails were reading and nobody was filling, and `03e5318` retired the cross-book symbol exclusivity rule so it reports rather than refuses. A stamp naming a commit whose guardrails have since changed looks like an answer and is not one, so before the first trade the stamp follows any commit that changes guardrail behaviour. Nothing has traded: all five books are still on `dry_run`.

Stamped into `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml` as `rules_commit` for books A, B and E.

### Applied

- A1 Stop: now 10 percent of the 14 day average true range and never inside the opening range, so a long stops at or below the range low and a short at or above the range high (was 1.5 percent of price or the range low if closer). The 1.5 percent number survives only as a fallback for a position whose average true range is not known, and the yaml says so. A model may still only tighten a stop, never widen one.
- A2 Profit target: now none at all, a position leaves by its stop or at the close (was a target or a trailing rule set by the model). Two independent studies found targets destroy the edge.
- A3 Volatility filter: now the 14 day average true range has to be above 0.50 US dollars and above 1.5 percent of the price, both of them, or the name is not a candidate (was no filter at all).
- A4 Selection: now rank the candidates by relative volume measured on the 9:30 to 9:35 window against the same window over the prior 14 days, keep 2 times normal as the floor, and take the top of the ranking (was a 2 times threshold and then the model picking freely). The ranking, not the size of the gap, is what carried the published result.
- A5 Direction: now the sign of the first five minute candle, close above open is a long, close below open is a short, and a flat candle where open equals close is no trade at all (was the sign of the overnight gap).
- A6 Position size: now risk based, 0.25 percent of book equity risked per trade, shares equal that money divided by the distance from entry to stop, with a notional cap of 10 percent of book equity in any one name (was 15 percent of equity per name with no risk rule).
- A7 Daily loss cap: now 1 percent of book equity (was 2 percent). With 10 positions each risking 0.25 percent the natural worst case in a day is 2.5 percent, so any cap above that could never bind and was decoration. 1 percent binds after four full stop outs.
- A8 Loss limits beyond the day: now weekly 4 percent, monthly 6 percent, and a pause for Mo's review after three consecutive losing days, with any one of the three pausing the book (was nothing beyond the day).
- A9 Correlation: now a sector cap of 25 percent of a book's gross exposure limit in any one sector, an account level cap of 15 percent on any single symbol across all five books, and the count of positions pointing the same way at once logged every tick so a month of it can be read back (was no correlation rule at all). A name whose sector the broker could not tell us is refused rather than assumed harmless.
- A11 The close: now flattening begins at 3:45 PM with limit orders at the bid or the ask, and anything still open at 3:55 PM is closed at market as a backstop (was market orders at 3:55 PM).
- A12 Hard exclusions: now leveraged and inverse funds, SPACs, warrants, rights, preferred shares, anything traded over the counter, anything listed outside the US and anything with a pending trading halt are dropped before the model ever sees the name (was no exclusion list).
- A13 Headlines: now no headlines and no news anywhere in the momentum packet or the prompt until there is a feed that carries where a story came from (was a prompt that told the model to weigh headlines). Press release copy is prompt injection with a profit motive.
- A14 Polling: now every 30 seconds from 9:35 to 11:00 while a momentum book holds a position or has a working order, and every 5 minutes the rest of the time (was every 5 minutes all day).
- A15 Ledger: now records on every decision and every fill the decision price, the slippage, the average true range, the relative volume, the rank, the direction candle, the money risked on that trade, and the sector (was 18 fields without any of those).
- A16 Success gate: now pre-registered, with operations gated and returns reported but not gated, written out in full below (was "near flat after costs").
- D1 Breadth: now 10 positions at risk based size (was 5 positions at up to 15 percent each).
- D2 VWAP fade: now a logged observation only in month one, the code writes down every time it would have fired and closes nothing on it (was an exit the model could call). The number of closes that counts as a fade stays at 2.
- D3 Entry window: now new entries stop at 10:15 AM (was 11:00 AM), and every entry the cutoff blocks is logged so month one measures what the cutoff cost.
- D7 Finviz: now gone, the optional cross check and its code path were deleted rather than left switched off (was an optional Finviz Elite cross check at 39.50 US dollars a month).

### Deferred

- A10 Shorting: still switched off, and still **pending Mo's decision**. This is not a decided deferral. The short side of the strategy is described in the spec but does not trade, `allow_shorts` stays false, and a short is refused with rule id `no_shorts`. The reason it is open at all: the short sale restriction under Rule 201 triggers on a 10 percent fall and then forbids shorting at or below the bid for two days, and a gap down name on heavy volume is exactly that population, so a "break below the range low" short may not be fillable as designed. Everything the code needs for shorts already exists, so this is one line to flip once Mo decides.

### Rejected

- The 90 day listing rule. The critique proposed excluding any name listed less than 90 days ago. Mo dropped it. The history requirement does the same job honestly: a name needs 30 completed sessions for the liquidity average and 14 for the average true range, and anything too new to measure fails those tests anyway. Excluding by listing date would also have thrown out names that have plenty of history and no problem.

### The success gate for month one, pre-registered

Written down before day one and not moved afterwards. This is the same list as the one in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`, and it lives here as well because a gate belongs with the version of the rules it judges.

**Operations. All four must pass, and all four are pass or fail.**

1. Zero manual restarts during market hours.
2. Zero cap breaches.
3. Zero unreconciled positions.
4. At least 95 percent of scheduled ticks actually ran.

**Returns. Reported honestly, and gated on nothing.**

5. At least 60 closed round trips.
6. Profit factor after doubling the measured slippage.
7. Maximum drawdown.
8. Hit ratio.
9. Profit and loss per trade in units of risk.
10. Return against SPY over the same days.

Returns cannot be a gate because one month gives 60 to 100 trades, and that is nowhere near enough to tell a 55 percent win rate from a coin flip, which needs about 384 trades.
