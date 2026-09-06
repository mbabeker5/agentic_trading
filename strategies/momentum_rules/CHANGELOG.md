# Changelog: opening momentum, rules only (book B)

This file records every change to this strategy's numbers: what changed, on what date, and the git commit that carried it. The reason it exists is the ledger. A decision written down in the ledger in October has to be readable against the exact rules it was made under, not against whatever the rules became by December. Without a dated commit beside each set of numbers, a good month and a changed stop loss are impossible to tell apart. The strategy file beside this one is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_rules/strategy.yaml` and the spec it implements is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`.

Book B is the rules only control for books A and E. Its numbers are identical to theirs in every respect apart from one: no model is ever called. The code takes the names off the ranking in order and follows the rules. That is the whole comparison month one is for, so any change to the numbers here has to be the same change made in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_hybrid/CHANGELOG.md` on the same day, and a test in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_books.py` fails if the two ever drift apart.

## Momentum v2, 2026-09-06

Approved by Mo from the consolidated critique at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md`

Commit: RULES_COMMIT_PLACEHOLDER

Stamped into `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml` as `rules_commit` for books A, B and E.

Book B has no model, so the two items that only change what a model is told, A13 and the model's half of D2, reach this book through the code alone. They are listed anyway, because the books have to be readable side by side and an item missing from one list would look like a difference in the rules.

### Applied

- A1 Stop: now 10 percent of the 14 day average true range and never inside the opening range, so a long stops at or below the range low and a short at or above the range high (was 1.5 percent of price or the range low if closer). The 1.5 percent number survives only as a fallback for a position whose average true range is not known, and the yaml says so.
- A2 Profit target: now none at all, a position leaves by its stop or at the close (was a target set at twice the stop distance). Two independent studies found targets destroy the edge.
- A3 Volatility filter: now the 14 day average true range has to be above 0.50 US dollars and above 1.5 percent of the price, both of them, or the name is not a candidate (was no filter at all).
- A4 Selection: now rank the candidates by relative volume measured on the 9:30 to 9:35 window against the same window over the prior 14 days, keep 2 times normal as the floor, and take the top of the ranking (was a 2 times threshold and then the top names by a combined score). The ranking, not the size of the gap, is what carried the published result.
- A5 Direction: now the sign of the first five minute candle, close above open is a long, close below open is a short, and a flat candle where open equals close is no trade at all (was the sign of the overnight gap).
- A6 Position size: now risk based, 0.25 percent of book equity risked per trade, shares equal that money divided by the distance from entry to stop, with a notional cap of 10 percent of book equity in any one name (was 15 percent of equity per name with no risk rule).
- A7 Daily loss cap: now 1 percent of book equity (was 2 percent). With 10 positions each risking 0.25 percent the natural worst case in a day is 2.5 percent, so any cap above that could never bind and was decoration. 1 percent binds after four full stop outs.
- A8 Loss limits beyond the day: now weekly 4 percent, monthly 6 percent, and a pause for Mo's review after three consecutive losing days, with any one of the three pausing the book (was nothing beyond the day).
- A9 Correlation: now a sector cap of 25 percent of a book's gross exposure limit in any one sector, an account level cap of 15 percent on any single symbol across all five books, and the count of positions pointing the same way at once logged every tick so a month of it can be read back (was no correlation rule at all). A name whose sector the broker could not tell us is refused rather than assumed harmless.
- A11 The close: now flattening begins at 3:45 PM with limit orders at the bid or the ask, and anything still open at 3:55 PM is closed at market as a backstop (was market orders at 3:55 PM).
- A12 Hard exclusions: now leveraged and inverse funds, SPACs, warrants, rights, preferred shares, anything traded over the counter, anything listed outside the US and anything with a pending trading halt are dropped before a name can be picked at all (was no exclusion list).
- A13 Headlines: now no headlines and no news anywhere in the momentum packet or the prompt until there is a feed that carries where a story came from (was a prompt that told the model to weigh headlines). Press release copy is prompt injection with a profit motive. Book B calls no model, so this reaches it only as the code that keeps news out of the candidate packet.
- A14 Polling: now every 30 seconds from 9:35 to 11:00 while a momentum book holds a position or has a working order, and every 5 minutes the rest of the time (was every 5 minutes all day).
- A15 Ledger: now records on every decision and every fill the decision price, the slippage, the average true range, the relative volume, the rank, the direction candle, the money risked on that trade, and the sector (was 18 fields without any of those).
- A16 Success gate: now pre-registered, with operations gated and returns reported but not gated, written out in full below (was "near flat after costs").
- D1 Breadth: now 10 positions at risk based size (was 5 positions at up to 15 percent each).
- D2 VWAP fade: now a logged observation only in month one, the code writes down every time it would have fired and closes nothing on it (was an exit the code acted on). The number of closes that counts as a fade stays at 2. The half of this item about a model calling a fade does not apply to book B, which calls none.
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
