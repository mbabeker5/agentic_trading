# Opening momentum spec: consolidated critique

Date: 2026-09-06. Prepared by the hub from six independent reviews (published evidence, execution realism, risk management, adversarial red team, model-in-the-loop design, live transition) plus two probes run on the paper account today. Written for Mo, who intends to put real money on this strategy immediately if the paper month succeeds. Every change below is a proposal until Mo approves it; strategy parameters change only through an approved, versioned commit stamped into the run registry.

Source reviews are saved beside this file as `momentum_spec_critique_2026-09-06_reviews/` once committed; the working copies are in the hub's scratchpad under `critique/`.

## Verdict in three sentences

The code as it stood this morning could not protect a position: the hard stop and target were never attached to a position, no bracket order was ever sent to the broker, and the kill switch would refuse a live account. The spec also diverges from the only published evidence for this strategy on the four things that made that strategy work: a very tight volatility-based stop, no profit target, broad selection ranked by relative volume, and hold to the close. The plan is sound as an operations test; it is not yet a strategy anyone should fund, and the reviews agree on what to change.

## Part 1. Defects in the code, being fixed today, no decision needed

These are bugs, not opinions. The trading worker has them as blocking work.

1. Positions were created with stop and target set to zero, so neither ever fired; only the trailing stop and the VWAP fade could close a trade. Fix: set both at fill time from the trigger record and clamp through the guardrail so the model can only tighten a stop, never widen it.
2. No bracket order exists in the code despite the spec saying the stop is "attached to the order as a bracket". The stop was a Python check that ran once every five minutes. Fix: native IBKR bracket (parent plus stop child in one group), stop-limit with a small offset, plus a 60-second market backstop if the stop triggers and does not fill.
3. The kill switch refused any account whose id did not start with DU, so it would not work on a live account, and it was a file checked only inside the loop, so a dead loop made it inert. Fix: act directly against the broker, work on live ids behind an explicit flag, heartbeat so a dead loop triggers it.
4. A model answer of "fade" did nothing; only "exit" acted. Fix: act on it or remove it from the prompt.
5. The prompt said the VWAP exit fires on two closes below VWAP; the code fired on one. Fix: one rule, rendered from the yaml into both.
6. The rules-only book picked three names while the model books picked five, which would have confounded the one comparison Mo cares most about. Fix: same count everywhere.
7. No temperature or seed was pinned, a hung model call could consume a whole five-minute tick, malformed model output could default a garbled side to "long", and no tests covered the model layer. Fix: temperature 0, 45-second timeout with fall-through to rules, strict output schema, reject unknown values, property-style tests.
8. The spec claimed a slippage column the ledger did not have. Fix: decision price and slippage columns added.
9. The scanner README described a long-only cut while the code handled shorts. Fix: docs reconciled.
10. The stop script for the Gateway depended on `telnet`, which macOS no longer ships, so the Gateway did not restart when asked. Fix: socket call plus kill-by-process fallback, and the watchdog must verify a restart produced a new login.
11. Two books could hold the same ticker, but IBKR nets positions per symbol, so reconciliation would be impossible. Fix: cross-book symbol exclusivity.

## Part 2. Spec changes with reviewer consensus, recommended for approval

Each of these was raised by at least two reviewers independently or is arithmetic.

| # | Change | From | To | Why |
|---|---|---|---|---|
| A1 | Stop | 1.5 percent of price, or the opening range low if closer | 10 percent of the 14-day average true range, never inside the opening range | The published edge is a tight, volatility-based stop. 1.5 percent is about five times wider than the tested stop and sits inside normal noise on a stock up 12 percent. Range-edge stops were the single largest source of cross-vendor result dispersion in the authors' own test, and month one runs on a partial feed. |
| A2 | Profit target | Target or trailing rule set by the model | No target. Exit on stop or at the close | Two independent studies found targets destroy the edge. |
| A3 | Volatility filter | None | 14-day average true range above 0.50 USD and above 1.5 percent of price | Without it the scan fills with quiet large caps whose five-minute range is noise. This was a universe filter in the published test. |
| A4 | Selection | Threshold at 2x relative volume, model picks up to 5 | Rank by relative volume measured on the 9:30 to 9:35 window against the same window over the prior 14 days, keep 2x as a floor, take the top N | The ranking, not the breakout, carried the published result. |
| A5 | Direction | From the overnight gap | From the sign of the 9:30 to 9:35 candle; no trade on a flat candle | The paper's exact rule. |
| A6 | Position size | 15 percent of equity per name | Risk-based: 0.25 percent of book equity per trade, shares = risk divided by stop distance, capped at 10 percent of equity | Equalises risk across names. At 15 percent, a 20 percent halt gap in one name costs 3 percent of the book, more than the daily cap. |
| A7 | Daily loss cap | 2 percent | About 1 percent, or re-derived once A6 is in | With five positions at 15 percent and a 1.5 percent stop the most five stop-outs can lose is about 1.1 percent, so a 2 percent cap could never bind. It was decoration. |
| A8 | Loss limits beyond the day | None | Weekly 4 percent, monthly 6 percent, three consecutive losing days: any one pauses the book for Mo's review | A book could lose 2 percent a day for ten days and no rule would notice. |
| A9 | Correlation | None | Sector cap 25 percent of gross; account-level per-symbol cap 15 percent across all books; log the count of simultaneous same-direction positions | Five morning gappers correlate 0.6 to 0.8; five names are about 1.3 independent bets. |
| A10 | Shorting | Allowed | Off in month one; revisit in month two with SSR handling | The short-sale restriction (Rule 201) triggers on a 10 percent drop and then forbids shorting at or below the bid for two days. Gap-down names are exactly that population, so "break below the range low" shorts cannot be filled as designed. Halt and buy-in risk compound it. Three reviewers reached this independently. |
| A11 | Close | Market orders at 3:55 | Begin flattening at 3:45 with limit orders; market backstop at 3:55 | Spreads widen and depth collapses in the last minutes. Note: one reviewer suggests market-on-close, another warns its 3:50 cutoff is irrevocable; limits from 3:45 avoid both problems. |
| A12 | Hard exclusions before the model sees a name | None | Names under the short-sale restriction, float under 20 million shares, listed under 90 days, in a trading halt or limit state, or whose 30-session dollar volume measured 30 days ago is under 20 million USD | The 20 million floor is a 30-day average, so yesterday's frenzy qualifies a shell. These are the promoter and binary-event traps the red team ranked as the largest source of loss. |
| A13 | Headlines to the model | The prompt tells the model to weight headlines; the scanner sends none | Remove headline fields until a feed with provenance exists; then pass source, timestamp and first 120 characters inside a fenced untrusted block | Press-release copy is prompt injection with a profit motive. |
| A14 | Polling | Every 5 minutes | Every 30 seconds from 9:35 to 11:00 while positions are open; 5 minutes otherwise | A tight stop needs sub-minute resolution even with brackets at the broker. |
| A15 | Ledger | 18 fields | Add decision price, slippage, setup type (earnings, biotech, offering, no news, promoted), days since listing, float, SSR flag, halt flag, maximum favourable excursion after a stop-out, entry-time bucket, and the same tags for shortlist names not traded | Without these, luck and selection cannot be told apart at month end. |
| A16 | Success gate | "Near flat after costs" | Operations must all pass: zero manual restarts in market hours, zero cap breaches, zero unreconciled positions, at least 95 percent of ticks executed. Returns reported, not gated: at least 60 closed round trips, profit factor after a 2x slippage haircut, drawdown, hit ratio, PnL per trade in R, alpha over SPY | One month of 60 to 100 trades cannot separate a 55 percent win rate from a coin flip (that needs about 384) or detect a monthly edge under about 7 percent. Pre-register the criteria before day one. |

## Part 3. Decisions only Mo can make

D1. **Breadth versus concentration.** The evidence favours 10 to 20 small positions ranked by relative volume; the current spec has five discretionary picks at up to 15 percent. Wider is closer to the tested strategy and dilutes the model's judgement; narrower keeps the model's role central. Recommendation: 10 positions at risk-based size for the model books, which keeps both the evidence and the experiment intact.

D2. **The VWAP fade exit.** It comes from a different published strategy (1-minute closes with reversal) and grafting it on as a discretionary exit is untested; it is also the main thing the model does between 9:35 and the close. Options: keep it as the model's exit tool, demote it to a logged observation for month one so the pick decision is what gets tested, or keep it with the rule fixed to two closes. Recommendation: log it, do not act on it, in month one.

D3. **Entry window.** Evidence is silent on the 11:00 cutoff; the red team says entries after 10:15 chase exhausted moves. Recommendation: cut at 10:15 and log every entry the cutoff blocks, so month one measures it.

D4. **Go-live ramp.** Reviewers propose 10 percent of intended size for 10 sessions, 25 percent for 10, 50 percent for 10, then full, with a return to paper on any cap breach, unreconciled position, crash with a position open, two daily-cap hits in five sessions, drawdown over 8 percent, or live slippage above twice paper. Mo said "immediately if successful"; the ramp is the responsible version of immediately. Decide the step sizes.

D5. **Live account funding.** The live account holds 100 USD. Day trading under 25,000 USD of equity risks a 90-day lock. Reviewers propose 32,000 to 35,000 by wire, a code rule refusing all orders below 27,500 net liquidation, and funding only one live book. Decide the amount and whether one book or several go live.

D6. **Live Gateway order-precaution settings.** Two reviewers disagree: one says bypass IBKR's order precautions for API orders so the code's own caps are the only gate; the other says never bypass, keep IBKR's caps just above the code's as a second layer. Recommendation: never bypass; two layers are cheaper than one mistake.

D7. **Data feeds.** Not a spec item but a cost decision: the three network feeds are bought (4.50 USD a month); nothing else is recommended. Finviz Elite at 39.50 USD is the only optional add, for scanner cross-checking, and only if IBKR's list proves unreliable.

D8. **Tax structure.** Short-term gains are ordinary income; wash sales bite across year-end; a Section 475(f) election must be filed by the return due date and cannot be retroactive. A trader-tax CPA should be consulted before the first live trade. Decide when.

## Part 4. Rejected or deferred, with reasons

R1. Building our own market data feed from the consolidated tape: 39,000 to 71,000 USD a year. Retail systems rent it through the broker.

R2. Robinhood MCP as a quote source: single-venue prices, bid and ask break outside regular hours, and Robinhood's customer agreement forbids using its data for anything outside a Robinhood account.

R3. Portfolio Margin: requires about 110,000 USD to open; Reg T is the only regime available and its 4x day-trade buying power is not the binding constraint anyway.

R4. Market-on-close for the flatten: its 3:50 cutoff is irrevocable; limits from 3:45 with a market backstop are safer.

R5. Direct Anthropic API for the Claude books: saves roughly 5 percent on about 150 USD a month and breaks the one-provider fairness of the model comparison.

R6. A dry-run week: replaced at Mo's instruction by an offline replay gate that must exercise every guardrail before any book is promoted.

## Part 5. What one month can and cannot tell us

It can prove the machine works: every day runs unattended, every cap holds, every position reconciles, every decision is logged with a reason, and slippage is measured rather than assumed. It cannot prove an edge. The published 41.6 percent a year headline used tight stops, 20 names, 4x leverage and one research group's data; at our risk per trade and gross cap it is unreachable by construction, and the authors themselves showed the same code on four vendors' data produced equity curves three times apart. Judge month one on hit ratio (the tested strategy ran near 48 percent), average PnL per trade in units of risk, and the operations list. The base rate for the humility file: the best large studies find 97 percent of day traders are expected to lose, and 0.13 percent of one 98,000-person cohort earned a modest profit over 300 sessions.

## Part 6. Open research gaps

- The published opening-range results all trace to one research group, one of whom sells trading education, and have no independent replication or post-2023 out-of-sample test. A second literature pass with a working search budget is owed.
- The Congress-trades research returned only unverified figures because its sources are script-rendered or rate-limited; it needs a rerun before any of those numbers are used.
- Commission and fee figures in the execution review are from memory and should be checked against IBKR's live schedule.
- Whether IBKR's scanner filters and real-time quotes reach the paper account after today's subscription purchase is unknown until the Tuesday 9:37 AM probe.
