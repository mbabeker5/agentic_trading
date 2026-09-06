# The opening-momentum scanner

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`

## What it is for

Every morning a handful of stocks open with a jump and unusually heavy trading,
almost always because something happened overnight. Those are the only names
this strategy is interested in. This script finds them.

It asks IB Gateway five questions, checks the answers against the rules in the
strategy spec, and writes a shortlist of at most twenty names to a JSON file.
Claude reads that file at 9:35 AM and decides which of them, if any, are worth
trading. The script itself decides nothing and trades nothing.

Both directions are on the list. Names off IBKR's gainers list are tagged
`long`, names off its fallers list are tagged `short`, and each row carries that
tag under both `direction` and `side` so whichever field the next step reads, it
reads the right one. Note that shorting itself was deferred to month two by the
review team on 2026-09-06, so `allow_shorts` is false in both momentum book
files and the loop will not act on a short even though the scanner finds them.
The shortlist is honest about what is there; the book decides what to do with it.

## The one thing to understand before anything else

**This script sends no filters to IB Gateway. Not one.** No `priceAbove`, no
`stVolume5MinAbove`, no `marketCapAbove`, no `volumeAbove`. Every rule in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`
is applied here, in our own code, against real daily bars.

The reason is a measurement, not a preference. On the morning of 2026-09-06,
against this account, every filter tag we tried made the scan return **zero
rows**, and the only sign of trouble was IBKR error 162, "Scanner filter X is
disabled", arriving in a callback nothing was reading, followed by 365 on the
same request. Nothing raised. Nothing logged at warning level. The caller saw an
empty list, and an empty list is also exactly what a morning when nothing gapped
looks like. The same scan with no filters returned 50 rows in under a second.

A loop that believed that empty list would have sat out the whole month and
reported "no candidates" every single day.

It got more interesting the same afternoon, after Mo paid for market data. Run
again at 13:40 Eastern on 2026-09-06, the same account gave a **mixed** answer:

| Filter tried | Rows back | Errors |
|---|---|---|
| none at all | 50 | the benign 162 only |
| `priceAbove 5` | 50 | the benign 162 only |
| `volumeAbove 1000000` | 50 | the benign 162 only |
| `stVolume5MinAbove 100000` | **0** | 162 then 365 |
| `marketCapAbove 1000000000` | **0** | 162 then 365 |

Two of the four now work and two still return nothing, including
`stVolume5MinAbove`, which is precisely the filter a 9:35 gap scan would most
want. That mixture is worse than all of them being off, because there is no way
to tell from a result which kind you got. So the rule stands and is not up for
review: whatever IBKR is willing to filter on today, we filter here.

The pre-flight records the current answer every morning without changing what
the scanner does. See "The filter probe" further down.

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
| `--enrichment-cap` | `35` | how many scan hits to pull extra data for, best ranked first |
| `--history-budget` | `55` | ceiling on historical data requests in one run, to stay on Gateway's good side |
| `--reference-symbol` | `SPY` | the busy stock used to work out how far the day's data reaches |
| `--verbose` | off | prints every decision, including the names it threw out and why |

Progress goes to the terminal, not into the JSON file.

### Exit codes

| Code | Meaning | What to do |
|---|---|---|
| `0` | the scan ran and could be believed, even if nothing survived the filters | nothing. An empty shortlist is a real and normal answer, especially before the open |
| `1` | could not reach Gateway at all | start Gateway with `agent/start_gateway.sh` |
| `3` | a scan could not be believed, so **nothing was written** | look at the error codes on the last line of stderr. The previous shortlist is untouched |

Code 3 is the one that matters. When it happens the script writes no file at
all, deliberately, so whatever shortlist was there before is still there. An
empty file and a broken scanner must never look the same to the loop, and an
empty file is what you get if you write one anyway. Before exiting it prints a
line on stderr beginning `SCAN_FAILURE_JSON `, holding the IBKR error codes and
messages, the per-scan diagnostics and the path that was left alone. The
pre-flight reads that line and puts the codes straight into the alert.

## Where the numbers come from

If `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`
exists, the script reads four values out of it:

| Key in the YAML | Meaning | Falls back to |
|---|---|---|
| `universe.price_floor` | ignore anything cheaper than this | 5 dollars |
| `universe.min_avg_dollar_volume` | ignore anything that normally trades less than this many dollars a day | 20,000,000 |
| `universe.dollar_volume_sessions` | how many completed sessions that average covers | 30 |
| `scanner.rel_volume_min` | how many times its normal pace a name has to be trading, measured at 09:35 | 2.0 |
| `scanner.max_candidates` | how long the shortlist can be | 20 |
| `scanner.finviz.enabled` | whether to cross-check against a Finviz Elite export | `false` |
| `scanner.finviz.export_url` | the whole Finviz export link | empty |
| `scanner.finviz.auth_token_key` | which key in `.secrets/finviz.env` holds the token | `FINVIZ_AUTH_TOKEN` |
| `scanner.finviz.secrets_file` | which file inside `.secrets/` to read it from | `finviz.env` |

Anything missing falls back to the value above. The script never writes to that
file. Another part of the project owns it.

`universe.min_avg_volume`, the old floor of a million shares a day, is still
read and still written into the output so an old run can be read back, but
nothing filters on it any more. See the next section for why it changed.

## What it actually does, in order

1. Runs the control scan, `MOST_ACTIVE`, with no filters. It exists to answer
   one question: is IBKR's scanner service actually answering this account at
   all? The market is never empty, so fewer than twenty rows back means nothing
   that follows can be believed.
2. Runs four more scans, all unfiltered, one at a time:

   | Scan code | What it is | Direction it implies |
   |---|---|---|
   | `TOP_PERC_GAIN` | biggest percentage gainers | long |
   | `TOP_PERC_LOSE` | biggest percentage fallers | short |
   | `HOT_BY_VOLUME` | names trading unusually heavily | neither, on its own |
   | `HIGH_STVOLUME_5MIN` | heaviest five minute volume | neither, on its own |

   All four are limited to US-listed shares and ETFs on the major exchanges,
   which is a location, not a filter, and is honoured. `TOP_OPEN_PERC_GAIN` is
   never used and a test enforces that: IBKR staff confirmed it returns nothing
   before the regular session is properly under way, which is the one moment
   this scanner runs. All four codes were confirmed present on this Gateway on
   2026-09-06 by reading `ib.reqScannerParameters()`, which listed 527 codes.
3. Puts every one of those five results through
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scan_truth.py`,
   which raises rather than hand back a result that cannot be believed. See
   "How a scan is checked" below.
4. Merges the lists by taking turns. First the names more than one scan flagged,
   in their best rank order, then alternating down the four. This matters more
   than it sounds: stacking the lists and then trimming would throw the last one
   away entirely and leave only gainers.
5. Adds the Finviz Elite names, if that cross-check is switched on. It is off.
6. Drops the obvious leveraged funds straight away, by ticker, before
   spending any data requests on them.
7. Keeps the first thirty-five and looks up daily price history for each: what it
   is trading at now, what it closed at yesterday, how many shares have changed
   hands today, its average daily dollar volume over the last thirty completed
   sessions, and its average daily share volume over the last twenty.
8. Applies the number filters, all of them here rather than at Gateway: price
   at or above the floor, average daily dollar volume at or above the liquidity
   floor, and relative volume at or above the threshold. All three are "at or
   above", not "above", which is what the numbers in the spec mean. A name with
   fewer than ten completed sessions of history gets no average at all, so it
   fails this step. A stock listed last week has no normal to be unusual
   against, and averaging its first three days would dress up a wild number as a
   settled one.
9. Settles each name's direction and drops the ones that contradict themselves.
   See "Long and short" below.
10. Looks up what each survivor actually is and drops it if it is priced in
    anything but US dollars, if its home exchange is not one of NYSE, NASDAQ,
    ARCA, AMEX, BATS or IEX, or if it is a leveraged or inverse fund.
11. Ranks what is left, trims to the shortlist length, and only then fetches
    the opening five-minute range for the names that made it. Fetching last
    saves data requests, which are rationed.
12. Writes the JSON file. Unless a scan failed, in which case it writes nothing
    and exits 3.

## How a scan is checked

Every scan, including the control, goes through
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scan_truth.py`
before a single row of it is believed. Four rules, and any one of them failing
raises `ScanFailure`, which becomes exit code 3 and no written file:

1. **Errors are captured against the scan's own request id.** IBKR sends the
   rows and its complaint about them separately, on different callbacks, so the
   complaint is matched back to the request that caused it. There is a 0.3
   second wait after each scan for late callbacks to catch up, because reading
   the errors immediately sometimes finds none and calls a broken scan healthy.
2. **The control has to come back with at least twenty rows.** The market is
   never that empty.
3. **The end-of-scan signal has to arrive inside thirty seconds.**
4. **Any of IBKR 162, 165, 365 or 492 on the request fails it,** as does an
   empty result with any error attached at all.

The one message that is allowed through is 162 "API scanner subscription
cancelled", which IBKR sends to confirm a finished one-shot scan has closed. It
arrives on every healthy scan and is recognised by its text.

Because the scans run one at a time rather than together, a slow morning takes a
few seconds longer. That is the price of knowing whose error is whose: ib_async
hands out request ids from a counter, and reading that counter to match errors to
scans only works while one request is in flight.

## Long and short

A gainers scan says a name is going up. A fallers scan says it is going down. A
volume scan says a name is busy and nothing at all about direction. So:

- flagged by `TOP_PERC_GAIN` only, direction is `long`
- flagged by `TOP_PERC_LOSE` only, direction is `short`
- flagged only by the volume scans, direction comes from the sign of the name's
  own move on the day
- flagged by both a gainers and a fallers scan, which should not happen but
  might, direction again comes from its own move, because its own price is
  better evidence than a list it appeared on

Then a name whose own move contradicts its tag is **dropped**, not shortlisted.
A name off the gainers list that is actually down on the day would otherwise get
a "break above the opening high" trigger pointing the wrong way, which is worse
than not listing it. That cut shows up as `passed_direction_agrees` in the
counts.

The score is the **size** of the move times the log of relative volume, not the
signed move. Ranking on the signed number would sort every short to the bottom
and the shortlist cap would then throw them all away.

The short price floor of 10 dollars in the book files is deliberately **not**
applied here. The scanner writes one shortlist that books A, B and E all read,
and a per-book rule belongs to the book, not to the shared list.

## The filter probe in the pre-flight

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py`
runs a sixth check every morning called `scanner_filters_enabled`. It sends two
filtered scans, `priceAbove 5` and `stVolume5MinAbove 100000`, through the same
truth check, and writes down whether each one worked. It **never fails the
morning**, whatever it finds, because a false is the state the scanner is
already built for and a true would be good news rather than an emergency.

Read the answer in `scanner_filters_enabled` at the top of
`output/preflight_YYYY-MM-DD.json`, and the per-filter detail in
`checks.scanner_filters_enabled.facts.probes`. Two filters rather than one
because on 2026-09-06 the two disagreed with each other, hours apart, on the
same account.

### The liquidity floor, in dollars rather than shares

Mo changed this on 2026-09-06. The floor used to be a million shares a day. It
is now 20 million dollars a day, averaged over the last thirty completed
sessions, worked out as each session's closing price times that session's
volume.

The reason is that a share count does not mean anything on its own. A million
shares of a 6 dollar stock is 6 million dollars of trading, and a million shares
of a 600 dollar stock is 600 million. The second one can absorb our order
without moving the price and the first one cannot, but the old rule treated them
as the same and, worse, threw out plenty of perfectly liquid expensive names
that trade far fewer than a million shares.

The new floor is also the wider one. A census run on 2026-09-04, which lives in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/liquidity_census/`,
found about 2,700 US names above 20 million dollars a day against about 1,950
above a million shares a day. So the new floor lets more names through than the
old one did, and measures the right thing while it does it.

Two consequences worth knowing about:

- **Nothing is filtered at Gateway any more, volume included.** Two separate
  reasons, and either alone would be enough. Gateway's own scanner can filter on
  a share count and has no dollar volume filter at all, and a share count cannot
  stand in for one: 20 million dollars is 4 million shares at 5 dollars and 40
  thousand shares at 500, so any share floor loose enough to keep the expensive
  names would let everything else through as well. And separately, a Gateway
  filter can be silently switched off by a subscription, as the top of this
  document sets out. Even the price floor, which does mean the same thing either
  way, is applied here rather than sent.
- **The daily history request grew from 40 days to 60.** Thirty trading sessions
  is about forty four calendar days, so the old request would have come up
  short. Sixty calendar days is roughly forty two sessions, which leaves room
  for holidays and for today's own part-formed bar.

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

**The floor is anchored at 09:35.** Mo's rule of 2026-09-06 is a statement about
one moment: the volume traded by 9:35, five minutes after the open, has to be at
least twice the stock's normal volume for that point in the day. Five minutes is
five three hundred and ninetieths of a session, so a name that normally trades a
million shares a day would normally have done about 12,800 by then, and it needs
about 25,600 to clear the floor.

The output says so out loud. Every run writes `rel_volume_anchor_eastern`,
`rel_volume_anchor_minutes` and `rel_volume_anchor_reached` at the top of the
JSON file, and each candidate carries `rel_volume_minutes_elapsed`, the number of
minutes of data its own ratio was actually measured over. If the data has not
reached 9:35 yet, which is what happens every time the scanner is run at 9:35 on
a delayed feed, a warning says so in plain words rather than letting the
shortlist imply a measurement that was never taken.

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

Names are ranked on the size of the day's move multiplied by the natural log of
relative volume. A big move on ordinary volume is not to be trusted, and heavy
volume with no price move is not a momentum trade, so multiplying the two
rewards names that have both. The log stops one enormous volume reading from
swamping everything else.

The size of the move, not the signed move. A stock down 9 percent on five times
its normal volume is as good a short as the mirror image is a long, and ranking
on the signed number would sort every short to the bottom of the list where the
cap would throw it away.

Names whose own move contradicts the scan that flagged them are removed
outright, not just ranked low. That cut shows up as `passed_direction_agrees` in
the counts, and "Long and short" above explains it.

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
| `rel_volume_anchor_eastern` | always `09:35`, the moment the relative volume floor is about |
| `rel_volume_anchor_minutes` | always 5, the same thing in minutes past the open |
| `rel_volume_anchor_reached` | whether the data actually reached 9:35. False means the ratios below were measured on less trading than the rule intends |
| `scan_codes` | the four IBKR scans that fed the shortlist |
| `control_scan_code` | the fifth scan, the one that proves the scanner is answering |
| `scan_filters_sent` | always `[]`, and a test keeps it that way |
| `scan_diagnostics` | one block per scan, explained below |
| `finviz` | whether the cross-check ran, and what it added |
| `thresholds` | the numbers used, and whether they came from the YAML or the built-in defaults |
| `counts` | how many names survived each stage, explained below |
| `scanner_requests_used` | how many of the five scanner requests were spent |
| `historical_requests_used` | how much of the historical data ration this run spent |
| `total_requests_used` | the two added together |
| `total_request_ration` | always 60, Gateway's ten minute allowance |
| `warnings` | anything that went wrong but did not stop the run |
| `candidates` | the shortlist |

`scan_diagnostics` is keyed by scan code, and each block holds:

| Field | Meaning |
|---|---|
| `role` | `control` for the control scan, `candidate source` for the other four |
| `direction` | `long`, `short`, or null for a volume scan that implies neither |
| `rows` | how many rows came back |
| `elapsed_s` | how long the request took |
| `completed` | whether the end-of-scan signal arrived in time |
| `req_id` | the IBKR request id, so an error can be matched to its scan |
| `filters` | always empty |
| `errors` | every error IBKR sent on that request id, as code and message |

A healthy scan carries exactly one error: 162 "API scanner subscription
cancelled", which is IBKR confirming the one-shot scan closed. Anything else
there, and in particular a 162 saying "disabled", a 165 or a 365, means the run
should not have been believed, and the pre-flight fails the morning on it.

`counts` is the useful one when a shortlist comes back shorter than expected,
because it shows exactly where the names went:

| Count | Meaning |
|---|---|
| `scanned_top_perc_gain` | rows returned by the gainers scan |
| `scanned_top_perc_lose` | rows returned by the fallers scan |
| `scanned_hot_by_volume` | rows returned by the heavy volume scan |
| `scanned_high_stvolume_5min` | rows returned by the five minute volume scan |
| `merged_unique` | distinct names across all four, plus Finviz if it is on |
| `after_known_leveraged_tickers` | left after dropping known leveraged funds by ticker |
| `capped_for_enrichment` | left after trimming to thirty-five |
| `daily_bars_ok` | how many returned usable price history |
| `passed_price_floor` | still at or above the price floor |
| `passed_dollar_volume` | still at or above the 20 million dollar average daily liquidity floor |
| `passed_rel_volume` | still trading at or above the relative volume threshold |
| `passed_direction_agrees` | the name's own move agrees with the scan that flagged it |
| `passed_us_listing` | priced in dollars and listed on an allowed US exchange |
| `passed_leverage_name_filter` | left after the fund name check |
| `opening_range_ok` | how many returned a first five minutes to measure |
| `final` | how many made the shortlist |
| `final_long` | of those, how many are long candidates |
| `final_short` | and how many are short candidates |

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
| `avg_volume_20d` | average shares traded per day over the last twenty completed sessions. Only the bottom half of the relative volume ratio, which is shares against shares. Nothing is filtered on it |
| `avg_dollar_volume` | average dollars traded per day over the last thirty completed sessions. This is the liquidity floor's number |
| `avg_dollar_volume_sessions` | how many completed sessions that average actually used, which is fewer than thirty for a recent listing |
| `rel_volume` | today's volume divided by what would be normal by this time of day |
| `rel_volume_minutes_elapsed` | how many minutes of trading that ratio was measured over. 5 means it was measured at the 9:35 anchor the rule is about |
| `direction` | `long` or `short`. Which way this name is a candidate |
| `side` | the same value again, because the loop reads `side` and the decision code reads either |
| `flagged_by` | which scans flagged it. Two entries is a stronger signal than one |
| `scan_rank` | the best place it took on any scan, 0 being the top of a list |
| `reasons` | short plain-language sentences explaining why it is on the list, meant to be read |
| `score` | the ranking number described above |
| `long_name` | the company or fund's full name |
| `stock_type` | `COMMON` for ordinary shares, `ETF` for a fund, and so on |

## Things worth knowing

**Error 492 is now fatal, and that is on purpose.** It says "you must subscribe
for additional permissions to obtain precise results for scanner", and it means
the scan ran but the ranking was built from prices we are not entitled to see.
The truth check treats it as a hard error, so a run that gets one exits 3 rather
than publishing a ranking it cannot vouch for. It was not seen on the live run of
2026-09-06 afternoon, after Mo paid for market data. If it starts appearing every
morning, that is a subscription problem to fix, not a check to loosen.

**Error 162 appears five times a run and is harmless.** It says "API scanner
subscription cancelled", once per scan, and it is Gateway confirming a one-shot
scan has finished. The truth check knows it by its text and lets it through. The
dangerous 162 is the one that says "Scanner filter X is disabled", and that one
stops the run.

**Error 165 means somebody else is logged in.** "Trading TWS session is connected
from a different IP address". It was seen at 13:15 on 2026-09-06 and every scan,
filtered or not, returned zero rows while it lasted. It cleared on its own. It is
a hard error, so the run exits 3 rather than reporting an empty market. This is
the same family as error 10197 in the watchdog: IBKR gives an account one market
data session and a login somewhere else takes it.

**Gateway rations requests** to sixty in any ten minutes, counted across the
whole connection. Go over and it starts refusing requests for everything, not
just this script. The arithmetic, in full:

```
  5   scanner requests: four scans plus the control
 55   left for historical data, which is the --history-budget
  1   SPY reference bars, to see how far today's data reaches
 35   daily bars, one per enriched name, which is --enrichment-cap
 19   opening ranges left, against a shortlist that can hold twenty
----
 60   the whole ration
```

So the only way to run out is for all thirty-five enriched names to survive every
filter and fill a shortlist of twenty. In that one case the twentieth name loses
its opening range and `warnings` says so, rather than the file quietly publishing
a name with no entry trigger. A real run is far under: the live run of 2026-09-06
spent 41 of the 60, five on scans and 36 on history.

The enrichment cap came down from forty to thirty-five to pay for the three extra
scans. The names that lose their place are the lowest ranked across all four
scans, which are the ones least likely to have survived the filters anyway. If
you are running the scanner by hand several times over, leave ten minutes between
goes.

**`ETF.EQ.US` is not a usable scan location.** It looks like the obvious way to
scan ETFs, but Gateway answers "market scanner is not configured for one of the
chosen locations". ETFs come back inside the ordinary `STK` scan anyway, marked
`stock_type: ETF`.

**Scan results arrive nearly empty.** The rows Gateway returns carry a ticker
and a contract id and almost nothing else. No exchange, no company name. That is
why every name needs a separate lookup before the US-listing and leveraged-fund
checks can run.

**Delayed data cannot see the open in real time.** This was the big one until Mo
paid for market data on 2026-09-06. Without a live subscription everything
Gateway hands back runs about fifteen minutes behind, so a 9:35 run sees data
from roughly 9:20, before the bell: no 9:30 to 9:35 range, barely any volume, and
a shortlist that comes back empty or close to it. Check `data_as_of_eastern` and
`market_data_type_label` in the output to see which world a given run was in. The
live run on the afternoon of 2026-09-06 reported `market_data_type_label: live`,
which is the answer we want.

Relative volume still behaves sensibly on delayed data, for what it is worth,
because the script measures how far the data actually reaches and compares
today's volume against what would be normal by that same point. Both halves of
the ratio are equally stale, so they cancel out.

**Run it after 4 PM and the shortlist reflects the whole day, not the open.**
Relative volume is measured against the full session once the session is over,
and the "opening range" is still the real 9:30 to 9:35 range, but the price will
be the close. Useful for checking the script works. Not useful as a trading
signal.

**Run it on a weekend and the session progress figure is nonsense.** SPY has no
bars for today, so the script says so in `warnings` and then falls back to the
wall clock, which on a Saturday afternoon reports something like "246 minutes
into the session". Nothing survives the filters anyway, because nothing has
traded, but do not read that number as meaning anything. It is a pre-existing
quirk of `measure_session_progress` and is only visible when the market is shut.

## The Finviz Elite cross-check, which is off

Finviz Elite has native gap and relative-volume filters and a CSV export
endpoint, which makes it a genuinely useful second opinion on what gapped this
morning. **Mo has not bought it** (39.50 dollars a month as of 2026-09-06), so
the switch is off and nothing in this project has signed up for anything.

With `scanner.finviz.enabled: false`, which is the shipped setting, the script
writes one line in the log and makes **no network call at all**. A test asserts
that by making any call to `urlopen` fail the test outright.

To turn it on later, three steps:

1. Set `scanner.finviz.enabled: true` in
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`.
2. Put the whole Finviz export link, screener settings and all, in
   `scanner.finviz.export_url`.
3. If that link does not already carry its own `auth=` token, put the token in
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/finviz.env`
   as a `KEY=value` line, and name the key in `scanner.finviz.auth_token_key`.
   That folder is gitignored. The token is appended to the link at request time
   and never appears in the log, in an error message, or in the shortlist.

When it is on, the ticker column of the CSV is read, those names join the union
tagged `finviz` in `flagged_by`, and they go through exactly the same price,
liquidity, relative volume, US listing and leveraged fund checks as everything
else. A name Finviz found that IBKR also found is tagged with both and is not
duplicated. A name only Finviz found arrives with no contract id, which is fine:
the script looks it up by ticker. The `finviz` block in the output says what
happened either way.

## Proved against the live Gateway

Run on 2026-09-06 at 14:29 Eastern, market shut, read only on client id 281,
into
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/shortlist_unfiltered_test.json`
(that folder is gitignored, so the file is not in the repo):

```
MOST_ACTIVE        control            50 rows  0.77s
TOP_PERC_GAIN      candidate source   50 rows  0.50s
TOP_PERC_LOSE      candidate source   50 rows  0.54s
HOT_BY_VOLUME      candidate source   50 rows  0.55s
HIGH_STVOLUME_5MIN candidate source   50 rows  0.52s
```

All five with an empty filter list, all five finishing, all five carrying
nothing but the benign 162 that says a finished one-shot scan closed. So
`HIGH_STVOLUME_5MIN` does exist on this Gateway and does answer, which was the
open question when the four codes were chosen.

The stages, in order: 177 unique names across the four scans, 170 after the
known leveraged and inverse tickers came out, 35 kept for enrichment, 35 with
usable daily bars, 13 through the 5 dollar price floor, 3 through the 20 million
dollar liquidity floor, and 0 through relative volume, because the market was
shut and nothing had traded today. Exit code 0. 41 of the 60 requests spent, 5
of them scanner requests and 36 historical.

The filter probe was run against the same Gateway a minute later and came back
`half on`: `priceAbove 5` returned 50 rows against a 50 row control, and
`stVolume5MinAbove 100000` returned zero rows with 162 "Scanner filter
stVolume5MinAbove is disabled" followed by 365. Pre-flight recorded that and
passed, which is the whole point of the probe.

An empty shortlist at the end of a run whose diagnostics are clean is the right
answer on a Saturday. The point of the run was the top half of that list.
