# The insider-buying sweep

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/sweep_insider.py`

## What it is for

Executives and directors have to tell the SEC within two business days whenever
they trade their own company's stock. Sales say very little, because people sell
for houses and tax bills. Open-market buys are different: somebody who is already
paid in salary and share options chose to put more of their own cash in.

This script reads every one of those filings, throws away everything that is not
a real cash purchase, scores what is left, and writes a shortlist of at most
fifteen companies to a JSON file. Claude reads that file later in the morning and
decides which names, if any, are worth buying. The script decides nothing.

The strategy behind it is written up in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_INSIDER.md`.

**It cannot trade.** It talks to exactly one place on the internet, `www.sec.gov`.
There is no broker code in the file, it never opens a connection to IB Gateway,
and it has no idea what any of these stocks currently cost. All it does is read
public filings and write a file.

## How to run it

From the project folder,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading`:

```
venv312/bin/python agent/sweep_insider.py \
    --since "2026-09-04T00:00" \
    --out output/insider_shortlist_2026-09-06.json
```

| Option | What it does |
|---|---|
| `--since` | Only look at filings the SEC accepted at or after this moment. A time with no timezone on it is read as US Eastern, which is the timezone the SEC works in. Defaults to midnight this morning. |
| `--out` | Where to write the shortlist. Defaults to `output/insider_shortlist_<today>.json` inside the project. |
| `--cache-dir` | Where downloaded filings are kept. Defaults to `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/edgar_cache`, which git ignores. |
| `--limit` | Read at most this many filings, newest first. An escape hatch for a quick test. A full three-day sweep is a few thousand filings and takes about five minutes the first time. |
| `--verbose` | Chattier logging. |

The exit code is 0 whenever the sweep ran, even if nothing survived the filters.
It is 1 only when the SEC could not be reached at all, in which case no file is
written and the previous shortlist is left alone.

### Why the second run is fast

Everything the SEC publishes about a finished filing is permanent, so once a
filing is on disk the script never asks for it again. The first three-day sweep
takes about five minutes and makes roughly 2,200 requests. Running it again the
same day takes about ten seconds and makes almost none. The cache lives in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/edgar_cache`
and is safe to delete at any time. The only thing never cached is the current
day's index, because that file is still being written as the day goes on.

## Where the filings come from, and why

The SEC offers two ways to find out what was filed recently, and this script
uses both, because each one is bad at what the other is good at.

**The daily index files** are the main source. One file per trading day, listing
every filing the SEC published that day, at addresses like
`https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/form.20260904.idx`.
One request gets a whole day. They are complete and they never change once the
day is over.

**The latest-filings feed** at
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&count=100&output=atom`
is the top-up. A filing appears here within a minute or two of the SEC accepting
it, well before the day's index catches up, so it is what makes an afternoon
sweep see the afternoon's filings.

The feed is not used as the main source because it is shallow. Measured on
2026-09-06, it holds roughly the last 4,800 entries and returns an error page for
anything older, and because it lists the same filing once for the company and
once for each insider named on it, those 4,800 entries were only about 1,600
filings. In practice it reached back about a day and a half. That is fine for
this morning and useless for a three-day catch-up, so it gets the job it is
actually good at.

The two lists are merged and de-duplicated on the filing's accession number, so a
filing that appears in both is read once.

## What it actually does, in order

1. **List the filings.** Fetch a daily index for every weekday from `--since` to
   today, then page the latest-filings feed backwards until it passes `--since`
   or runs out. Weekends and market holidays have no index file, and a missing
   file is treated as normal rather than as an error.
2. **Download each filing.** One request each, to the complete submission file at
   `https://www.sec.gov/Archives/edgar/data/<company>/<accession>.txt`. That
   single file carries the acceptance timestamp and the structured Form 4 XML
   together, which is why it is used instead of fetching a filing index page and
   then the XML separately. Eight downloads run at once, paced to eight requests
   a second, comfortably under the SEC's limit of ten.
3. **Read the XML.** Pull out the company, its ticker, who was buying, their job
   title, the director / officer / ten-percent-owner checkboxes, the Rule 10b5-1
   plan checkbox, and every share transaction with its code, price, date and the
   holding left afterwards.
4. **Keep only real buys.** Transaction code `P`, marked as acquired rather than
   disposed of, with a price on it, and with no sign of a pre-scheduled plan.
5. **Group by company, then by person.** Somebody who bought in three goes over
   two days is judged on what they spent in total, not on each slice.
6. **Apply the money floors, score, and rank.** Write the top fifteen.

If any single filing fails to download or fails to parse, it is counted and
skipped. One broken filing never stops the sweep.

### Which trades count as buys

Only transaction code `P`, which is an open-market or private purchase for cash.
Everything else on a Form 4 is noise for this purpose: `M` is an option exercise,
`A` is a share award, `F` is shares handed back to cover tax, `G` is a gift, `S`
is a sale. A `P` that is somehow marked as a disposal is also dropped, as is any
purchase with no price on it, because a buy with no price cannot clear a dollar
threshold.

### Pre-scheduled trades, and why the script is deliberately twitchy about them

A Rule 10b5-1 plan is set up months in advance and then runs on autopilot. A
purchase made under one carries no fresh opinion, so the strategy excludes them.
A purchase is treated as pre-scheduled if any of these is true:

- the form's own 10b5-1 checkbox is ticked (`aff10b5One` in the XML),
- the remarks mention a 10b5-1 plan,
- a footnote attached to that transaction mentions a 10b5-1 plan,
- or the filing has 10b5-1 footnotes somewhere and this transaction has no
  footnotes of its own to distinguish it.

That last rule catches things it does not strictly have to, and that is on
purpose. Wrongly keeping a planned buy means buying on a signal that was never
there, which costs money. Wrongly dropping one just means missing a name.

### The money floors

Straight from the strategy document. A single insider buying alone has to spend
at least **$25,000**. Inside a cluster, meaning two or more different insiders at
the same company buying within ten trading days of each other, **$10,000** each is
enough, because several people acting together says more than any one of them
acting alone.

The script tries the generous floor first, checks whether a real cluster of two
or more actually forms, and falls back to the strict floor if it does not. The
ten-trading-day window is counted in weekdays, so a holiday week reads a day or
two long. That only ever makes the window slightly generous, which is the
harmless direction.

### The score

Four things multiplied together, all of them from the strategy document.

| Part | What it measures | Range |
|---|---|---|
| Role weight | Chief executive or finance chief 2.0, any other serving officer 1.5, director 1.0, ten-percent owner 0.8. The highest among the buyers is used. | 0.8 to 2.0 |
| Size | How much was spent, against the $25,000 floor, on a log scale so a $10 million buy scores more than a $100,000 one without swamping the whole list. | about 0.3 upwards |
| Conviction | How much the buying changed what the insider already held. A holding that doubles is treated as the maximum, so somebody who owned 200 shares and bought 400 more cannot take over the list. | 1.0 to 2.0 |
| Cluster | 1.0 for one buyer, 1.5 for two, 2.0 for three, and so on. | 1.0 upwards |

The four are multiplied and scaled by ten, so a lone director spending exactly
$25,000 scores about 3, and a chief executive spending millions alongside two
colleagues scores in the hundreds. The number only exists to rank the list.
Nothing downstream treats it as a probability.

## What is in the JSON file

The top block:

| Field | What it means |
|---|---|
| `timestamp`, `timestamp_utc` | When the sweep ran, Eastern and UTC. |
| `since` | The moment the sweep looked back to. |
| `source` | Which of the two SEC sources actually got used on this run. |
| `filings_scanned` | How many Form 4 filings were downloaded and read. |
| `purchases_found` | How many genuine cash purchases were found in them, before the money floors. |
| `after_filters` | How many companies cleared every filter. `candidates` holds the best fifteen of these. |
| `thresholds` | The floors and role weights the run used, copied out so the output explains itself. |
| `counts` | Every stage of the funnel, for working out where names went. |
| `edgar_requests_made`, `edgar_cache_hits`, `edgar_request_failures` | How much work the run did and how much it got for free. |
| `warnings` | Anything worth a human's attention, in plain English. |

Each entry in `candidates`:

| Field | What it means |
|---|---|
| `ticker` | The trading symbol, taken from the filing itself. |
| `cik` | The SEC's permanent id number for the company. |
| `issuer_name` | The company name as the SEC has it. |
| `insiders` | One row per person, described below. |
| `cluster_count` | How many different insiders bought within ten trading days of each other. 1 means a lone buyer. |
| `role_weight_max` | The most senior buyer's weight. 2.0 means a chief executive or finance chief was one of them. |
| `total_value_usd` | What the qualifying buyers spent between them, in dollars. |
| `score` | The ranking number described above. Higher is more interesting. |
| `reasons` | Plain-language sentences explaining why this company is on the list. Written to be read, not parsed. |
| `last_price`, `avg_volume_20d`, `dollar_volume_ratio` | Always `null`. See below. |
| `enrichment_note` | A reminder of why those three are empty. |

Each row inside `insiders`:

| Field | What it means |
|---|---|
| `name` | The insider, as the filing spells it. A joint filing shows the first name plus how many others filed with them. |
| `title` | Their job title from the filing, or which checkboxes were ticked if there is no title. |
| `shares`, `price`, `value_usd` | What they bought, the average price paid, and what it cost. |
| `pct_increase_in_holding` | Shares bought as a percentage of what they held beforehand. 50 means they added half again. `null` when the filing does not say, or when they held none of it before. |
| `shares_owned_before` | What they held before the first of these buys, as reported. |
| `is_new_position` | True when the filing shows they held none of this security before buying. |
| `security_title` | What they actually bought, for example "Common Stock". |
| `is_common_stock` | False when the buying was in preferred shares, units, warrants or similar. Worth checking, see below. |
| `held_indirectly` | True when the shares sit in a trust or a holding company rather than in the person's own name. |
| `role_weight` | This person's weight, as in the scoring table. |
| `transaction_date` | The day of their most recent buy in this batch. |
| `filing_accepted_at` | When the SEC accepted the filing. This is what `--since` compares against. |
| `accession_number` | The SEC's id for the filing. |
| `url` | Link to the filing on the SEC's website, so any number here can be checked by eye in about ten seconds. |

### The three empty fields

`last_price`, `avg_volume_20d` and `dollar_volume_ratio` are always `null`, and
that is deliberate rather than a bug. This script has no market data of any kind.
The trading loop fills them in from IBKR before it applies the strategy's $5 price
floor and 500,000-share liquidity floor. Until it does, a candidate here has
passed the filings test and nothing else.

## Things worth knowing

**A ticker on a Form 4 is not a promise that the stock is tradable.** Filings
carry the ticker the company typed in. Companies whose shares are not listed leave
it blank, and those are dropped and counted under
`counts.purchases_dropped_no_ticker`. The rest still need the loop's price and
volume check. Insider buying skews heavily towards small companies, so expect thin
names and wide spreads.

**Watch the `is_common_stock` flag.** A Form 4 reports a buy of whatever security
the insider holds, and that is sometimes preferred shares or units rather than the
ordinary stock the ticker refers to. The first live run turned up a director
spending $10 million on preference shares of a company whose common stock trades
under a different price entirely. Those still appear on the shortlist, because the
buying is real information, but `is_common_stock` is false and the `reasons` say
so in words. It is a judgement call for Claude, not an automatic exclusion.

**Read the sentences in `reasons` that start with "Careful".** There are three of
them, and each one flags something the numbers alone would hide. One says the
buying was not in the common stock. One says every buyer in a "cluster" paid the
identical price on the identical day, which is a company share scheme running
rather than several people separately deciding the stock is cheap. The first live
run had exactly that at Wix.com: six executives, same day, same price to the cent,
and it still came out top of the list on score. The third says the trade happened
long before the filing arrived. Insiders are meant to file within two business
days, and on the first run one buy reached the SEC 27 trading days late, by which
point it is not news. None of the three is an automatic exclusion. They are there
for Claude to weigh.

**Every insider on a joint filing is not a cluster.** Some Form 4s are filed
jointly, usually a fund and the person who runs it, and the same purchase is
reported under both names. Crediting it to each would double the money and invent
a two-person cluster out of one trade. The script credits the purchase once, to
the first name on the filing, keeps the most senior of their role weights, and
says in the name field how many others filed alongside.

**Amendments are ignored.** Form 4/A restates an earlier filing, so counting it
would count the same purchase twice.

**"Open market" is looser than it sounds.** Code `P` covers private purchases too,
including buying shares straight from the company under a sales agreement. It is
still the insider's own cash, so it stays in, but the footnotes on the filing are
worth a glance when the amount looks unusual.

**The trading-day window is approximate.** Cluster distance is counted in
weekdays, with no list of market holidays. Across a holiday week the ten-day
window stretches to eleven or twelve calendar trading days. That is a deliberate
simplification, and it errs towards finding clusters rather than missing them.

**The signal is slow by design.** Two business days pass between the trade and the
filing, and the whole market reads the same filing at the same moment. Whatever
edge exists here is in judging which buys matter, not in getting there first.

## SEC quirks hit while building this

- **The latest-filings feed is shallow and lies about it.** Asking for entries past
  roughly 4,800 does not return an empty feed, it returns an HTML error page with a
  503 status. Just below that boundary it returns a valid, cheerful feed titled
  "No recent filings" with nothing in it. Neither looks like the end of a list, so
  the script stops on either.
- **Every filing appears in the feed two or more times.** Once for the company,
  once for each insider named on it. A hundred entries can be forty filings.
  Everything is de-duplicated on the accession number.
- **The daily index also repeats filings**, once per party, for the same reason.
- **Friday evening filings still count as Friday.** Filings accepted as late as
  10 PM Eastern on 2026-09-04 carried a filing date of 2026-09-04 and appeared in
  that day's index, so nothing falls into a gap at the end of the day.
- **A quiet day is much quieter than a busy one.** 2026-09-02 had 820 Form 4
  filings, 2026-09-03 had 958, and 2026-09-04, going into a long weekend, had 441.
  A low count is not a sign the sweep missed something.
- **The SEC wants to know who you are.** Every request sends the header
  `User-Agent: agentic_trading research mtalib.personal@gmail.com`. Without a
  descriptive User-Agent the SEC blocks the request outright. The rate limit is ten
  requests a second and this script sits at eight, so retries can never tip it over.
- **Every filing seen so far uses the same XML layout**, schema version X0609, with
  the 10b5-1 checkbox as a single field for the whole document rather than one per
  transaction. The parser handles the per-transaction placement too, since older and
  newer forms differ, but nothing in the live sample needed it.
