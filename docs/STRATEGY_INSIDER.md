# Strategy spec: insider buying

Status: draft for Mo's approval, written 2026-09-06. Nothing here trades until Mo says the numbers are right. Companion to `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`, which describes the shared machinery.

## The idea in one paragraph

Executives and directors must tell the SEC within two business days whenever they trade their own company's stock. Sales tell you little, people sell for houses and taxes. Open-market buys are different: someone already paid in salary and options chose to put more of their own cash in. When several do it in the same week, or the CEO buys big relative to what they hold, the stock has historically beaten the market over the following months. This book buys those situations, holds for days to weeks, and exits on a stop or a clock.

## The signal

Source document: SEC Form 4. What counts:

- **Transaction code P only.** That is an open-market or private purchase for cash. Everything else is noise for our purpose: option exercises (code M), awards (A), gifts (G), tax withholding (F).
- **No pre-scheduled trades.** Since 2023 the form has a checkbox for trades made under a Rule 10b5-1 plan, which are set months ahead and carry no fresh opinion. Any buy with that box ticked is excluded.
- **Weighting.** Three things raise a filing's score: a cluster, meaning two or more distinct insiders buying within ten trading days; the buyer's role, with CEO and CFO buys worth roughly double a director's; and size, both relative to the insider's existing holding (a 20% increase says more than 1%) and relative to the stock's daily dollar volume (a buy worth a day of trading is a statement, a buy worth a minute is not).

## The data path

SEC EDGAR is free, needs no account, and publishes a filing to its feeds within minutes of acceptance. The code uses three pieces of it:

1. **The latest-filings feed**, filtered to form type 4, polled every 15 minutes during EDGAR's acceptance hours of 6 AM to 10 PM Eastern. Filings accepted after 5:30 PM carry the next day's filing date but appear on the feed the same evening, so an evening sweep catches them for the next morning.
2. **The Form 4 XML document** inside each filing. It is structured, not a PDF, so transaction code, price, share count, the 10b5-1 checkbox, the insider's title and post-trade holdings all parse cleanly.
3. **The submissions API** at data.sec.gov for each company, to fetch recent history and count the cluster.

Optional paid signal source, off until Mo buys it: Quiver Quantitative (API Hobbyist $30 a month, Trader $75, has an official MCP, no quotes) behind a config flag. Free official sources stay primary. EDGAR allows ten requests a second with a descriptive User-Agent header. The free OpenInsider screener shows the same purchases and is a handy cross-check, but it is a website, not an API, so the code does not depend on it.

## The day

**7:00 AM Eastern, morning sweep.** Parse every Form 4 accepted since the previous sweep. Keep code P buys with the plan checkbox unticked. Score and group by company. Apply the floors below. Output a shortlist of at most 15 with the reason each was flagged.

**9:45 AM, Claude reviews.** With the shortlist, each company's recent price chart, the insider's history (does this person buy often, or is this rare) and any headline, Claude picks up to three new names for the day, writes a rationale for each pick and each skip, and sets a limit price at or below the last close plus 1%.

**Through the day, every 30 minutes.** Manage open positions: hard stop, trailing stop, target, time stop. Entries stay working as day limit orders and are cancelled unfilled at 3:50 PM.

**4:30 PM, afternoon sweep.** Same parse for filings accepted during the day. Anything that qualifies waits for the next morning's review. No after-hours orders.

This book holds overnight and for weeks. **It is exempt from the 3:55 PM flat rule** that governs the opening-momentum book. Its risk lives in the per-position stop and the book-level daily loss cap instead.

## Every parameter and its proposed value

| Parameter | Proposed | Notes |
|---|---|---|
| Book size | $100,000 | Virtual book inside the paper account |
| Position size | 5% of book, about $5,000 | Smaller than the day-trading book because positions are held through news and overnight gaps |
| Max open positions | 10 | Half the book invested at full load |
| New entries per day | 3 at most | Keeps Claude choosing rather than collecting |
| Hard stop | 8% below entry | Held overnight, so wider than intraday |
| Trailing stop | 10% below the highest close since entry, active once the position is up 8% | Lets a winner run, locks in part of it |
| Target | None fixed | The trailing stop and the time stop do the exiting |
| Time stop | 30 trading days | Out regardless of price, the edge decays |
| Daily loss cap | 2% of this book, per book | Halts new entries for the day and closes what is open |
| Price floor | $5 | |
| Liquidity floor | 500,000 shares average daily volume | Insider buys skew small, so this is lower than the momentum book's floor |
| Minimum buy size to count | $25,000 per filing, or $10,000 each inside a cluster | Filters token purchases |
| Shorting | No, long only | Insider selling is not a usable signal |
| Order types | Limit entries, stop orders held in code, market exits on time stop | |

## What the code enforces versus what Claude decides

**Code:** the sweep, filters, scoring, every cap above, the stops, the time stop, the daily loss cap, the order reference tag, the ledger. Nothing Claude says can move a number in the table.

**Claude:** which qualifying names to buy today and why; whether a filing looks like conviction or a director topping up to meet an ownership guideline; whether a headline explains the buy away. Every pick and skip gets a written reason.

## How this book fits the virtual-book design

Its folder is `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/insider/`, holding `strategy.yaml` (every number above, plus `holds_overnight: true`), `prompt.md` (the judgment layer, with the yaml values injected), and a `model` field naming the brain, for example `anthropic/claude-fable-5-1`. Every order carries the IBKR order reference `INSIDER`, so fills are attributed to this book and never confused with the others sharing the paper account. Its equity, positions and daily loss cap are tracked separately in the ledger.

## Known weaknesses

- **Insiders are early.** They buy because they think the stock is cheap, not because it is about to move. The historical edge shows up over three to twelve months. A one-month test catches only the front of that.
- **The signal is slow.** Two business days from trade to filing, and the market reads the same filing we do. Any edge is in judgment about which buys matter, not in speed.
- **Small caps dominate.** Big-company insiders rarely buy in the open market. Expect thin names, wide spreads and paper fills that flatter reality.
- **Backtests lie a little.** Published studies on insider buying suffer from survivorship, since companies that went bust drop out of the data. The proposed stops exist because of that.

## How we judge month one

Operations first, exactly as in the main spec: every sweep ran, no cap breached, every fill and decision in the ledger with a reason, positions reconciled daily against the broker.

Returns second, with a caveat: 30-day holds mean most positions are still open at month end. Judge on mark-to-market equity against SPY and the other books, and on pick quality (how many stopped out fast). Carrying this book into month two should not require it to have beaten the day-trading book in four weeks.
