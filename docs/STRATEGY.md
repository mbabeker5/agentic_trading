# Strategy spec: opening momentum, month one

Status: draft for Mo's approval, written 2026-09-02, shorting added the same day at Mo's request. Nothing here trades until Mo says the numbers are right.

## The idea in one paragraph

Some stocks open the day with a jump and unusually heavy trading, usually because of news overnight. When such a stock keeps pushing above the high of its first five minutes, and volume backs it up, the move often carries on for an hour or two. We buy that push, protect it with a tight stop, and are out of everything before the close. The mirror image applies too: a stock gapping down on heavy volume that keeps breaking below its opening range can be shorted, with the same tight stop above. No overnight risk, no options, no borrowed money beyond what a short technically needs. It is one of the oldest day-trading patterns because it is simple to see and simple to test, which is exactly what month one needs.

## Who does what

The code does the boring, rule-bound work and enforces every hard limit. Claude does the judgment in between and writes down why. Neither side can skip the other.

- **Code**: scans the market at the open for both gappers up and gappers down, filters candidates, watches prices every five minutes, refuses any order that breaks a limit, closes everything at 3:55 PM, writes the ledger.
- **Claude**: at 9:35 reads the shortlist, the five-minute bars and any headline, picks up to five names, sets each one's entry trigger, stop and target, and sizes them. Through the day it decides whether a position is fading and whether a new entry still makes sense. Every decision, including "do nothing", gets a one-line reason in the ledger.

## The day, step by step

**Before 9:35 AM Eastern.** IBKR's scanner ranks US stocks and ETFs by percentage gain and by unusual volume. The code keeps names priced above $5 with average daily volume above one million shares, whose opening volume is well above their normal pace, and throws out leveraged and inverse ETFs. Result: a shortlist of at most 20, long and short candidates together, each tagged with why it was flagged.

**9:35 AM.** Claude reviews the shortlist and picks up to five. For each it records the opening range (the high and low of 9:30 to 9:35), an entry trigger (price breaks above the range high on rising volume), a stop (the range low or 1.5% below entry, whichever is closer), and a target or a trailing rule.

**Every five minutes until 3:55 PM.** The loop wakes, checks each open position against its stop and target, and asks Claude whether momentum has faded (a five-minute close back below the day's volume-weighted average price is the standard tell). New entries from the shortlist are allowed only until 11:00 AM. The caps below are checked before any order.

**3:55 PM.** Everything still open is sold at market. Then the Daily tab is filled in: equity, SPY close, alpha, commissions paid.

## Every parameter and its proposed value

| Parameter | Proposed | Notes |
|---|---|---|
| Paper starting balance | $100,000 | Paper account reset to this on day one |
| Max per position | 10% of equity | About $10,000 at the start |
| Max open positions | 5 | So at most half the account is at risk at once |
| Stop loss | 1.5% below entry, or the opening range low if closer | Hard, attached to the order as a bracket |
| Daily loss cap | 2% of equity | Hit it and the code halts new trades for the day, closes what is open |
| Flat by | 3:55 PM Eastern | Market orders |
| New entries allowed | 9:35 to 11:00 AM only | |
| Loop cadence | Every 5 minutes, market hours | |
| Universe | US-listed stocks and ETFs at IBKR | No international, no fixed income in month one |
| Price floor | $5 | |
| Volume floor | 1,000,000 shares average daily | |
| Shortlist size | 20 at most | |
| Shorting | Allowed (Mo, 2026-09-02) | Same caps as longs, stop 1.5% above entry or the range high if closer, easy-to-borrow names only, price floor $10 |
| Gross exposure cap | 100% of equity | Longs plus shorts added together may never exceed the account value. No margin borrowing for longs. Proposed backstop; 50% is the tighter alternative |
| Options | Not in month one | |
| Order types | Limit entries, bracket stops, market exits at close | |

## The pattern day trader rule, and why paper ignores it

US regulators call anyone who makes four or more round-trip day trades in five business days in a margin account a pattern day trader, and require that account to hold at least $25,000. Fall below it and the broker blocks day trading for 90 days. This strategy would trip the rule in its first week.

The paper account is exempt because it holds simulated money, and IBKR does not apply the rule there. That is fine for testing the logic, but it means month one says nothing about whether the strategy survives the rule with real money. If the test succeeds and we go live, the live account needs to stay comfortably above $25,000, or the strategy has to be reshaped to under four day trades a week.

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
