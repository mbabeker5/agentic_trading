# Strategy spec: Congress trades

Status: draft for Mo's approval, written 2026-09-06. Nothing here trades until Mo says the numbers are right. Companion to `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`, which describes the shared machinery.

## The idea in one paragraph

Members of the US House and Senate must disclose their stock trades under the STOCK Act. Some sit on committees that write the rules for the industries they trade in, and a few have records professional managers would envy. This book buys what members buy, weighting large trades, committee links to the company's sector, and several members buying the same name. It holds for weeks. The honest framing: a bet that what a member knew when they bought is still worth something once the public finds out.

## The signal

Source document: the Periodic Transaction Report (PTR) each member files. What counts:

- **Purchases only.** Sales are excluded for the same reason as in the insider book, people sell for many reasons.
- **Size band.** Members disclose ranges, not amounts: $1,001 to $15,000, $15,001 to $50,000, $50,001 to $100,000, and so on up to over $1,000,000. Score rises with the band. A buy in the lowest band by itself does not qualify.
- **Committee relevance.** A member of Armed Services buying a defence contractor, or of Energy and Commerce buying a pharma name, scores higher than the same trade by a member with no committee link. The code keeps a table of committees to sectors; Claude judges the borderline cases.
- **Crowding.** Two or more members buying the same stock within 30 days raises the score. One member alone in the lowest two bands does not qualify.
- **Spouse and dependent trades count**, since the form covers them and many of the most-watched trades are filed that way.

## The data path

The official sources are free but painful. The House Clerk's site publishes PTRs as PDFs, some of them scanned handwriting. The Senate's electronic filing site is a web form with no download API. Parsing those directly is a project in itself, so the code goes to free mirrors first:

1. **House Stock Watcher and Senate Stock Watcher.** Community projects that parse the official filings into clean JSON, published on GitHub and refreshed roughly daily. First stop. Their weakness is that they are volunteer-run and have had gaps; the code checks the last-updated date and flags staleness beyond three days.
2. **Capitol Trades.** A free website with a clean, searchable table updated through the day, useful for cross-checking and for committee metadata. It has no public API, so the code reads it only as a fallback and never depends on it.
3. **Paid fallback, if the free mirrors fail during the month:** Quiver Quantitative offers a congressional trading API on a paid plan in the tens of dollars a month, updated within hours of a filing. Finnhub has a similar endpoint. Neither is switched on until needed.

Whatever the source, the code records both dates for every trade: the date the member traded and the date the filing appeared. The gap between them is the strategy's central problem.

## The timing problem, in plain words

Members have up to 45 days to disclose, and most use a good part of it, so a purchase that shows up this morning was made three to six weeks ago and the price has had time to react. The strategy is not "trade what they trade" but "trade what they traded, if the reason still holds". A defence stock bought ahead of a months-long budget cycle may still be worth following. A stock bought ahead of an announcement that already happened is not. Telling those apart is Claude's job, and the trailing stop exists because it will often be wrong.

## The day

**7:30 AM Eastern, disclosure sweep.** Pull new filings from the mirrors. Keep purchases. Score by band, committee link and crowding. Apply the floors below. Output a shortlist of at most 15 with reasons, each carrying the trade date and the filing date.

**9:45 AM, Claude reviews.** With the shortlist, price charts since the member's trade date, committee context, and any headline, Claude picks up to two new names for the day, writes a rationale for each pick and each skip, and sets a limit at or below the last close plus 1%. A stock that has already run more than 15% since the member bought is a skip by default; Claude may override with a written reason.

**Through the day, every 30 minutes.** Manage open positions: hard stop, trailing stop, time stop. Day limit entries are cancelled unfilled at 3:50 PM.

This book holds overnight and for weeks. **It is exempt from the 3:55 PM flat rule.** Its risk lives in the per-position stop and the book-level daily loss cap.

## Every parameter and its proposed value

| Parameter | Proposed | Notes |
|---|---|---|
| Book size | $100,000 | Virtual book inside the paper account |
| Position size | 5% of book, about $5,000 | |
| Max open positions | 10 | |
| New entries per day | 2 at most | The signal is thin; most days there is nothing worth buying |
| Hard stop | 10% below entry | Wider than the insider book because these are held longest |
| Trailing stop | 12% below the highest close since entry, active once the position is up 10% | |
| Target | None fixed | |
| Time stop | 60 trading days | About three months, since the edge, if any, is slow |
| Daily loss cap | 2% of this book, per book | Halts new entries for the day and closes what is open |
| Price floor | $10 | |
| Liquidity floor | 1,000,000 shares average daily volume | Members mostly buy large caps, and it keeps paper fills honest |
| Minimum band to count | $15,001 to $50,000 alone, or $1,001 to $15,000 when two or more members bought | |
| Staleness limit | Skip trades more than 60 days old on arrival | Late filers |
| Shorting | No, long only | |
| Order types | Limit entries, stops held in code, market exits on time stop | |

## What the code enforces versus what Claude decides

**Code:** the sweep, the scoring table, staleness, every cap above, the stops, the time stop, the daily loss cap, the order reference tag, the ledger.

**Claude:** whether the reason behind a buy still stands weeks later, which qualifying names to take and why, whether a committee link is real. Every pick and skip gets a written reason.

## How this book fits the virtual-book design

Its folder is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/congress/`, holding `strategy.yaml` (every number above, plus `holds_overnight: true`), `prompt.md`, and a `model` field. Every order carries the IBKR order reference `CONGRESS`. Equity, positions and the daily loss cap are tracked separately from the other books in the ledger.

## Known weaknesses

- **Stale by design.** The 45-day window is the whole difficulty. Studies of Congress trading since the 2012 STOCK Act find the average member does not beat the market, and the famous outperformers are a handful of people.
- **Few trades.** Many days the sweep will find nothing that qualifies. A month may produce ten positions. The sample is small and the results will be noisy.
- **Data quality.** Free mirrors miss filings, misread PDFs and sometimes stop updating. The code flags staleness, but it cannot see what a mirror never parsed.
- **Attention crowding.** Congress trades are popular content. By the time a filing is public, retail traders have often already piled in, which is part of why the 15% run-up skip rule exists.

## How we judge month one

Operations first, as in the main spec: every sweep ran, staleness flagged, no cap breached, every fill and decision logged with a reason, positions reconciled daily against the broker.

Returns second, with the same caveat as the insider book: 60-day holds mean the month ends with nearly everything open. Judge on mark-to-market equity against SPY and the other books, and on whether the data path held up. If the mirrors failed more than twice, month two starts with a paid feed or the book is parked.
