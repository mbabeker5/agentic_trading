# Strategy spec: opening momentum, month one

Status: draft for Mo's approval, written 2026-09-02, position cap raised to 15% on 2026-09-06. **Shorting deferred to month two pending review** (review team, 2026-09-06): the short side described below stays switched off in the code until the hub's consolidated critique lands. Nothing here trades until Mo says the numbers are right. This document stands on its own: everything needed to understand and run the strategy is written here.

## The idea in one paragraph

Some stocks open the day with a jump and unusually heavy trading, usually because of news overnight. When such a stock keeps pushing above the high of its first five minutes, and volume backs it up, the move often carries on for an hour or two. We buy that push, protect it with a tight stop, and are out of everything before the close. The mirror image applies too: a stock gapping down on heavy volume that keeps breaking below its opening range can be shorted, with the same tight stop above. No overnight risk, no options, no borrowed money beyond what a short technically needs. It is one of the oldest day-trading patterns because it is simple to see and simple to test, which is exactly what month one needs.

## Who does what

The code does the boring, rule-bound work and enforces every hard limit. Claude does the judgment in between and writes down why. Neither side can skip the other.

- **Code**: scans the market at the open for both gappers up and gappers down, filters candidates, watches prices every five minutes, refuses any order that breaks a limit, closes everything at 3:55 PM, writes the ledger.
- **Claude**: at 9:35 reads the shortlist, the five-minute bars and any headline, picks up to five names, sets each one's entry trigger, stop and target, and sizes them. Through the day it decides whether a position is fading and whether a new entry still makes sense. Every decision, including "do nothing", gets a one-line reason in the ledger.

## The day, step by step

**Before 9:35 AM Eastern.** IBKR's scanner ranks US stocks and ETFs by percentage gain and by unusual volume. The code keeps names priced above $5 that trade at least $20 million a day on average over the last 30 sessions, whose volume by 9:35 is at least twice their normal pace for that time of day, and throws out leveraged and inverse ETFs. Result: a shortlist of at most 20, long and short candidates together, each tagged with why it was flagged.

**9:35 AM.** Claude reviews the shortlist and picks up to five. For each it records the opening range (the high and low of 9:30 to 9:35), an entry trigger (price breaks above the range high on rising volume), a stop (the range low or 1.5% below entry, whichever is closer), and a target or a trailing rule.

**Every five minutes until 3:55 PM.** The loop wakes, checks each open position against its stop and target, and asks Claude whether momentum has faded (a five-minute close back below the day's volume-weighted average price is the standard tell). New entries from the shortlist are allowed only until 11:00 AM. The caps below are checked before any order.

**3:55 PM.** Everything still open is sold at market. Then the Daily tab is filled in: equity, SPY close, alpha, commissions paid.

## Every parameter and its proposed value

| Parameter | Proposed | Notes |
|---|---|---|
| Book size | $100,000 | A virtual book: its own capital, positions and limits, tracked separately inside the shared paper account. Every order carries an IBKR order reference tag so fills are attributed to this book |
| Max per position | 15% of book equity (Mo, 2026-09-06) | About $15,000 at the start |
| Max open positions | 5 | So at most 75% of the book is deployed at once |
| Stop loss | 1.5% below entry, or the opening range low if closer | Hard, attached to the order as a bracket |
| Daily loss cap | 2% of equity | Hit it and the code halts new trades for the day, closes what is open |
| Flat by | 3:55 PM Eastern | Market orders |
| New entries allowed | 9:35 to 11:00 AM only | |
| Loop cadence | Every 5 minutes, market hours | |
| Universe | US-listed stocks and ETFs at IBKR | No international, no fixed income in month one |
| Price floor | $5 | Kept as a junk filter |
| Liquidity floor (Mo, 2026-09-06) | $20,000,000 average daily dollar volume over 30 sessions | Replaces the old 1,000,000 share floor. A census on 2026-09-04 found about 2,700 US names above $20M dollar volume against about 1,950 above 1M shares, so the new floor is wider and better matched to how much we can trade. Script and data in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/liquidity_census/` |
| Relative volume floor (Mo, 2026-09-06) | 2x normal by 9:35 | Volume traded by 9:35 must be at least twice the stock's usual volume for that time of day. Below 2x the name is skipped |
| Shortlist size | 20 at most | |
| Shorting | Deferred to month two pending review | Off in the code (`allow_shorts: false`). When switched on: same caps as longs, stop 1.5% above entry or the range high if closer, price floor $10, and the easy-to-borrow rule below |
| Easy-to-borrow rule (Mo, 2026-09-06) | All three must hold at the moment of entry | IBKR shortable indicator at the easy-to-borrow level; borrow fee under 1% a year; at least 10 times our intended share count available to borrow. Any miss and the short is skipped, logged with the reason |
| Gross exposure cap | 100% of book equity | All positions added together may never exceed the book's value. No margin borrowing. With 5 positions at 15% the natural ceiling is 75%, so this is a backstop |
| Cross-book symbol exclusivity (review team, 2026-09-06) | One ticker, one book, at any moment | No two books may hold, or have a working entry order in, the same name. IBKR nets positions per symbol inside the shared account, so a second book in the same ticker would vanish into the first book's line and neither book could be reconciled. Ties go first come, first served, resolved by the order the books appear in `config/books.yaml`. Exits of a book's own position are never blocked. Enforced as rule `symbol_exclusive`, and detected after the fact by the daily reconciliation as kind `symbol_shared` |
| Halted names (review team, 2026-09-06) | No order into a name that cannot be traded | While IBKR's halted tick (tick type 49) says the name is halted, only an exit or a flatten goes out. While the name sits in a limit-up limit-down band, no new position is opened. If the halt status could not be read at all, no new position is opened either: an unknown halt status is refused rather than assumed clean. Enforced as rule `halted` |
| Options | Not in month one | |
| Order types | Limit entries, bracket stops, market exits at close | |

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

**Operations, must all pass:**
- Every trading day ran without a manual restart.
- No order ever breached a cap or fired outside market hours.
- The account was flat every day by 3:55 PM.
- Every fill and every decision appears in the ledger with a reason.
- Fills matched what the loop believed it held. No phantom or missing positions.

**Returns, reported honestly:**
- Total return against SPY over the same days, from the Summary tab.
- Max drawdown, win rate, average win and loss, number of trades, commissions paid.
- A note on paper fills: IBKR's simulator is optimistic on limit orders, so real fills would be somewhat worse.

If operations pass and returns are anywhere near flat after costs, month two is a live account with a small balance. If operations fail anywhere, the strategy waits and the plumbing gets fixed first.
