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

## Implementation notes

Written 2026-09-06. This section says what was actually built, where it puts its files, and what it cannot do yet.

**The code.** It is one file, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py`, with its tests in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_preopen.py`. It reads the broker and never touches an order. There is a test that reads the module's own text and fails if a future edit ever reaches for one of the order methods, so that promise is checked on every run rather than trusted.

**One tick at a time.** There is no long running process anywhere in this project. launchd wakes `agent/loop.py`, the loop does the one thing that belongs to that minute, and the process exits. So `preopen.py` is written the same way. Its entry point is `step(now, broker)`: it looks at the clock and at what is already on disk, works out what this single tick owes, does that much, saves what it learned, and returns. Nothing sleeps and there is no waiting loop.

Everything that has to survive from one tick to the next lives in one file a day, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/preopen_state_2026-09-08.json` and one like it for every other date. It holds the candidate list, which names already have their history saved, when each historical request went out, the watch list, and the shortlist once it has been made.

**The pre-open wants a wake up every minute.** The pacing rule is four historical requests a minute, and a tick cannot send more than that because the tick is over in a second or two. Twenty six ticks between 9:00 and 9:26, four requests each, is about a hundred requests, which is exactly the arithmetic in the timeline above. Wake it every five minutes instead and the same window only pays for about twenty requests, and most of the candidate list reaches 9:35 with nothing behind it. So the launchd job for the pre-open window fires every minute, not every five. That line is `every 1 minute from 09:00 to 09:26 on weekdays` in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/templates/tick.template`, added on 2026-09-06, and it took the tick job from 84 wake ups a day to 110.

One honest correction to the timeline. Each name needs two requests, the five minute bars for the volume baseline and the daily bars for the average true range, so a hundred requests covers about fifty names rather than a hundred. The candidate list still holds up to a hundred, ordered biggest gap first, and any name that never gets its history is written down as not rankable rather than quietly dropped.

**The honest limit on the streaming step.** A streaming subscription belongs to a process, and this process exits a second after it starts, at which point the Gateway closes every line it opened. So the 9:28 step does not really subscribe to anything, and the code says so in as many words. What it really does is settle which names the 9:35 ranking is about and record which of them would have claimed a line, including the rule that a Gateway reporting fewer than a hundred lines leaves us keeping the top sixty.

That means the 9:30 to 9:35 candle is not built from live ticks. It is read back out of the five minute bars instead, one request per name at 9:35, capped at forty so the burst cannot break the ration. By then the pre-open pulls have been finished for nine minutes, so the ten minute window is nearly empty again and forty is safe. This is the halfway version and it is labelled as one in the code. A genuinely streaming opening range needs a process that stays alive from 9:28 to 9:35, and there is not one yet. When there is, it writes its candles to `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/preopen_opening_range_2026-09-08.json` and the ranking already prefers that file over asking for bars, so the change is one new process rather than a rewrite.

**Where the files go.** All of it under `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`:

- the cache, one small file per symbol per day per kind, in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/preopen_cache/`, named like `AAPL_2026-09-08_bars5m.json` and `AAPL_2026-09-08_daily.json`. A restart reads these instead of asking again, which is what makes a crash at 9:14 cheap. A file that cannot be read counts as a miss and costs one extra request, never an error.
- the day's state, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/preopen_state_2026-09-08.json`.
- the day's timings, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/preopen_timings_2026-09-08.json`, holding one entry per step with its start, its end, how long it took, what it was allowed, and whether it went over.

**The budgets, and what happens when one is crossed.** Six of them, and they are two different kinds of thing. Three are durations, meaning the step itself must not take longer than that: the gap scan five seconds, the ranking two seconds, the model call forty five seconds. Three are wall clock deadlines, meaning the step must be finished by that time whatever it took: the history pulls by 9:26, the streaming step by 9:29, the orders sent by 9:36:30. The last two of the six belong to `agent/loop.py` rather than to this file, which never asks a model anything and never sends an order, but they are defined in one place so the loop can stamp its own two steps into the same timings file.

Crossing any of them writes the step down as over budget and raises an alert naming it, through `agent/alerts.py`, which is the channel everything else in this project already uses: iMessage, Slack, a macOS banner, and a line in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/alerts.log`. No new alert channel was invented for this, because an alert in a second place is an alert that gets missed. The alert line is also written into the timings file itself, so the record survives a morning when every channel is down. A morning where nothing gapped and nothing needed pulling is not treated as a missed deadline, because an alarm that cries wolf is one that gets ignored on the day it matters.

**Running it by hand with the market shut.** No broker is attached, so nothing reaches the network:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py \
  --now "2026-09-08 09:12"
```

That prints which phase of the morning that time falls in, what the tick would do, where every file goes, and all six budgets. Change the time to 09:28 or 09:35 to see the other phases. It writes its state and timings into `output/` exactly as a real tick would, so it is a genuine rehearsal rather than a print out. To keep the real `output/` folder untouched, point it somewhere else first:

```
AGENTIC_TRADING_ROOT=/tmp/preopen_rehearsal \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py --now "09:12"
```

The tests are the other way to see it work, and they run a whole morning against handmade bars in a fraction of a second:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_preopen.py -q
```
