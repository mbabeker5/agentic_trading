# Congress disclosure sweep

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/sweep_congress.py`

Reads the stock trades that members of the US House and Senate are required to
disclose, keeps the buys, scores them, and writes a shortlist of at most fifteen
tickers. Claude reads that shortlist at 9:45 AM and decides whether any of them
are worth buying.

The script only reads public disclosure data over the open web. It never
connects to IB Gateway, it never places an order, and there is no order code in
the file.

Companion to the strategy it implements:
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_CONGRESS.md`

## How to run it

From the project folder:

```
venv312/bin/python agent/sweep_congress.py \
    --since 2026-08-01 \
    --out output/congress_shortlist_2026-09-06.json
```

| Flag | What it does |
|---|---|
| `--since` | Earliest disclosure date to include. This is the date the filing was received, not the date of the trade. Defaults to 45 days ago. |
| `--out` | Where to write the JSON. Defaults to `output/congress_shortlist_<today>.json`. |
| `--cache-dir` | Where downloaded filings are kept so a second run is quick. Defaults to `output/congress_cache/`, which is gitignored. |
| `--max-candidates` | How many names to write at most. Defaults to 15. |
| `--verbose` | Chattier logging. |

The exit code is 0 whenever at least one source answered, even when nothing
survived the filters. It is 1 only when every source was unreachable.

A first run takes about twenty seconds because it downloads every filing. After
that the filings are cached, and since a filing never changes once it is filed,
the cache is never wrong. A repeat run takes about four seconds.

## Where the data comes from, and how healthy it was on 2026-09-06

The mirrors this project originally planned to use are gone. What replaced them
is better: the government's own systems.

| Source | Alive? | Last updated | Format | Free API? |
|---|---|---|---|---|
| **House Clerk**, `disclosures-clerk.house.gov` | Yes | 2026-09-03, so 3 days old | ZIP holding a tab separated index, plus one PDF per filing | No key, no signup, plain HTTPS |
| **Senate EFD**, `efdsearch.senate.gov` | Yes | 2026-09-02, so 4 days old | JSON for the filing list, HTML tables for each filing | No key, no signup, but you must accept a terms page first |
| **congress-legislators** on GitHub | Yes | 2026-09-03 | YAML | Yes, raw files over HTTPS |
| House Stock Watcher, the S3 bucket | **No** | n/a | n/a | Answers HTTP 403 Access Denied. Its GitHub repository has been deleted. |
| Senate Stock Watcher, the S3 bucket | **No** | n/a | n/a | Answers HTTP 403 Access Denied. Its GitHub repository last saw a change in March 2021. |
| Capitol Trades | **No** | n/a | n/a | The website answers every request, `robots.txt` included, with a bot challenge behind HTTP 429. Their own data service answers HTTP 503 on every path because something is misconfigured on their side. |
| Unusual Whales, Quiver, Finnhub, Financial Modeling Prep | Paid | n/a | n/a | All refuse without an API key. None were signed up for. |

So the two Stock Watcher datasets the strategy document names are both dead,
not merely stale. The script does not use them and does not try.

**Primary source: the House Clerk plus the Senate site, together.** They are not
alternatives to each other, they cover different chambers, so the script runs
both and uses whatever answers.

**Fallback: Capitol Trades.** Only touched when both official sources fail. It
reads the website's HTML, so it will break the next time they redesign the page.
Since their site could not be reached at all on 2026-09-06, that code path has
never run against live data. Treat it as untested. If both official sources ever
do fail, expect to fix it by hand rather than trusting what it returns.

### What the House PDFs are like

The House index tells you who filed and when, but not what they traded. The
trades live in one PDF per filing. Those are filed electronically these days, so
they carry a real text layer and can be read without guessing at handwriting.

Two things in those PDFs are worth knowing about, because both were quietly
losing trades until they were fixed:

- A disclosed amount often wraps onto a second line, so `$15,001 -` sits above
  `$50,000`.
- A long company name also wraps, and when it does the PDF hands the text back
  out of order, with part of the name and sometimes the ticker itself landing
  *after* the trade instead of before it. Missing this drops real trades,
  including names as ordinary as Alphabet and Applied Materials.

Members who still file on paper send in a scan, and a scan has no text in it.
The live run on 2026-09-06 found 8 such filings out of 51. The script counts
them, names their document IDs in the warnings, and moves on. Nothing short of
optical character recognition would recover those.

### One legal note

The House Clerk site carries a notice saying it is unlawful to use this data for
"any commercial purpose, other than by news and communications media for
dissemination to the general public", citing 5 U.S.C. app. 105(c). For one
person trading their own paper account that is probably not what the clause is
aimed at, but it is worth knowing before this ever becomes a product.

## What the script does with the data

1. **Keeps purchases only.** Sales are ignored, because people sell for all
   sorts of reasons. Trades filed for a spouse or a dependent child count, since
   the form covers them and many of the most watched trades arrive that way.
2. **Keeps ordinary shares only.** Options, municipal bonds, treasury bills,
   private partnerships and pooled funds are dropped. Some have no ticker to
   trade at all, and an index fund tells you nothing about a company, which is
   the whole basis of this strategy.
3. **Records both dates.** The date the member traded and the date the filing
   appeared, plus the gap between them in days. That gap is the strategy's
   central problem, so it is on every record.
4. **Drops trades that were already stale on arrival.** If more than 60 days
   passed between the trade and the filing, the filer was late and the trade is
   skipped.
5. **Applies the minimum size rule.** A buy of $15,001 to $50,000 or larger
   qualifies on its own. A buy of $1,001 to $15,000 only qualifies when two or
   more different members bought the same ticker within 30 days of each other.
6. **Counts the crowd.** How many different people bought the same ticker inside
   any 30 day window. A member who filed the same stock three times still counts
   once.
7. **Scores and sorts**, then writes the top fifteen.

## How the score is built

```
score = (size band x 2) + (committee link x 3) + ((crowd count - 1) x 4)
```

- **Size band** runs 1 to 10, from $1,001 to $15,000 up to over $50,000,000.
- **Committee link** is 0, 1 or 2, explained below.
- **Crowd count** is the number of different members who bought.

So one member buying a million dollars of something scores about the same as two
members buying a mid sized position in a company their committee regulates. That
is deliberate. Two people arriving at the same stock within a month of each other
is the strongest signal in this data, and so is somebody putting real money down.

## The committee link, and why it is only half done

The script ships a table of committees and the sectors they touch: Armed
Services to defense and aerospace, Energy and Commerce to health care and pharma
and energy and telecom, Financial Services and Banking to financials, Agriculture
to agriculture and food, Transportation to airlines and rail and autos,
Intelligence and Homeland Security to defense and cyber, Judiciary and Commerce
to technology, Natural Resources and Energy to oil gas and mining, and Veterans
Affairs to health care.

Who sits on what comes from the `unitedstates/congress-legislators` project on
GitHub, which publishes current members and current committee membership as YAML
and was last updated 2026-09-03. On the live run it resolved all 539 sitting
members, 531 of whom hold a committee seat. If that dataset is ever unreachable,
a small hand written table takes over and the output says
`"committee_data_complete": false` so nobody mistakes it for the real thing.

Matching a filing to a person is fiddlier than it sounds. A House filing carries
the member's state and district number, and only one person holds a district, so
that is exact. A Senate filing carries nothing but a name, so that falls back to
comparing the words in the two names. This matters: the House Clerk files April
McClain Delaney under surname "Delaney", while the legislators dataset calls her
surname "McClain Delaney". Matching on the surname alone loses her entirely.

The district trick has one trap, and the script guards against it. Someone who
has left Congress can still be filing, because they have 45 days to disclose and
the clock does not stop when they go. The dataset only lists sitting members, so
their old district now belongs to whoever replaced them. Taking the district at
face value would file that trade under the wrong person and hand them somebody
else's committees. So the script checks that the surname on the filing actually
matches the person holding the seat, and where it does not, it leaves the
committees empty and says so in the warnings. A trade with no committee link is a
worse answer than the truth. A trade attributed to the wrong member is a wrong
one.

**The half that is missing is the company's sector.** `ticker_sector` is
deliberately left empty. The loop fills it in from the industry IBKR reports for
the contract, which is a far better answer than anything derivable here. Until
then the script scores the link from the member's side and takes a rough guess at
the company from its name:

| Value | Means |
|---|---|
| `0` | Nobody who bought this sits on a committee this strategy links to a sector. |
| `1` | Somebody does, but the company's name gives no clue whether it trades in that committee's patch. |
| `2` | Somebody does, and the company's name points straight at one of that committee's sectors. |

A `1` can become a `2` once IBKR reports the real industry. Nothing in this
script has looked at the company itself yet.

## What is in the output file

### The top block

| Field | Meaning |
|---|---|
| `timestamp`, `timestamp_utc` | When the sweep ran. |
| `since` | The earliest disclosure date included. |
| `source_used` | Which sources actually answered. |
| `sources_tried_and_failed` | Which ones did not. |
| `source_last_updated` | The newest filing date any source had. |
| `source_stale_by_days` | How many days old that is. |
| `staleness_flag` | True when the newest filing is more than 3 days old. The strategy asks for this. Note that a Monday morning run will often flag, because nobody files at the weekend. |
| `staleness_note` | The same thing in a sentence. |
| `transactions_scanned` | Every transaction row read, buys and sells, all asset types. |
| `purchases` | How many of those were share purchases. |
| `after_filters` | How many tickers cleared staleness and the minimum size rule. |
| `dropped_stale_over_60_days` | Purchases thrown out for arriving too late. |
| `dropped_below_minimum_band` | Tickers thrown out for being too small and having nobody else alongside. |
| `committee_data_source`, `committee_data_complete` | Where committee membership came from, and whether it is the real dataset or the fallback table. |
| `counts` | Per source detail: filings found, rows read, filings that were unreadable scans. |
| `warnings` | Anything that went wrong, in plain sentences. |
| `candidates` | The shortlist. |

### Each candidate

| Field | Meaning |
|---|---|
| `ticker` | The symbol as disclosed. |
| `asset_description` | The company name as the member wrote it. |
| `members` | Everyone who bought it, newest filing first. See below. |
| `crowd_count` | How many different people bought it inside a 30 day window. |
| `committee_relevance` | 0, 1 or 2, as explained above. |
| `committees_in_play` | The committees those buyers sit on that this strategy tracks. |
| `committee_matches` | The specific links found, for example "House Financial Services covers financials". |
| `best_amount_band`, `best_amount_band_label` | The largest single disclosed size, as a number and in words. |
| `ticker_sector` | Always null. The loop fills it from IBKR. |
| `ticker_sector_note` | Says so, in the file, so nobody wonders. |
| `guessed_sectors_from_name` | A rough guess from the company's name. Not a classification, and not to be trusted over IBKR. |
| `score` | See the formula above. |
| `reasons` | Plain sentences explaining why this name is on the list. |
| `last_price`, `avg_volume_20d` | Always null. The loop fills these from IBKR so the price floor of $10 and the volume floor of a million shares can be applied. |

### Each member inside a candidate

| Field | Meaning |
|---|---|
| `name` | Their full name, resolved against the legislators dataset. |
| `chamber` | House or Senate. |
| `party`, `state`, `district` | From the legislators dataset. |
| `owner` | Whose account it was: self, spouse, joint or dependent child. |
| `committees` | The committees they sit on that this strategy tracks. |
| `amount_band` | 1 to 10. |
| `amount_band_label` | The range as disclosed, for example `$15,001 - $50,000`. |
| `band_midpoint_usd` | The middle of that range, purely to give a sense of size. Members never disclose an actual amount, so this is not a real number. |
| `transaction_date` | When they traded. |
| `disclosure_date` | When the filing appeared. |
| `gap_days` | The days between the two. |
| `source_url` | A link straight to the filing. Worth opening when a name looks odd. |

## What the live run found

Run on 2026-09-06 for everything disclosed since 2026-08-01, written to
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/congress_shortlist_test.json`:

- 51 House filings and 26 readable Senate filings
- 679 transaction rows read
- 148 of those were share purchases
- 92 dropped for arriving more than 60 days after the trade
- 29 tickers dropped for being too small with nobody else alongside
- 15 names on the shortlist
- Newest filing 2026-09-03, so not flagged stale

## Known weaknesses

- **Everything here is old news by design.** Members have up to 45 days to
  disclose. On this run the gaps ran from 10 to 45 days. The strategy is not
  "trade what they trade", it is "trade what they traded, if the reason still
  holds", and judging that is Claude's job.
- **Paper filers are invisible.** 8 of 51 House filings on this run were scans
  with no text. Their trades are simply not here.
- **The sector half of the committee link is unfinished** until IBKR fills it in,
  so a `committee_relevance` of 1 is an open question rather than a weak answer.
- **The company name guess is crude.** It is a keyword list, not a
  classification. It exists to get from 1 to 2 on obvious cases, nothing more.
- **One member can flood the list.** On this run seven of the fifteen names came
  from a single member's dependent child's account. The scoring pushes them below
  the crowded and committee linked names, which is right, but the shortlist still
  ends up lopsided when one person trades a lot. Worth watching.
- **Members who have left Congress lose their committee link.** The roster only
  lists sitting members, and they have 45 days to file after they go. Their
  trades still appear and still score, they just score as though they sat on no
  committee. The warnings name anyone this happened to. Fixing it properly means
  also loading the historical roster, which is a 9 MB file, and that did not seem
  worth adding to every run for a handful of filings.
- **The fallback is not a real fallback.** Capitol Trades has never been reached,
  so if both official sources go down at once, this sweep produces nothing and
  exits 1.
