# Pre-open flow for the momentum books

Confirmed by Mo through the hub on 2026-09-06. The point is to have the opening range and the volume baseline ready at 9:35 without touching IBKR's historical-data pacing cap (about 60 requests in any 10 minutes) during the open itself.

## Timeline, Eastern time

1. **9:00 to 9:25, gap scan.** Run the pre-market gap scan every few minutes on pre-market prices and keep a candidate list of up to 100 names. Budget: each scan finishes in 5 seconds.
2. **9:00 to 9:25, history pulls.** For each new candidate pull the 14-day 5-minute history (relative-volume baseline for the 9:30 to 9:35 window) and the 14-day ATR inputs. Spread the requests evenly, never more than 4 a minute, so about 100 requests fit in 25 minutes with room under the cap. Cache every result on disk keyed by symbol and date under `output/preopen_cache/`, so a restart does not pull again. Budget: all pulls complete by 9:26.
3. **By 9:28, streaming quotes.** Subscribe streaming quotes for the final top-100 list (the feed allows 100 lines). The 9:30 to 9:35 opening range and its volume are built from live ticks, never from a historical request. Budget: subscriptions complete by 9:29.
4. **9:35, rank and decide.** Rank in memory by relative volume against the prior 14 days' same window (2x floor), apply the volatility filter and the direction rule, call the model, and have orders out by 9:36. Budgets: rank 2 seconds, model 45 seconds, orders sent by 9:36:30.
5. **Late gappers.** A name that appears after 9:28 joins only if a streaming line is free; otherwise it is logged as skipped with the reason.
6. **Timings.** Every step's start, end and duration are logged every day to `output/preopen_timings_YYYY-MM-DD.json` and summarised in the journal. Crossing any budget raises an alert naming the step. On Tuesday 2026-09-08 the actual timings are measured and recorded.

## What this replaces

The earlier design ran the scanner and its enrichment at 9:30 to 9:35, which would have spent most of the pacing budget in the five minutes where it is scarcest and made the 9:35 pick late on busy days.

## Where the code lives

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py` (to be written), driven by the tick loop from 9:00, with the scanner's filters reused from `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`.
