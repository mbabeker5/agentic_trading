# The opening-momentum scanner

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`

## What it is for

Every morning a handful of stocks open with a jump and unusually heavy trading,
almost always because something happened overnight. Those are the only names
this strategy is interested in. This script finds them.

It asks IB Gateway five questions, checks the answers against the rules in the
strategy spec, and writes a shortlist of at most twenty names to a JSON file,
ranked by relative volume with the heaviest first. Claude reads that file at
9:35 AM and decides which of them, if any, are worth trading. The script itself
decides nothing and trades nothing.

Both directions are on the list, and which one a name gets comes from the first
five minutes of its own trading: a 9:30 to 9:35 candle that closed above where
it opened is a `long`, one that closed below is a `short`, and one that opened
and closed at exactly the same price is no trade at all and comes off the list.
Each row carries the tag under both `direction` and `side` so whichever field
the next step reads, it reads the right one. Note that shorting itself was
deferred to month two by the review team on 2026-09-06, so `allow_shorts` is
false in both momentum book files and the loop will not act on a short even
though the scanner finds them. The shortlist is honest about what is there; the
book decides what to do with it.

**Momentum v2, 2026-09-06.** Four of Mo's approved changes landed in this file
on that date and are described in their own sections below: the volatility floor
(A3), ranking by relative volume rather than by the size of the move (A4),
direction from the opening candle (A5), and the hard exclusions (A12). A fifth
decision, D7, took the optional Finviz Elite cross-check out of the file
altogether; it is gone rather than switched off, and a test keeps it gone. The
reasoning for all five is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md`.

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
exists, the script reads these values out of it:

| Key in the YAML | Meaning | Falls back to |
|---|---|---|
| `universe.price_floor` | ignore anything cheaper than this | 5 dollars |
| `universe.min_avg_dollar_volume` | ignore anything that normally trades less than this many dollars a day | 20,000,000 |
| `universe.dollar_volume_sessions` | how many completed sessions that average covers | 30 |
| `universe.atr_days` | how many sessions the average true range covers | 14 |
| `universe.min_atr_usd` | the smallest daily range worth trading, in dollars | 0.50 |
| `universe.min_atr_pct_of_price` | and the same floor as a share of the price | 1.5 |
| `universe.min_history_sessions` | how many completed sessions a name needs before it is judged at all | 30 |
| `universe.exclude_spacs` | drop blank cheque companies | `true` |
| `universe.exclude_warrants_and_rights` | drop warrant and rights lines | `true` |
| `universe.exclude_preferred` | drop preferred shares | `true` |
| `universe.require_us_primary_listing` | keep OTC and non-US lines out | `true` |
| `universe.exclude_halted` | drop anything IBKR says is halted | `true` |
| `scanner.rel_volume_min` | how many times its normal pace a name has to be trading, measured at 09:35 | 2.0 |
| `scanner.max_candidates` | how long the shortlist can be | 20 |
| `scanner.rel_volume_window` | the window the strategy's own relative volume rule is about, carried for the record | `09:30-09:35` |
| `scanner.rel_volume_baseline_days` | how many prior days that window is measured against, carried for the record | 14 |

Anything missing falls back to the value above. The script never writes to that
file. Another part of the project owns it.

The last two are written into the output and are not used for arithmetic here.
The real 9:30 to 9:35 measurement against the prior fourteen days is built from
streaming ticks by
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py`.
This scanner's own relative volume is the same idea measured from daily bars,
which is the fallback for a morning when the pre-open run did not happen, and
writing the window down means a shortlist says which of the two it got.

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
5. Drops the obvious leveraged funds straight away, by ticker, before
   spending any data requests on them.
6. Keeps the first thirty-five and looks up daily price history for each: what it
   is trading at now, what it closed at yesterday, how many shares have changed
   hands today, its average daily dollar volume over the last thirty completed
   sessions, its average daily share volume over the last twenty, and its
   average true range over the last fourteen.
7. Drops anything with fewer than thirty completed sessions of history. A stock
   listed last week has no normal to be unusual against, and averaging its first
   three days would dress up a wild number as a settled one. This is the rule
   that replaced the listing age rule Mo rejected; see "The hard exclusions"
   below.
8. Applies the number filters, all of them here rather than at Gateway: price
   at or above the floor, average daily dollar volume at or above the liquidity
   floor, the volatility floor, and relative volume at or above the threshold.
   All of them are "at or above", not "above", which is what the numbers in the
   spec mean.
9. Settles each name's direction from the scan it came off and the sign of its
   own move, and drops the ones that contradict themselves. This is the cheap
   check; the real one comes at step 12. See "Long and short" below.
10. Looks up what each survivor actually is, including what industry IBKR puts
    it in, and drops it if it is priced in anything but US dollars, if its home
    exchange is not one of NYSE, NASDAQ, ARCA, AMEX, BATS or IEX, or if it is a
    leveraged or inverse fund, a SPAC, a warrant, a rights line, a preferred
    share, or something IBKR reported as halted.
11. Ranks what is left by relative volume, heaviest first, trims to the
    shortlist length, and only then fetches the opening five-minute range for
    the names that made it. Fetching last saves data requests, which are
    rationed.
12. Takes each shortlisted name's direction from the sign of its 9:30 to 9:35
    candle, dropping any name whose candle opened and closed at the same price,
    and numbers what survives 1, 2, 3 down the list.
13. Writes the JSON file. Unless a scan failed, in which case it writes nothing
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

**The rule that decides is the sign of the 9:30 to 9:35 candle** (change A5,
approved 2026-09-06). Closed above where it opened, the name is a `long`. Closed
below, it is a `short`. Opened and closed at exactly the same price, it is **no
trade** and comes off the shortlist entirely. That is the published strategy's
own rule, word for word, and it beats anything the overnight gap implies,
because the gap is what happened before the bell and the candle is what buyers
and sellers actually did once trading started. A name that gapped up 10 percent
and then faded through its first five minutes is a short under this rule, and it
used to be a long.

That check can only run once the opening ranges are in, which is late in the
run, so a cheaper one runs first on the scan lists themselves:

- flagged by `TOP_PERC_GAIN` only, direction is `long`
- flagged by `TOP_PERC_LOSE` only, direction is `short`
- flagged only by the volume scans, direction comes from the sign of the name's
  own move on the day
- flagged by both a gainers and a fallers scan, which should not happen but
  might, direction again comes from its own move, because its own price is
  better evidence than a list it appeared on

A name whose own move contradicts its tag is **dropped** at that point, not
shortlisted. A name off the gainers list that is actually down on the day would
otherwise get a "break above the opening high" trigger pointing the wrong way,
which is worse than not listing it. That cut shows up as
`passed_direction_agrees` in the counts.

Then the candle overrules whatever that cheap check decided, for every name
whose candle is known. The names dropped for a flat candle show up as the gap
between `passed_direction_agrees` and `passed_direction_candle`, and `warnings`
names them. A name whose candle is **not** known keeps the direction the cheap
check gave it rather than being thrown away, which matters on delayed data,
where a 9:35 run has no 9:30 bar yet.

The short price floor of 10 dollars in the book files is deliberately **not**
applied here. The scanner writes one shortlist that books A, B and E all read,
and a per-book rule belongs to the book, not to the shared list.

## The volatility floor

A candidate has to actually move enough in a normal day for a five minute
breakout to mean anything. The measure is the **average true range** over the
last fourteen completed sessions, and a name has to clear **both** halves of the
floor: at least **0.50 dollars** of daily range and at least **1.5 percent** of
its own price. This was a universe filter in the published test, and without it
the shortlist fills up with quiet large caps whose whole five minute range is
noise.

Both halves are needed because either one alone lets the wrong names through. 50
cents of range on a 400 dollar stock is dead quiet, so the percentage catches
that one. 1.5 percent of a 6 dollar stock is 9 cents, which is inside the
spread, so the dollar floor catches that one.

The true range of a session is not simply its high minus its low, because that
misses the gap. It is the largest of three numbers: high minus low, the distance
from the high to yesterday's close, and the distance from the low to yesterday's
close. A stock that closed at 20, opened at 24 and then traded between 24 and 25
has a one dollar high-to-low range and a five dollar true range, and five is the
honest number. The average is the plain mean of the last fourteen of those.

A name whose average true range cannot be worked out **fails** the filter. Not
measurable means not traded, which is the safe answer. The survivors show up as
`passed_volatility` in the counts, and every shortlisted row carries `atr`,
`atr_days_used` and `atr_pct_of_price` so the number can be checked.

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

### The score, which is now the ranking by relative volume

**The shortlist is ranked by relative volume alone, heaviest first** (change A4,
approved 2026-09-06). The `score` field on each row is simply that name's
relative volume, and `rank` is where it came: 1 for the busiest name, 2 for the
next, and so on down the list. The top `max_candidates` are kept.

It used to be the size of the day's move multiplied by the natural log of
relative volume. That was our own invention. The published result this strategy
is copying came from ranking candidates by relative volume and taking the top
few, and it was the **ranking** that carried the result, not the size of the
gap. So a name up 2 percent on nine times its normal volume now goes ahead of a
name up 20 percent on three times, which is the reverse of the old order.

The 2 times normal floor has not gone anywhere. It still runs earlier, as a
filter: a name below twice its normal pace never reaches the ranking at all.
What changed is only the order of the survivors.

`rank` is numbered after the flat-candle drop, so the published list always
reads 1, 2, 3 with no holes in it.

Names whose own move contradicts the scan that flagged them are removed
outright, not just ranked low. That cut shows up as `passed_direction_agrees` in
the counts, and "Long and short" above explains it.

### The hard exclusions

Change A12, approved 2026-09-06. These names never reach the model at all,
because they are structurally not what this strategy trades whatever their price
did this morning:

| Dropped | How it is spotted | Switch |
|---|---|---|
| leveraged and inverse funds | the ticker list and the fund name words, described above | `universe.exclude_leveraged_etfs` |
| SPACs, meaning blank cheque companies | a name containing "Acquisition Corp", "Acquisition Co", "Acquisition Holdings", or the word SPAC on its own | `universe.exclude_spacs` |
| warrants | IBKR's `WAR` stock type, the word warrant in the name, or a warrant ticker shape | `universe.exclude_warrants_and_rights` |
| rights lines | a rights ticker suffix **and** the word right or rights in the name | `universe.exclude_warrants_and_rights` |
| preferred shares | IBKR's `PREFERRED` stock type, "Preferred", "Pfd" or "Pref Shs" in the name, or a `.PR` style ticker | `universe.exclude_preferred` |
| anything not on a US venue | the US listing test, which is what keeps OTC and non-US lines out | `universe.require_us_primary_listing` |
| anything halted | IBKR's own halt flag, when it gives one | `universe.exclude_halted` |

Two of those tests are deliberately cautious about the ticker, because getting
them wrong throws out real businesses every single morning:

- A **rights** line is only dropped when the name says "right" or "rights" as
  well as the ticker ending in R or RT. Plenty of ordinary companies have
  tickers ending in R, Palantir and Builders FirstSource among them.
- A bare trailing **W** is only read as a warrant on a five character ticker,
  which is the NASDAQ convention of a fifth letter bolted onto a four letter
  root. Reading it on any ticker would throw out Lowe's (LOW), Dow (DOW) and
  Corning (GLW). Ticker shapes with a separator in them, like `.WS`, `-WS` and
  a trailing `+`, are unambiguous and are dropped on sight.

**The halt check cannot actually be made here today.** IBKR's contract details
carry no halt flag on this account, so the code looks for one, finds nothing,
and writes a line into `warnings` saying so rather than implying it looked and
found the name trading normally. The halt check that really runs is the one on
the order path, in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py`,
rule id `halted`, which reads IBKR's tick type 49. Nothing here invents a halt
flag to fill the gap.

**There is no rule about how recently a name listed, and that is deliberate.**
The reviewers proposed dropping anything listed in the last 90 days. Mo rejected
it and replaced it with a demand for enough history to measure the name at all:
the thirty completed sessions the dollar volume average needs
(`universe.min_history_sessions`) and the fourteen the average true range needs.
A name that has traded long enough to be measured has traded long enough to be
traded, and a listing date is a worse proxy for that than the sessions
themselves. The names that fall at that hurdle show up as `passed_history` in
the counts, and a test asserts no listing-age rule has crept back in.

### The industry each name is in

Every shortlisted row now carries `sector`, taken from IBKR's contract details
(its `industry` field, falling back to `category` and then `subcategory`,
whichever first says something), along with `category` and `subcategory`
themselves for the month end review. The **sector cap** in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py`
is what reads it, and it refuses an entry outright when nobody can say what
industry a name is in, so an empty `sector` means that name cannot be traded
even though it is on the list. That is worth noticing rather than ignoring, and
the run names any such shortlisted names in `warnings`.

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
| `merged_unique` | distinct names across all four scans |
| `after_known_leveraged_tickers` | left after dropping known leveraged funds by ticker |
| `capped_for_enrichment` | left after trimming to thirty-five |
| `daily_bars_ok` | how many returned usable price history |
| `passed_history` | how many have the thirty completed sessions it takes to judge them |
| `passed_price_floor` | still at or above the price floor |
| `passed_dollar_volume` | still at or above the 20 million dollar average daily liquidity floor |
| `passed_volatility` | still above both halves of the volatility floor, 0.50 dollars and 1.5 percent of price |
| `passed_rel_volume` | still trading at or above the relative volume threshold |
| `passed_direction_agrees` | the name's own move agrees with the scan that flagged it |
| `passed_us_listing` | priced in dollars and listed on an allowed US exchange |
| `passed_leverage_name_filter` | left after the fund name check |
| `passed_hard_exclusions` | left after the SPAC, warrant, rights, preferred and halt checks |
| `opening_range_ok` | how many returned a first five minutes to measure |
| `passed_direction_candle` | left after dropping the names whose opening candle was flat |
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
| `opening_range_open` | what the 9:30 to 9:35 candle opened at |
| `opening_range_close` | and what it closed at. These two are what decided `direction` |
| `volume_today` | shares traded so far today |
| `avg_volume_20d` | average shares traded per day over the last twenty completed sessions. Only the bottom half of the relative volume ratio, which is shares against shares. Nothing is filtered on it |
| `avg_dollar_volume` | average dollars traded per day over the last thirty completed sessions. This is the liquidity floor's number |
| `avg_dollar_volume_sessions` | how many completed sessions that average actually used, which is fewer than thirty for a recent listing |
| `completed_sessions` | how many completed daily bars the name has at all. Under `min_history_sessions` and it never reached the filters |
| `atr` | the average true range in dollars: how far this name travels in a normal session |
| `atr_days_used` | how many sessions that average used. 14 on a normal run |
| `atr_pct_of_price` | the same range as a percentage of the price, which is the second half of the volatility floor |
| `rel_volume` | today's volume divided by what would be normal by this time of day |
| `rel_volume_minutes_elapsed` | how many minutes of trading that ratio was measured over. 5 means it was measured at the 9:35 anchor the rule is about |
| `direction` | `long` or `short`. Which way this name is a candidate, taken from the opening candle |
| `side` | the same value again, because the loop reads `side` and the decision code reads either |
| `flagged_by` | which scans flagged it. Two entries is a stronger signal than one |
| `scan_rank` | the best place it took on any scan, 0 being the top of a list |
| `rank` | where it came on this shortlist. 1 is the heaviest relative volume |
| `reasons` | short plain-language sentences explaining why it is on the list, meant to be read |
| `score` | the ranking number, which is now simply the relative volume |
| `long_name` | the company or fund's full name |
| `stock_type` | `COMMON` for ordinary shares, `ETF` for a fund, and so on |
| `sector` | what industry IBKR puts it in. The sector cap reads this, and an empty string means the name cannot be entered |
| `category` | IBKR's finer grain under the industry |
| `subcategory` | and finer again. Nothing filters on either; they are here for the month end review |

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

## The Finviz Elite cross-check, which was removed

There used to be an optional second opinion here. Finviz Elite has native gap
and relative volume filters and a CSV export endpoint, so the scanner could
download that export and fold those tickers into the union as a cross-check on
what IBKR's own lists found.

**It is gone.** Mo decided not to buy Finviz Elite (39.50 dollars a month), which
is decision D7 in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md`,
and on 2026-09-06 the whole path came out of the file: the settings, the
download, the CSV reader, the `finviz` tag on a candidate and the `finviz` block
in the output. It was deleted rather than left switched off, because a dead code
path that talks to the network is a thing somebody eventually turns on by
accident.

A note near the top of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`
says the same thing, so nobody adds it back thinking its absence was an
oversight, and a test in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_scanner_filters.py`
fails if the word turns up anywhere in that file outside that note. IBKR's four
scans plus the control scan are the whole source of names now.

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
