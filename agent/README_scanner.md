# The opening-momentum scanner

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`

## What it is for

Every morning a handful of stocks open with a jump and unusually heavy trading,
almost always because something happened overnight. Those are the only names
this strategy is interested in. This script finds them.

It asks IB Gateway two questions, checks the answers against the rules in the
strategy spec, and writes a shortlist of at most twenty names to a JSON file.
Claude reads that file at 9:35 AM and decides which of them, if any, are worth
trading. The script itself decides nothing and trades nothing.

**It does not place orders.** It makes exactly four kinds of call to Gateway,
all of them reads: run a scan, fetch price bars, look up what a ticker is, and
set whether it wants live or delayed prices. There is no order code in the file,
so there is nothing to accidentally fire.

It also connects with the read-only flag set. Worth being precise about that
flag, because it is easy to over-trust: it stops this script from touching or
asking about orders, but it does not make Gateway refuse an order that something
else sends. Gateway has its own read-only switch, `ReadOnlyApi` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/ibc.ini`,
and it is currently off. Turning that on is the setting that actually makes the
paper account unable to trade, and it is worth doing before the trading loop
goes live.

## How to run it

From the project folder:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py \
  --out output/shortlist_2026-09-02.json
```

Leave `--out` off and it writes to
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/shortlist_<today>.json`
on its own. The `output/` folder is not tracked by git.

IB Gateway has to be running and logged in first, which
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh`
handles.

Other switches, all optional:

| Switch | Default | What it does |
|---|---|---|
| `--out` | today's dated file in `output/` | where to write the shortlist |
| `--host` | `127.0.0.1` | where Gateway is |
| `--port` | `4002` | Gateway's API port. 4002 is the paper account |
| `--client-id` | `201` | the scanner's own API slot, so it does not clash with the trading loop |
| `--config` | `config/guardrails.yaml` | where to read the threshold numbers from |
| `--enrichment-cap` | `40` | how many scan hits to pull extra data for |
| `--history-budget` | `58` | ceiling on data requests in one run, to stay on Gateway's good side |
| `--reference-symbol` | `SPY` | the busy stock used to work out how far the day's data reaches |
| `--verbose` | off | prints every decision, including the names it threw out and why |

Progress goes to the terminal, not into the JSON file. The exit code is 0
whenever the scan ran, even if nothing survived the filters, because an empty
shortlist is a real and normal answer. It is 1 only when the script could not
reach Gateway at all.

## Where the numbers come from

If `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`
exists, the script reads four values out of it:

| Key in the YAML | Meaning | Falls back to |
|---|---|---|
| `universe.price_floor` | ignore anything cheaper than this | 5 dollars |
| `universe.min_avg_volume` | ignore anything that normally trades fewer shares a day | 1,000,000 |
| `scanner.rel_volume_min` | how many times its normal pace a name has to be trading | 2.0 |
| `scanner.max_candidates` | how long the shortlist can be | 20 |

Anything missing falls back to the number above. The script never writes to that
file. Another part of the project owns it.

## What it actually does, in order

1. Asks Gateway twice. Once for `TOP_PERC_GAIN`, the biggest percentage
   gainers, and once for `HOT_BY_VOLUME`, the names trading unusually heavily.
   Both are limited to US-listed shares and ETFs on the major exchanges, priced
   above the floor.
2. Merges the two lists by taking turns. First the names that showed up on
   both lists, then alternating down the two. This matters more than it sounds:
   stacking one list on top of the other and then trimming would throw the whole
   volume list away and leave only gainers.
3. Drops the obvious leveraged funds straight away, by ticker, before
   spending any data requests on them.
4. Keeps the first forty and looks up daily price history for each: what it
   is trading at now, what it closed at yesterday, how many shares have changed
   hands today, and its average daily volume over the last twenty completed
   sessions.
5. Applies the number filters: price above the floor, average daily volume
   above the minimum, relative volume above the threshold, and still up on the
   day. A name with fewer than ten completed sessions of history gets no
   average volume at all, so it fails this step. A stock listed last week has
   no normal to be unusual against, and averaging its first three days would
   dress up a wild number as a settled one.
6. Looks up what each survivor actually is and drops it if it is priced in
   anything but US dollars, if its home exchange is not one of NYSE, NASDAQ,
   ARCA, AMEX, BATS or IEX, or if it is a leveraged or inverse fund.
7. Ranks what is left, trims to the shortlist length, and only then fetches
   the opening five-minute range for the names that made it. Fetching last saves
   data requests, which are rationed.
8. Writes the JSON file.

### Relative volume, and why it is not just today's volume

A stock that has traded two million shares by 10 AM is behaving very differently
from one that has traded two million by 3 PM. So the script compares today's
volume against the volume you would *expect* by this point in the day: the
twenty-day average, scaled by how much of the 390-minute session has gone by. A
relative volume of 3.0 means three times the normal pace for the time of day.

The "how much of the session has gone by" figure comes from how far SPY's bars
actually reach, not from the clock on the wall. Delayed market data runs about
fifteen minutes behind, so trusting the clock would make every stock look
quieter than it really is.

### Leveraged and inverse funds

These move two or three times the market and are not what this strategy is
after, so they are excluded two ways. There is a list of the usual suspects by
ticker in the `LEVERAGED_INVERSE_TICKERS` constant near the top of the script,
covering TQQQ, SQQQ, SOXL, UVXY and about seventy others. Separately, any fund
whose full name contains a giveaway word gets dropped: 2X, 3X, Ultra, Inverse,
Bear, Bull, Leveraged or Short.

The name check is deliberately skipped for ordinary company shares, so a real
company called something like Bullfrog AI is not thrown out over a word in its
name. Only funds and other non-ordinary listings get the name treatment.

### The score

Names are ranked on percentage gain multiplied by the natural log of relative
volume. A big move on ordinary volume is not to be trusted, and heavy volume
with no price move is not a momentum trade, so multiplying the two rewards names
that have both. The log stops one enormous volume reading from swamping
everything else.

Names that are down on the day are removed outright, not just ranked low. The
volume scan flags plenty of stocks falling hard on heavy trading, and this
strategy only ever buys, so pairing one of those with a "break above the opening
high" instruction would be nonsense. That cut shows up as `passed_moving_up` in
the counts.

## What is in the JSON file

The top of the file describes the run:

| Field | Meaning |
|---|---|
| `timestamp` | when the scan finished, Eastern time |
| `timestamp_utc` | the same moment in UTC |
| `trade_date` | the trading day this shortlist belongs to |
| `market_data_type` | 1 live, 2 frozen, 3 delayed, 4 delayed frozen |
| `market_data_type_label` | the same thing in words |
| `data_as_of_eastern` | how recent the data actually is, which lags the timestamp on delayed data |
| `session_minutes_elapsed` | how many of the day's 390 trading minutes the data covers |
| `session_minutes_total` | always 390, the length of a normal session |
| `scan_codes` | which IBKR scans were run |
| `thresholds` | the numbers used, and whether they came from the YAML or the built-in defaults |
| `counts` | how many names survived each stage, explained below |
| `historical_requests_used` | how much of the data ration this run spent |
| `warnings` | anything that went wrong but did not stop the run |
| `candidates` | the shortlist |

`counts` is the useful one when a shortlist comes back shorter than expected,
because it shows exactly where the names went:

| Count | Meaning |
|---|---|
| `scanned_top_perc_gain` | rows returned by the gainers scan |
| `scanned_hot_by_volume` | rows returned by the volume scan |
| `merged_unique` | distinct names across both |
| `after_known_leveraged_tickers` | left after dropping known leveraged funds by ticker |
| `capped_for_enrichment` | left after trimming to forty |
| `daily_bars_ok` | how many returned usable price history |
| `passed_price_floor` | still above the price floor |
| `passed_avg_volume` | still above the average volume minimum |
| `passed_rel_volume` | still trading above the relative volume threshold |
| `passed_moving_up` | still up on the day rather than down |
| `passed_us_listing` | priced in dollars and listed on an allowed US exchange |
| `passed_leverage_name_filter` | left after the fund name check |
| `opening_range_ok` | how many returned a first five minutes to measure |
| `final` | how many made the shortlist |

Each entry in `candidates` looks like this:

| Field | Meaning |
|---|---|
| `symbol` | the ticker |
| `conId` | IBKR's own permanent id for the contract. Use this, not the ticker, when placing an order later. Tickers get reused |
| `primaryExchange` | the stock's home exchange |
| `last` | most recent traded price in dollars |
| `gain_pct` | percentage move from yesterday's close |
| `opening_range_high` | the highest price in the first five minutes. The entry trigger is a break above this |
| `opening_range_low` | the lowest price in the first five minutes. This is one of the two candidates for the stop |
| `volume_today` | shares traded so far today |
| `avg_volume_20d` | average shares traded per day over the last twenty completed sessions |
| `rel_volume` | today's volume divided by what would be normal by this time of day |
| `flagged_by` | which scans flagged it. Two entries is a stronger signal than one |
| `reasons` | short plain-language sentences explaining why it is on the list, meant to be read |
| `score` | the ranking number described above |
| `long_name` | the company or fund's full name |
| `stock_type` | `COMMON` for ordinary shares, `ETF` for a fund, and so on |

## Things worth knowing

**The scanner complains about permissions every single run.** Gateway returns
error 492, "you must subscribe for additional permissions to obtain precise
results for scanner", because the account has no live market data subscription.
The scan still returns results, they are just ranked off delayed prices. The
script takes that error as proof it is on delayed data, switches to delayed mode
and reruns the scans so the file honestly reports `market_data_type: 3`. Once Mo
subscribes to live data this should stop and the file should start saying 1.

**Error 162 appears twice a run and is harmless.** It says "API scanner
subscription cancelled". That is just Gateway confirming a one-shot scan has
finished. It is logged quietly along with the other status chatter.

**Gateway rations historical data,** to sixty requests in any ten minutes,
counted across the whole connection. Go over and it starts refusing requests for
everything, not just this script. That is why the run is capped at forty names,
and why the opening ranges are fetched last and only for the names that made the
shortlist.

The arithmetic is one request to check how current the data is, one per name
being checked, and one more per name that makes the shortlist. Forty names and a
full shortlist of twenty would be sixty one requests, one over the line, so the
budget stops at fifty eight. A normal run spends low fifties because the filters
thin the shortlist well below twenty. If the budget does run out, the names that
lose their data are the lowest-ranked ones, and `warnings` in the output says so
plainly rather than leaving you to guess. If you are running the scanner by hand
several times over, leave ten minutes between goes.

**`ETF.EQ.US` is not a usable scan location.** It looks like the obvious way to
scan ETFs, but Gateway answers "market scanner is not configured for one of the
chosen locations". ETFs come back inside the ordinary `STK` scan anyway, marked
`stock_type: ETF`.

**Scan results arrive nearly empty.** The rows Gateway returns carry a ticker
and a contract id and almost nothing else. No exchange, no company name. That is
why every name needs a separate lookup before the US-listing and leveraged-fund
checks can run.

**Delayed data cannot see the open in real time, and this is the big one.** The
account currently has no live data subscription, so everything Gateway hands
back runs about fifteen minutes behind. Run the scanner at 9:35 AM and the most
recent data available is from roughly 9:20, before the bell. There is no 9:30 to
9:35 range yet, barely any volume, and the shortlist will come back empty or
close to it. Nothing in the script can fix that. It is a data subscription
problem, and until Mo subscribes, the honest options are to run the scanner
around 9:50 and accept that it is judging the first five minutes fifteen minutes
late, or to treat the shortlist as after-the-fact research rather than a live
signal. Check `data_as_of_eastern` in the output to see how stale a given run is.

Relative volume still behaves sensibly on delayed data, for what it is worth,
because the script measures how far the data actually reaches and compares
today's volume against what would be normal by that same point. Both halves of
the ratio are equally stale, so they cancel out.

**Run it after 4 PM and the shortlist reflects the whole day, not the open.**
Relative volume is measured against the full session once the session is over,
and the "opening range" is still the real 9:30 to 9:35 range, but the price will
be the close. Useful for checking the script works. Not useful as a trading
signal.
