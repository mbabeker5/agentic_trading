# Strategy spec: opening momentum, month one

Status: **Momentum v2, approved by Mo on 2026-09-06.** This is no longer a draft waiting on the momentum numbers. Every number below is signed off, and what is written here is what the code and the strategy files now carry. It all comes from the consolidated critique at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md`. **One item is still open: shorting (A10) is pending Mo's decision and stays switched off**, so the short side is described here but does not trade. Parameters change only through an approved, versioned commit, and each change is written down in the changelog beside the strategy file it belongs to. This document stands on its own: everything needed to understand and run the strategy is written here.

## What changed in Momentum v2 and why

The item ids below (A1, D3 and so on) are the ones used in the critique and in both changelogs, so a decision sitting in the ledger can always be traced back to the rule it was made under.

| Item | Was | Now | Why |
|---|---|---|---|
| A1 | Stop at 1.5% of the price, or the opening range low if that was closer | Stop at 10% of the 14 day average true range, and never inside the opening range | 1.5% is about five times wider than the tested stop and sits inside normal noise on a stock that has just jumped 12% |
| A2 | The model set a profit target or a trailing rule | No target at all. A position leaves by its stop or at the close | Two independent studies found targets destroy the edge |
| A3 | No volatility filter | The 14 day average true range must be above $0.50 and above 1.5% of the price | Without it the list fills with quiet large caps whose five minute range is just noise |
| A4 | A 2x relative volume threshold, then the model picked freely | Rank by relative volume on the 9:30 to 9:35 window against the same window over the prior 14 days. 2x stays as the floor. Take the top of the ranking | The ranking, not the size of the gap, is what carried the published result |
| A5 | Direction taken from the overnight gap | Direction taken from the sign of the first five minute candle. A flat candle is no trade | It is the rule the published test actually used |
| A6 | 15% of book equity per name | Risk 0.25% of book equity per trade. Shares equal that money divided by the distance from entry to stop. Notional capped at 10% of book equity | Equal risk on every name. At 15%, one halted stock gapping 20% costs more than the whole daily cap |
| A7 | Daily loss cap of 2% | Daily loss cap of 1% | Ten positions risking 0.25% each can lose 2.5% in a day, so a 2% cap could never bind. It was decoration |
| A8 | Nothing beyond the day | Weekly 4%, monthly 6%, and three losing days in a row. Any one of them pauses the book for Mo to look at | A book could lose money steadily for two weeks and no rule would notice |
| A9 | No correlation rule | Sector cap of 25% of the gross exposure limit, a 15% cap on any one symbol across all five books, and the count of same direction positions logged every tick | Morning gappers move together, so ten of them are nothing like ten independent bets |
| A10 | Allowed in the spec, already switched off in the code pending review | Still switched off. **Pending Mo's decision**, not decided | The short sale restriction bans shorting at or below the bid for two days after a 10% fall, and gap down names are exactly that population |
| A11 | Market orders at 3:55 PM | Limit orders at the bid or the ask from 3:45 PM, with a market backstop at 3:55 PM | Spreads widen and depth thins in the last minutes, so a market order pays for the hurry |
| A12 | No hard exclusions | Leveraged and inverse funds, SPACs, warrants, rights, preferred shares, anything over the counter, anything listed outside the US and anything with a pending halt are all dropped before the model sees them | These are the promoter and binary event traps the red team ranked as the largest source of loss |
| A13 | The prompt told the model to weigh headlines | No headlines and no news anywhere in the packet or the prompt | Press release copy is prompt injection with a profit motive |
| A14 | Polling every 5 minutes | Every 30 seconds from 9:35 to 11:00 while the book holds a position or has a working order, every 5 minutes the rest of the time | A stop this tight needs sub-minute resolution |
| A15 | 18 ledger fields | Adds the decision price, the slippage, the average true range, the relative volume, the rank, the direction candle, the money risked and the sector | Without them, luck and judgment cannot be told apart at month end |
| A16 | "Near flat after costs" | Operations gated, returns reported but not gated, all of it written down before day one | One month cannot measure an edge. It can measure whether the machine works |
| D1 | 5 positions at up to 15% each | 10 positions at risk based size | Closer to the tested strategy, and it stops one name deciding the month |
| D2 | The VWAP fade closed positions | A logged observation only in month one. The code writes down every time it would have fired and closes nothing on it. Two closes still counts as a fade | It comes from a different published strategy and was never tested here. Month one tests the pick |
| D3 | New entries until 11:00 AM | New entries until 10:15 AM, and every entry the cutoff blocks is logged | Entries after 10:15 chase moves that are already spent. The log measures what the cutoff cost |
| D7 | An optional Finviz Elite cross check | Gone, and the code path with it | One source of truth for the scan, and no monthly fee for a check we do not need |

## The idea in one paragraph

Some stocks open the day with a jump and unusually heavy trading, usually because of news overnight. The first five minutes set a range, a high and a low. If the volume behind the move is far above what that stock normally does in those five minutes, and the price then breaks out of the range, the move often carries on for an hour or two. We take that break, protect it with a stop sized to the stock's own daily swing, and hold until either the stop is hit or the day ends. There is no profit target, because the handful of trades that run a long way are what pay for all the small losses. The mirror image applies to a stock gapping down, which can be shorted on a break below its opening range low, although shorting is switched off until Mo decides on it. No overnight risk, no options, no borrowed money beyond what a short technically needs. It is one of the oldest day-trading patterns because it is simple to see and simple to test, which is exactly what month one needs.

## Who does what

The code does the boring, rule-bound work and enforces every hard limit. Claude does the judgment in between and writes down why. Neither side can skip the other.

- **Code**: runs the pre-open scan and pulls the history it needs, builds the opening range from live ticks, applies the filters, ranks the survivors by relative volume, reads the direction off the first five minute candle, works out every position's size from the risk budget, sends the order with its stop attached, refuses anything that breaks a limit, flattens into the close, writes the ledger.
- **Claude**: at 9:35 reads the ranked shortlist and decides which of the top names to actually take and which to skip, with a one line reason for each either way. It does not set the size and there is no target for it to set. It may tighten a stop, never widen one. Through the day it gives its read on each open position, and that read is recorded.

## The day, step by step

**9:00 to 9:25 AM Eastern, before the open.** The pre-market gap scan runs every few minutes and keeps a list of up to 100 candidates. For each new name the code pulls the 14 days of five minute history that the relative volume baseline needs and the inputs for the 14 day average true range, spread out at no more than four requests a minute. That is deliberate: IBKR allows only about 60 historical requests in any 10 minutes, and doing this work early means the budget is not being spent in the five minutes around the open when it is scarcest. Streaming quotes for the final list are subscribed by 9:28, the opening range is built from live ticks between 9:30 and 9:35 rather than from any historical request, the ranking runs at 9:35 and the orders are out by 9:36. The full timeline, the time budget for each step and what happens to a name that gaps late are in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/PREOPEN_FLOW.md`.

**9:30 to 9:35 AM.** The market opens and the first five minute candle forms. Its high and low are the opening range. Whether it closed above or below its open is the direction: above is a long, below is a short, and a candle that opens and closes at exactly the same price is no trade.

**9:35 AM.** The code drops anything failing the volatility filter, the liquidity floor, the price floor, the history requirement or the hard exclusions. What is left is ranked by relative volume, highest first, and the top 20 go to Claude. Claude picks from the top of that ranking, up to 10 names, and skips the rest with a reason. The code sizes each pick against the risk budget, checks the sector and symbol caps, and sends a limit order at the break of the opening range with the stop attached to it. Orders are out by 9:36.

**9:35 to 10:15 AM.** New positions may be opened. After 10:15 no new position is opened at all, and every entry that the cutoff blocks is written into the ledger so month one can say what the cutoff cost.

**Through the day.** While the book holds a position or has a working order, the loop wakes every 30 seconds from 9:35 to 11:00. The rest of the time it wakes every 5 minutes. It checks each position against its stop, notes whether the VWAP fade rule would have fired (it changes nothing in month one), and asks Claude for a read. Every cap is checked before any order.

**3:45 PM.** Flattening begins, with limit orders sitting at the bid or the ask.

**3:55 PM.** Anything still open goes out at market as a backstop. Then the Daily tab is filled in: equity, SPY close, alpha, commissions paid.

## Every parameter and its value

Every row that changed on 2026-09-06 names the approved item it came from.

| Parameter | Value | Notes |
|---|---|---|
| Book size | $100,000 | A virtual book: its own capital, positions and limits, tracked separately inside the shared paper account. Every order carries an IBKR order reference tag so fills are attributed to this book |
| Risk per trade | 0.25% of book equity (A6, 2026-09-06) | $250 on a $100,000 book. This is the number that decides the share count. Replaces the flat 15% per name |
| Max per position | 10% of book equity (A6, 2026-09-06) | A cap on the value of the holding, on top of the risk rule above, so a very tight stop cannot buy an enormous position. Was 15% |
| Max open positions | 10 (D1, 2026-09-06) | Was 5. Ten small positions rather than five big ones |
| Stop loss | 10% of the 14 day average true range, and never inside the opening range (A1, 2026-09-06) | Hard, attached to the order as a bracket. For a long the stop sits at or below the opening range low, for a short at or above the range high. Replaces 1.5% of price or the range low if closer. 1.5% survives only as a fallback for a position whose average true range is not known, and the strategy file says so |
| Profit target | None (A2, 2026-09-06) | A position leaves by its stop or at the close, and by nothing else |
| Volatility filter | 14 day average true range above $0.50 **and** above 1.5% of the price (A3, 2026-09-06) | Both have to hold. Fail either one and the name is not a candidate |
| Selection | Rank by relative volume on the 9:30 to 9:35 window against the same window over the prior 14 days (A4, 2026-09-06) | 2x normal stays as the floor, applied before the ranking. The top of the ranking is what gets traded |
| Direction | The sign of the first five minute candle (A5, 2026-09-06) | Close above open is a long, close below open is a short, open exactly equal to close is no trade. Was taken from the overnight gap |
| Daily loss cap | 1% of book equity (A7, 2026-09-06) | Hit it and the code halts new trades for the day and closes what is open. Was 2%, which could never bind |
| Weekly loss cap | 4% of book equity (A8, 2026-09-06) | Pauses the book for Mo's review |
| Monthly loss cap | 6% of book equity (A8, 2026-09-06) | Pauses the book for Mo's review |
| Losing day streak | 3 losing days in a row (A8, 2026-09-06) | Pauses the book for Mo's review. Any one of the three limits above is enough on its own |
| Sector cap | 25% of the book's gross exposure limit in any one sector (A9, 2026-09-06) | $25,000 on a $100,000 book at the 100% gross cap, so two and a half positions. A name whose sector the broker could not tell us is refused rather than assumed harmless |
| Per symbol cap, whole account | 15% of the money the books hold between them (A9, 2026-09-06) | Across all five books, not just this one. A second layer under the one ticker, one book rule |
| Same direction count | Logged every tick (A9, 2026-09-06) | How many positions point the same way at once. Nothing acts on it in month one; the point is to have a month of it to read back |
| Flat by | Flattening begins 3:45 PM Eastern, market backstop at 3:55 PM (A11, 2026-09-06) | Limit orders at the bid or the ask from 3:45. Anything still open at 3:55 goes out at market. Was market orders at 3:55 |
| New entries allowed | 9:35 to 10:15 AM only (D3, 2026-09-06) | Was 11:00. Every entry the cutoff blocks is logged so the cost of the cutoff is measured |
| Loop cadence | Every 30 seconds from 9:35 to 11:00 while a position or a working order exists, every 5 minutes otherwise (A14, 2026-09-06) | Was every 5 minutes all day |
| VWAP fade | Logged, acts on nothing (D2, 2026-09-06) | Two five minute closes back through the day's volume-weighted average price still counts as a fade. In month one the code writes down every time it would have fired and closes nothing on it |
| Headlines and news | None anywhere (A13, 2026-09-06) | No headline reaches the packet or the prompt until there is a feed that says where a story came from |
| Universe | US-listed stocks and ETFs at IBKR | No international, no fixed income in month one |
| Price floor | $5 | Kept as a junk filter |
| Liquidity floor (Mo, 2026-09-06) | $20,000,000 average daily dollar volume over 30 sessions | Replaces the old 1,000,000 share floor. A census on 2026-09-04 found about 2,700 US names above $20M dollar volume against about 1,950 above 1M shares, so the new floor is wider and better matched to how much we can trade. Script and data in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/liquidity_census/` |
| History requirement | 30 completed sessions, and 14 for the average true range (A12, 2026-09-06) | A rule excluding anything listed in the last 90 days was considered and rejected. The history requirement does the same job honestly: a name too new to measure fails the liquidity floor and the volatility filter anyway |
| Hard exclusions | Leveraged and inverse funds, SPACs, warrants, rights, preferred shares, anything traded over the counter, anything listed outside the US, anything with a pending halt (A12, 2026-09-06) | Applied before the model ever sees a name |
| Shortlist size | 20 at most | What the ranking hands to the model. Ten of them at most can become positions |
| Shorting | **Pending Mo's decision. Off in the code** (A10, 2026-09-06) | `allow_shorts: false`. Not a decided deferral: the decision is still Mo's to make. When switched on: same caps as longs, stop at or above the opening range high, price floor $10, and the easy-to-borrow rule below |
| Easy-to-borrow rule (Mo, 2026-09-06) | All three must hold at the moment of entry | IBKR shortable indicator at the easy-to-borrow level; borrow fee under 1% a year; at least 10 times our intended share count available to borrow. Any miss and the short is skipped, logged with the reason |
| Gross exposure cap | 100% of book equity | All positions added together may never exceed the book's value. No margin borrowing. With 10 positions at 10% the ceiling is exactly 100%, so unlike before, this one can actually bite |
| Cross-book symbol exclusivity (review team, 2026-09-06) | One ticker, one book, at any moment | No two books may hold, or have a working entry order in, the same name. IBKR nets positions per symbol inside the shared account, so a second book in the same ticker would vanish into the first book's line and neither book could be reconciled. Ties go first come, first served, resolved by the order the books appear in `config/books.yaml`. Exits of a book's own position are never blocked. Enforced as rule `symbol_exclusive`, and detected after the fact by the daily reconciliation as kind `symbol_shared` |
| Halted names (review team, 2026-09-06) | No order into a name that cannot be traded | While IBKR's halted tick (tick type 49) says the name is halted, only an exit or a flatten goes out. While the name sits in a limit-up limit-down band, no new position is opened. If the halt status could not be read at all, no new position is opened either: an unknown halt status is refused rather than assumed clean. Enforced as rule `halted` |
| Ledger fields (A15, 2026-09-06) | Decision price, slippage, average true range, relative volume, rank, direction candle, money risked, sector | Written on every decision and every fill, on top of what the ledger already carried |
| Scanner cross-check | None (D7, 2026-09-06) | The optional Finviz Elite check and its code path were deleted rather than left switched off. Do not add it back thinking it went missing |
| Options | Not in month one | |
| Order types | Limit entries, bracket stops, limit exits from 3:45 PM with a market backstop at 3:55 PM | |

## How the stop and the size are worked out

Two of the new numbers deserve spelling out, because everything else hangs off them.

**The average true range.** This is the average size of a day's price swing over the last 14 sessions, counting the gap from the previous day's close. A sleepy utility might swing 40 cents on a normal day. A small biotech might swing 3 dollars. Measuring the stop against that number instead of against a flat percentage means the stop is small on a quiet stock and wide on a wild one, which is the point: the same stop should be equally hard to hit whatever the name is. Ten percent of the 14 day average true range is a genuinely tight stop, and a tight volatility-based stop is the one thing every published version of this strategy has in common. On top of it, the stop may never sit inside the opening range, because inside the range is inside the noise the trade is made of, so a stop there would be taken out by the setup itself.

**The size.** Each trade risks 0.25% of the book, which is $250 on a $100,000 book. The share count is that money divided by the distance from the entry to the stop. Say a stock has a 14 day average true range of $1.20, so the stop starts 12 cents away, and the entry is $20.00. If the opening range low sits at $19.80, the stop moves down to $19.80 because it may not sit inside the range. The distance is now 20 cents, so the size is $250 divided by $0.20, which is 1,250 shares, which is $25,000 of stock. That is more than the 10% notional cap of $10,000, so the order is cut to 500 shares and the trade risks $100 rather than $250. Being under the risk budget is fine. Being over it is not.

**Why the daily cap is 1%.** Ten positions each risking 0.25% means the natural worst case in a single day is 2.5%. A cap set anywhere above that could never fire, which is what was wrong with the old 2% number: it looked like a limit and was decoration. At 1% the cap binds after four full stop-outs, which is a bad morning and the right moment to stop for the day.

## Price feed in month one

Mo enabled real-time data sharing to the paper account on 2026-09-02 (IBKR applies it overnight). The live account holds only IBKR's free feed, "US Real-Time Non Consolidated Streaming Quotes", which is the top of book from the Cboe exchanges plus IEX, roughly a fifth of US volume. So month one prices off a real-time but partial view of the market: last prices track the real market closely on liquid names, while bid and ask can sit a cent or two off the true national best on thinner ones. The agent's entries are limit orders, so a stale quote costs a missed fill rather than a bad one. The recommended upgrade (hub research, 2026-09-06, in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/quote_feeds_2026-09-06.md`) is the streaming NBBO by network at $1.50 each for Networks A, B and C, $4.50 a month in total, not the $10 snapshot bundle. Two facts shape the code regardless of feed: IBKR fills paper orders against its own quotes, so the decision code always prices off IBKR quotes, never an outside feed, to avoid a gap between the price the model decided at and the fill; and the ledger's slippage column measures exactly that gap. Robinhood's MCP is rejected as a price feed: single venue, and its terms forbid external use. Whichever feed was live is recorded in the ledger notes each day.

## Day trading rules, and why paper ignores them

Two regimes exist in 2026 and we do not yet know which one applies to Mo's account.

**Old regime, the pattern day trader rule.** Anyone making four or more round-trip day trades in five business days in a margin account is a pattern day trader and must hold at least $25,000. Fall below it and the broker blocks day trading for 90 days. This strategy would trip the rule in its first week.

**New regime, the intraday margin deficit framework.** FINRA retired the pattern day trader rule effective 2026-06-04 (Regulatory Notice 26-10) with a phase-in running to 2027-10-20. A migrated account has no $25,000 floor and no four-in-five count. Instead, an order that would put the account into an intraday margin deficit must be cured within about three business days, and four failures in twelve months can bring a 90-day restriction. IBKR says new margin accounts are generally not subject to the old rule but may be during the transition. Mo's account was opened 2026-09-02, so its regime is unknown until the API is asked: three "day trades remaining" numbers mean the old regime, unlimited or absent means the new one. The Tuesday 2026-09-08 pre-flight reads and logs it.

**What the code does.** Under the old regime, this strategy keeps a rolling five-business-day day-trade counter in the ledger. It is not blocked by the counter, since day trading is the whole strategy, but it logs every trade the rule would have blocked so the live-money cost is measured. Under the new regime, the counter still runs for the record, and every order is checked so it cannot create an intraday margin deficit; the gross exposure cap of 100% of book equity with no borrowing makes a deficit structurally impossible, and the code asserts that rather than assuming it.

**Why paper ignores both.** The paper account holds simulated money and IBKR applies neither regime to it. Month one therefore says nothing about how the strategy fares under either set of rules with real money. Mo's standing assumption for live: keep at least $25,000 of account equity until the regime is confirmed.

## How we judge month one

Operations first, returns second. A month is too short to know whether a day-trading edge is real. It is plenty to know whether the machine works.

This list is **pre-registered** (A16, 2026-09-06). It was written down before day one and it does not move afterwards. That matters more than it sounds: a bar that can be lowered at the end of the month is not a bar, it is a story told about whatever happened.

**Operations. All four must pass, and all four are pass or fail.**

1. Zero manual restarts during market hours. Nobody touched it on a trading day.
2. Zero cap breaches. No order ever went out that broke a limit, and no limit was ever exceeded after the fact.
3. Zero unreconciled positions. What the loop believed it held matched what IBKR actually held, every day, with no phantom and no missing lines.
4. At least 95% of scheduled ticks actually ran. A tick is one wake-up of the loop, so this measures how much of the month the book was genuinely awake.

**Returns. Reported honestly, and gated on nothing.**

5. At least 60 closed round trips. A round trip is one position opened and closed. Below 60 there is not enough to report on.
6. Profit factor after doubling the measured slippage. Profit factor is the total money won divided by the total money lost, so above 1.0 means the winners paid for the losers. Slippage is the gap between the price a decision was made at and the price the fill came back at, and it gets doubled before the sum because IBKR's paper simulator is optimistic on limit orders and real fills would be worse.
7. Maximum drawdown. The largest peak to trough fall in the book's value over the month.
8. Hit ratio. The share of round trips that made money. The published version of this strategy ran near 48%, which is a reminder that a winning strategy does not need to win most of the time.
9. Profit and loss per trade in units of risk. One unit of risk is the money that trade had at stake, so a trade stopped out is minus one and a trade making twice what it risked is plus two. Counting this way makes a $100 trade and a $250 trade comparable.
10. Return against SPY over the same days, from the Summary tab.

**Why returns cannot be a gate.** One month gives 60 to 100 trades. That is nowhere near enough to tell a 55% win rate from a coin flip, which needs about 384 trades before the difference shows through the noise. Gating on returns over one month would mean funding or killing the strategy on a number that is mostly luck in either direction.

If all four operations criteria pass, month two goes live. The size it starts at is still Mo's decision, and so is which book gets funded. If any operations criterion fails, the strategy waits and the plumbing gets fixed first.
