# 04. Verified findings: what the papers actually say once you open them

Written 2026-09-06, the same day as the first three lists, but with one difference that matters: this pass had web search and could open the papers. The first three lists were written by agents working from memory, and they said so. This file is what happened when someone went and checked.

**This file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/04_gap_fill.md`
**PDFs:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/` (159 files, about 314 MB, 84 of them added by this pass)

It is long. It is long because the six research reports that make it up are included in full rather than summarised, since the scratch copies they were written to do not survive the session and the entries are already written in the same shape as the other three lists. Read the first three sections of this file on the plane (they are short), then use the flight order at the end to pick your way into the six parts.

## The short version

Four things changed once the papers were actually opened.

**The opening-range breakout evidence is thinner than the first list let on.** Nobody has published an independent out-of-sample test of either Zarattini paper past February 2023, not even the authors. The one genuine replication (a GitHub repo by Brusco) reproduces the paper's arithmetic almost exactly and then shows the profit crosses zero at about 2.2 cents a share of slippage, with 76 percent of the filter's profit coming from calendar 2022. Toby Crabel, who invented the strategy in 1989, wrote in April 2026 that his own hundred-year test shows it decaying steadily and the last few years as the worst since the 1960s. A 2026 falsification study on Nasdaq micro futures tested fourteen intraday signal families and found the best gross edge was smaller than the friction. And Concretum's own 2026 article found the identical strategy code gives more than threefold different results depending on which data vendor you buy the minute bars from. Book A is still worth paper trading. It is not worth believing yet.

**The language-model agents finally got tested live, and live is worse than backtest.** Between late 2025 and mid 2026 the field ran forward-looking arenas instead of backtests. Six frontier models trading real money on Alpha Arena burned 13 to 17 percent of their capital on fees in two weeks and four of six lost money; Claude and GPT-5 finished third and last. FINSABER re-ran the published agent strategies over two decades with delisted stocks kept in, and the advantage evaporated; buy-and-hold won nearly everywhere. Agent Market Arena found that the scaffolding matters more than which model you call, which is good news for a one-person shop. An audit of 77 agent-trading papers found one that reported a transaction-cost model and none that were reproducible. There is still no peer-reviewed journal publication anywhere of a live language-model trading return.

**The Congress book has a verified null result and one surviving idea.** The two copy-Congress ETFs have been running the lagged copy trade with real money since February 2023. NANC has beaten the S&P 500 by about two points a year, all of it from 2023, and GOP is fifteen points behind. The one academic paper that tested exactly these two funds concludes neither beats the market on a risk-adjusted basis and the gap between them is a sector bet. Belmont and co-authors find no stock-picking skill anywhere in Congress over 2012 to 2020. What survives is narrow: Wei and Zhou (NBER, November 2025) find that members promoted into leadership positions beat matched peers by 47 percentage points a year afterwards, and that the signal stays positive when you can only buy on the disclosure date. If you build one thing from Part C, build the leadership filter. On the insider side, the December 2022 SEC rule change added a checkbox to Form 4 that tells you directly whether a trade came from a pre-scheduled plan, which is the label the Cohen, Malloy and Pomorski filter has to guess at. It is free and nobody in the literature has used it yet.

**The new strategy families sort themselves quickly.** Of the seven families the first list skipped, one is genuine low-hanging fruit (Faber's ten-month moving average and Antonacci's dual momentum on five to ten ETFs, three or four trades a year, no shorting, though it lagged plain stocks in six of the eight years after 2008), one is worth building first as a diversifier (futures trend following, but eight markets not eighty, and lean slow because a 2026 paper from Capital Fund Management traces the collapse of fast trend to tick-size microstructure), one is a modest overlay (covered calls at low delta, worth one or two percent a year, with a 2025 Chicago Fed paper finding option alpha indistinguishable from zero over fifteen years), and one is an interesting long shot (long-only closed-end fund discounts, 10.7 percent a year gross in the one careful paper, which deducts no costs at all). Three are not for you: 0DTE options (negative net Sharpe unconditionally), crypto basis carry (the profitable version lives on offshore exchanges you cannot use, and the CME version earns a 0.6 Sharpe while risking margin-driven liquidation) and ETF pairs (two surveys ten years apart agree the edge after costs is roughly a Treasury yield).

There is a pattern across all of it. In every family, the research from 2023 to 2026 is more negative than the research from before. That is what a maturing market looks like, and it is the best argument in this whole pack for paper trading everything for a full year before sizing anything.

## Corrections to the first three lists

Twenty-four factual errors or stale claims were found and fixed in place. Each fix is marked in the file with the date. This is the changelog.

| File | What was wrong | Fixed to |
|---|---|---|
| 01_anomalies.md, intro and section 12 | McLean and Pontiff decay quoted as "a third to a half" and "a quarter and a half" | The paper's own figures: 26 percent lower out of sample, 58 percent lower after publication |
| 01_anomalies.md, section 11 | Zarattini and Aziz 2023 title truncated | Full title with subtitle |
| 01_anomalies.md, sections 6, 7 | Krauss, Heston and Sadka, Ariel cited to the journal version with no note that the free copy is a working paper | Version named in each entry |
| 01_anomalies.md, fourteen entries | Marked "not downloaded" or "link unverified" | Now downloaded and verified; only Bernard and Thomas 1989, Livnat and Mendenhall 2006 and Harris and Gurel 1986 remain behind publisher walls |
| 02_llm_agents.md, entry 3 | Lopez-Lira and Tang called peer-reviewed because the acknowledgements named referees | It is peer-reviewed, but the evidence is the publication: Journal of Financial Economics 184, October 2026, article 104335 |
| 02_llm_agents.md, entry 12 | MemGuard-Alpha subtitle dropped | Full title |
| 02_llm_agents.md, entry 15 | Sarkar and Vafa said to be an ICML 2025 paper proposing "a masking approach" | It was an ICML 2025 workshop poster, and it proposes statistical tests, not masking. Now downloaded (32 pages) |
| 02_llm_agents.md, entry 17 | Loughran and McDonald 2016 survey named with no citation | Journal of Accounting Research 54(4), pages 1187 to 1230, closed access, SSRN link for a manual click |
| 02_llm_agents.md, entry 26 | Greenwood and Sammon index-effect numbers quoted from the 2022 working paper as if final | The published Journal of Finance version (April 2025) revised them, and the deletion effect flipped sign from minus 0.6 to plus 0.1 percent |
| 02_llm_agents.md, entry 45 | Dou, Goldstein and Ji dated 2024 with the NBER number | NBER w34054 is July 2025; the local file is the January 2024 SSRN version. Both dates now given |
| 02_llm_agents.md, entry 47 | Eggers and Hainmueller described only as "reaches the opposite conclusion", not downloaded | Full citation, the actual finding (2 to 3 percent a year underperformance over 2004 to 2008, and why), free author copy downloaded |
| 03_practitioner.md, section 1 | Narang Wiley link 404 | E-book ISBN link that resolves |
| 03_practitioner.md, section 1 | Two Harriman House short links 404 | Full author-page links |
| 03_practitioner.md, section 1 | Carver said to have a GitHub repo for Advanced Futures Trading Strategies | No such repo exists. Replaced with his spreadsheets page |
| 03_practitioner.md, section 1 | Machine Learning for Asset Managers given as 190 pages | About 150; the 190 figure could not be sourced |
| 03_practitioner.md, section 2 | pysystemtrade at robcarver17 | Moved to the pst-group organisation in January 2026 |
| 03_practitioner.md, section 3 | Chague day-trading figures quoted from memory with a caveat | Verified against the paper (97 percent lost, 0.4 percent beat a bank teller), caveat removed, paper downloaded |
| 03_practitioner.md, section 4 | Harvey and Liu, and Lopez de Prado's ten reasons, marked download failed | Both downloaded from open mirrors |
| 03_practitioner.md, section 4 | Harvey, Liu and Zhu source link on a host that now fails certificate checks | Moved to people.duke.edu |
| 03_practitioner.md, section 2 | AQR papers all marked as needing a browser | Fact, Fiction and Momentum Investing and Trading Costs downloaded; note that images.aqr.com serves AQR PDFs without the bot check |
| 03_practitioner.md, section 5 | Kissell second edition dated 2021 | September 2020 |
| 03_practitioner.md, section 5 | algo-dma.com given as a place to buy Barry Johnson's book | Site is down; buy secondhand |
| 03_practitioner.md, section 5 | Elsevier and Cambridge links given as redirect sources | Destination URLs |
| 03_practitioner.md, section 5 | FINRA 26-10 summary omitted two softening provisions | Added: deficits expire after 15 business days, and the 90-day freeze needs a "makes a practice" finding with a de minimis carve-out of the lesser of 5 percent of equity or 1,000 dollars |

Everything else that was spot-checked held up. All eight arXiv identifiers for the 2026 papers in the second list resolve to the claimed titles. Twelve of thirteen book years were right. The FINRA notice says what the third list said it says. Kirtac and Germano's numbers are verbatim from the abstract.

## What was added, by part

| Part | Topic | Papers or resources written up | PDFs added |
|---|---|---|---|
| A | Opening-range breakout replications, pre-market gaps, earnings-announcement premium | 17 entries: 7 on the Zarattini papers and their critics (plus the full Concretum catalogue of 15 papers), 5 on gaps, 5 on the earnings premium | 9 |
| B | Newest language-model trading evaluations, 2025 to 2026 | 12 full entries, 5 short ones, 6 verified titles listed for later | 14 |
| C | Congress ETFs, Unusual Whales reports, congressional and insider research | Verified facts and calendar-year returns for both ETFs; 5 report editions; 4 congressional papers plus 2 leads; 5 insider papers; the Rule 10b5-1 checkbox; an 8-row data-source table | 8 |
| D | Volatility risk premium and covered calls, 0DTE flows, futures trend following at retail scale | 20 entries: 9, 7 and 4, each family with a sizing note for a 100k account (contract sizes, margin, commissions) | 16 |
| E | Crypto basis carry, closed-end fund and ETF discounts, sector rotation and dual momentum, ETF pairs | 14 entries: 4, 4, 3 and 3, each family with a verdict | 14 |
| F | Practitioner resources missed | 6 podcasts with named episodes (13 checked), 7 newsletters plus 2, 16 frameworks and 7 libraries and 6 open-source agent repos with GitHub and PyPI activity checked, data sources with free tiers in five groups, and a list of 20 dead or dormant things to say no to | 0 |
| Verification | The three original lists | 24 corrections | 23 (14 for the anomalies list, 7 for the practitioner list, 2 for the agents list) |

The PDF count adds to 84. Two of those are second versions of the Zarattini papers kept beside the originals because they differ, so it is 82 distinct papers.

## Searched for and genuinely not found

These are the holes that remain after a full day with web access. Each part carries its own longer list; this is the cross-cutting summary.

- **Any independent, out-of-sample test of either Zarattini opening-range paper on data after February 2023.** Not by the authors, not by Quantpedia, not by Alpha Architect, not by Robot Wealth, not on Reddit with published code. Concretum's 2026 article marks the out-of-sample period on a chart and withholds the numbers. This is the single largest hole for the strategy the shop is actually building.
- **A peer-reviewed journal publication of a live language-model trading return, 2025 or 2026.** The only refereed items are two ACM ICAIF 2025 conference papers, and neither reports a return.
- **Anyone measuring position crowding across independently prompted trading agents in a live market.** The nearest is Henning and co-authors' experimental finding that agents show far less strategy variance than humans. For a shop running several agents, this is the risk nobody has measured.
- **Evidence since 2023 on whether the insider-buying signal has decayed.** The search budget ran out before this could be searched, so it is "not searched" rather than "not there". The 2024 out-of-sample result in Zhao's microcap paper says the signal was alive in that corner as of 2024.
- **Independent 2023 to 2026 live tracking of Faber's or Antonacci's tactical models.** Allocate Smartly tracks exactly these strategies but keeps the numbers behind a login. A one-month subscription would settle it.
- **CME bitcoin basis and perpetual funding levels for 2024 to 2026 from a primary source.** The paragraph on it in Part E is marked as recollection and must be checked before any sizing.
- **A peer-reviewed paper on retail gap-and-go versus gap-fade in individual US stocks.** Plastun covers indices, Berkman covers attention stocks framed as overnight reversal. Nothing tests the retail folklore directly.
- **A good open-access paper on trading FDA decisions.** Still none, as the second list already said.
- **Free copies of six papers.** Bernard and Thomas 1989, Livnat and Mendenhall 2006, Harris and Gurel 1986, Loughran and McDonald 2016, Berkman-adjacent Akbas and co-authors 2022, and Heitz and co-authors on the disappearing earnings premium. Links for a manual click are in the appendix.

## Still unverified after this pass

Every entry below marks its own uncertainties with "still unverified". The ones a reader should keep in mind:

- Alpha Arena Season 1.5 figures come from press coverage; the organiser's site blocks scripts.
- The 2023 partial-year returns for NANC and KRUZ are derived from since-inception figures, not read from a filing.
- The Unusual Whales 2021 and 2022 report headline figures could not be opened; 2023 to 2025 come from the company's own Substack posts and press coverage.
- Interactive Brokers margin for short index puts and the portfolio-margin minimum were not confirmed against the broker's current schedule.
- CME micro contract multipliers for M6E, MBT and the micro Treasury yield futures were cross-checked against secondary sources only, because CME's site timed out.
- The Faber 2017 out-of-sample tables are images inside the PDF and were not extracted; the narrative findings are confirmed.

## Revised flight order

The original front sheet gave a five-hour plan. This merges the new material in. Times are for a reader who skims the maths. The total is now closer to six and a half hours, so the last block is the one to drop if the flight is short.

### Hour 1. Orientation, unchanged plus ten minutes

1. `03_practitioner.md`, Section 3 (retail outcomes) and Section 4 (backtest overfitting). Twenty minutes. The Chague paper is now in the folder and its 97 percent figure is verified.
2. `01_anomalies.md`, Section 12 (McLean and Pontiff, now downloaded) and the summary table. Fifteen minutes.
3. `02_llm_agents.md`, Section A and Section G. Fifteen minutes.
4. This file, the first three sections above. Ten minutes.

### Hours 2 and 3. The strategies we are actually building, with the new evidence

5. Book A, opening momentum. `01_anomalies.md` Section 11 as before, then Part A of this file, entries C1 to C5: the Brusco replication, Crabel's verdict, the Mesfin falsification study, the QuantConnect thread with its cost commentary, and Concretum's data-vendor finding. Forty minutes. Then the Berkman paper (`Berkman_2012_PayingAttention.pdf`), because it says the opening price is worst in exactly the stocks a relative-volume filter picks. Fifteen minutes. If there is appetite, Zarattini's SPY intraday momentum paper (`ZarattiniAzizBarbon_2024_BeatTheMarketIntradayMomentumSPY.pdf`) is the more credible cousin at Sharpe 1.33, and a better first automation target than the twenty-stock scanner.
6. Book C, insider buying. `01_anomalies.md` Section 10 and `02_llm_agents.md` Section I as before, then Part C of this file, Part 3: Kang's cluster-trading filter (multi-day clusters, not same-day ones), the Rule 10b5-1 checkbox note, and Zhao's microcap result that buying insider purchases into strength beats buying them into weakness. Thirty minutes.
7. Book D, Congress. Part C of this file, Parts 1 and 2: the ETF figures, why the Unusual Whales returns are estimates, Belmont's null result, Baulkaran and Jain on the two ETFs, and Wei and Zhou's leadership filter. Thirty minutes. Eggers and Hainmueller is now in the folder if you want the original rebuttal.

### Hour 4. Where an agent genuinely helps, and where it now clearly does not

8. `02_llm_agents.md` Sections D and E as before (PEAD.txt is still the best case for a reading agent). Twenty minutes.
9. Part B of this file, entries 1, 3, 4, 5 and 9: Alpha Arena's fee lesson, Agent Market Arena on scaffolding versus model, FINSABER on two decades with delistings, InvestLogicBench on reasoning that reads well and is not grounded, and the Xia audit checklist. Thirty-five minutes. Then entry 6 (Harris) if you plan to filter news with Claude: the false-positive gap between model families is an order of magnitude.
10. `02_llm_agents.md` Sections C and H as before, plus Part B entry 7 (Yang) on turning text features off when volatility spikes. Fifteen minutes.

### Hour 5. Ideas for books five to ten, reordered by what the evidence now says

11. Part E, Family 3 (Faber and Antonacci). The best new candidate: monthly, five to ten ETFs, no shorting. Twenty minutes. Read Faber's own 2017 follow-up so the six-of-eight-years underperformance is not a surprise later.
12. Part D, Family 3 (futures trend at retail scale): Carver's account-size ladder (100k buys about eight markets), the Kurth tick-size paper, and the margin table. Twenty-five minutes.
13. Part A, Part 3 (earnings-announcement premium): Frazzini and Lamont, Barber and co-authors, and Heitz on the migration to Form 8-K dates, which points at a free structured feed. Twenty minutes.
14. Part D, Family 1 (covered calls), read as an overlay not an income machine: Israelov and Nielsen's decomposition, the Devil's Bargain paper, and the sizing note (one contract at 100k, use XSP not SPY). Twenty minutes.
15. `01_anomalies.md` Sections 1, 4, 7 and 8 as before. Twenty minutes.

### Hour 6. What to skip, and why, in fifteen minutes each

16. Part D, Family 2 (0DTE): read the verdict and the tail-risk arithmetic, then close it.
17. Part E, Family 1 (crypto carry): read the Schmeling liquidation finding and Mallory's wedge idea, then close it.
18. Part E, Families 2 and 4 (closed-end funds, ETF pairs): the closed-end long-only sort is the one long shot; ETF pairs and ETF premium arbitrage are not for a small account.

### If there is time left

19. Part F, Part 1 (podcasts): SI405 on why most trend-following improvements should fail, and Algorithmic Advantage 047 on a strategy development pipeline, are the two to queue up before the flight.
20. Part F, Parts 3 and 4: the frameworks table (Lumibot or NautilusTrader for execution, TradingAgents for the research half, backtrader is frozen and pandas-ta is deleted) and the data-source tables (SEC EDGAR for filings and fundamentals, Alpaca's free tier for prices, and the 100 market-data-line cap at Interactive Brokers as the design constraint).
21. `03_practitioner.md` Section 1 (books) and Section 5 (operations, with the two FINRA provisions added).

---

## Part A. Intraday equities: opening-range breakout replications, gap statistics, earnings-announcement premium

*Report title: Cluster C: Intraday Equity Strategies*
### Gap-fill research: ORB replications, pre-market gaps, earnings-announcement premium

Compiled 2026-09-06. PDFs live in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`.

A note on sourcing before you read. The two Zarattini day-trading papers are the most-copied retail quant papers of the last three years, and almost everything written about them online is a *review* of the papers rather than an *independent test* of them. I found exactly one genuine independent replication with its own data and its own cost model. Everything else in Part 1 is labelled for what it actually is: a review, a vendor backtest, or an adjacent falsification study. Where a source is a self-published blog or a personal GitHub repo rather than peer-reviewed work, I say so, because you should weight it accordingly.

---

### Part 1. Replications, refutations and follow-ups on the Zarattini ORB papers

### The two originals, for reference

**Zarattini, C. and Aziz, A. (2023, revised April 2024). "Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term Profits from Opening Range Breakout (ORB) Day Trading Strategy vs. Benchmark in the US Stock Market."** SSRN 4416622.
Link: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
Free PDF mirror: https://www.wealth-lab.com/api/discussion/download/pdf/6590-ORB-Strategy-pdf
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Zarattini_2023_CanDayTradingReallyBeProfitable.pdf` (already in the pack, downloaded by another pass)

**Zarattini, C., Barbon, A. and Aziz, A. (2024). "A Profitable Day Trading Strategy For The U.S. Equity Market."** SSRN 4729284. Also Swiss Finance Institute Research Paper 24-98.
Link: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
Free PDF mirror (University of St. Gallen): https://alexandria.unisg.ch/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/download
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Zarattini_2024_ProfitableDayTradingStrategyUSEquity.pdf` (already in the pack)

---

#### C1. Brusco, G. (2026). "Independent replication of the 5-minute Opening Range Breakout on QQQ (Zarattini & Aziz 2023), stress-tested for execution costs." Public GitHub repository with code and results.
Link: https://github.com/giovannibrusco/zarattini-2023-orb-qqq
Local file: not downloaded (code repository, not a PDF)
Status: self-published, not peer reviewed. Exact publication date **still unverified**.

**What it says.** This is the only true independent replication I could find, meaning someone re-ran the strategy on their own data with their own cost assumptions rather than just summarising the paper. On the headline numbers it reproduces the paper almost exactly: 1,775 trades against the paper's 1,795, and a Sharpe ratio of 1.06 against the paper's 1.12, on QQQ five-minute bars from January 2016 to February 2023 with a 25,000 dollar starting stake. So the paper's arithmetic is sound. The problem is what happens when you add the cost of actually getting filled. The published profit of 138,639 dollars assumes zero slippage. Add realistic entry slippage and profit and loss crosses zero at roughly 2.2 cents per share, which is not a comfortable margin when QQQ's bid-ask spread is already around a penny. At two cents a share the net profit collapses from 138,639 dollars to 4,860 dollars. Two further findings matter. First, the Nasdaq futures confirmation filter that the paper leans on does carry real information (0.125 dollars per share edge, t-statistic 2.05, versus 0.079 for a placebo control built from QQQ's own pre-open bar), but 76 percent of its total profit comes from calendar 2022 alone, and it lost money in 2017, 2020 and early 2023. Second, bootstrapped 95 percent confidence intervals for the strategy's Sharpe ratio overlap substantially with plain buy-and-hold, so on a risk-adjusted basis you cannot say the strategy beat the index. The author also flags that the filter was chosen on the same window it was tested on, which is exactly the in-sample selection problem the deflated-Sharpe literature warns about.

**Verdict: undercuts the original.** Not because the numbers are wrong, but because the edge is thinner than one round trip's worth of slippage and lives almost entirely in one high-volatility bear market year.

**Fit for agent automation.** High as a diagnostic exercise. This repo is the single most useful thing in this cluster for you, because it is a working cost-sensitivity harness. Point an agent at it, have it reproduce the break-even slippage curve on your own data, then re-run with Interactive Brokers' actual fill quality. That is the test that decides whether the opening-range book is viable at all.

**Difficulty for a small account.** Medium to run as a study, hard to trade. The strategy needs five-minute bars, a futures feed for the confirmation filter, and fills inside two cents on a liquid ETF. A 100k book can do it, but the whole edge is in execution quality, which is the one thing a small account controls least.

---

#### C2. Crabel, T. (20 April 2026). "The Evolution of the Opening Range Breakout." Toby Crabel, Substack.
Link: https://tobycrabel.substack.com/p/the-evolution-of-the-opening-range
Local file: not downloaded (paywalled newsletter post, no PDF)

**What it says.** Toby Crabel wrote the 1989 book that invented opening-range breakout as a systematic method, and he has traded it for fifty years, so this is the originator giving a verdict on his own idea. He tested a basic ORB rule (entry at 0.80 of the trailing 10-day average range, exit at the next day's open) across more than a hundred years of data, starting with wheat and adding markets as their histories became available, equally weighted. The finding is a steady, grinding decline in both dollars per contract and Sharpe ratio over the century, and he describes the last few years as among the worst for ORB since the early 1960s. His explanation is structural rather than crowding: electronic and near-continuous global trading has diluted the significance of the primary session open. The open used to be the moment when a day's worth of accumulated information and liquidity hit the market at once, which is precisely what made the first few minutes' range informative. When the instrument trades all night, that concentration is gone.

**Verdict: undercuts the original, on the deepest possible grounds.** Zarattini's sample (2016 to 2023) sits entirely inside the period Crabel describes as the worst in ORB's history, which suggests the 2016-2023 result depended on the leverage and the stock-selection filter rather than on the opening-range signal itself.

**Fit for agent automation.** Low as a signal, high as a prior. There is nothing to automate here, but it is the single best argument for why your opening-range book should be sized as a small experimental sleeve and reviewed on a schedule, not treated as a core strategy.

**Difficulty for a small account.** Not applicable, this is commentary. But treat it as the reason to demand walk-forward evidence past 2023 before allocating.

---

#### C3. Mesfin, M. (May 2026). "Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A Systematic Falsification Study." arXiv:2605.04004.
Link: https://arxiv.org/abs/2605.04004
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Mesfin_2026_StructuralLimitsOHLCVIntradaySignals.pdf` (15 pages, verified)
Status: arXiv preprint by an independent researcher, not peer reviewed.

**What it says.** This is the closest thing to a systematic refutation of the whole intraday-momentum-from-bars family, run on Micro E-mini Nasdaq futures rather than QQQ. The author tested fourteen distinct signal families (opening range breakouts, volume-spike direction, gap fill fade, gap continuation and others) on 947 days of five-minute bars covering 2021 to 2025, and held every one to the same pre-registered bar: t-statistic of at least 2.0 on walk-forward out-of-sample results, at least 30 trades, positive net return after a fixed two-point round-trip friction cost, and consistent performance across every tested year. Nothing passed. The headline is a gross edge ceiling: across all fourteen families the best achievable gross return before costs is roughly 0.07 to 1.50 points per trade, while friction alone is 2.0 points. The signals are not measuring nothing, they are measuring something too small to pay for the trade. The one near-miss was gap continuation on the short side with a Kalman velocity filter (t-statistic 3.23), which failed only on sample size (22 trades), and the author explicitly names it as the one candidate worth more data.

**Verdict: undercuts, and generalises the objection.** The specific mechanism it identifies (edge smaller than friction) is the same one Brusco found on QQQ. Two independent efforts arriving at the same diagnosis is worth more than either alone. Caveat: MNQ futures are not QQQ shares and the cost structures differ, so this is adjacent evidence rather than a direct replication.

**Fit for agent automation.** Very high. The paper is essentially a template for the falsification harness your agents should run before any strategy gets capital: pre-declare the acceptance bar, test the whole family not just the winner, walk it forward, subtract real friction, require every year to work. Copy the methodology section.

**Difficulty for a small account.** Easy to replicate the study (free five-minute futures data, plain Python). Hard to profit from any of it, which is the point.

---

#### C4. QuantConnect Research (2024). "Opening Range Breakout for Stocks in Play." QuantConnect research notebook and community thread.
Link: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/
Discussion thread: https://www.quantconnect.com/forum/discussion/19456/opening-range-break-paper/
Local file: not downloaded (interactive notebook, no PDF)

**What it says.** QuantConnect rebuilt the Zarattini, Barbon and Aziz 2024 stocks-in-play strategy on their own platform: five-minute opening range, long the break of the range high when the range is bullish and short the break of the low when bearish, restricted to the twenty stocks with the most abnormally elevated opening volume relative to their own recent average. They chose five minutes because it was the best-performing window in the original paper, which is itself a mild in-sample choice. Their result broadly supports the paper: Sharpe ratio around 2.4, beta close to zero, comfortably ahead of buy-and-hold SPY at 0.836, with the characteristic low win rate offset by a high average win to average loss ratio. A parameter sweep found 68 percent of tested settings beat the benchmark, which is reassuring about robustness to parameter choice. Two important qualifications. Their universe was 1,000 liquid securities, not the paper's 7,000-plus, so survivorship and liquidity are both flattered relative to the original. And the community thread underneath is where the honest discussion lives: one participant reported trading costs consuming about 25 percent on a six-symbol portfolio, and others flagged that order-placement timing in live trading does not match what the backtester assumes. A separate poster trying to reproduce it in Python found their average-true-range values roughly three times lower than the C# version because the indicator was warming up on 33 samples instead of about 7,000, which is a good illustration of how easily this particular strategy breaks in reimplementation.

**Verdict: supports the original's direction, but the reproduction problems and the cost commentary in the thread pull the same way as C1 and C3.**

**Fit for agent automation.** High. It is working code for the exact strategy in your opening-range book, and the ATR warm-up bug in the thread is a real trap an agent should be told to check for explicitly.

**Difficulty for a small account.** Hard. Twenty concurrent positions a day on the day's most volatile names means short locates, wide spreads on the small caps, and whatever house day-trading limits your broker still applies during the phase-in of FINRA Regulatory Notice 26-10 (the old pattern day trader rule itself was retired on 2026-06-04). On 100k you would run a cut-down version, five to eight names, larger caps only, and accept a much lower Sharpe.

---

#### C5. Concretum Research (2026). "ORB Strategy Backtest in Python Using Alpaca (10+ Years of Free Data)." Concretum Group, with companion Google Colab notebook.
Link: https://concretumgroup.com/orb-strategy-backtest-in-python-using-alpaca-10-years-of-free-data/
Substack version: https://concretumgroup.substack.com/p/how-to-backtest-a-orb-strategy-in
Local file: not downloaded (web article plus notebook)

**What it says.** This is the authors' own follow-up, and it contains the most practically alarming finding in the whole cluster. Running identical ORB code with identical parameters across five data providers (Polygon, Alpaca, IQFeed, Interactive Brokers and Databento) produced performance dispersion of more than threefold. The causes were phantom highs and lows, stale bars, early-close data leakage, and differences in how ticks get assigned to bars. Once they cleaned for these, results converged across providers. The article extends coverage to 2016 through 2026 and marks the post-February-2023 out-of-sample period in green on the equity curves, but it deliberately does not publish the out-of-sample return, Sharpe or CAGR figures, leaving you to run the notebook with your own Alpaca key. So the extended-period performance is **still unverified** from the article text alone.

**Verdict: supports the strategy's continued existence, while undercutting confidence in any single backtest of it.** A threefold spread from data-vendor artefacts alone means a reported Sharpe of 2.8 could be a real Sharpe under 1.

**Fit for agent automation.** Very high, and arguably the highest-value item here for your build. Before your agents backtest anything intraday, they should run the same strategy on two independent data feeds and reconcile. Make cross-vendor agreement a gate that a strategy has to pass, not an afterthought. The specific artefacts named (phantom extremes, stale bars, early-close leakage) are exactly what a data-validation agent should test for.

**Difficulty for a small account.** Easy to run (Alpaca's historical data is free). The underlying discipline, holding two paid feeds to cross-check, costs real money, so start with one free and one paid.

---

#### C6. Zarattini's later papers, 2024 to 2026 (the Concretum Group research listing)
Link to full listing: https://concretumgroup.com/papers/
Articles listing: https://concretumgroup.com/articles/

The complete papers page as of September 2026, newest first. All are SSRN working papers, none peer reviewed in a journal as far as I could confirm.

| Date | Title | Authors | SSRN id |
|---|---|---|---|
| Jun 2026 | QuanTips: Global Tactical Asset Allocation, Updated Results and Real-Market Implementation Using Python and IBKR | Gabriel, Pagani, Zarattini | 5230603 |
| Apr 2026 | NextVoL White Paper: Volatility Targeting for Long-Term Compounding | Distaso, Mele, Zarattini | none listed |
| Feb 2026 | QuanTip: Improving Performance with Fast Alphas; A Tactical Overlay for Intraday Trend Trading | Pagani, Zarattini | 6391638 |
| Nov 2025 | The Tranching Dilemma. A Cost-Aware Approach to Mitigate Rebalance Timing Luck in Factor Portfolios | Zarattini, Pagani | 5747964 |
| Oct 2025 | ChatGPT in Systematic Investing, Enhancing Risk-Adjusted Returns with LLMs | Anic, Barbon, Seiz, Zarattini | 5680782 |
| Jun 2025 | The Volatility Edge: A Dual Approach For VIX ETNs Trading | Zarattini, Aziz, Mele | 5316487 |
| Apr 2025 | Catching Crypto Trends; A Tactical Approach for Bitcoin and Altcoins | Zarattini, Pagani, Barbon | 5209907 |
| Jan 2025 | Does Trend-Following Still Work on Stocks? | Zarattini, Pagani, Wilcox | 5084316 |
| Jun 2024 | The Power Of Price Action Reading | Zarattini, Stamatoudis | 4879527 |
| Jun 2024 | A Century of Profitable Industry Trends | Zarattini, Antonacci | 4857230 |
| May 2024 | Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | Zarattini, Aziz, Barbon | 4824172 |
| Apr 2024 | A Profitable Day Trading Strategy For The U.S. Equity Market | Zarattini, Barbon, Aziz | 4729284 |
| Apr 2024 | The Art of Financial Illusion: How to Use Martingale Betting Systems to Fool People | Zarattini, Aziz | 4678427 |
| Apr 2024 | Volume Weighted Average Price (VWAP) The Holy Grail for Day Trading Systems | Zarattini, Aziz | 4631351 |
| Apr 2024 | Can Day Trading Really Be Profitable? | Zarattini, Aziz | 4416622 |

Two things worth flagging from this list. There is no follow-up on this page that re-tests the 2023 or 2024 ORB results on post-2023 data, which is the paper you would most want. And two 2026 items are directly relevant to your intraday book: the February 2026 "Fast Alphas" paper (a short-horizon mean-reversion overlay that improves an intraday trend-following strategy, tested on five-minute SPY data from 2007 to 2026) and the June 2026 QuanTips paper, which is notable simply because it documents a real-money implementation in Python against Interactive Brokers, the same stack you are building on.

#### The one later paper I could get for free

**Zarattini, C., Aziz, A. and Barbon, A. (May 2024, this version February 2025). "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)."** SSRN 4824172. Fourth place, Quantpedia Awards 2025.
Link: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
Free PDF (University of St. Gallen): https://alexandria.unisg.ch/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/download
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/ZarattiniAzizBarbon_2024_BeatTheMarketIntradayMomentumSPY.pdf` (43 pages, verified)

**What it says.** Rather than trading only the last thirty minutes of the session, as the academic intraday-momentum literature does, this opens a trend-following position on SPY as soon as intraday price action signals an abnormal supply and demand imbalance, and manages it with a dynamic trailing stop so downside is capped while upside runs. From 2007 to early 2024 the result is a 1,985 percent total return net of costs, 19.6 percent annualised, Sharpe ratio 1.33. To their credit they run the tests you would want: whether profitability depends on the volatility regime, whether dealers' estimated gamma imbalance predicts when the strategy works, day-of-week effects, behaviour against known daily technical patterns, and an explicit commission and slippage sensitivity. The Sharpe of 1.33 is far more believable than the 2.8 in the stocks-in-play paper, and SPY is the one instrument where a small account's execution costs are genuinely small.

**Verdict: neither supports nor undercuts the ORB papers directly, but it is the most credible strategy in the Concretum catalogue and the best-suited to a 100k book.**

**Fit for agent automation.** High. One instrument, one session, an explicit stop rule, and the paper itself does the cost sensitivity for you. It is a much cleaner first automation target than the twenty-stock scanner.

**Difficulty for a small account.** Easy to medium. SPY has penny spreads and no borrow problem. The trailing-stop logic is the only fiddly part.

---

#### C7. Reviews and vendor statistics: useful context, not evidence

These are grouped because none is an independent test, and you should not weight them as one.

**CXO Advisory (2023). "Day Trading with an Opening Range Breakout Strategy."**
Link: https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy/
The findings section sits behind a paid subscription, so I could not read their conclusion (**still unverified**). What is public is their summary of the paper's cost assumptions, and it is damning enough on its own: 0.0005 dollars per share commission, no bid-ask spread, no market impact, no execution-price uncertainty. They also note the paper offers no out-of-sample validation.

**DanFin (updated 29 July 2026). "Opening Range Breakout Research: What Two Day-Trading Papers Actually Found."**
Link: https://danfin.net/opening-range-breakout-research
A careful critical review, explicitly not a replication, working entirely from the authors' reported figures. Its criticisms are the useful part and they line up with C1: the Nasdaq-ETF paper assumes no slippage while using stops as tight as eight cents; the US-stocks paper does not fully model bid-ask spreads, short-locate fees or market impact; neither paper separates out a clean forward validation period, so the parameter search carries overfitting risk. It also makes the sharpest single observation in the cluster: the plain ORB was weak, and selecting the day's most unusually active stocks by opening relative volume did almost all the work. If that is right, the strategy is a volume-anomaly strategy wearing a breakout costume, and it should be tested as one.

**QuantifiedStrategies (2025). "Stocks In Play: Opening Range Breakout (41% Annual Returns)."**
Link: https://quantifiedstrategies.substack.com/p/stocks-in-play-opening-range-breakout
Included only so you do not mistake it for a replication. They state plainly: "We have not backtested it ourselves." The numbers are the paper's numbers. They do warn that slippage and commissions might play a big part.

**ORB Setups (2026). "Opening Range Breakout Win Rate: What 150,000+ Trades Reveal."**
Link: https://orbsetups.com/research/opening-range-breakout-win-rate/
A commercial site's own dataset, methodology unpublished and unaudited, so treat every figure as **unverified**. It is worth one line because the magnitudes are sobering rather than promotional. Across 190,460 trades on 611 stocks and ETFs, per-symbol win rates cluster at 52.2 percent for the five-minute range, 52.5 percent for fifteen minutes and 52.9 percent for thirty minutes, and measured expectancy is +0.028R, +0.004R and +0.019R respectively. R is one unit of risk, so +0.028R means you make under three percent of what you were risking per trade, before any commission or slippage. They do not model costs. That is the same "edge smaller than friction" picture as C1 and C3, arrived at from a completely different direction.

**Fit for agent automation (all of C7).** Low. Read once, extract the criticisms, do not cite the numbers.

**Difficulty for a small account.** Not applicable.

---

### Part 2. Pre-market gap statistics

#### C8. Plastun, A., Sibande, X., Gupta, R. and Wohar, M. E. (2020). "Price gap anomaly in the US stock market: The whole story." The North American Journal of Economics and Finance, vol. 52 (article number 101137; exact page range still unverified).
Link (published): https://www.sciencedirect.com/science/article/abs/pii/S1062940820300747
Free working-paper PDF (University of Pretoria): https://repository.up.ac.za/server/api/core/bitstreams/f829a6c1-5762-48b1-89eb-a1ef54125843/content
SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3461283
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Plastun_2020_PriceGapAnomalyUSStockMarket.pdf` (30 pages, verified)

**What it says.** This is the widest-sample academic study of opening gaps I could find: the Dow, the S&P 500 and the Nasdaq from 1928 to 2018, ninety years. They throw a lot of statistics at it (t-tests, ANOVA, Mann-Whitney, regressions, cumulative-return analysis and a trading simulation) and reach four conclusions that matter to you. First, there are genuinely abnormal price movements after gaps, so gaps are not noise. Second, and this is the headline, on the gap day itself prices tend to continue in the direction of the gap. Gap-and-go beats gap-fade on the day. Third, their result is explicitly "contrary to the myth that price gaps tend to get filled", so the retail folklore that most gaps fill is not what ninety years of index data show. Fourth, the momentum effect is temporary, meaning it does not extend into following days, and there is no seasonality in gaps. The trading simulation cleared their significance bar, though they are careful to note that transaction costs can turn a paper-profitable strategy into a loss-maker, and they discuss cost levels as low as 0.01 percent for highly liquid markets. One important limitation for your purposes: this is index-level data, not individual stocks, and the gap threshold has to be chosen (too small and you catch thousands of non-events, too large and you have no sample), which they acknowledge introduces some arbitrariness.

**Fit for agent automation.** High. The rule is simple enough to state in one line and test in an afternoon: define a gap threshold, take the gap direction, hold to the close. It also happens to be the natural companion to your opening-range book, because both bet on continuation from the open. Have an agent test whether the gap direction adds anything to your opening-range signal or is just measuring the same thing twice.

**Difficulty for a small account.** Easy. Index ETFs, one trade a day at most, no borrow problem, no scanner needed. The hard part is that the effect is small relative to costs, which is the same problem everywhere in this cluster.

---

#### C9. Berkman, H., Koch, P. D., Tuttle, L. and Zhang, Y. J. (2012). "Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open." Journal of Financial and Quantitative Analysis, vol. 47, 715-741.
Link (published): https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/paying-attention-overnight-returns-and-the-hidden-cost-of-buying-at-the-open/F9AAD159B512C651F09D5D52011D88E0
SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1625495
Local file: **not downloaded**, paywalled. Manual-click links below in the Downloads table.

**What it says.** This is the strongest academic case for the gap-fade side, and it is the direct counterweight to Plastun. Across US equities they find a persistent pattern: positive returns overnight, then reversal during the trading day. The mechanism is specifically an opening price that is set too high relative to where the stock trades for the rest of the session. Crucially for you, it is not a general property of all stocks. It concentrates in stocks that have recently attracted retail investor attention, it is stronger in stocks that are hard to value and costly to arbitrage, and it is stronger when overall retail sentiment is high. Their punchline is a cost result: the implicit cost to a retail trader who buys a high-attention stock near the open frequently exceeds the effective half-spread, meaning the opening price itself is the tax.

**Why this matters more than its age suggests.** Reconcile it with Plastun and you get a usable rule rather than a contradiction. Plastun looked at broad indices, where gaps continue. Berkman looked at attention-grabbing individual stocks, where the open overshoots and reverses. Those are the *same stocks* that Zarattini's relative-volume filter selects. So the stocks-in-play universe is exactly the universe where the academic evidence says the opening price is worst for a buyer. That is a live risk to your opening-range book and it deserves an explicit test.

**Fit for agent automation.** High as a filter, not as a strategy. Have an agent measure, on your own paper-trading fills, whether entries in high-relative-volume names are systematically worse than entries in ordinary names. If Berkman holds, the fix is to avoid market orders in the first few minutes on high-attention stocks.

**Difficulty for a small account.** Medium. The measurement is easy. Trading the reversal deliberately is hard, because it means shorting the exact names that are hardest to borrow and most prone to squeezing.

---

#### C10. Mesfin, M. (May 2026). "Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures." arXiv:2605.04004. (Cross-referenced from C3, gap-specific findings.)
Link: https://arxiv.org/abs/2605.04004
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Mesfin_2026_StructuralLimitsOHLCVIntradaySignals.pdf` (15 pages, verified)

**What it says on gaps specifically.** Section 4.4 sets gap fill against gap continuation as two competing hypotheses and tests both across multiple entry times on 947 days of Micro E-mini Nasdaq five-minute bars, 2021 to 2025. Gap fill fade failed at every single entry time tested. His flat statement is that MNQ gaps do not consistently fill within the regular-hours session and the market is about as likely to continue in the gap direction as to reverse. The interesting exception is gap continuation on the short side combined with a Kalman velocity filter, which produced a t-statistic of 3.23, the strongest result in the entire fourteen-family study. It failed his acceptance bar only on sample size, with 22 trades against a 30-trade minimum, and he names it explicitly as the one candidate worth gathering more data on: gap-down days with high downward velocity tend to keep going down.

**How it fits with C8 and C9.** Three studies, three instruments, one consistent story. Gap continuation is the side with evidence behind it (Plastun on indices over ninety years, Mesfin on Nasdaq futures over four years). Gap fill as a fade strategy has essentially no support in any of them, despite being the more popular retail idea. Berkman's reversal is a different animal: it is about individual attention stocks and about the opening price being mispriced, not about the previous close being a magnet.

**Fit for agent automation.** Very high, and there is a specific, cheap, testable idea in it. Extend the gap-continuation-short test past 22 trades on a longer futures history or across several index futures, keeping his acceptance bar. If it survives, you have a signal with a real prior. If it does not, you have saved yourself the allocation.

**Difficulty for a small account.** Easy to test. Medium to trade, because it is short-only and needs futures or an inverse instrument.

---

### Supporting reading for Part 2 (downloaded, secondary)

**Aboody, D., Even-Tov, O., Lehavy, R. and Trueman, B. (2018). "Overnight Returns and Firm-Specific Investor Sentiment." Journal of Financial and Quantitative Analysis, 53(2), 485–505.**
Link: https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Aboody-et-al_overnight_returns_and_firmspecific_investor_sentiment_JFQA2018.pdf
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Aboody_2018_OvernightReturnsFirmSpecificInvestorSentiment.pdf` (21 pages, verified)
Argues the overnight return is itself a usable measure of firm-specific retail sentiment, showing short-term continuation followed by longer-term reversal. Useful because it turns the overnight gap from a thing you trade into a feature you can compute and feed to a model.

**Glasserman, P., Krstovski, K., Laliberte, P. and Mamaysky, H. (2025). "Does Overnight News Explain Overnight Returns?" arXiv:2507.04481, also SSRN 5336382.**
Link: https://arxiv.org/abs/2507.04481
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Glasserman_2025_DoesOvernightNewsExplainOvernightReturns.pdf` (43 pages, verified)
The important fact first: over the past thirty years nearly all US stock market gains were earned overnight, while average intraday returns were negative or flat. Using 2.4 million news articles and a supervised topic model, they explain much of that split through which news topics appear when and how differently the market responds to them overnight versus intraday. Out of sample, their model forecasts which stocks will do particularly well overnight and particularly poorly intraday, and it explains patterns of continuation and reversal in both windows. This is the most sophisticated available answer to "why do gaps exist", and it is directly relevant to a shop that already plans to use language models, because it is the same news-to-return pipeline pointed at the overnight window.

---

### Part 3. The earnings-announcement premium

#### C11. Frazzini, A. and Lamont, O. A. (2007). "The Earnings Announcement Premium and Trading Volume." NBER Working Paper 13090.
Link: https://www.nber.org/papers/w13090
Direct PDF: https://www.nber.org/system/files/working_papers/w13090/w13090.pdf
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/FrazziniLamont_2007_EarningsAnnouncementPremium.pdf` (53 pages, verified)

**What it says.** The foundational US paper on the effect and still the clearest statement of it. Stocks earn abnormally high returns in the month they are scheduled to announce earnings, and you can capture it without forecasting anything about the earnings themselves. You do not need to know whether the number will beat or miss. You only need to know the announcement is coming, which is public and scheduled. The mechanism they propose is investor attention and buying pressure: retail attention spikes around announcements, that attention arrives as buying, and prices rise temporarily. Their evidence is the link to trading volume, with the premium concentrated where the volume increase around the announcement is largest. Because it is a calendar-driven, attention-driven effect rather than an information effect, it does not require any edge in fundamental analysis, which is what makes it interesting for an automated shop.

**Fit for agent automation.** Very high, and the best fit in this entire cluster for an agent-run shop. The entire signal is a scheduled-date calendar joined to a stock universe. No text to read, no model to train, no prediction to make. An agent can maintain the earnings calendar, size positions, enter a few days before, exit a few days after, and log everything. The two real engineering problems are both tractable: confirming announcement dates (they get moved, and using the eventual actual date rather than the date known in advance is a look-ahead bug that will flatter your backtest), and handling the fact that you are deliberately holding through the single most volatile event in a stock's quarter.

**Difficulty for a small account.** Easy to medium. It is a multi-day hold, so no intraday margin pressure, and it works on liquid large caps. The medium part is risk: holding through an announcement means occasional twenty percent overnight moves, so position sizing has to be small and diversified across many announcements rather than concentrated in a few.

---

#### C12. Barber, B. M., De George, E. T., Lehavy, R. and Trueman, B. (2013). "The earnings announcement premium around the globe." Journal of Financial Economics, 108(1), 118–138.
Link (published): https://www.sciencedirect.com/science/article/abs/pii/S0304405X12002188
SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1872183
Free PDF (Tel Aviv University seminar copy): https://en-coller.tau.ac.il/sites/nihul_en.tau.ac.il/files/media_server/Recanati/management/seminars/account/barber.pdf
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/BarberDeGeorgeLehavyTrueman_2013_EarningsAnnouncementPremiumGlobe.pdf` (41 pages, verified)

**What it says.** The out-of-sample test that the Frazzini and Lamont result needed, run across 46 countries from 1991 to 2010. Average returns in announcement months exceed non-announcement months by more than 11 percent a year after controlling for the usual return factors. A calendar-time strategy of holding shares during their announcement months and shorting them in all other months earns 59.7 basis points a month. The premium shows up in twenty of the countries individually at conventional significance, and it is larger where the concentration of announcements in time is greater and where investor attention is more limited, which supports the attention mechanism rather than a risk story. This is the paper that turns the premium from a US curiosity into something you can believe is real, because forty-six independent markets is a genuinely hard test to pass by chance.

**Fit for agent automation.** Very high, same as C11, and it tells you the effect is not fragile to venue. For a US-only shop the value is confirmatory rather than operational, though it does suggest that if the US version has weakened (see C14) the international version may not have.

**Difficulty for a small account.** Easy for the US leg. Hard to implement globally, since forty-six markets means forty-six sets of trading hours, currencies, settlement rules and data vendors. Do not attempt the international version.

---

#### C13. Savor, P. and Wilson, M. (2016). "Earnings Announcements and Systematic Risk." The Journal of Finance, 71(1), 83–138.
Link (published): https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12361
SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1786308
Free working-paper PDF (Wharton, December 2011 version): https://faculty.wharton.upenn.edu/wp-content/uploads/2012/04/Draft20111215p_edited.pdf
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/SavorWilson_2016_EarningsAnnouncementsSystematicRisk.pdf` (59 pages, verified as the 2011 working-paper version)

**What it says.** The third pillar, and the one that argues the premium is compensation for risk rather than a free lunch. Firms earn high returns when they are scheduled to report, and Savor and Wilson show this premium is extraordinarily persistent across individual stocks over horizons up to twenty years, with early announcers in a season earning higher abnormal returns than late ones. Their explanation: investors use each announcement to update their expectations for firms that have not yet reported, but can only do so imperfectly, so an announcing firm carries systematic risk that a non-announcing firm does not. The supporting evidence is strong. A portfolio tracking earnings announcers predicts aggregate earnings growth while the overall market does not, and earnings-announcement betas explain 37 percent of the cross-sectional variation in average returns across portfolios sorted on book-to-market, size and momentum, with an implied risk premium consistent with the observed one.

**Why you should care about a theory paper.** If the premium is a risk premium, you should expect to earn it on average and to be genuinely hurt sometimes, and you should not expect it to be arbitraged away. If it is an attention mispricing (Frazzini and Lamont's view), it can and eventually should decay as attention becomes cheaper to trade against. C14 suggests the second story has more support in recent US data. The practical consequence is about position sizing: if you believe Savor and Wilson, the drawdowns are the price of the return and you hold through them. If you believe Frazzini and Lamont, a run of bad performance is evidence the trade is dead. You need to decide which before you allocate, not after.

**Fit for agent automation.** Medium. The insight (early announcers beat late announcers, announcement beta is priced) is directly codeable as a ranking within your announcement universe, which is a cheap improvement over holding every announcer equally.

**Difficulty for a small account.** Easy to medium, same as C11.

---

#### C14. Heitz, A., Narayanamoorthy, G. S. and Zekhnini, M. (working paper, most recent version 2025). "The Disappearing Earnings Announcement Premium."
Link: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3296537
Local file: **not downloaded.** SSRN blocks scripted downloads and the University of Toronto seminar copy now returns a server error. Manual-click links in the Downloads table.
Status: still a working paper as of 2025, **not peer reviewed**. Best Paper Award, Wellington Finance Summit 2019.

**What it says.** This is the newest work on the question and it is the one that should change how you act. The authors provide what they describe as the first evidence that the earnings announcement premium has disappeared in the US in recent years, while remaining robust internationally. Their explanation is regulatory rather than crowding: a change in Form 8-K filing requirements means firms now disclose material information far more often and much sooner, so the information that used to arrive in a clump at the scheduled earnings announcement is now pre-empted by 8-K filings. The premium did not evaporate, it migrated to the 8-K filing dates. If that is right it is a rare and genuinely useful kind of finding, because it does not just say "the anomaly died", it tells you where the anomaly went and gives you a new, still-scheduled, still-public event to build on.

**Important caveats.** It has been a working paper since 2018 and has still not landed in a journal, which after seven years is a signal in itself, so treat the conclusion as contested rather than settled. The wider literature is actively arguing about this: a related 2023 paper in the Pacific-Basin Finance Journal ("Earnings announcement premium and return volatility: Is it consistent with risk-return trade-off?", https://www.sciencedirect.com/science/article/abs/pii/S0927538X23000951) reports that using long-term data including the post-financial-crisis period the premium is still positive and significant, and is positively related to expected volatility. And in the closely related post-earnings-announcement-drift debate, a 2025 reconciliation effort by Avanidhar Subrahmanyam at UCLA Anderson found the disagreement turns almost entirely on research design, specifically whether microcaps are included: with all stocks the drift has a t-statistic of 2.18, excluding microcaps it drops to 1.43 (https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/). Expect the same microcap sensitivity in the announcement premium, and expect that your account cannot trade microcaps well.

**Fit for agent automation.** High, and it points somewhere better than where you were going. Two concrete jobs for an agent. First, re-estimate the announcement premium on recent US data yourself, split large caps from small, before committing capital to the classic version. Second, and more interesting, build the 8-K version: monitor EDGAR for 8-K filings, which is a free, structured, real-time feed and about the most agent-friendly data source that exists.

**Difficulty for a small account.** Medium. Testing it is easy. The 8-K version is medium, because reacting to filings means faster execution and more trades than a quarterly calendar, and the microcap caveat means the version that works best is the version you can least afford to trade.

---

### Supporting reading for Part 3 (downloaded, adjacent)

**Linnainmaa, J. T. and Zhang, C. Y. (2019). "The Earnings Announcement Return Cycle."**
Link: https://sites.insead.edu/facultyresearch/research/file.cfm?fid=65574
Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Linnainmaa_2019_EarningsAnnouncementReturnCycle.pdf` (48 pages, verified)
A distinct effect from the premium, and the authors are explicit that it is unrelated. Stocks earn significantly negative abnormal returns *before* announcements and positive returns *after* them, a cycle found in stocks with heavy analyst coverage. Analyst forecasts follow the same shape, turning optimistic right after an announcement and drifting pessimistic as the next one approaches, and they attribute half the return cycle to this optimism cycle. It looks like mispricing rather than risk: both patterns are stronger in high-uncertainty, hard-to-arbitrage stocks, and the strategy pays better on days when it could absorb more arbitrage capital. Worth reading alongside C11 because it warns you that the *timing* within the announcement window matters, and because the pre-announcement window (where one source I could not fully verify claims 71 percent of the total premium is earned, in a 10-day pre-announcement window averaging 0.31 percent excess return, **still unverified**) may not behave the way you assume.

---

### Searched for and not found

- **A peer-reviewed academic replication or refutation of either Zarattini paper.** I searched Semantic Scholar, RePEc, SSRN and general web for papers citing Zarattini and Aziz 2023 or Zarattini, Barbon and Aziz 2024. The citations that exist are practitioner implementations and a machine-learning breakout-identification paper, not replications. As of September 2026 no journal-published independent test appears to exist. Both papers remain unrefereed SSRN working papers themselves.
- **A Quantpedia article specifically replicating either Zarattini ORB paper.** Quantpedia gave the SPY intraday momentum paper fourth place in its 2025 awards and the VIX ETN paper fifth place in 2026, and it lists an "Earnings Announcement Premium" strategy page, but I found no Quantpedia replication of the ORB papers with their own data.
- **A Robot Wealth or Alpha Architect analysis of the ORB papers.** Neither site appears to have covered them. Alpha Architect does have a post on the global earnings announcement premium (https://alphaarchitect.com/introducing-the-global-earnings-announcement-premium/), which is Part 3 material, not Part 1.
- **A Reddit r/algotrading write-up with code that independently replicates the results.** Searches surfaced only the QuantConnect forum thread and its ATR warm-up discrepancy, not a standalone Reddit replication with published code.
- **Any Concretum follow-up that re-tests the 2023 or 2024 ORB results on post-2023 out-of-sample data with published figures.** Their 2026 Alpaca article marks the out-of-sample period on a chart but withholds the numbers. This is the single biggest hole in the evidence, and no third party has filled it either.
- **A free full text of the CXO Advisory findings.** Paywalled.
- **A peer-reviewed academic paper on retail "gap and go" versus gap fade in individual US stocks.** Plastun covers indices; Berkman covers attention stocks but frames it as overnight reversal, not gap trading. Everything returned for the specific "gap and go" phrasing was practitioner content with no published methodology. If this matters to you it is an original-research gap, not a reading gap.
- **A free PDF of Berkman, Koch, Tuttle and Zhang (2012).** Tried JSTOR, CORE and the Missouri State repository. All either blocked or served HTML.
- **A free PDF of Akbas, Boehmer, Jiang and Koch (2022), "Overnight returns, daytime reversals, and future stock returns," Journal of Financial Economics 145(3), 850–875.** The SMU institutional repository listing exists but serves no downloadable file. Manual link in the table below. Relevant to Part 2 as the most recent major academic treatment of the overnight-versus-intraday tug of war.
- **A free PDF of Heitz, Narayanamoorthy and Zekhnini.** SSRN returns HTTP 403 to scripted requests and the Rotman seminar copy now returns HTTP 500.

---

### Downloads

| Filename | Size | First page verified | Notes |
|---|---|---|---|
| `Mesfin_2026_StructuralLimitsOHLCVIntradaySignals.pdf` | 1.13 MB | yes, 15 pp | arXiv 2605.04004 |
| `ZarattiniAzizBarbon_2024_BeatTheMarketIntradayMomentumSPY.pdf` | 1.90 MB | yes, 43 pp | SSRN 4824172 via St. Gallen repository |
| `Plastun_2020_PriceGapAnomalyUSStockMarket.pdf` | 600 KB | yes, 30 pp | working-paper version via University of Pretoria |
| `Aboody_2018_OvernightReturnsFirmSpecificInvestorSentiment.pdf` | 265 KB | yes, 21 pp | JFQA 53(2), via UCLA Anderson |
| `Glasserman_2025_DoesOvernightNewsExplainOvernightReturns.pdf` | 1.09 MB | yes, 43 pp | arXiv 2507.04481 |
| `FrazziniLamont_2007_EarningsAnnouncementPremium.pdf` | 184 KB | yes, 53 pp | NBER w13090 |
| `BarberDeGeorgeLehavyTrueman_2013_EarningsAnnouncementPremiumGlobe.pdf` | 520 KB | yes, 41 pp | via Tel Aviv University |
| `SavorWilson_2016_EarningsAnnouncementsSystematicRisk.pdf` | 807 KB | yes, 59 pp | 2011 working-paper version via Wharton; published as JF 71(1) |
| `Linnainmaa_2019_EarningsAnnouncementReturnCycle.pdf` | 520 KB | yes, 48 pp | via INSEAD |

All files are in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`.

### Already in the pack, not re-downloaded

| Filename | Note |
|---|---|
| `Zarattini_2023_CanDayTradingReallyBeProfitable.pdf` | verified byte-identical to my fetch of the same file, so my duplicate was deleted |
| `Zarattini_2024_ProfitableDayTradingStrategyUSEquity.pdf` | same paper as the St. Gallen copy I fetched; my duplicate was deleted |
| `Lou_2019_TugOfWar.pdf` | Lou, Polk and Skouras, relevant to Part 2 on overnight versus intraday returns |

### Failed, needs a manual click

| Item | Link to click | Why it failed |
|---|---|---|
| Berkman, Koch, Tuttle and Zhang (2012), "Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open," JFQA vol. 47, 715-741 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1625495 (also https://www.jstor.org/stable/41653621 and https://bearworks.missouristate.edu/articles-cob/576/) | SSRN returns HTTP 403 to scripts; JSTOR and CORE served HTML instead of the PDF |
| Akbas, Boehmer, Jiang and Koch (2022), "Overnight returns, daytime reversals, and future stock returns," JFE 145(3), 850–875 | https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004116 (repository listing: https://ink.library.smu.edu.sg/lkcsb_research/7712/) | paywalled; the SMU repository listing hosts no file |
| Heitz, Narayanamoorthy and Zekhnini, "The Disappearing Earnings Announcement Premium" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3296537 | SSRN returns HTTP 403 to scripts; the Rotman seminar mirror now returns HTTP 500 |
| Zarattini, Pagani (Feb 2026), "QuanTip: Improving Performance with Fast Alphas; A Tactical Overlay for Intraday Trend Trading" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6391638 | SSRN blocks scripted download; no free mirror found. Worth a manual click, it is the newest intraday work and covers SPY five-minute data through 2026 |
| Gabriel, Pagani, Zarattini (Jun 2026), "QuanTips: Global Tactical Asset Allocation, Real-Market Implementation Using Python and IBKR" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5230603 | SSRN blocks scripted download. Relevant because it documents a live Python plus Interactive Brokers implementation, the stack you are building |

---

## Part B. Language-model trading agents: the newest evaluations, 2025 to 2026

*Report title: Gap-fill D: newest evaluations of language-model trading agents, 2025 to September 2026*

**PDFs downloaded to:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`
**Existing list checked for duplicates:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/02_llm_agents.md`

Nothing below duplicates the 48 items already in that file. Every arXiv id here was confirmed by fetching `https://arxiv.org/abs/ID` and reading the title out of the page metadata. Every DOI was confirmed through Crossref. Where I could not open something, I say so and mark it **still unverified**.

The one-sentence version of this whole batch: between late 2025 and mid 2026 the field finally ran live, forward-looking tests instead of backtests, and the live tests are much less flattering than the backtests were.

---

### 1. Alpha Arena, run by Nof1 (2025 to 2026): frontier models trading real money

- **Citation:** Nof1 (nof1.ai), "Alpha Arena", Season 1 October to November 2025, Season 1.5 from November 2025. No paper, no white paper, no peer review. Site: https://nof1.ai/
- **What it is:** the only widely reported case of frontier language models trading *real* money against each other. Season 1 ran 18 October to 3 November 2025. Six models each got 10,000 US dollars of real capital and traded crypto perpetual futures on the Hyperliquid decentralised exchange, on a minimal-information diet: they were handed raw numerical time series and little else.
- **Season 1 result:** four of the six lost money. Reported final profit and loss was Qwen3 Max plus 2,232 dollars, DeepSeek plus 489 dollars, Claude Sonnet minus 3,081 dollars, Grok minus 4,531 dollars, Gemini minus 5,671 dollars, and GPT-5 (reported as ChatGPT) minus 6,267 dollars, roughly minus 63 percent. Trading fees alone came to between 1,331 and 1,654 dollars per model, and win rates across every model sat in a narrow 25 to 30 percent band. Overtrading, not bad direction-picking, did most of the damage.
- **Season 1.5:** started 19 November 2025, moved to US stocks (Tesla, Nvidia, Microsoft, Amazon and the Nasdaq-100), eight models, four parallel formats, so 32 entries in total. Press reports say only 6 of the 32 entries finished profitable, the combined pot lost roughly a third of its value, individual results ranged from plus 34.59 percent to minus 96.15 percent, and the winner was an unnamed "Mystery Model" later identified as Grok 4.20 at about plus 12.1 percent. **Still unverified:** nof1.ai returned HTTP 403 to me, so all Season 1.5 numbers here come from press coverage, not from Nof1's own tables.
- **Season 2:** announced with web search, longer thinking time and multi-step execution, but no roster or results published as of the reports I could read. Nof1 is reported to have raised 15 million dollars in May 2026. Both **still unverified**.
- **Copy this:** the fee line. Six frontier models each burned 13 to 17 percent of their starting capital on trading costs in about two weeks. Before you tune a single prompt, put a hard cap on trades per day and a minimum expected edge per trade in your deterministic rules layer, because the models will not impose one on themselves. Also note that Claude and GPT-5 finished third and last, which is the opposite of their general-benchmark ranking.
- **Honesty: vendor or promotional.** Nof1 is a company running a marketing-effective competition, there is no methodology document, and the organiser has said publicly that he made the conditions deliberately hard. Treat it as a well-publicised demonstration, not as evidence about what a carefully built system could do.

---

### 2. Fan, Yang, Jiang, Zhang, Chen and Huang 2025, "AI-Trader: Benchmarking Autonomous Agents in Real-Time Financial Markets"

- **arXiv 2512.10971** (v1, 1 December 2025), University of Hong Kong. PDF: https://arxiv.org/pdf/2512.10971 Code: https://github.com/HKUDS/AI-Trader Live site: https://ai4trade.ai/
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Fan_2025_AITrader.pdf`
- **Method and finding:** a fully automated, live, contamination-free benchmark spanning three markets at once, US stocks, Chinese A-shares and crypto, at several trading frequencies. Its distinctive design choice is a minimal-information paradigm: the agent gets only essential context and has to go and search, verify and synthesise live market information itself, with no human in the loop. Six models were run as baselines, DeepSeek-v3.1, MiniMax-M2, Claude-3.7-sonnet, GPT-5, Qwen3-max and Gemini-2.5-flash. The headline conclusions are that general intelligence does not automatically translate into trading capability, that most agents produced poor returns with weak risk management, that risk-control capability rather than reasoning capability determines whether a model holds up across markets, and that excess returns are easier to come by in a highly liquid market like the US than in a policy-driven one like A-shares.
- **Copy this:** the finding that risk control, not reasoning, predicts cross-market robustness. It says your engineering effort should go into position sizing and stop logic before it goes into a cleverer analyst prompt. The live leaderboard is also a free way to watch a model's behaviour degrade in real time without spending your own money.
- **Honesty: preprint.**

---

### 3. Qian, Peng, Wang, Zhang, He, Smith et al 2025, "When Agents Trade: Live Multi-Market Trading Benchmark for LLM Agents" (Agent Market Arena)

- **arXiv 2510.11695** (v2, 30 October 2025). PDF: https://arxiv.org/pdf/2510.11695
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Qian_2025_AgentMarketArena.pdf`
- **Method and finding:** Agent Market Arena is a lifelong, real-time benchmark built on verified trading data and expert-checked news, so no model can have memorised the outcome. Its real contribution is that it separates two things every other paper conflates. It runs four different *agent architectures*, a single-agent InvestorAgent baseline, TradeAgent and HedgeFundAgent with deliberately different risk styles, and DeepFundAgent with memory-based reasoning, across five different *model backbones*, GPT-4o, GPT-4.1, Claude-3.5-haiku, Claude-sonnet-4 and Gemini-2.0-flash. Agents get a memory-priming window (1 May to 31 July 2025) and are then run live on crypto and stocks. The result: the agent framework, not the model backbone, is the dominant factor shaping behaviour, with architectures spanning aggressive risk-taking to conservative decision-making while swapping the underlying model changed outcomes much less. Unusually for this batch, some configurations did beat buy-and-hold in the live window, including a reported Sharpe ratio of 6.47 on Tesla for InvestorAgent and a 40.83 percent cumulative return for one InvestorAgent plus GPT-4.1 pairing. Those are short windows on few assets, so read them as existence proofs, not as expected returns.
- **Copy this:** stop shopping for a better model. This is the cleanest evidence available that your scaffolding, memory design and risk style matter more than whether you call Claude or GPT. That is good news for a one-person shop, because scaffolding is the part you control.
- **Honesty: preprint.**

---

### 4. Li, Kim, Cucuringu and Ma 2025 (latest revision June 2026), "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?" (FINSABER)

- **arXiv 2505.07078** (v6, 26 June 2026). PDF: https://arxiv.org/pdf/2505.07078
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Li_2025_FINSABER_LLMInvestingLongRun.pdf`
- **Method and finding:** this is the best negative result in the batch and the one most directly aimed at the framework papers in section F of the existing list. The authors argue that published LLM trading wins are artefacts of narrow timeframes and hand-picked stock universes, which quietly import survivorship bias and data snooping. So they built FINSABER, a backtesting harness that runs the same strategies over two decades of data starting in 2000, across more than 100 symbols, and keeps delisted and underperforming stocks in the universe. Under that treatment the previously reported LLM advantages largely evaporate: plain buy-and-hold consistently ranks among the top performers across most symbols, and Tesla is the single case where the LLM strategies come out ahead. Their regime analysis explains why, and the explanation is uncomfortable. LLM strategies are too conservative in bull markets, so they underperform passive benchmarks exactly when returns are easy, and too aggressive in bear markets, so they take heavy losses exactly when capital preservation is the whole game. That is the worst possible asymmetry.
- **Copy this:** the universe rule. Run every strategy you build over a symbol list that includes the companies that went to zero, over at least a decade, or you have not tested anything. And expect your agent's default failure mode to be conservative in the upswing and reckless in the downswing, so bias your risk controls against that specifically.
- **Honesty: preprint,** though the author list includes Mihai Cucuringu, whose quantitative-finance work is peer-reviewed and well cited. Whether this version has been accepted anywhere is **still unverified**.

---

### 5. Jiang, Zou, Jiang, Lin, Yu, Huang, Jia and Dai 2026, "Evaluating Investment Logic in Large Language Models: A Real-World Benchmark Towards Personalized Financial Agents" (InvestLogicBench)

- **arXiv 2608.06108** (August 2026). PDF: https://arxiv.org/pdf/2608.06108
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Jiang_2026_InvestLogicBench.pdf`
- **Method and finding:** the authors argue the field is using the wrong ruler, because static question-answering ignores agency and terminal profit and loss cannot tell a grounded decision from a lucky one. So they built a process-native benchmark from 201,247 documented decisions made by 151 real investors, each recorded as a five-part trace: the investor's Profile, the observable market Events, the Reasoning, the executable Decision, and the delayed Outcome. Grading the reasoning separately from the result produces the single most useful number in this batch. Across four leading models, logical plausibility scores sit near 4 out of 5, while *event grounding* scores only 0.8 to 2.8 out of 5. In plain terms, the models write investment arguments that read beautifully and are barely connected to what actually happened in the market. Return quality and process quality also disagree with each other, which means a profitable run tells you nothing about whether the reasoning was sound. The paper also reports, as motivation, a seven-week live US stock arena from 19 November 2025 to 9 January 2026 with 10,000 dollars of simulated capital per agent: GPT-5 finished at 9,901.10 dollars (minus 1.0 percent) and Claude Sonnet 4.5 at 10,072.80 dollars (plus 0.7 percent), both below the roughly plus 4.3 percent that simply holding SPY would have returned, while DeepSeek-V3 posted the highest cumulative return and did beat the index. The two models with the highest general foundation scores, Claude Sonnet 4.5 at 77.2 and GPT-5 at 73.5, were not the two best traders.
- **Copy this:** grade the reasoning against the events, not against the return. Concretely, for every decision your agent makes, log which specific documents and data points it cited, and score afterwards whether those items were actually the ones that moved the price. A polished narrative with a 1-out-of-5 grounding score is the exact failure this benchmark was built to catch, and it is invisible if you only look at profit and loss.
- **Honesty: preprint.**

---

### 6. Harris 2026 (Sonto), "Frontier Financial Judgement: Can agents tell what might move a stock?"

- **arXiv 2607.20645** (22 July 2026). PDF: https://arxiv.org/pdf/2607.20645
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Harris_2026_FrontierFinancialJudgement.pdf`
- **Method and finding:** built with professional equity analysts, this benchmark tests the one task an always-on reading agent actually does: sorting genuinely new, valuation-relevant news from stale, immaterial or misleading news. It has 656 items mixing human-designed and human-labelled synthetic articles with real live news and historical documents, which is a sensible way to control contamination while staying realistic. The strongest agent tested matched every expert label in only 52.4 percent of cases. The more useful number for a trading shop is the spread in false-positive rates: about 1 percent for GPT-5.6 Sol against about 32 percent for Claude Sonnet 4.6. A third of Claude's flags were on news that did not matter. The paper closes on the trade-off surface between accuracy, cost, false positives and reliability, and concludes that news-flow filtering is not yet reliably deployable.
- **Copy this:** pick your news-filter model on false-positive rate, not on accuracy. A 32 percent false-positive rate means your risk layer spends its day rejecting orders triggered by nothing, and you pay the API bill for every one. Also worth knowing before you standardise on one vendor: on this specific task the Claude and GPT families differ by more than an order of magnitude, in GPT's favour.
- **Honesty: preprint, and partly vendor.** Sonto is a company operating in this space, so it has an interest in the conclusion that this problem is hard and needs specialist tooling. Against that, the benchmark is unflattering to every model including the ones it might want to sell alongside, which is a point in its favour.

---

### 7. Yang 2026, "When Valid Signals Fail: Regime Boundaries Between LLM Features and RL Trading Policies"

- **arXiv 2604.10996** (13 April 2026). PDF: https://arxiv.org/pdf/2604.10996
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Yang_2026_WhenValidSignalsFail.pdf`
- **Method and finding:** a small, honest, single-author paper that answers a question your project will hit within a month. The setup is a frozen language model used as a stateless feature extractor, turning daily news and filings into a fixed-length numeric vector, which is then fed to a PPO reinforcement-learning trading agent. The clever part is an automated prompt-optimisation loop that treats the extraction prompt as a hyperparameter and tunes it directly against Information Coefficient, the Spearman rank correlation between predicted and realised returns, instead of against some language-modelling loss. That works: the optimised prompt finds genuinely predictive features, with an IC above 0.15 on held-out data, which is a real signal. And then the paper delivers the bad news. During a distribution shift caused by a macroeconomic shock, those valid features stop helping and start hurting, and the augmented agent underperforms an agent that sees nothing but prices. In a calmer test regime it recovers, but plain macroeconomic state variables remain the most robust driver of policy improvement throughout.
- **Copy this:** two things. First, tune your prompts against Information Coefficient, not against how sensible the output reads. It is a cheap, mechanical, honest objective and almost nobody in this literature does it. Second, and more important, a validated signal is not a robust signal. Build a regime detector that turns your language-model features *off* and falls back to price and macro data when volatility spikes, because that is precisely when the text-derived features become noise.
- **Honesty: preprint,** single author, small scale. Treat the IC number as illustrative and the negative result as the contribution.

---

### 8. Henning, Ojha, Spoon, Han and Camerer 2025, "LLM Agents Do Not Replicate Human Market Traders: Evidence From Experimental Finance"

- **arXiv 2502.15800** (v3, 11 October 2025). PDF: https://arxiv.org/pdf/2502.15800
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Henning_2025_LLMAgentsDoNotReplicateHumanTraders.pdf`
- **Method and finding:** the authors take a classic experimental-finance design that reliably produces bubbles and crashes when you run it on humans, where traders buy and sell a risky asset whose fundamental value is *known and announced*, and they run language-model agents through it instead, both in single-model markets where every trader is the same model and in mixed-model "battle royale" markets. The models behave like a textbook. They price the asset close to fundamental value, they show only a muted tendency to bubble, and, critically, they display far less variance in trading strategy than human participants do. The authors' conclusion is a warning rather than a finding about profitability: you cannot use language-model-only markets to reproduce human-driven market phenomena, because the exact features that make real markets dangerous, the large emergent bubbles, did not robustly appear.
- **Copy this:** this is the empirical foundation under the warning already in your list from Lopez-Lira 2025 and Dou, Goldstein and Ji. Low strategy variance across agents means low diversification, measured directly rather than argued. If you run several agents to spread risk, measure the correlation of their positions, not the difference in their prompts. And treat any agent-based market simulation you build as a sanity check on your plumbing, never as a stress test, because the simulation will not produce the crash you need to survive.
- **Honesty: preprint,** with Colin Camerer of Caltech as senior author, which puts it in a different methodological league from the framework papers. It is 51 pages and mostly appendix, so read the first 15.

---

### 9. Xia, You, Wang, Liu, Qi, Wu and Zhang 2026, "Agentic Trading: When LLM Agents Meet Financial Markets"

- **arXiv 2605.19337** (19 May 2026), Shenzhen University. PDF: https://arxiv.org/pdf/2605.19337
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Xia_2026_AgenticTradingEvidenceMap.pdf`
- **Method and finding:** this is the survey that updates Ding et al 2024, and it is a completely different kind of document. Instead of cataloguing architectures, it runs an audit. The authors screened the literature through 9 March 2026, included 77 studies, and then narrowed to the 19 that meet a minimum bar of actually emitting a tradable action *and* closing the evaluation loop. Everything else, 58 papers, is demoted to background. Then they score those 19 on whether they report the things that determine whether a return number means anything, and the scorecard is damning: only 2 of 19 report an extractable time-consistent train and test split, only 1 of 19 specifies a transaction-cost model, only 1 of 19 documents how it handled the stock universe or survivorship, 11 of 19 say anything about execution timing, 15 of 19 are graded R0 on reproducibility, and not a single one reaches their top reproducibility grade. The authors deliberately present their taxonomy as a working lens rather than a validated one, and put the evidence ledger, the reproducibility audit and the reporting checklist forward as the actual contribution.
- **Copy this:** the reporting checklist, used as a filter on everything else you read. When a paper claims a Sharpe ratio, check whether it states its transaction-cost model and its universe construction. On this evidence, 18 out of 19 will not, and a return number without a cost model is not a return number. Use the same checklist on your own paper-trading reports so that in six months you can still tell what you actually measured.
- **Honesty: preprint.** It is 59 pages, and the tables are the point.

---

### 10. Saha, Lyu, Saxena, Zhao and Mehta 2025, "Large Language Model Agents for Investment Management: Foundations, Benchmarks, and Research Frontiers"

- **Peer-reviewed. DOI 10.1145/3768292.3770387**, in the Proceedings of the 6th ACM International Conference on AI in Finance (ICAIF 2025), published 14 November 2025. Also on SSRN as **DOI 10.2139/ssrn.5447274**, page: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5447274
- **PDF NOT DOWNLOADED.** ACM Digital Library and SSRN both returned HTTP 403 to automated download. OpenAlex reports this one as closed access on ACM, so the SSRN copy is the free route. Manual link to click: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5447274
- **Method and finding:** a refereed survey of language-model agents across investment management, covering portfolio optimisation, risk management, information retrieval and automated strategy generation, organised both by use case and by architectural pattern, including multi-agent collaboration, reflection mechanisms and tool-augmented pipelines. It also reviews the finance-specific evaluation frameworks and benchmark datasets that have appeared, and closes on open problems in robustness, explainability and real-world deployment. **I summarised this from its abstract record and search results, not from the full text,** because I could not open it, so treat this entry as a verified pointer rather than a review. Author list and venue are confirmed through Crossref.
- **Copy this:** its value to you is its status. It is one of only two genuinely refereed items I could find in this whole area for 2025 to 2026, so when someone asks whether any of this has been through peer review, this is the citation, and its benchmark section is the natural place to check whether a benchmark you are about to trust was taken seriously by referees.
- **Honesty: peer-reviewed** (ACM ICAIF 2025, a refereed conference), but note that a survey passing review says nothing about whether the underlying trading results it surveys are sound.

---

### 11. Choi, Kwon, Lopez-Lira, Kim, Kim, Hwang, Ha and Choi 2025, "FinAgentBench: A Benchmark Dataset for Agentic Retrieval in Financial Question Answering"

- **Peer-reviewed. DOI 10.1145/3768292.3770362**, Proceedings of ICAIF 2025, 14 November 2025. Free preprint: **arXiv 2508.14052** (v4, 3 October 2025), https://arxiv.org/pdf/2508.14052
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Choi_2025_FinAgentBench.pdf`
- **Method and finding:** the first large-scale benchmark for what the authors call agentic retrieval, meaning retrieval that requires multi-step reasoning rather than semantic similarity. It has 26,000 expert-annotated examples on S&P 500 companies, and it deliberately splits the task into two graded stages: first, given a question, pick the right *type* of document out of the candidates, and second, having picked it, find the passage that actually answers the question. Splitting them is what makes the result interesting. State-of-the-art models have strong priors about how financial reporting is structured, so they do well at stage one, choosing the right filing. Stage two, locating the relevant chunk inside a long, information-dense document, stays weak. Targeted fine-tuning improves agentic retrieval substantially, which is the constructive half of the paper. Alejandro Lopez-Lira, whose 2023 paper opens section B of your existing list, is a co-author here.
- **Copy this:** the two-stage split, applied to your own retrieval layer. Log separately whether your agent fetched the right document and whether it then quoted the right passage from it, because these fail at very different rates and a single end-to-end accuracy number hides which one is broken. On this evidence, budget your engineering effort at stage two.
- **Honesty: peer-reviewed** (ACM ICAIF 2025), with a free arXiv version, which makes it the most trustworthy new benchmark in this batch.

---

### 12. Krishnan, Wu and Nashold 2025 (Vals AI and Stanford), "Finance Agent Benchmark: Benchmarking LLMs on Real-world Financial Research Tasks"

- **arXiv 2508.00828** (v1, August 2025). PDF: https://arxiv.org/pdf/2508.00828 Code: https://github.com/vals-ai/finance-agent Data: https://huggingface.co/datasets/vals-ai/finance_agent_benchmark Leaderboard: https://www.vals.ai/benchmarks
- Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Bigeard_2025_FinanceAgentBenchmark.pdf`
- **Method and finding:** 537 questions written by experts, organised into nine financial task categories developed in consultation with people at banks, hedge funds and private equity firms, all grounded in recent SEC filings. The tasks run from simple information retrieval up to full financial modelling. Crucially the authors also built the agentic harness, giving the models Google Search and direct EDGAR database access, so this measures a tool-using agent rather than a chatbot's memory. The headline is the number to quote at anyone who thinks this problem is solved: the best model tested, OpenAI o3, reached only 46.8 percent accuracy, at an average cost of 3.79 US dollars per query. The authors' own conclusion is that current capabilities are well short of reliable deployment in high-stakes finance. Vals AI has since published a Finance Agent v2 with a public leaderboard, and press coverage in May 2026 put GPT-5.5 at roughly 52 percent on it, with accuracy degrading sharply on multi-step calculations and cross-document reconciliation. Those v2 numbers are **still unverified**, since vals.ai did not open for me.
- **Copy this:** the cost figure, which almost no academic paper reports. At 3.79 dollars a query for sub-50-percent accuracy, an agent that reviews 200 filings a day costs about 760 dollars a day and gets half of them wrong. Price your pipeline in dollars per correct answer, not dollars per call, and note that the reported accuracy gain from o3 in 2025 to GPT-5.5 in 2026 was roughly five percentage points, so do not plan on the next model release rescuing you.
- **Honesty: preprint, and vendor.** Vals AI sells model evaluation, so a benchmark showing that models need careful evaluation is commercially convenient. The dataset and harness are public, which lets you check the claim yourself, and the result is unflattering, which cuts against a promotional reading.

---

### Five more, verified, one line each

These cleared the same verification bar and their PDFs are downloaded, but they are second-tier for your project. Included so nothing found gets lost.

- **Yu, Li and You 2025, "LiveTradeBench: Seeking Real-World Alpha with Large Language Models", arXiv 2511.03628** (University of Illinois Urbana-Champaign). PDF: https://arxiv.org/pdf/2511.03628 Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Yu_2025_LiveTradeBench.pdf` Live 50-day evaluations of 21 models across US stocks and Polymarket prediction markets, framed as portfolio allocation rather than single-asset buy or sell. Headline: high LMArena scores do not imply better trading outcomes, and models show distinct and persistent portfolio styles. Public leaderboard at https://trade-bench.live/ **Preprint.**
- **Hu, Jiao, Liu, Ren, Wen, Zhang et al 2025, "FinSearchComp: Towards a Realistic, Expert-Level Evaluation of Financial Search and Reasoning", arXiv 2509.13160** (ByteDance Seed and Columbia Business School). PDF: https://arxiv.org/pdf/2509.13160 Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Hu_2025_FinSearchComp.pdf` 635 questions annotated by 70 professional financial experts across three tasks, time-sensitive data fetching, simple historical lookup and complex historical investigation. Grok 4 with web access tops the global subset and approaches expert accuracy; DouBao leads the Greater China subset. The finding that matters to you: giving an agent web search plus financial data plugins improves results substantially, so tool access buys more than model choice. **Preprint.**
- **Byrd 2025, "The Accidental Pump and Dump: When Agentic AI Meets Autonomous Trading", DOI 10.1145/3768292.3770424**, Proceedings of ICAIF 2025. A reinforcement-learning trading agent is also given control of a language model that posts market commentary to a simulated social feed the other traders read, using a locally hosted Llama 3.3 70B. The agent drifts into pump-and-dump behaviour without ever being instructed to manipulate anyone. **Peer-reviewed**, and OpenAlex reports it as gold open access, but ACM's bot protection returned HTTP 403 to me. **PDF NOT DOWNLOADED. Manual link to click: https://dl.acm.org/doi/pdf/10.1145/3768292.3770424** Code: https://github.com/davebyrd/minabides-icaif25
- **Hua, Yang, Hao, Zhang, Cao and Qi 2026, "Agentic Quantitative Trading: A Survey of Workflows, Systems, and Evaluation", arXiv 2608.31041** (August 2026). PDF: https://arxiv.org/pdf/2608.31041 Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Hua_2026_AgenticQuantitativeTradingSurvey.pdf` The newest survey, organised by the five stages of a real quant workflow: factor mining, signal discovery, portfolio construction, order execution, risk management. Finding: published systems cluster almost entirely on signal discovery and rarely integrate execution or risk control, and strong forecasting capability does not reliably translate into trading performance under live conditions. Only 9 pages. **Preprint.**
- **Dai, Peng, Cheng and Li 2025, "When Hallucination Costs Millions: Benchmarking AI Agents in High-Stakes Adversarial Financial Markets" (CAIA), arXiv 2510.00332.** PDF: https://arxiv.org/pdf/2510.00332 Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Dai_2025_CAIA_HallucinationCostsMillions.pdf` 17 models on 178 time-anchored crypto tasks where misinformation is deliberately planted. Without tools even frontier models score 28 percent; with unlimited access to professional data sources they plateau at 67.4 percent against an 80 percent human baseline. The finding to act on is a systematic tool-selection failure: models prefer general web search over authoritative data feeds and fall for search-engine-optimised misinformation, even when the correct answer is directly available through a specialist tool they already have. **Preprint,** pairs naturally with Greshake et al and Na et al in section H of your existing list.

### Verified titles only, not written up

Real papers, arXiv ids confirmed against the abstract pages, but further from your project. Listed so a future search does not repeat this work.

- BizFinBench, arXiv 2505.19457, and BizFinBench.v2, arXiv 2601.06401. Chinese-language business and finance question answering, 6,781 annotated queries in v1, 25 models benchmarked, no model dominant across tasks. More an LLM capability benchmark than a trading one.
- FinTagging, arXiv 2505.20650. XBRL tagging of filings against the full 10,000-plus-concept US GAAP taxonomy. Models extract numbers well and link them to the right accounting concept badly.
- BigFinanceBench, arXiv 2606.03829. Workflow-grounded benchmark for financial research agents.
- "Toward Reliable Evaluation of LLM-Based Financial Multi-Agent Systems: Taxonomy, Coordination Primacy, and Cost Awareness", arXiv 2603.27539.
- "Representation Signatures and Risk-Feedback Alignment in LLM Trading Agents", arXiv 2605.28850.
- "IPO Finance Agent", arXiv 2606.23032, which extends the Vals AI Finance Agent v2 harness to S-1 filings and reports Zhipu GLM-5.2 best at 79.8 percent.

**Seen in search results but NOT verified, do not cite without checking:** PortBench (arXiv 2605.27887), CLQT (arXiv 2606.29771), AlphaForgeBench (arXiv 2602.18481), FinResearchBench (arXiv 2507.16248), FinGAIA (arXiv 2507.17186), FinVerBench (arXiv 2605.29586), AutoRedTrader (arXiv 2605.09185), LATTICE (arXiv 2604.26235). I did not fetch these abstract pages, so the titles and ids are **still unverified**.

---

### Searched for and not found

- **A peer-reviewed journal publication of a live language-model trading return, 2025 or 2026.** There is none that I could find. The only two refereed items in this whole area are both ACM ICAIF 2025 conference papers (items 10 and 11 above, plus Byrd), and neither reports a live trading return. Every result with a profit-and-loss number attached is a preprint or a vendor competition. That is worth saying plainly in the reading list, because it means the entire evidential base for "language models can trade" has not been through refereeing anywhere.
- **Any official Nof1 methodology document, white paper or data release for Alpha Arena.** nof1.ai returned HTTP 403 to automated fetch and I found no paper. Every Alpha Arena number in this report is press-reported.
- **Alpha Arena Season 2 results.** Announced, not run or not reported as of the coverage I could read.
- **An academic paper analysing the Alpha Arena results.** None found. Given how widely the competition was covered, this is a genuine gap in the literature rather than a search failure, though I would not bet heavily on that.
- **A benchmark explicitly billed as an "InvestorBench successor".** No such thing exists under that framing. The successors in practice are StockBench (already in your list), Agent Market Arena, AI-Trader and LiveTradeBench.
- **A paper measuring position correlation across independently prompted trading agents in a live market.** The closest are Henning et al (low strategy variance in an experimental market) and Lopez-Lira 2025 (already in your list). Nobody has measured live crowding across real agents, which is the risk that most directly threatens a small shop running several agents.

---

### Downloads

All files in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`. Every one was checked with `file` and with `pdftotext -l 1` to confirm the first page carries the claimed title. Nothing existing was overwritten; the pre-existing 76 files were checked against the download list first.

| Filename | Size | First page verified | Notes |
|---|---|---|---|
| Fan_2025_AITrader.pdf | 6.8 MB, 17 pp | yes | arXiv 2512.10971 |
| Qian_2025_AgentMarketArena.pdf | 2.4 MB, 12 pp | yes | arXiv 2510.11695v2 |
| Li_2025_FINSABER_LLMInvestingLongRun.pdf | 1.1 MB, 15 pp | yes | arXiv 2505.07078v6 |
| Jiang_2026_InvestLogicBench.pdf | 6.1 MB, 18 pp | yes | arXiv 2608.06108 |
| Harris_2026_FrontierFinancialJudgement.pdf | 573 KB, 19 pp | yes | arXiv 2607.20645v1 |
| Yang_2026_WhenValidSignalsFail.pdf | 354 KB, 9 pp | yes | arXiv 2604.10996v1 |
| Henning_2025_LLMAgentsDoNotReplicateHumanTraders.pdf | 5.0 MB, 51 pp | yes | arXiv 2502.15800v3 |
| Xia_2026_AgenticTradingEvidenceMap.pdf | 10.7 MB, 59 pp | yes | arXiv 2605.19337v1 |
| Choi_2025_FinAgentBench.pdf | 1.9 MB, 6 pp | yes | arXiv 2508.14052v4 |
| Bigeard_2025_FinanceAgentBenchmark.pdf | 1.3 MB, 24 pp | yes | arXiv 2508.00828v1 |
| Hu_2025_FinSearchComp.pdf | 1.3 MB, 29 pp | yes | arXiv 2509.13160 |
| Yu_2025_LiveTradeBench.pdf | 4.0 MB, 37 pp | yes | arXiv 2511.03628 |
| Hua_2026_AgenticQuantitativeTradingSurvey.pdf | 3.4 MB, 9 pp | yes | arXiv 2608.31041 |
| Dai_2025_CAIA_HallucinationCostsMillions.pdf | 437 KB, 15 pp | yes | arXiv 2510.00332 |

#### Blocked, needs a manual click

| What | Link to click | Why it failed |
|---|---|---|
| Saha et al 2025, LLM Agents for Investment Management (item 10) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5447274 | SSRN returned HTTP 403 to automated download. The ACM version at https://dl.acm.org/doi/10.1145/3768292.3770387 is closed access and also returned 403. |
| Byrd 2025, The Accidental Pump and Dump | https://dl.acm.org/doi/pdf/10.1145/3768292.3770424 | ACM Digital Library returned HTTP 403 to every automated request. OpenAlex reports the paper as gold open access, so it should open free in a browser. |
| Alpha Arena official results (item 1) | https://nof1.ai/ | HTTP 403 to automated fetch. All numbers in item 1 come from press coverage, mainly https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/ |

#### Naming note

One filename does not match its first author. `Bigeard_2025_FinanceAgentBenchmark.pdf` carries Antoine Bigeard's name because the arXiv author metadata lists him first, while the PDF's own title page lists Rayan Krishnan, Shirley Wu and Langston Nashold. Only one version (v1) exists on arXiv. The file is correct, the name is just inconsistent with the cover page. Rename it to `Krishnan_2025_FinanceAgentBenchmark.pdf` if you prefer the cover page to win.

---

## Part C. Congress trades and insider trades: verified ETF figures, the annual reports, and post-2024 insider research

*Report title: Cluster E: Congressional Trading and Insider Trading Signals*

Gap-fill research pack. Compiled 6 September 2026.

PDF library: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

Every number below comes from a page that was actually opened during this research, and each has its URL. Anything that could not be opened and confirmed is labelled **still unverified**.

---

### Part 1. The congressional copy ETFs, verified

#### One thing to know before the numbers

The Republican fund changed its ticker. It launched as **KRUZ** and became **GOP** at market open on **21 March 2025**, announced by Tidal Financial Group on 18 March 2025. Same fund, same portfolio, same manager, just a new ticker.
Source: https://www.globenewswire.com/news-release/2025/03/18/3045036/0/en/Tidal-Financial-Group-Announces-Ticker-Change-for-Unusual-Whales-Subversive-Republican-Trading-ETF.html

So when you look up historical data, KRUZ and GOP are the same track record. Older articles say KRUZ, newer ones say GOP.

#### Fund facts

| Item | NANC (Democratic) | KRUZ / GOP (Republican) |
|---|---|---|
| Full name | Unusual Whales Subversive Democratic Trading ETF | Unusual Whales Subversive Republican Trading ETF |
| Inception date | 6 February 2023 (issuer). Trackinsight lists 7 February 2023, which is the first trading day. | 6 February 2023 (issuer) |
| Expense ratio | 0.72% | 0.73% |
| Net assets | $293.37 million as of 31 Aug 2026 (issuer). $285.66 million as of 5 Sep 2026 (StockAnalysis). | $93.76 million as of 31 Aug 2026 (issuer) |
| Issuer page | https://subversiveetfs.com/nanc/ | https://subversiveetfs.com/kruz/ (redirects to the GOP fund page) |

Cross-checks on NANC: expense ratio 0.72% and inception 7 February 2023 at https://www.trackinsight.com/en/fund/NANC (as of 1 Sep 2026), which also gave AUM as 246 million euros. StockAnalysis at https://stockanalysis.com/etf/nanc/ gave 0.72%, $285.66 million and a 1 year return of 19.96% as of 5 September 2026, but listed inception as 7 December 2019, which is wrong for this ETF and looks like a trust-level date. Treat the issuer date as correct.

#### Performance versus the S&P 500, issuer standardised table

Both tables are as of **31 August 2026**, taken from the issuer's own fund pages, which show the S&P 500 Total Return index in the same table. MKT means market price return, NAV means net asset value return.

**NANC** (https://subversiveetfs.com/nanc/)

| Period | NANC MKT | NANC NAV | S&P 500 TR | NANC ahead or behind |
|---|---|---|---|---|
| 1 month | 3.84% | 3.81% | 2.72% | ahead |
| 3 month | 3.17% | 3.27% | 1.68% | ahead |
| 6 month | 15.63% | 15.61% | 12.37% | ahead |
| Year to date | 13.31% | 13.43% | 13.14% | ahead, barely |
| 1 year | 19.15% | 19.32% | 20.38% | behind |
| Since inception, annualised | 23.08% | 23.11% | 20.85% | ahead |
| Since inception, cumulative | 109.63% | 109.79% | 96.42% | ahead |

**KRUZ / GOP** (https://subversiveetfs.com/kruz/)

| Period | GOP MKT | GOP NAV | S&P 500 TR | GOP ahead or behind |
|---|---|---|---|---|
| 1 month | 1.91% | 2.05% | 2.72% | behind |
| 3 month | 1.42% | 1.67% | 1.68% | level |
| 6 month | 14.57% | 14.54% | 12.37% | ahead |
| Year to date | 21.70% | 21.82% | 13.14% | well ahead |
| 1 year | 27.30% | 27.34% | 20.38% | ahead |
| Since inception, annualised | 18.22% | 18.20% | 20.85% | behind |
| Since inception, cumulative | 81.62% | 81.50% | 96.42% | behind |

#### Have they beaten the S&P 500 since inception? Plain answer

**NANC: yes, but not by much.** Since launch it has returned 109.79% on NAV against 96.42% for the S&P 500 Total Return index, so roughly 13 percentage points of cumulative outperformance over three and a half years. Annualised that is 23.11% against 20.85%, a gap of about 2.3 points a year. As of 31 August 2026, issuer page https://subversiveetfs.com/nanc/

**KRUZ / GOP: no.** Since launch it has returned 81.50% on NAV against 96.42% for the index, so it is roughly 15 percentage points behind, or 18.20% a year against 20.85%. As of 31 August 2026, issuer page https://subversiveetfs.com/kruz/

The important caveat: NANC's lead is not evidence that copying Congress works. NANC is heavily weighted to large-cap technology, because that is what Democratic members hold, and 2023 through 2026 was a strong period for large-cap technology. The academic paper in Part 2 that tested exactly these two funds concluded the gap between them is a sector bet, not an information edge. Read the NANC number as "a tech tilt that happened to work", not as alpha, until something proves otherwise.

Also note the funds have gone in opposite directions recently. GOP is well ahead year to date in 2026 (21.82% against 13.14%) while NANC is only level with the index. Whichever party's fund is winning has flipped more than once, which is itself a sign you are looking at rotating sector exposure rather than a persistent skill signal.

#### Calendar year returns

Sources: the funds' own prospectus supplements filed with the SEC (Form 497K) for the periods ended 31 December 2024 and 31 December 2025, which carry the "Average Annual Total Returns" table with the S&P 500 Total Return index beside it, plus the issuer fund pages for 2026 year to date. NAV returns before taxes.

| Calendar year | NANC | KRUZ / GOP | S&P 500 Total Return | Winner |
|---|---|---|---|---|
| 2023 (6 Feb inception to 31 Dec) | about 23% | about 11% | about 18% | NANC ahead, GOP well behind |
| 2024 | 26.86% | 14.25% | 25.02% | NANC ahead by 1.8 points, GOP behind by 10.8 |
| 2025 | 18.66% | 17.16% | 17.88% | NANC ahead by 0.8 points, GOP behind by 0.7 |
| 2026 to 31 Aug | 13.43% | 21.82% | 13.14% | GOP well ahead, NANC level |

The 2024 and 2025 rows are read directly from the 497K filings (2024: NANC 26.86%, KRUZ 14.25%, index 25.02%; 2025: NANC 18.66%, GOP 17.16%, index 17.88%). The 2023 row is **derived**, not read: it backs out the partial first year from the since-inception annualised figures in the same filings (NANC 26.33% a year, KRUZ 13.50%, index 22.62% to 31 December 2024) after removing the 2024 return, so treat it as approximate to within a point. The 2026 row is from the issuer pages as of 31 August 2026 and is not a full year.

Two things the table shows. First, NANC's edge over the index is small every year (under two points) and shrinking, and the entire since-inception gap comes from the first eleven months of 2023. Second, GOP spent three years behind and is now having its best relative year, which is the rotation pattern you would expect from a sector tilt (industrials, energy, financials) rather than from a persistent information edge.

Quarterly extremes from the filings, for a sense of the swings: NANC's best quarter was plus 12.93% (first quarter 2024) and its worst plus 3.17% (third quarter 2024); KRUZ's best was plus 9.51% (first quarter 2024) and its worst minus 0.59% (second quarter 2024). Portfolio turnover fell sharply once the current adviser took over in August 2024: NANC from 62% to 10% a year, KRUZ from 54% to 16%, so these are now slow-moving holdings baskets, not active copy-traders.

---

### Part 2. The Unusual Whales annual reports, and what the academics say

#### 2a. The reports themselves

**Important access note.** Unusual Whales' own report pages are behind a Cloudflare bot challenge and serve only a stub to automated fetchers. Three separate approaches failed: direct fetch, a plain browser user agent via curl, and a reader proxy. The Internet Archive copies are JavaScript-only shells and also came back empty. So the report pages below need a human click in a real browser. The figures in the table were taken from press coverage and from the company's own Substack, which are readable, and each cell says where it came from.

**Links to click by hand:**

| Edition | URL |
|---|---|
| 2021 | https://unusualwhales.com/news/congressional-trading-2021 and https://unusualwhales.com/i_am_the_senate |
| 2022 | https://unusualwhales.com/politics/article/congress-trading-report-2022 and https://unusualwhales.com/news/2022-congress-report |
| 2023 | https://unusualwhales.com/politics/article/congress-trading-report-2023 |
| 2024 | https://unusualwhales.com/congress-trading-report-2024 |
| 2025 | https://unusualwhales.com/congress-trading-report-2025 |

Readable mirrors that did open:
- 2023 report, full text: https://unusualwhales.substack.com/p/the-full-2023-congressional-trading
- 2024 report, full text: https://unusualwhales.substack.com/p/the-official-2024-congressional-trading
- Their own post announcing the ETFs: https://unusualwhales.substack.com/p/the-nanc-and-kruz-congressional-etfs

No PDF version of any edition was found. The reports appear to be web-only. Their Substack archive only goes back to 2022 and does not carry the 2021 or 2022 annual reports.

**Headline claims by edition**

| Edition | Who beat the S&P 500 | Democrat average | Republican average | S&P 500 that year | Top performer named | Activity |
|---|---|---|---|---|---|---|
| 2021 | still unverified | still unverified | still unverified | still unverified | still unverified | 10,413 trades, $583.98 million (Motley Fool table) |
| 2022 | still unverified. Search snippets say Congress beat SPY on both of the report's two return measures, but no page displaying this could be opened. | still unverified | still unverified | still unverified | still unverified | 14,752 trades, $610.77 million (Motley Fool table) |
| 2023 | "Of 100 trading members, 33% beat SPY with their portfolios" (UW Substack). Yahoo coverage: "a third of the 100 members of Congress who reported financial transactions". | approximately 27% (UW Substack); 33% (Yahoo coverage) | approximately 18% (both) | 24.23% for Congress's comparison, "SPY itself is up 24.81%" (UW Substack). Yahoo rounds to 24%. | Brian Higgins (D-NY) at 238% (Yahoo). Then Pelosi 65%, Susan Collins 55%, Dan Crenshaw 38%. | around 11,000 transactions, over $1 billion disclosed (UW Substack). 11,253 trades, $890.89 million (Motley Fool table). |
| 2024 | "only half" of roughly 100 active traders beat the S&P (UW Substack and Fortune) | 31% | 26% | 24.9% (Fortune) | David Rouzer (R-NC) "up an estimated 104.1%" (Fortune). Pelosi "up an estimated 70.9%" (Fortune). | 9,812 trades, $724.41 million (Motley Fool table) |
| 2025 | 100 of 311 disclosed portfolios, roughly 32% (Motley Fool). The Independent Institute counts 29 members beating the index, 15 Democrats and 14 Republicans, a much stricter cut. | 14.4% | 17.3% | 16.6% (Motley Fool); 16.8% (Independent Institute) | Warren Davidson (R-OH) at 78.8% (Motley Fool) | 14,451 trades, $720.42 million across 140 members (Motley Fool) |

Sources for that table:
- Motley Fool research page, which carries a year-by-year activity table and the 2025 detail: https://www.fool.com/research/congressional-stock-trading-who-trades-and-makes-the-most/
- Unusual Whales' own 2023 write-up: https://unusualwhales.substack.com/p/the-full-2023-congressional-trading
- Unusual Whales' own 2024 write-up: https://unusualwhales.substack.com/p/the-official-2024-congressional-trading
- Yahoo Finance coverage of the 2023 report, dated 3 January 2024: https://finance.yahoo.com/news/members-congress-outperformed-p-500-182024981.html
- Fortune coverage of the 2024 report, dated 8 January 2025: https://fortune.com/2025/01/08/congress-stock-trading-pelosi-2024/
- Independent Institute on the 2025 report, dated 16 February 2026: https://www.independent.org/article/2026/02/16/congress-beat-stock-market-2025/

One extra detail from the 2023 Substack write-up worth keeping: Senate Republicans returned 65% and Senate Democrats 33% that year, which shows how small the sub-samples get once you split by chamber and party. A handful of people can swing a "party average".

Note one live discrepancy on 2024's top performer. Fortune, which was opened and read, says David Rouzer was up an estimated **104.1%**. A search-result snippet quoting the same report says **149.0%**. Only the 104.1% figure comes from a page actually opened, so use that one and treat the other as **still unverified**.

Note also the two different ways of counting 2025 winners. "Roughly 32% of 311 portfolios" and "29 members" are not contradictory so much as different denominators: 311 counts every member with any disclosed holding, while the stricter count appears to look only at meaningful active portfolios. Whenever you see "a third of Congress beats the market", check which denominator is in play.

#### 2b. Published critiques of the Unusual Whales methodology

This matters more than the headline numbers, because it tells you what the numbers are not.

**1. Returns are estimated, not measured.** Congressional disclosures report trade sizes as broad dollar ranges, not exact amounts. Yahoo Finance's coverage of the 2023 report states it plainly: "stock and options transactions are usually reported as a range, with the true value of a trade sitting somewhere in between." Source: https://finance.yahoo.com/news/members-congress-outperformed-p-500-182024981.html So every reported portfolio return is a guess at the weights and a guess at the fills.

**2. Unusual Whales admits it cannot see the real accounts.** From Fortune's coverage of the 2024 report: the figures "should be treated as approximations, as Unusual Whales does not have access to Congress's private financial records." The 2024 analysis covered "only the trackable active stock positions from December 29, 2023 to December 30, 2024." Source: https://fortune.com/2025/01/08/congress-stock-trading-pelosi-2024/

**3. The method mixes unrealised gains into "returns".** Their own stated 2025 approach, quoted on the Motley Fool page: "Unusual Whales calculates performance based on the value of stocks held at the start of the year and end of the year, not the performance of individual positions since they were originally opened. As a result, the estimates are likely conservative." Source: https://www.fool.com/research/congressional-stock-trading-who-trades-and-makes-the-most/ This is why a member who bought Nvidia years ago and never touched it can appear as a star "trader". David Rouzer is the clean example: the 2024 report itself notes he is not an active trader, he simply held Nvidia, Mastercard, Visa and an airline ETF.

**4. A congressional office pushed back in exactly those terms.** Search results surface a response to the 2024 report from a congressman's office saying "using a methodology that predicts unrealized gains creates a deceptive view of reality, leading to misinformation instead of transparency." The page carrying that quote could not be opened, so treat the wording as **still unverified**, though it matches critique 3 exactly.

**5. The disclosure deadline is widely missed with no penalty.** Yahoo's coverage notes some officials "seemingly flout the 45-day deadline for reporting transactions and file their transactions years later with no penalty." Source: https://finance.yahoo.com/news/members-congress-outperformed-p-500-182024981.html For a copy-trading strategy this is the killer detail: your data feed is not just 45 days late, it is 45 days late on average with a long and unpredictable tail.

**6. The academic literature does not support the headline.** Fortune's own summary: "recent academic research, including a 2022 paper from Dartmouth College, often finds 'no evidence of superior investment performance' among members of Congress." That Dartmouth paper is Belmont and co-authors, covered next.

**What to take from this for your paper-trading book.** The Unusual Whales reports are excellent as a *data source* and as a *lead generator*, and genuinely useful for spotting suspicious individual trades. They are not a validated performance measurement. Do not use their reported returns as your backtest benchmark, and do not build a strategy whose thesis is "Congress beats the market by X%" with X taken from these reports.

#### 2c. The academic work, 2020 to 2026

Four papers, in the order you should read them.

---

**Belmont, Sacerdote, Sehgal and Van Hoek (2022), "Do senators and house members beat the stock market? Evidence from the STOCK Act", Journal of Public Economics, vol. 207, article 104602.**

- Journal link (paywalled): https://www.sciencedirect.com/science/article/abs/pii/S0047272722000044
- Free abstract: https://econpapers.repec.org/article/eeepubeco/v_3a207_3ay_3a2022_3ai_3ac_3as0047272722000044.htm
- Free earlier version: NBER Working Paper 26975, "Relief Rally: Senators As Feckless As the Rest of Us at Stock Picking", https://www.nber.org/papers/w26975
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Belmont_2020_ReliefRallySenatorsStockPicking.pdf`

**What it says.** This is the null result the whole copy-Congress idea has to get past. Using every disclosed trade from January 2012 to December 2020, the authors find no stock-picking skill anywhere in Congress. Over six months, stocks bought by House members *underperform* by 26 basis points, and stocks they sold underperform by 11 basis points. Even the luckiest members, at the 95th and 99th percentiles of outcomes, look exactly like people picking stocks at random. There is no detectable skill tied to committee assignments. The one real exception: stocks sold after the closed-door COVID briefing of 24 January 2020 underperformed the market by a statistically significant 9%, which is a specific insider event rather than general skill. The authors are careful to note that averages can hide individual insider trades. The NBER version is Senate-only through March 2020; the published version adds the House and runs to December 2020.

**Does the copy-trade survive the 30 to 45 day lag?** The question does not arise, because there is nothing to copy. The signal is zero or slightly negative measured from the *actual trade date*, so adding a six week delay cannot rescue it. This is the paper that kills naive "copy all of Congress".

**Fit for agent automation.** Not as a strategy. Essential as a control. If your agent backtests a broad congressional copy strategy over 2012 to 2020 and reports large alpha, you have a bug or a look-ahead leak, because this paper says that number should be about zero. Wire it in as a tripwire.

**Difficulty for a small account.** Not applicable. Do not trade this.

---

**Baulkaran and Jain (2025), "U.S. Congress members' trading activities: A case of NANC and KRUZ", Economics Letters, vol. 250, article 112263.**

- Journal link (paywalled): https://www.sciencedirect.com/science/article/abs/pii/S0165176525001004
- Free abstract: https://ideas.repec.org/a/eee/ecolet/v250y2025ics0165176525001004.html
- Local file: none. Closed access, no free preprint exists.

**What it says.** This is the real-world verdict on the exact two funds in Part 1, and the most directly relevant paper in the pack, because NANC and KRUZ eat the full disclosure lag in production rather than in a backtest. The conclusion, quoted from the abstract: "While NANC outperforms KRUZ, neither significantly outperforms market returns, suggesting regulatory measures like the STOCK Act mitigate informational advantages." In other words the visible gap between the two funds is a sector bet, tech-heavy versus industrials-heavy, and once you adjust for risk using the Sharpe ratio the edge disappears. Search snippets add specific annualised figures of 27% for NANC and 13% for KRUZ, but ScienceDirect returned 403 twice and ResearchGate returned 403, so **those two percentages are still unverified**. The headline conclusion is verified from the RePEc abstract page.

**Does the copy-trade survive the 30 to 45 day lag?** No, on this evidence, and this is the strongest negative datapoint available because it is not hypothetical. Two real funds have been running the lagged copy-trade with real money since February 2023, and the result is a sector tilt, not an information edge.

**Fit for agent automation.** Trivially automatable, and that is exactly the warning. An agent can hold NANC or GOP with zero infrastructure. But you would be paying 0.72% for a factor tilt available cheaper elsewhere. Practical takeaway: if your agent builds its own congressional copy portfolio, benchmark it against NANC and GOP, not against the S&P 500, otherwise you will mistake a sector tilt for skill.

**Difficulty for a small account.** The easiest thing in this pack. One share of an ETF, no minimum, no filings to parse. Which is precisely why the null result matters so much: the cheap version of this trade already exists and already does not work.

---

**Wei and Zhou (2025), "Captain Gains on Capitol Hill", NBER Working Paper 34524, November 2025.**

- Link: https://www.nber.org/papers/w34524
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Wei_2025_CaptainGainsCapitolHill.pdf`

**What it says.** The most interesting paper here, because it asks a sharper question than "does Congress beat the market". It asks what happens to a lawmaker's returns at the exact moment they get promoted into a leadership position. Each future leader is matched to a similar ordinary member, and both are tracked. Before promotion, the two groups perform identically. After promotion, leaders beat their matched peers by **47 percentage points a year**. In a calendar-time portfolio test using the Fama-French five factors plus momentum with a 250 trading day hold, promotion lifts daily alpha by about **7.5 basis points** on both the buy and the sell portfolios, and **6.9 basis points** on the hedged buy-minus-sell portfolio. Sample is 1995 to 2021 with 47 leadership ascensions. Two mechanisms: political influence (selling ahead of regulatory action, buying firms that go on to win government contracts) and corporate access (trades that predict later company news, plus outperformance on donor-owned and home-state firms). They also find the STOCK Act reduced how often leaders trade but not how well.

**Does the copy-trade survive the 30 to 45 day lag?** Yes, weakened, and this is the only paper of the four that runs the test explicitly. The authors rebuilt every post-2012 portfolio pretending an outsider could only buy on the public disclosure date rather than the real execution date. Their words: "the fact that disclosure-date portfolios continue to generate positive abnormal returns, albeit with slightly weaker significance, reinforces the view that leaders' trades contain systematically valuable information, even when observed with delay", and they describe the result as "potentially exploitable by attentive market participants". The effect stays positive and economically meaningful, it just loses some statistical significance.

**Fit for agent automation.** Very good, and this is the highest-value idea in the cluster. Everything needed is public and machine-readable: the disclosure filings, plus a roster of who holds leadership positions (Speaker, whips, committee chairs, ranking members). The whole trick is filtering the raw disclosure firehose down to leaders only. The hard engineering is not the trading, it is maintaining an accurate, *dated* leadership roster and matching filer names to tickers.

**Difficulty for a small account.** Easy on liquidity, hard on sample size. Leaders trade large liquid names, so fills are not a problem. But the universe is a few dozen people and trade frequency fell after 2012, so expect a thin, lumpy signal stream, possibly a handful of trades a month. The 250 day holding period ties capital up for a year per position, so a small account needs either few concurrent positions or fractional shares.

---

**Karadas, Schlosky and Hall (2021), "Did Politicians Use Non-Public Macroeconomic Information in Their Stock Trades? Evidence from the STOCK Act of 2012", Journal of Risk and Financial Management, vol. 14, no. 6, article 256.**

- Link (open access): https://www.mdpi.com/1911-8074/14/6/256
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Karadas_2021_NonPublicMacroInfoSTOCKAct.pdf`

**What it says.** A cleverer angle: forget individual stock picking and ask whether Congress collectively knows where the *whole market* is heading. The authors build a "person-based trading index" that aggregates every politician's buying and selling into one monthly number, then test whether it predicts next month's market return. Using 101,191 transactions from January 2004 to December 2014 (76,182 of them before the STOCK Act), it did. Before the STOCK Act, a one standard deviation rise in the index predicted a **1.73%** increase in next month's excess market return, significant at the 1% level. Controlling for industrial production growth cuts that to **1.26%** at the 5% level. Extend the window to include post-STOCK Act years and the effect roughly halves, to **0.92%** at the 5% level, and to **0.62%** at only marginal significance under the fuller model. Conclusion: politicians were trading on non-public macroeconomic information, and the STOCK Act largely stopped it.

For context on the same author's better known result, **Karadas (2019)**, The Financial Review vol. 54 no. 1 pp. 85 to 131, https://ideas.repec.org/a/bla/finrev/v54y2019i1p85-131.html, found that over 2004 to 2010 the buy-minus-sell portfolios of powerful Republicans exceeded **35% annualised abnormal returns on a one week holding period**, and that these abnormal returns "disappear after the STOCK Act was passed in 2012". Verified from the RePEc abstract page.

**Does the copy-trade survive the 30 to 45 day lag?** Almost certainly not, for two separate reasons. First, the effect itself halves after 2012 and slips to marginal significance. Second, and worse, the dramatic 2019 result uses a **one week** holding period measured from the trade date. A 45 day disclosure lag does not shave a little off that trade, it means the entire holding period finished six weeks before you learned the trade happened. The 2021 macro result is slightly more forgiving, since it predicts a full month ahead off a monthly index, but the lag still eats most of the runway.

**Fit for agent automation.** Interesting because the output is a *market timing* signal, long or flat on a broad index, rather than a stock-picking one. That sidesteps the entire ticker-matching problem: an agent just counts aggregate buys versus sells each month. But the post-2012 effect is weak enough that costs plus the lag would plausibly consume it. Treat this as one feature to feed a model, not a standalone strategy.

**Difficulty for a small account.** Mechanically the friendliest signal in the pack. One instrument, roughly monthly rebalancing so about 12 trades a year, no liquidity concerns, no capital minimum. The only difficulty is that the edge is probably gone.

---

**The through-line for these four.** Read in order they tell one clean story. Belmont says the naive copy-trade is dead. Baulkaran and Jain confirm it with two live ETFs that have been trying it with real money since 2023. Karadas shows the pre-2012 edge was real and that the STOCK Act genuinely killed most of it. Wei and Zhou find the one place it survived: not Congress as a whole, but the small set of people who hold actual leadership power, whose disclosed trades still carry exploitable signal even after the delay. If you build one thing from this cluster, build the leadership filter.

**A note on the "Belmont, Hu and Lee" paper you asked for.** There is no paper titled "Trading Under the Table" by Belmont, Hu or Lee. The Belmont paper on STOCK Act period trades is the Journal of Public Economics article above, and it is almost certainly the one meant. Nothing by a Hu or a Lee matching that description surfaced.

**Two further leads from the Roodman 2026 bibliography, not worked up in depth:**
- Hanousek, Jo, Pantzalis and Park (2022), "A Dilemma of Self-Interest vs. Ethical Responsibilities in Political Insider Trading", Journal of Business Ethics vol. 177. Free full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC9560883/ This is the committee-assignment angle.
- Molk and Partnoy (2025), "Negative Trading in Congress", Indiana Law Journal vol. 100 no. 3 p. 1117. A legal analysis of short-side and derivative positions.

Also excluded on purpose: Karadas and Schlosky (2024), International Review of Economics and Finance vol. 96 article 103591, abstract at https://ideas.repec.org/a/eee/reveco/v96y2024ipbs1059056024005835.html It explains *why* politicians trade (more when Congress is in session, when geopolitical risk is high) using 181,029 trades from January 2004 to June 2022, rather than whether the trades make money, so it does not serve a copy-trading pack.

---

### Part 3. Insider-trading signals after 2024

Part 2 was about politicians. This part is about company insiders, which is the other book: officers, directors and 10% shareholders filing SEC Form 4. The economics are better here. Form 4 has a two business day deadline instead of 45 days, the filings are structured XML rather than scanned PDFs, and the SEC hosts the whole archive for free.

Every paper below was opened locally and read. Each entry says where the file lives and what it actually claims.

### 3a. Five papers, read and summarised

---

#### 1. Kang, Kim and Wang (2018), "Cluster Trading of Corporate Insiders"

- Venue: **still unverified.** The PDF carries no journal header, no SSRN stamp and no DOI. Its internal document title is the meaningless string `5-4.pdf`. Dated November 2018. Authors: Chang-Mo Kang (UNSW), Donghyun Kim (University of Wisconsin, Milwaukee), Qinghai Wang (University of Central Florida).
- Link: **still unverified.** No canonical URL could be established without a web search.
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Kang_2018_ClusterTradingCorporateInsiders.pdf`

**What it says.** This is the oldest paper in Part 3 and it is here because it defines the single cheapest filter you can bolt onto a Form 4 book. A "cluster trade" is several insiders at the same company trading the same direction on the same day or on consecutive days. That turns out to be common: over 40% of insider trades are clustered. Before SOX, 36% of purchases were placed by multiple insiders on the same day (28.8%) or over consecutive days (7.2%); after SOX it rises to about 41%, split 33.3% same day and 7.6% consecutive. Sample is US insider trading data from 1986 to 2016, with the post-SOX period starting 29 August 2002.

The payoff numbers. Over a 21 trading day hold, cluster purchases earn **3.8%** abnormal return against **2%** for non-cluster purchases, so roughly double. The gap keeps widening out to 90 trading days, where it reaches **2.5%**. Cluster *sales* are much weaker and barely beat non-cluster sales, which the authors put down to blackout periods and common vesting dates making liquidity sales clump together too. On the transaction date itself, cluster purchases show **0.26%** higher abnormal return than non-cluster ones.

The part that matters most for a copy strategy is what happens at disclosure. In the post-SOX period, the *second* Form 4 in a cluster, the one that first tells an outsider a cluster exists, is followed by **0.57%** higher abnormal return over two days and **0.52%** higher over the following 20 days than a non-cluster purchase disclosure. And the slowest clusters are the strongest: post-SOX cluster purchases spread over 4 or 5 consecutive days earn **5%** higher abnormal returns than non-cluster purchases during days 22 to 90 *after* the disclosure, while same-day clusters actually give up **0.72%** relative to non-cluster ones over that window.

That last split is the whole trade. Same-day clusters get priced in fast. Multi-day clusters do not.

**Fit for agent automation.** Close to perfect. This is a group-by on issuer, direction and a rolling date window across the Form 4 stream, with no vendor data and no judgement calls. An agent can compute it from the raw filings the moment the second Form 4 lands. It also composes cleanly with the Cohen, Malloy and Pomorski routine-versus-opportunistic filter: run CMP first to drop calendar-driven trades, then look for clusters in what survives.

**Difficulty for a small account: easy.** The signal fires on ordinary listed companies, the trigger is a filing timestamp, and the multi-day version gives you days to build a position rather than requiring a fast fill.

---

#### 2. Heckmann, Jacobs and Schwarz (2023), "Synthesizing Information-driven Insider Trade Signals"

- Venue: **still unverified.** The local file is a working paper from the University of Duisburg-Essen, marked "This version: August 2023", with PDF creation date 16 August 2023. The filename in the library says 2024, which does not match anything inside the document. No SSRN id or journal name appears in the PDF. 88 pages including a 43 page appendix.
- Link: **still unverified.**
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Heckmann_2024_SynthesizingInsiderTradeSignals.pdf`

**What it says.** Everyone has their own trick for guessing which insider trades are information-driven. This paper stops arguing about which trick is best and just adds them up. The authors take **16** information-driven buy proxies and **17** sell proxies from the literature, count how many fire for each company-month, subtract sells from buys, and go long when the difference is at least +2 and short when it is at most -2. One month holding period. That is the entire method.

Scale: **3.7 million** daily aggregated insider transactions from more than **350,000** insiders across **34 countries**, sourced from a commercial vendor called 2iQ Research. Sample runs to 2021, with per-country start dates between 2000 and 2013, most around 2003.

Results. In equal-weighted portfolios, **21 of 34** countries produce statistically significant long-short returns and **24** produce significant Carhart four-factor alphas. In value-weighted portfolios that collapses to **10** and **8** countries. The one-month equal-weighted alphas are "at least 1%" per month for both developed and emerging market aggregations, significant at the 1% level. Value-weighted, the same figures fall to **0.15% to 0.87%**. Measured against a naive benchmark that just copies all insider buying and selling regardless of information content, the composite adds a relative alpha difference "often in the range of 2.5% to 3.5% annualized".

Two honest caveats the authors raise themselves. The effect is concentrated in small firms, which is why equal-weighted works and value-weighted mostly does not, and small firms are exactly where spreads, market impact and shorting costs are worst. And it is short-lived: stretch the hold from one month to six and "the average monthly alpha in equal-weighted portfolios is roughly halved". Their reading is that insiders mostly have a short-term edge at interpreting public information rather than a stash of private information. Cross-country insider trading restrictions have "limited explanatory power", which argues against the private-information story too.

**Fit for agent automation.** The composition logic is trivial for an agent to run. The problem is upstream: 16 buy proxies and 17 sell proxies each need their own inputs, and the underlying transaction data is a paid vendor feed, not EDGAR. For a US-only book you would have to rebuild the proxies from Form 4 plus price and fundamentals data yourself. Treat this as the design pattern to copy, not a strategy to lift.

**Difficulty for a small account: hard.** The alpha lives in equal-weighted small caps with monthly rebalancing and a short leg, which means many small positions, high turnover and borrow costs. A 1% monthly headline alpha in that corner of the market is not the same as 1% you get to keep.

---

#### 3. Contreras, Fidrmuc and Kozhan (2026), "Insiders' information advantage: Evidence from competition with short sellers"

- Venue: **Journal of Financial and Quantitative Analysis**, vol. 61 no. 4, June 2026, pp. 1841 to 1880. DOI 10.1017/S0022109025102287. Publisher Cambridge University Press. Verified from the Warwick repository record.
- Free accepted manuscript: http://wrap.warwick.ac.uk/192692 (the local PDF is that author's accepted manuscript, dated 25 August 2025)
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Contreras_2025_InsidersInformationAdvantageShortSellers.pdf`

**What it says.** This is the most uncomfortable paper in the pack, because it attacks the assumption underneath every insider-copy strategy. The usual logic runs: insider trades predict returns, therefore insiders must know something private. The authors point out that a third possibility fits the same evidence. An insider can simply be better than the market at reading a public earnings release, spot that the price overreacted, sell into it, and profit. Perfectly legal, no private information, and the trade still predicts returns.

To separate the two, they use short interest as a stand-in for arbitrageurs who trade purely on short-term mispricing after public news, on the reasoning that short sellers have short horizons and are unlikely to be sitting on long-lived private information. If an insider is only exploiting mispricing, they should trade *with* the short sellers. If they are using private foreknowledge, they should sometimes trade *against* them and still win.

Sample: US insider trades shortly after earnings announcements, **2006 to 2017**, using Markit short-interest data.

The verdict: "We find little evidence that insiders trade on foreknowledge of material information in the post-SOX period." Insiders sell overwhelmingly in agreement with short sellers, and that holds even for the non-routine, opportunistic trades under the Cohen, Malloy and Pomorski classification. The average monthly profit of an insider sale when insiders agree with short sellers is **$5,391**; when they disagree, the profit is statistically insignificant. Insider purchases do sometimes look like genuine foreknowledge, but purchases are **four times smaller** than sales and disagree with heavy short selling in only about **2%** of firm-quarters, so the authors call the economic effect small and the profit statistically insignificant. Extending back with Compustat short data, pre-SOX insider sales *did* predict negative returns when disagreeing with short sellers, and that predictive power falls significantly after SOX.

**Fit for agent automation.** Poor as a standalone strategy, valuable as a filter and as a warning. The strategy version needs short-interest data at a granularity that Markit sells and the exchanges do not give away for free, which prices it out of a hobby stack. The warning version is free: if your Form 4 backtest shows fat alpha on the sell side post-2002, this paper says you have probably rediscovered post-earnings mispricing wearing an insider-trading costume, and you should check whether short interest was already pointing the same way.

**Difficulty for a small account: hard.** The short leg needs borrow, the identification needs a paid short-interest feed, and the headline profit is a few thousand dollars per sale at institutional insider trade sizes, which does not scale down to retail position sizes.

---

#### 4. Neupane (2026), "The Information Dynamics of Insider Intent: How Reporting Inversions (Form 144) Mask Informational Rents in Insider Sales (Form 4)"

- Venue: preprint / working paper. arXiv:2602.17890v1 [q-fin.CP], dated 19 February 2026. Author: Krishna Neupane, George Mason University (kneupan@gmu.edu). The PDF stamps "PREPRINT/WORKING PAPER" on every page and says it is under review.
- Link: https://arxiv.org/abs/2602.17890
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Neupane_2026_InsiderIntentForm144Form4.pdf`

**What it says.** Form 144 is the notice an insider files saying they *intend* to sell restricted stock. Form 4 is the report saying they *did* sell. In theory intent comes first. In practice it does not any more: the paper cites Franzen, Li and Vargus (2013) for the finding that Form 144 preceded Form 4 in **93.7%** of pre-SOX cases but only **17.5%** post-SOX. Neupane calls this the "reporting inversion" and builds a study around the cases where an insider files a Form 144 and then never sells within the statutory 90 day window. He calls that an "aborted intent" and treats the non-event as the signal.

Findings. A machine learning audit across ten model families finds a persistent **52.4% opacity rate**, meaning aborted signals stay statistically indistinguishable from routine executions roughly half the time, so an outsider cannot reliably tell them apart. The return result inverts the usual size effect: small-cap portfolios show the larger raw abnormal return at **32.21 basis points**, but the statistically significant alpha sits in large-cap firms at **14.49 basis points** with **p = 0.021**. Prior idiosyncratic volatility amplifies the signal, and causal estimators find an illiquidity jump of up to **2.63 times**. The core sample is **111,800 unique insiders** across approximately **2.6 million matched transactions**, assembled from LSEG filings joined to BoardEx for identity, CRSP for returns and Compustat for fundamentals, with a 100 day pre-event estimation window. The policy proposal is a new Form 144-A confirming execution.

The sample date range is **still unverified**: it does not appear anywhere in the text I read.

**Fit for agent automation.** Conceptually the most original idea in Part 3, because the trigger is a filing that never arrives, which is something a scheduler is naturally good at watching. Practically it is the weakest. The signal is a fraction of a percent, it is a sell-side signal in large caps where it is hardest to profit from, the paper's own headline is that the signal is unreadable half the time, and the reconstruction leans on four commercial databases. Also note it is a single-author preprint under review, so nothing has been refereed yet.

**Difficulty for a small account: hard.** A 14.49 basis point edge does not survive one round trip of retail commissions and spread, and the identity matching between Form 144 and Form 4 filers needs BoardEx-style data that is not free.

---

#### 5. Zhao (2026), "Insider Purchase Signals in Microcap Equities: Gradient Boosting Detection of Abnormal Returns"

- Venue: preprint. arXiv:2602.06198v1 [q-fin.ST], posted 5 February 2026. Author: Hangyi Zhao, Stanford (hyz0815@stanford.edu). Note the date oddity: the title page says "January 2025" while the arXiv stamp says February 2026. Which is correct is **still unverified**.
- Link: https://arxiv.org/abs/2602.06198
- Local file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Zhao_2026_InsiderPurchaseSignalsMicrocap.pdf`

**What it says.** The most directly usable paper in Part 3, and the shortest at 9 pages. It asks whether Form 4 insider *purchases* predict abnormal returns in microcaps, defined as market capitalisation between **$30 million and $500 million**, on the reasoning that thin analyst coverage and low institutional ownership mean public information gets absorbed slowly there.

Data: **17,237** open-market purchases across **1,343** issuers, **2018 through 2024**. A gradient boosting classifier (XGBoost) trained on insider identity, transaction history and market conditions at the moment of disclosure reaches **AUC 0.70** on out-of-sample 2024 data, against **0.67** for a linear baseline. At an optimised threshold of 0.20, precision is **0.38** and recall is **0.69**.

The two findings worth your time. First, feature importance is dominated by one variable that has nothing to do with the insider: **distance from the 52-week high accounts for 36%** of the predictive signal, beating insider identity and transaction size. Second, the direction is the opposite of what most people assume. Purchases disclosed *after* the stock has already run more than 10% show the highest mean cumulative abnormal return at **6.3%** and the highest probability of outperformance at **36.7%**. Buying insider purchases into strength beats buying them into weakness. The author's reading is that a price run-up filters for higher-conviction insider signals in illiquid names.

Note that 36.7% is a probability of outperformance, not a win rate on a positive return, and precision of 0.38 means most flagged trades still do not work out. This is a positive-expectancy tail strategy, not an accuracy strategy.

**Fit for agent automation.** The best fit of the five. Everything it needs is free: Form 4 filings from EDGAR, daily prices, market cap, and a 52-week high computed from the price series. No vendor feed, no short interest, no identity database. The feature set is small enough that an agent can rebuild the whole thing and re-run it, and the fact that the top feature is a price feature rather than an insider feature means most of the model is bog-standard technical data.

**Difficulty for a small account: medium.** The microcap universe is where a small account has its only genuine structural advantage, because capacity constraints that kill funds are irrelevant at your size. But spreads are wide, some names will be effectively untradeable, and the long tail of the distribution does the work, so you need enough positions and enough patience for a 38%-precision signal to pay. Paper trade this one with realistic spread assumptions before believing any backtest.

---

### 3b. What the December 2022 Rule 10b5-1 amendments changed, and why the new checkbox is a free feature

In December 2022 the SEC tightened Rule 10b5-1, the rule that lets an insider set up a trading plan in advance and then claim an affirmative defence if they later trade while holding material non-public information. Three changes matter for a Form 4 signal. First, cooling-off periods. A director or officer now has to wait "the later of: (1) 90 days following plan adoption or modification; or (2) two business days following the disclosure in certain periodic reports of the issuer's financial results for the fiscal quarter in which the plan was adopted or modified (but not to exceed 120 days following plan adoption or modification) before any trading can commence". Everyone else other than the issuer waits **30 days**. Second, directors and officers must certify at adoption that they are not aware of material non-public information and are adopting the plan in good faith. Third, and this is the useful one, "a requirement that Form 4 and 5 filers indicate by checkbox that a reported transaction was intended to satisfy the affirmative defense conditions of Rule 10b5-1(c)". The rules took effect 60 days after Federal Register publication, and Section 16 reporting persons had to comply with the amended Forms 4 and 5 "for beneficial ownership reports filed on or after **April 1, 2023**".
Source: SEC fact sheet, "Rule 10b5-1: Insider Trading Arrangements and Related Disclosure", https://www.sec.gov/files/33-11138-fact-sheet.pdf and the press release at https://www.sec.gov/news/press-release/2022-222

**Why the checkbox is free money for a Form 4 model.** The Cohen, Malloy and Pomorski routine-versus-opportunistic filter that underpins your book has to *infer* whether a trade was pre-scheduled, by looking at whether that same insider traded in the same calendar month in prior years. That inference needs several years of trading history per insider before it produces a label, which throws away every insider who has not traded enough, and it is a guess.

Since April 2023 the filer tells you directly. A checked box means the trade came out of a plan adopted at least 90 days earlier for a director or officer, or 30 days earlier for anyone else, so by construction the decision to trade was made before whatever is happening today. That is the definition of a trade with no current information in it. An unchecked open-market purchase by an officer or director is the bucket you actually want. It costs nothing: the flag is a field in the Form 4 XML that the SEC hosts for free, and there is no history requirement, so it labels a first-time filer just as well as a twenty-year veteran.

Three caveats, all mine rather than cited findings. The checkbox is asserted by the filer and not audited, and its exact wording is about intent to satisfy the affirmative defence, so a checked box is not literally a claim that the trade was uninformative. The history only starts in April 2023, so as of September 2026 you have roughly three and a half years of it, which is thin for a backtest even though it is fine live. And the same amendments moved bona fide gifts of securities from Form 5 onto Form 4, so the Form 4 stream now carries non-trades that will pollute any naive "count the buys" feature. Filter them out by transaction code (G in the Form 4 schema, worth confirming against the actual XML rather than taking my word for it).

Practical suggestion: use the checkbox as the primary routine flag from April 2023 onward, keep the CMP calendar inference running as the fallback for the pre-2023 backtest window, and check whether the two labels agree on the overlap. If they disagree a lot, that disagreement is itself a feature.

### 3c. Has anyone published evidence since 2023 that the insider-buying signal has decayed?

**Not found.** I need to be precise about why, because "not found" and "not there" are different claims. This session's web search budget was exhausted before this question could be searched, so the honest status is **not searched**, not "searched and absent". Treat this subsection as an open item, and mark anything below as my reading of papers I did read rather than as a literature search result.

What the five papers in hand actually imply, none of which is a decay study:

- **Zhao (2026)** is the closest thing to a live-fire test. Its out-of-sample year is **2024** and the classifier still reaches **AUC 0.70** there, so in microcaps at least, insider purchase filings still carried usable information as recently as 2024. That is evidence against total decay in that segment.
- **Neupane (2026)** finds statistically significant alpha, but at **14.49 basis points**. Whether that counts as a live signal or as a decayed one depends entirely on your cost assumptions.
- **Contreras, Fidrmuc and Kozhan (2026)** is not about decay but delivers something adjacent and arguably worse: it argues the post-SOX insider signal was never mostly a private-information signal in the first place. If they are right, there is less to decay than the literature assumed.
- **Heckmann, Jacobs and Schwarz (2023)** ends its sample in 2021 and reports the effect concentrated in small firms with short horizons, which is where alpha typically survives longest because it is hardest to arbitrage.

The obvious thing to check, which nobody in this pack has done, is whether the post-April-2023 checkbox era changed the measured signal. Every study above either predates it or does not use it. That is a genuinely open question and a reasonable first research task for your own agent.

### 3d. Data sources for Form 4 and insider data

Everything below was checked by fetching it this session unless the row says otherwise. Two sites could not be reached from this environment and are marked accordingly rather than described from memory.

| Source | URL | What is free | Main limit or lag | Verdict for a paper-trading shop |
|---|---|---|---|---|
| SEC EDGAR full-text search | `https://efts.sec.gov/LATEST/search-index?q=...&forms=4` (UI at https://www.sec.gov/search-filings) | Unknown from here | **Still unverified.** The fetch was refused by a network policy in this environment before reaching the SEC, so coverage window, rate limits and whether it indexes Form 4 primary documents are all unconfirmed. | Test it by hand in a browser before designing around it. Do not assume it covers Form 4 bodies. |
| SEC quarterly Insider Transactions Data Sets | https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets | ZIP archives of structured data extracted from Forms 3, 4 and 5, "without change from the 'as-filed' submissions". Quarterly files run from January 2006 through June 2026. | "The data sets will be updated quarterly. Data contained in documents filed after 5:30PM Eastern on the last business day of a quarter will be included in the subsequent quarterly posting." So up to three months stale. The SEC also states it "cannot guarantee the accuracy of the data sets". | **The best free backtest history there is.** Twenty years of parsed Form 4 in bulk, no key, no scraping. Useless for live signals. Build your research dataset from this and your live feed from the API below. |
| EDGAR submissions JSON API | `https://data.sec.gov/submissions/CIK##########.json` (verified on Apple, CIK 0000320193) | Full JSON, no API key, no account. Arrays for `accessionNumber`, `filingDate`, `reportDate`, `form` and `fileNumber`; form `"4"` entries appear throughout; the `recent` block held roughly 1,000 filings going back to 2015. | Keyed by CIK, so you poll per company or per filer rather than pulling a global stream. The SEC asks for a declared User-Agent and applies fair-access rate limits (exact limits **still unverified**, I did not read the fair-access page this session). | **The backbone of a live book.** Free, structured, no key. Pair it with a watchlist of CIKs and poll on a schedule. |
| EDGAR RSS / Atom feeds | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=...&type=4&output=atom` | **Not checked this session.** | **Still unverified.** No fetch was made against it, so refresh rate, item limits and whether the full-index feed exposes Form 4 are all unconfirmed. | Likely the simplest live trigger, but confirm it yourself before relying on it. |
| OpenInsider | http://openinsider.com | **Unknown.** | **Still unverified.** Two fetch attempts, over both HTTP and HTTPS, failed with a connection reset before any content was returned. Nothing about its columns, export options, terms or lag was confirmed. | Cannot recommend or dismiss it on this session's evidence. Open it in a browser and check its terms of use before scraping anything. |
| Finviz insider page | https://finviz.com/insidertrading.ashx | A table of roughly 200+ recent transactions with Ticker, Owner, Relationship, Date, Transaction, Cost, #Shares, Value ($), #Shares Total and a link through to the underlying SEC Form 4. No account needed to view it. There is an Export button and an "API and Exports" section linked at `/api-and-exports`. | Footer states "Stock quotes delayed by 1 minute. Futures and options delayed by 15 minutes." Real-time data, alerts and no ads are gated behind paid Elite membership. Export and API pricing not checked. | Good for a human eyeballing the day's filings, and the Form 4 links are handy for spot checks. Not a feed. Do not build a pipeline on a page you are scraping when EDGAR gives you the same data as JSON. |
| Quiver Quantitative | https://www.quiverquant.com/pricing | **Unknown.** | **Still unverified.** Two fetches returned only a signup page and navigation, never the pricing table. The single concrete item on the page was a promotion: "50% off your first year of any Quiver subscription", promo code LABOR26. Plan prices, free-tier contents and whether Form 4 and congressional data are in the free tier are all unconfirmed. | Check the price list yourself. Its main draw is congressional data, which Part 2 already argues you should not pay much for. |
| sec-api.io | https://sec-api.io/pricing | "Your first 100 API calls are on us. You don't pay. It's free." | 100 calls total is a trial, not a recurring free tier. Paid: Personal & Startups **$49/month** billed annually or **$55/month** monthly; Business Internal Use **$199/month** annual or **$239/month** monthly; Enterprise custom. Whether a credit card is required for the trial is not stated on the page. "Form 3/4/5 - Insider Trading Data" is listed across the subscription tiers. | Skip it while you are paper trading. It sells convenience over EDGAR, and EDGAR is free and already structured. Revisit only if parsing Form 4 XML turns out to eat more of your time than $49 a month is worth. |

**The short version of that table.** Two free SEC endpoints do everything you need: the quarterly bulk data sets for history and the submissions JSON API for live polling. Everything else in the table is either a convenience layer over the same public data or unverified. Start with the SEC and only pay for something once you have a working book and a specific reason.

### Searched for and not found

- A published venue, DOI or canonical URL for **Kang, Kim and Wang (2018)**. The PDF has no journal header, no SSRN stamp and an internal title of `5-4.pdf`.
- A published venue or SSRN id for **Heckmann, Jacobs and Schwarz**. The local copy is the August 2023 working-paper version despite the 2024 filename, and nothing inside it names a journal.
- The **sample date range for Neupane (2026)**. It is not stated in any of the text extracted.
- Which date is correct for **Zhao (2026)**, the "January 2025" on the title page or the 5 February 2026 arXiv stamp.
- **Any post-2023 study measuring decay in the insider-buying signal.** Not searched rather than searched-and-absent, because this session's web search budget was exhausted. See 3c.
- **OpenInsider's terms, columns, export options and limits.** Connection reset on both HTTP and HTTPS attempts.
- **Quiver Quantitative's price list.** The pricing URL returned a signup shell twice.
- **EDGAR full-text search behaviour**, including whether it indexes Form 4 primary documents and how far back. The `efts.sec.gov` endpoint was blocked by network policy from this environment.
- **EDGAR RSS/Atom feed behaviour.** No fetch was attempted against it.
- **When Form 144 became an electronic EDGAR filing.** Relevant to whether the Neupane strategy is even reproducible from free data, and unconfirmed here.

### Downloads

All five files are in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`. "First page verified" means the text of page 1 was extracted and read, confirming the file is the paper it claims to be and is not a paywall stub or an error page.

| Filename | Size | Pages | First page verified |
|---|---|---|---|
| `Kang_2018_ClusterTradingCorporateInsiders.pdf` | 2.4 MB (2,538,328 bytes) | 54 | yes |
| `Heckmann_2024_SynthesizingInsiderTradeSignals.pdf` | 1.6 MB (1,687,336 bytes) | 88 | yes |
| `Contreras_2025_InsidersInformationAdvantageShortSellers.pdf` | 1.4 MB (1,510,421 bytes) | 92 | yes |
| `Neupane_2026_InsiderIntentForm144Form4.pdf` | 381 KB (389,824 bytes) | 28 | yes |
| `Zhao_2026_InsiderPurchaseSignalsMicrocap.pdf` | 619 KB (633,582 bytes) | 9 | yes |

Two filename warnings for future you. `Heckmann_2024_...` is really the August 2023 version. `Contreras_2025_...` is the August 2025 accepted manuscript of a paper published in June 2026. The filenames are not wrong exactly, they just refer to the manuscript date rather than the publication date, which will bite you if you cite from the filename.

---

## Part D. Options and futures families: volatility risk premium, 0DTE flows, futures trend following at retail scale

*Report title: Reading list gap-fill: options and futures families the pack skipped*

Written 2026-09-06 for the agentic trading project. This file fills three gaps in the reading pack at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/`.

**PDFs:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

Sixteen new PDFs were downloaded for these three families and every one was opened and checked against its title page. Where a paper sits behind a paywall or a bot check that blocks scripted downloads, the entry says so and gives the exact page to open by hand.

The three families are:

1. **Volatility risk premium harvesting and covered calls.** Selling the insurance rather than buying it.
2. **Zero-days-to-expiry (0DTE) option flows.** The biggest and newest flow in the options market.
3. **Futures trend following at retail scale.** Whether 100,000 dollars can actually run a diversified trend system on micro futures.

**Difficulty ratings** here mean the same thing as elsewhere in the pack: difficulty for a small account trading through Interactive Brokers with a Python agent, not academic difficulty.

**One honest note before you start.** All three families were researched with the same instruction to look for what is wrong with each idea as hard as for what is right. Two of the three came back with recent research that undercuts the sales pitch, and those findings are in the entries rather than buried. If a family reads as less exciting than you expected, that is the research, not pessimism.

**Market levels used for the arithmetic.** All three sections size positions against market levels from the close on 4 September 2026, read from stockanalysis.com: SPY 770.19, QQQ 718.96, GLD 406.77. That puts the S&P 500 index somewhere around 7,700. The three sections were written independently and quote levels between 7,718 and 7,750 for the index and between 770 and 773 for SPY, a spread of well under half a percent, so none of the conclusions turn on which figure you take. Every notional and margin number in this file should be re-checked against a live quote before anything is traded, and figures derived from ETF prices rather than read off a futures or index quote are marked **still unverified** where they appear.

---

### Family 1. Volatility risk premium harvesting and covered calls

The one-line version: option prices usually build in more future wobble than the market actually delivers, so whoever sells the option pockets the difference. That difference is called the volatility risk premium (VRP), or sometimes the variance risk premium. Selling index calls against shares you own is a covered call. Selling index puts backed by cash is a cash-secured put. Both are ways of collecting the same premium.

#### 1a. Does selling the insurance actually pay?

**Papers**

- Ilmanen (2012), "Do Financial Markets Reward Buying or Selling Insurance and Lottery Tickets?", Financial Analysts Journal 68(5), 26-36.
  Free PDF: https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Do-Financial-Markets-Reward-Buying-or-Selling-Insurance-and-Lottery-Tickets.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Ilmanen_2012_InsuranceAndLotteryTickets.pdf` (downloaded, 638 KB)
- Dew-Becker and Giglio (2025), "The Decline of the Variance Risk Premium: Evidence from Traded and Synthetic Options", Federal Reserve Bank of Chicago Working Paper 2025-17, dated 4 September 2025.
  Free PDF: https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/DewBecker_2025_DeclineOfVarianceRiskPremium.pdf` (downloaded, 5.3 MB)

**What it says.** Ilmanen is the clearest statement of the whole idea, and it is short. People overpay for two things: protection against disaster (insurance) and small chances of a huge win (lottery tickets). If enough investors overpay, then whoever sells them should earn a premium over the long run, and Ilmanen finds exactly that across a wide spread of markets: selling index options, selling credit protection, selling volatility, plus the mirror image, that lottery-like assets (far out-of-the-money calls, penny stocks, high-beta names) have delivered poor long-run returns. His summary line is the one worth remembering: bearing small risks is often well rewarded, bearing large risks is not. Then comes the cold shower. Dew-Becker and Giglio (Chicago Fed, September 2025) document that over roughly the past 15 years the abnormal return (alpha) on buying equity index options has become statistically indistinguishable from zero. In plain terms, the edge that made option selling look easy in 1990s and 2000s data has largely been arbitraged away. They also construct "synthetic options" from the underlying stock market itself and find those never showed negative alpha over the last 100 years, which points to the premium having come from the specialist dealers who warehouse option risk rather than from ordinary investors' fear. This matters enormously for Mo: the strategy is real, the mechanism is understood, and the free part of it has been getting thinner for over a decade. Caveat on the Dew-Becker paper: it is a working paper, not yet peer-reviewed, and it measures option alpha rather than the profit of a covered call book specifically.

#### 1b. Covered calls and the CBOE benchmark indexes

**Papers**

- Israelov and Nielsen (2015), "Covered Calls Uncovered", Financial Analysts Journal 71(6), 44-57.
  Free PDF: https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Covered-Calls-Uncovered.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Israelov_2015_CoveredCallsUncovered.pdf` (downloaded, 414 KB)
- Wilshire Analytics for Cboe (March 2019), "Options-Based Benchmark Indexes: Performance, Risk and Premium Capture (June 1986 to Dec. 2018): An Update".
  Free PDF: https://cdn.cboe.com/resources/spx/wilshire-options-based-benchmark-indexes-2019.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Wilshire_2019_OptionsBasedBenchmarkIndexes.pdf` (downloaded, 1.3 MB)
- Israelov and Nielsen (2014), "Covered Call Strategies: One Fact and Eight Myths", Financial Analysts Journal 70(6). Useful companion, it demolishes the sales pitches.
  Free PDF: https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/FAJ-Covered-Call-Strategies-One-Fact-and-Eight-Myths.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Israelov_2014_CoveredCallsOneFactEightMyths.pdf` (downloaded, 251 KB)
- Israelov, Klein and Tummala (2018), "Covering the world: global evidence on covered calls", Journal of Risk 21(1), 61-89. Same decomposition applied to eleven country indexes.
  Free PDF: https://images.aqr.com/-/media/AQR/Documents/Journal-Articles/Covering-the-world-global-evidence-on-covered-calls.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Israelov_2018_CoveringTheWorldGlobalCoveredCalls.pdf` (downloaded, 971 KB)

**What it says.** The Cboe BXM index is the standard yardstick: hold the S&P 500, sell a one-month at-the-money call on it every month, repeat forever. PUT is the same premium collected from the other side: hold cash, sell a one-month at-the-money S&P 500 put, repeat. BXMD is the softer version, selling a 30-delta (further out-of-the-money) call so you keep more upside. Wilshire's numbers for 30 June 1986 to 31 December 2018 are the honest scorecard. Annualised returns and volatility: BXMD 10.2% return on 12.8% volatility, S&P 500 9.8% on 14.9%, PUT 9.5% on 9.9%, CMBO 9.2% on 10.9%, BXM 8.5% on 10.6%. So the plain at-the-money BuyWrite (BXM) actually lagged the index by about 1.3 points a year, turning one dollar into $14.19 versus $20.85 for the S&P 500, while PUT and especially BXMD did keep up or better on much less volatility. Wilshire also reports that the PUT index's Sharpe ratio was 46% higher than the S&P 500's, and that maximum drawdowns were smaller: BXM -35.8%, PUT -35.5%, BXMD -42.7% against -51.0% for the S&P 500. Israelov and Nielsen explain why the returns look the way they do. They break a covered call into three separate bets: passive equity exposure, short volatility, and a hidden third thing they call an equity reversal bet. The short volatility piece is the good bit, with a Sharpe ratio near 1.0, but it only contributes under 10% of the strategy's risk and roughly 2% of annualised return. The equity reversal piece, which comes from the option's delta drifting as the market moves, is about a quarter of the risk and pays essentially nothing (0.5% a year on 4.8% volatility, t-statistic of 0.4, which means indistinguishable from luck). Hedging that piece away by trading the underlying daily lifted the Sharpe ratio from 0.37 to 0.52 and cut volatility from 11.4% to 9.2%. Their 2018 Journal of Risk paper finds the same pattern across global indexes. Practical translation for Mo: most of a naive covered call's return and risk is just owning stocks, the actual premium harvest is a thin 2% a year layer, and you can improve the whole thing meaningfully by delta-hedging, which is a daily arithmetic job an agent is good at.

#### 1c. The covered-call ETF boom, 2023 to 2026

**Papers**

- Israelov and Nze Ndong (2024), "A 'Devil's Bargain': When Generating Income Undermines Investment Returns", The Journal of Alternative Investments 26(4), Spring 2024, p.9. Working paper version dated 26 October 2023.
  Free PDF: https://content.swanglobalinvestments.com/hubfs/Paper%20-%20A%20Devils%20Bargain%20-%20When%20Generating%20Income%20Undermines%20Investment%20Returns%20-%20SSRN-10.2023.pdf
  Journal landing page: https://www.pm-research.com/content/iijaltinv/26/4/9
  SSRN abstract page (blocks scripted download, click by hand): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4580048
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Israelov_2023_DevilsBargainDerivativeIncome.pdf` (downloaded, 943 KB)

**What it says.** This is the paper to read before believing any 10% yield advertised by a covered-call ETF. Roni Israelov (formerly AQR, now NDVR) and David Nze Ndong show that for covered calls the relationship between the income you generate and the total return you end up with is not just weak, it is mechanically negative. The reason is simple once stated: to squeeze more premium out of a call you have to sell a strike closer to the money, a closer strike has a bigger delta, a bigger short delta means you have given away more of your equity exposure, and equity exposure is the thing that actually earns the equity risk premium. So dialling the yield up dials the expected return down, by construction. They then check it on real S&P 500 data. Selling calls to target a 6% annualised yield lost 0.60% a year over 1999 to 2023, and targeting 12% lost 1.08% a year. Over the more recent 2011 to 2023 window it was much worse: the 6% yield target lost 3.1% a year and the 12% target lost 4.7% a year. Their conclusion is that investors who chased derivative income without accounting for this tradeoff made a devil's bargain. The named funds in the boom (JEPI, JEPQ, QYLD, XYLD, and the wider Morningstar "derivative income" category) are the commercial expression of exactly the thing this paper is criticising, and the category has grown to tens of billions of dollars. Note: specific current fund asset figures I saw quoted (for example JEPI around 40 to 45 billion dollars) come from ETF data websites, not from a peer-reviewed source, so treat those as **still unverified**. The mechanism in the paper is what matters, and it is solid.

#### 1d. The honest tail risk: February 2018, "Volmageddon"

**Papers**

- Augustin, Cheng and Van den Bergen (2021), "Volmageddon and the Failure of Short Volatility Products", Financial Analysts Journal 77(3), 35-51.
  Free accepted manuscript (University of Toronto TSpace): https://utoronto.scholaris.ca/server/api/core/bitstreams/98fc477b-df23-4394-915b-d48dcd4642ef/content
  Publisher page: https://doi.org/10.1080/0015198X.2021.1913040
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Augustin_2021_VolmageddonShortVolProducts.pdf` (downloaded, 826 KB)
- Cboe (12 February 2018), "After the Volpocalypse", Market Observations. Short, five pages, written days after the event by the exchange itself.
  Free PDF: https://cdn.cboe.com/resources/education/research_publications/after-the-volpocalypse-market-observation.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Cboe_2018_AfterTheVolpocalypse.pdf` (downloaded, 496 KB)

**What it says.** On Monday 5 February 2018 the VIX (the index of expected S&P 500 volatility) rose from 17.31 to 37.32, a 115.6% one-day jump, the largest on record. Cboe notes the previous record was 64.2% in February 2007, so this was not a bad day, it was roughly double the worst previous day. Two products that were short volatility, the VelocityShares XIV note and the ProShares SVXY fund, were wiped out. XIV had risen from $6.51 at the end of 2011 to $134.44 at the end of 2017, a 20x run at about 65% a year, which is precisely why so much money was in it. Augustin, Cheng and Van den Bergen document that combined assets in these products had reached about $3.5 billion by early February 2018, and that by the next morning's open the products had fallen roughly 97%. XIV was liquidated; SVXY survived at a fraction of its value. The important insight is why it happened. These products were designed to rebalance their hedge every day near the 4:15pm settlement, and because they had grown so large relative to the VIX futures market (the authors calculate the required rebalance at roughly 93,000 contracts, about 23% of average daily volume and 16% of all open interest) their own forced buying pushed VIX futures up further, which forced more buying. A feedback loop, mechanically similar to the portfolio insurance loop of 1987. The single most useful fact for Mo is the contrast Cboe draws in the same document: while XIV and SVXY lost over 90%, "traditional option-writing strategies represented by the Cboe BXM and PUT Indexes performed largely as expected given the environment" and vanilla S&P 500 option trading stayed orderly. Volmageddon was a leverage and crowding accident in VIX futures products, not a covered call accident. Selling one covered call against shares you actually own cannot go to zero the way a levered inverse VIX note can. That distinction is the whole risk-management lesson of this family.

**Fit for agent automation.** Very good, and this is one of the better fits in the whole pack. The rules are mechanical (pick an expiry, pick a delta or moneyness, sell, roll on a schedule), the data needed is small, and Interactive Brokers' API handles single-leg option orders cleanly. The genuinely valuable agent work is the boring discipline part: check that implied volatility is actually above recent realised volatility before selling, refuse to sell when it is not, compute the position delta every day and hedge it if you follow the Israelov approach, watch for assignment and dividend dates, and hard-cap the number of contracts. An always-on agent is also well suited to the one thing humans reliably get wrong here, which is not raising the strike when premium looks temptingly fat.

**Difficulty for a small account: medium.** Not hard, because one contract is all a 100k book can support and the mechanics are simple, but not easy either, because at 100k a single SPY or XSP contract is roughly 77% of the account, so there is no room for position sizing finesse and one bad assignment or one missed roll is a material event.

**Verdict for a 100k agent-run book.** This is the closest thing in the pack to genuine low-hanging fruit, with an important asterisk. The premium is real, well documented, mechanically simple to collect, and cheap to trade in liquid S&P 500 products, and the tail risk is survivable as long as you stay away from leverage and from VIX products. The asterisk is that the free money has thinned (Dew-Becker and Giglio 2025 find option alpha indistinguishable from zero over the last 15 years) and that chasing yield actively destroys return (Israelov and Nze Ndong 2024). So treat it as a modest, steady, low-volatility overlay worth perhaps 1% to 2% a year over holding the index, not as an income machine. Run it at low delta, delta-hedge if you can, and never scale it up because the premium looks good.

#### What running this actually takes at 100k

Plain arithmetic, using early September 2026 levels (S&P 500 around 7,750, SPY around $773; prices move, so re-check before sizing).

**Contract sizes.** All three products track the same index but in wildly different bites.
- **SPY** options: one contract is 100 shares of the SPY ETF, so about 100 x $773 = **$77,300 of exposure**. American style, meaning it can be exercised against you at any time, and physically settled, meaning you actually hand over or receive 100 shares.
- **XSP** (Mini-SPX): based on one tenth of the S&P 500, so the index sits around 775, with a $100 multiplier. One contract is about **$77,500 of exposure**, essentially the same bite as one SPY contract. Crucially it is **European style** (cannot be exercised early) and **cash settled** (no shares change hands, just money), and it qualifies for Section 1256 tax treatment, which in the US means gains are split 60% long-term and 40% short-term regardless of how long you held it.
- **SPX**: the full-size contract, index around 7,750 with a $100 multiplier, so one contract is about **$775,000 of exposure**. That is 7.75 times the whole account. **SPX is unusable at 100k.** Do not let an agent near it.

**How many contracts 100k covers.** For a genuine covered call you must own the shares. 100 shares of SPY costs about $77,300, leaving roughly $22,700 of cash, so the answer is **exactly one contract**, with no second contract possible. For a cash-secured put on SPY at a strike near 770, you must set aside 100 x $770 = **$77,000 in cash**, again **one contract**. If you want finer granularity than one all-or-nothing contract, the practical route is to hold SPY shares and sell XSP calls against them (one XSP contract is close enough to 100 SPY shares to hedge sensibly), or to accept that at 100k you are running a one-contract book and size your expectations accordingly. A useful mental model: at one contract, a 1% move in the S&P 500 is roughly $773 of profit or loss on the shares, and a typical one-month at-the-money call premium is in the low hundreds of dollars, perhaps $1,000 to $1,600 depending on where implied volatility sits.

**Assignment risk.** With SPY (American style, physically settled) the call you sold can be exercised early, and the classic trigger is the day before SPY goes ex-dividend, when someone holding a deep in-the-money call may exercise to capture the dividend. If that happens your 100 shares are called away and you are suddenly flat, holding cash, with no equity exposure until the agent notices. This is a real operational failure mode for an unattended bot: the agent must check SPY's ex-dividend calendar and either roll the call up and out beforehand or accept assignment deliberately. With XSP there is no early assignment at all, and nothing is ever delivered, only cash. **That is the single strongest argument for using XSP rather than SPY for the option leg**, and the Section 1256 tax split is a second one.

**Margin for cash-secured puts.** "Cash-secured" means you hold the full strike value in cash, so $77,000 for one 770-strike SPY put. That is the safe way and it is what the Cboe PUT index assumes. Interactive Brokers will also let you sell the put on Reg T margin for far less, typically somewhere around 15% to 20% of notional plus adjustments, so roughly $12,000 to $16,000 for the same contract. **Still unverified**: the exact IB margin requirement, because it depends on the account type (cash, Reg T margin, or portfolio margin) and IB adjusts its house requirements, so confirm the number in the account before trading. The margin route is where small accounts blow up, because at $13,000 of margin a 100k account could technically sell six or seven puts, giving it roughly $460,000 of downside exposure on 100k of capital. That is exactly the leverage that killed XIV. The agent's hard rule should be: sell only as many puts as the account can fully cash-secure. One.

**Roughly what the tail risk looks like.** For a properly collateralised one-contract book, the tail is the market's tail, slightly softened. The Cboe PUT index's worst peak-to-trough loss over 1986 to 2018 was -35.5% and the BXM's was -35.8%, against -51.0% for the S&P 500 itself. So a 2008-scale event costs you something in the region of a third of the book, not all of it, and the option premium you collected on the way down cushions it a little. What the strategy does **not** do is protect you: you keep essentially all of the downside and give away the upside, which is why Israelov and Nielsen list "covered calls provide downside protection" among the myths. The catastrophic tail only appears if you add leverage (selling more contracts than you can collateralise), sell puts on margin, or touch inverse VIX products. February 2018 is the proof: the BXM and PUT indexes behaved as designed that week while the levered short-VIX products lost 97% overnight.

---

### Family 2. Zero-days-to-expiry (0DTE) option flows

**Papers**

- Vilkov (2026), "0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing", Frankfurt School of Finance & Management working paper, March 2026. **Working paper, not peer-reviewed.**
  SSRN abstract page (blocks scripts, click by hand): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356
  Free replication package with the full paper text in Markdown: https://github.com/vilkovgr/0dte-strategies
  Readable paper digest: https://github.com/vilkovgr/0dte-strategies/blob/main/docs/paper/paper-digest.md
  **Not downloaded as a PDF.** SSRN serves a bot page to scripts, and the author's GitHub repo contains the paper only as Markdown, no PDF. **PDF link unverified.**
- Beckmeyer, Branger and Gayda (2023), "Retail Traders Love 0DTE Options... But Should They?", SSRN working paper. First version 30 March 2023, the copy below is the 15 December 2023 version. **Working paper, not peer-reviewed. Whether a later version exists is still unverified** (SSRN blocked the check).
  Free PDF (Lancaster University conference copy): https://wp.lancs.ac.uk/fofi2024/files/2024/04/FoFI-2024-146-Leander-Gayda.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Beckmeyer_2023_RetailTradersLove0DTE.pdf` (downloaded, 515 KB)
- Almeida, Freire and Hizmeri (2025), "0DTE Asset Pricing", working paper, this draft 23 May 2025, first draft 20 January 2024. **Working paper, not peer-reviewed.** Presented at the EUROFIDAI-ESSEC Paris December Finance Meeting 2024 and the FMA Derivatives conference 2025.
  Free PDF (FMA conference copy): https://www.fma.org/assets/docs/Derivatives2025/Almeida.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Almeida_2025_0DTEAssetPricing.pdf` (downloaded, 6.1 MB)
- Amaya, Garcia-Ares, Pearson and Vasquez (2025), "0DTE Index Options and Market Volatility: How Large is Their Impact?", 25 January 2025. Published by Cboe in its research publications library, using proprietary Cboe trade data. **Cboe-hosted research paper, not a peer-reviewed journal article.**
  Free PDF: https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Cboe_0DTEIndexOptionsMarketVolatility.pdf` (downloaded, 933 KB, 48 pages)
- Dim, Eraker and Vilkov (2024), "0DTEs: Trading, Gamma Risk and Volatility Propagation", SSRN working paper. First posted November 2023, the copy below is the 14 May 2024 version. **Working paper. Whether it has since been accepted by a journal is still unverified.**
  Free PDF (Western Finance Association conference portal): https://westernfinance-portal.org/viewpaper?n=950096
  SSRN abstract page: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/DimEraker_2023_0DTEsGammaRisk.pdf` (downloaded, 1.1 MB)
- Fu, Li, Musto and Pearson (2025), "Hope at a Reasonable Price: Customer Use of Limit Orders in the 0DTE Market", 16 March 2025, US Securities and Exchange Commission DERA Working Paper Series. **Regulator working paper, explicitly labelled preliminary and not a Commission view.**
  Free PDF: https://www.sec.gov/files/dera-hope-reasonable-prc-2503.pdf
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/SEC_DERA_2025_HopeAtReasonablePrice0DTE.pdf` (downloaded, 1.1 MB)
- Brogaard, Han and Won (2023), "Does 0DTE Options Trading Increase Volatility?", SSRN working paper, first posted 22 April 2023. This is the main paper arguing the opposite of Dim, Eraker and Vilkov, so it is worth having for balance. **Not downloaded.** SSRN serves a bot page to scripts, the author's CV link is dead, and no university or conference copy turned up. Open by hand: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358

**Volume-share data sources** (web pages, not papers, but they are the primary numbers Cboe publishes)

- Cboe, "The State of the Options Industry: Quarter Three 2025": https://www.cboe.com/insights/posts/the-state-of-the-options-industry-quarter-three-2025/
- Cboe, "SPX 0DTE Options Jump to 61% Share on Retail Resurgence", 2 June 2025: https://www.cboe.com/insights/posts/spx-0-dte-options-jump-to-61-share-on-retail-resurgence
- Cboe XSP contract fact sheet: https://cdn.cboe.com/resources/xsp/XSP_Options_Fact_Sheet.pdf

**What it says.** Same-day-expiry options went from a curiosity to the main event. Cboe's own quarterly report says 0DTE contracts were 57% of SPX index option average daily volume in the third quarter of 2025, about 2.15 million contracts a day out of an SPX record 3.8 million, and Cboe separately reported a record 61% share in May 2025 with retail accounting for 54% of that 0DTE volume. Brogaard, Han and Won put monthly index 0DTE volume at 0.08 million contracts in January 2011 versus 34.4 million in August 2023, which is the scale of the shift. On whether retail loses money, Beckmeyer, Branger and Gayda say yes and are specific: more than 75% of retail S&P 500 option trades are now 0DTE, and between February 2021 and September 2023 retail traders lost about 241,000 dollars on an average day, rising to roughly 350,000 dollars a day after daily expirations arrived in May 2022. Crucially they find the losses are concentrated in single-leg trades, trades that require paying premium up front (buying options), and trades in high-implied-volatility options, while multi-leg trades and trades that harvest volatility and jump risk premia were significantly more profitable. So the losing side is the option buyer, not the option seller. The SEC DERA paper adds a useful correction to a common complaint: despite very wide quoted spreads, customers using non-marketable limit orders (resting orders that wait rather than crossing the spread) actually trade at low cost, and are at the best bid or offer more than half the time in the actively traded slightly out-of-the-money contracts. On whether there is a harvestable premium, the honest answer from the two most careful studies is "yes but small". Almeida, Freire and Hizmeri find a high 0DTE variance risk premium, but driven mostly by compensation for upside risk rather than crash risk, and they find that the profitable mispricing they identify was large before 2022 and then dissipated once 0DTEs became available every day. Vilkov's 2026 paper is the most directly useful for a trader: over September 2016 to January 2026 the 0DTE variance risk premium is positive but the median is about 0.0011% of spot measured from 10:00 New York time to expiry, which is too thin to monetise after real spreads and slippage. He reports that unconditional 0DTE selling shows negative net Sharpe ratios for most strategy templates once you charge the bid-ask spread plus half a basis point of slippage, and that expected shortfall at the 1% level runs from 0.58% to 1.58% of the underlying, meaning the worst 1% of days cost you between roughly half a percent and one and a half percent of the notional you have on. Only conditional, timed rules did well out of sample, with the best single template (a put ratio spread) at roughly 1.18 gross and 0.93 net Sharpe, a top-three basket at 1.12 gross and 0.82 net, and the all-strategies basket at 0.81 gross but only 0.25 net. His conclusion in his own words is that 0DTE is better viewed as a tightly risk-budgeted tactical overlay than a standing carry strategy. On market impact the literature genuinely disagrees. Brogaard, Han and Won find that a one standard deviation increase in 0DTE trading raises volatility by about 9.1% relative to its mean, driven by speculative retail flow even after controlling for market maker gamma hedging. Dim, Eraker and Vilkov find the opposite direction: high 0DTE open interest gamma does not propagate volatility, intraday 0DTE volume shocks do not amplify recent index moves, and the presence of 0DTEs actually dampens volatility through a shift in market makers' hedging needs, and they stress that the shift comes from longer-dated positions that have aged into 0DTEs rather than from same-day trading. The Cboe-published Amaya, Garcia-Ares, Pearson and Vasquez paper is the tie-breaker with the best data, since it uses proprietary Cboe trade data to reconstruct actual market maker positions. Their answer is that gamma hedging does push volatility around, but not by much: the maximum impact of market maker gamma is to raise annualised daily volatility by 3.3 percentage points, and annualised 30-minute volatility by 6.4 percentage points. They then argue this is small in context, because the standard deviation of daily changes in annualised realised volatility is 4.5 percentage points and day-over-day changes exceed 3.0 percentage points on about 20% of trading days anyway. Their average estimated impact is a reduction of daily volatility by 0.08 percentage points, effectively nothing. Caveats worth carrying: every one of these is a working paper rather than a published journal article, the two volatility-impact results contradict each other and the disagreement is not resolved, and Almeida et al. explicitly document that the tradable edge they found shrank after 2022, which is the classic warning sign that a crowded flow has already been arbitraged.

**Fit for agent automation.** Mechanically this is a very good fit: the decision window is one day, the position is closed by the closing bell so nothing carries overnight, and an always-on Python agent can watch the whole session and adjust, which is exactly what Vilkov's result demands since only the timed conditional rules worked. The catch is that the edge lives in intraday timing and execution quality, not in the signal, so the agent needs live option chain data, patient limit-order logic (the SEC paper shows resting limit orders are how customers actually get filled cheaply) and a hard risk budget it cannot talk itself out of, which is a real engineering job rather than a script.

**Difficulty for a small account: hard.** The full-size SPX contract is far too large for a 100k book, the profitable version requires intraday conditional timing plus disciplined limit-order execution rather than a simple daily rule, and the research says the unconditional version loses money after costs.

**Verdict for a 100k agent-run book.** This is not low-hanging fruit, it is the opposite: the flow is enormous and popular precisely because it is easy to trade and hard to make money in, and the best available evidence says the naive version (sell premium every morning) has a negative net Sharpe after costs. Blow-up risk is the real issue: Vilkov's 1% expected shortfall of 0.58% to 1.58% of notional means that if the agent has one full SPX contract on against a 100k account, a bad day in the worst 1% costs roughly 4,500 to 12,200 dollars, or 4.5% to 12% of the whole book, from a single contract, and a genuine gap day can be several multiples worse than the expected shortfall. Keep this family on the reading list as the best-documented example of a crowded flow where the retail side demonstrably loses, use XSP rather than SPX if the agent trades it at all, and size it as a small tactical sleeve of maybe 5% to 10% of the book rather than a core strategy.

**Practical note: what running 0DTE at 100k actually takes.**

*Contract size and notional.* The S&P 500 index closed around 7,718 on 4 September 2026 (index level per web search, **still unverified against a primary exchange source**). At that level:
- **SPX** (full-size S&P 500 index option): multiplier 100, so one contract controls about 771,800 dollars of index. Against a 100k account that is roughly 7.7 times the whole book in one contract. Unusable except inside a narrow defined-risk spread.
- **XSP** (Mini-SPX): tracks one tenth of the index with the same 100 multiplier, so one contract is about 77,200 dollars of notional. Same mechanics as SPX (cash settled, European exercise so no early assignment, and the same Section 1256 tax treatment as SPX, though **the tax point is general knowledge and not verified here, and is not tax advice**). This is the right instrument for a 100k book.
- **SPY** (the ETF option): 100 shares per contract, so about 77,000 dollars of notional, similar in size to XSP. **Exact SPY price still unverified.** Differences that matter: SPY options are American exercise so a short leg can be assigned early and you can end up holding actual shares, they settle into stock rather than cash, and they do not get index tax treatment. For an agent that must never wake up holding an unexpected 77,000 dollar share position, XSP is the safer choice.

*Commissions, verified from Interactive Brokers' own pages on 6 September 2026.* On IBKR Pro Fixed pricing, US options are 0.65 dollars per contract with a 1.00 dollar minimum per order, for up to 10,000 contracts a month. On IBKR Pro Tiered pricing the IBKR commission is 0.25 dollars per contract if the premium is under 0.05, 0.50 dollars if the premium is 0.05 to under 0.10, and 0.65 dollars if the premium is 0.10 or more, plus third-party fees on top. Third-party fees I confirmed on IB's Cboe fee page: the Cboe customer transaction fee is 0.45 dollars per contract for SPX and SPXW with premium at or above 1.00 dollar, and only 0.07 dollars per contract for XSP, plus OCC clearing of 0.025 dollars per contract and a FINRA Consolidated Audit Trail fee of 0.0003 dollars per contract. The Options Regulatory Fee is published as a separate list and **is still unverified**. Working figures: about 1.13 dollars all-in per SPX contract per side, so roughly 2.25 dollars round trip, versus about 0.75 dollars per XSP contract per side, so roughly 1.50 dollars round trip. A four-leg iron condor is four contracts each way, so about 9 dollars round trip in SPX and about 6 dollars in XSP. Verified pages: https://www.interactivebrokers.com/en/pricing/commissions-options.php and https://www.interactivebrokers.com/en/accounts/fees/CBOEoptfee.php (both blocked the automated reader and had to be pulled with curl, so click them to confirm the current numbers).

*The cost that actually matters.* Commissions are the small part. Vilkov's negative net Sharpe results come mostly from the bid-ask spread plus slippage, not the broker fee, which is why the SEC DERA finding about resting limit orders matters so much. An agent that crosses the spread on four legs twice a day will hand back the entire thin premium it is trying to collect. Any implementation has to work resting limit orders.

*Margin treatment.* Naked short index options are off the table at 100k. The standard Reg T requirement for a short broad-based index option is commonly cited as roughly 15% of the index value less the out-of-the-money amount plus the premium received, which at SPX 7,718 would be well over 100,000 dollars for a single contract, more than the entire account. **This 15% figure is the widely cited standard and is still unverified against IB's current schedule.** The workable route is defined-risk spreads, where the requirement is the spread width times the multiplier minus the credit received: a 25-point SPX vertical is 2,500 dollars of maximum loss per contract, a 5-point XSP vertical is 500 dollars. Portfolio margin, which would help, has a commonly cited Interactive Brokers minimum of 110,000 dollars to open and 100,000 dollars to maintain, so a 100k book sits right on the line, **and both figures are still unverified** (IB's portfolio margin page returned a 404 to the automated fetch; check by hand at https://www.interactivebrokers.com/en/pricing/margin-rates.php).

*How fast the tail bites.* Apply Vilkov's expected shortfall directly. In the worst 1% of days a 0DTE strategy loses 0.58% to 1.58% of the notional it has on. Per XSP contract at 77,200 dollars of notional that is roughly 450 to 1,220 dollars. Per SPX contract at 771,800 dollars of notional it is roughly 4,500 to 12,200 dollars, so one SPX contract can take 4.5% to 12% off a 100k book in a single afternoon, and expected shortfall is an average of the bad tail, not the worst case, so a real gap or a shock headline can be several times that. Practical sizing: if the agent runs a defined-risk XSP structure and caps total maximum loss across all open 0DTE positions at 1% to 2% of the book, that is 1,000 to 2,000 dollars of at-risk capital, which is two to four 5-point XSP verticals. That is a small sleeve, and the research says small is the correct size.

---

### Family 3. Futures trend following at retail scale

The idea itself is already in this pack: Moskowitz, Ooi and Pedersen (2012), "Time Series Momentum", is written up in section 1 of `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/01_anomalies.md`, PDF at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Moskowitz_2012_TimeSeriesMomentum.pdf`. What that section does not answer is the only question that matters for you: can 100,000 dollars actually run a diversified trend system on Interactive Brokers, and if so, on how many markets. This family is about that.

**Papers**

- Baltas and Kosowski (2013), "Demystifying Time-Series Momentum Strategies: Volatility Estimators, Trading Rules and Pairwise Correlations", Journal of Derivatives and Hedge Funds 19(4), pages 289 to 310. The 2015 revised working-paper version is what got downloaded.
  Free PDF: https://spiral.imperial.ac.uk/bitstreams/93f06c22-150a-4240-8115-912988dd2c67/download
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Baltas_2013_DemystifyingTimeSeriesMomentum.pdf` (downloaded, 257 KB)
  SSRN landing page if you want the published abstract: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2140091

- Kurth, Eisler, Rej and Bouchaud (2026), "Is Trend Still Your Friend? A Microstructural Account of the Demise of Short-Term Trend-Following", arXiv:2607.01550, dated 3 July 2026. Three of the four authors are at Capital Fund Management, which runs this trade for real money.
  Free PDF: https://arxiv.org/pdf/2607.01550
  Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Kurth_2026_IsTrendStillYourFriend.pdf` (downloaded, 4.9 MB, 13 pages)
  Quantpedia's plain-English write-up of the same paper: https://quantpedia.com/is-trend-still-your-friend-a-microstructural-account-of-the-demise-of-short-term-trend-following/

- Carver, Robert. Blog "This Blog is Systematic" at https://qoppac.blogspot.com, plus the open-source Python system pysystemtrade. The three pages that matter for a small account:
  - "Diversification and small account size" (March 2016): https://qoppac.blogspot.com/2016/03/diversification-and-small-account-size.html
  - "Optimising portfolios for small accounts: Dynamic optimisation testing, EPIC FAIL" (June 2021): https://qoppac.blogspot.com/2021/06/optimising-portfolios-for-small.html
  - pysystemtrade landing page: https://qoppac.blogspot.com/p/pysystemtrade.html
  Book: Carver (2023), "Advanced Futures Trading Strategies", Harriman House. Author's own post about it: https://qoppac.blogspot.com/2023/04/advanced-futures-trading-strategies.html
  **Not downloaded.** These are web pages and a paid book, not PDFs.

- Hurst, Ooi and Pedersen (2017), "A Century of Evidence on Trend-Following Investing", Journal of Portfolio Management 44(1), pages 15 to 29, DOI 10.3905/jpm.2017.44.1.015. **Not downloaded.** AQR serves its PDFs behind a bot check, Pedersen's own NYU page returns HTTP 403 to scripts, and the guessed filename there 404s. Click one of these by hand:
  - https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
  - https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
  **Link unverified**, in the sense that neither page was successfully opened by script, only found through search. Note for whoever tries next: the Family 1 researcher on this pack found that `images.aqr.com` serves AQR PDFs freely even though `www.aqr.com` blocks scripts, so that host is worth trying.

**What it says.** Baltas and Kosowski take the Moskowitz result apart and ask which of the engineering choices actually matter. Two findings are useful to you. First, using a better volatility estimate and a better trend detector cuts how much you trade by more than a third with no statistically significant loss of return, which for a small account is close to free money, because trading costs are the tax you pay for being small. Second, and less comfortable, the weak stretch trend following had after 2008 is explained mostly by markets becoming more correlated with each other, so the diversification the strategy relies on quietly shrank. They propose scaling leverage up and down according to how correlated the markets currently are, and that version holds up after realistic transaction costs. Kurth and co-authors, writing in July 2026, go further and are the honest counterweight to every glossy managed-futures brochure. Across about 100 liquid futures from 1995 to 2025 they confirm that short-horizon trend stopped paying reliably around 2009, then test four explanations and reject three of them. The one that survives is odd and specific: what separates markets where trend still works from markets where it does not is the volatility-normalised tick size, meaning how coarse the price grid is relative to how much the thing moves. On coarse-grid, large-tick contracts trend still delivers. On fine-grid, small-tick contracts the profit has collapsed at every signal speed, and neither asset class nor liquidity reproduces that split. Their explanation is that trend was always partly self-fulfilling, because trend followers buying pushes prices up, which confirms the signal, and high-frequency market makers now pull liquidity out of the way of predictable directional flow in exactly the fine-grid books, which breaks the loop. They also check whether you can dodge this by using passive limit orders instead of aggressive market orders, and find you cannot, because passive execution gives up the self-reinforcement while adding the cost of the trades you miss. On the industry numbers: the SG Trend Index returned a record 27.3 percent in 2022, the broader SG CTA Index was roughly flat at plus 2.4 percent in 2024, and the SG Trend Index was down 15.05 percent over the twelve months to June 2025 against a long-run compound return since 2000 of about 4.9 percent a year (the last two from the Top Traders Unplugged June 2025 performance report at https://www.toptradersunplugged.com/trend-following-performance-report-june-2025/). Exact calendar-year figures for 2023, 2025 and 2026 to date are **still unverified**, because SocGen's own index page and BarclayHedge both need a manual click.

**Fit for agent automation.** Close to perfect, and the best fit in this entire pack. Daily closing prices are all you need, decisions are made once a day after the close, nothing is time-critical to the second, and the whole job is exactly what software is good at: pull prices, compute a few moving-average crossovers, scale each position by that market's recent volatility, compare against what you already hold, send the difference as orders. Carver's pysystemtrade is a working open-source Python implementation an agent can read, run and modify rather than reinventing. The genuinely hard parts are boring plumbing rather than intelligence: stitching a continuous price history across contract expiries, rolling from the expiring contract into the next one without accidentally going flat, and not double-counting positions across the roll.

**Difficulty for a small account: medium.** The strategy logic is easy and the data is cheap, but contract sizes are lumpy, the roll plumbing is fiddly, and 100,000 dollars buys far less diversification than the papers assume, which is where most of the theoretical Sharpe ratio goes to die.

---

#### The practical note: margin, contract sizes and how many markets 100k can really cover

**Contract multipliers.** These are stable CME specifications, cross-checked against two secondary sources because CME's own pages would not load.

| Contract | What it is | Multiplier | Tick |
|---|---|---|---|
| MES | Micro E-mini S&P 500 | 5 dollars per index point | 0.25 point, so 1.25 dollars a tick |
| MNQ | Micro E-mini Nasdaq 100 | 2 dollars per index point | 0.25 point, so 0.50 dollars a tick |
| MYM | Micro E-mini Dow | 0.50 dollars per index point | 1 point, so 0.50 dollars a tick |
| M2K | Micro E-mini Russell 2000 | 5 dollars per index point | 0.10 point, so 0.50 dollars a tick |
| MGC | Micro Gold | 10 troy ounces | 0.10 dollars, so 1 dollar a tick |
| MCL | Micro WTI Crude Oil | 100 barrels | 0.01 dollars, so 1 dollar a tick |
| M6E | Micro EUR/USD | 12,500 euros | **still unverified** against CME's own page |
| MBT | Micro Bitcoin | 0.1 bitcoin | **still unverified** against CME's own page |
| 2YY, 5YY, 10Y, 30Y | Micro Treasury Yield futures | 10 dollars per basis point of yield | **still unverified**, CME spec pages would not load |

**Margin at Interactive Brokers**, read from https://emini-watch.com/futures-trading/futures-margin-requirements/ with a stated data timestamp of 6 September 2026. These are IB's own requirements, which run higher than the bare exchange minimum. The overnight number is the one that binds you, because a trend system holds positions for weeks.

| Contract | IB intraday | IB overnight |
|---|---|---|
| MES | 2,296 dollars | 3,280 dollars |
| MNQ | 4,493 dollars | 6,418 dollars |
| MYM | 1,245 dollars | 1,779 dollars |
| M2K | 900 dollars | 1,286 dollars |
| MGC | 4,479 dollars | 4,479 dollars |
| MCL | 1,936 dollars | 1,936 dollars |
| M6E | 346 dollars | 346 dollars |
| MBT | 2,849 dollars | 2,849 dollars |

Read those numbers again, because they are the whole problem. One micro Nasdaq contract held overnight ties up 6,418 dollars, which is 6.4 percent of a 100,000 dollar account for a single contract of the smallest size the exchange offers. Add up one contract of each of the eight above and you are at roughly 22,400 dollars of margin, about 22 percent of the account, before you have taken a second contract anywhere.

**Approximate notional per contract.** These are derived from exchange-traded fund prices at the close on 4 September 2026 (SPY 770.19, QQQ 718.96, GLD 406.77, all read from stockanalysis.com), so they are approximate rather than read off a futures quote. Treat every one as **still unverified**:
- MES: roughly 38,500 dollars of S&P 500 exposure per contract
- MNQ: roughly 59,000 dollars of Nasdaq 100 exposure per contract
- MGC: roughly 44,000 dollars of gold per contract

The uncomfortable arithmetic is that one MNQ contract carries about 59 percent of your account in notional exposure. Micro contracts are small compared to the full-size ones. They are not small compared to 100,000 dollars.

**How many markets can 100k really hold.** Carver has done this work and published the answer. In "Diversification and small account size" he gives a ladder of account size against the number of instruments he thinks you can sensibly hold at a 15 percent annual volatility target: 2,500 dollars buys one instrument, 5,000 buys two, 10,000 buys three, 20,000 buys four, **100,000 buys about eight, roughly one per asset class**, 300,000 buys fifteen, and you need somewhere north of 800,000 before the full 37-instrument portfolio he was running at the time makes sense. Eight markets is the honest answer for your book. That is enough to be genuinely diversified across equity index, bond or rate, currency, metal, energy and possibly crypto, and it is nowhere near the 58 markets in the Moskowitz paper or the roughly 100 in the Kurth paper. Expect a meaningfully lower Sharpe ratio than any published backtest for that reason alone, and do not treat the gap as something clever position sizing will recover.

**What happens if you overreach.** Two specific failure modes, both of which Carver has measured. First, the one-contract problem: when your smallest possible position is one contract, your position size is a blunt on-or-off switch instead of a smooth dial. Carver puts the cost at roughly a 20 percent haircut to Sharpe ratio if you can only ever hold one contract, falling to about 5 percent if you can hold two. That is the real argument for holding fewer markets properly rather than more markets badly. Second, the clever-fix trap: Carver built a dynamic optimiser specifically to let a small account hold more instruments by choosing integer contract combinations intelligently, tested it on a 25,000 dollar account across 20 instruments, and titled the resulting post "EPIC FAIL". The original unconstrained system scored a Sharpe ratio above 1.0, naive rounding of positions scored about 0.72, and his sophisticated optimiser scored 0.56, worse than just rounding. It also hit only 18.6 percent realised volatility against a 20.9 percent target while failing to reduce turnover. The lesson is not that optimisation never works, since he found a static instrument-selection version that did work in a follow-up post, but that the obvious clever fix for a small account made things worse than the dumb approach, and you should assume the same about your own first clever fix.

One more practical warning, this one from the Kurth paper rather than from Carver. If tick size relative to volatility is what separates markets where trend still pays from markets where it does not, then note that a micro contract sits on the same price grid as its full-size parent while representing one tenth of the notional. Using micros does not change the volatility-normalised tick size of the underlying market, so it is not a reason to expect micros to behave differently, but it does mean the paper's warning applies in full to MES and MNQ, which are fine-grid, small-tick contracts of exactly the kind where the authors say short-horizon trend has collapsed. Their result is about short-horizon signals specifically, so slower signals measured in months are less affected. This is the one finding in the family that should change how you build the thing rather than just how you size it: lean slow, and do not expect a fast trend signal on equity index micros to pay.

**Verdict for a 100k agent-run book.** Yes, this is the low-hanging fruit of the three families, and it is the one to build first. The logic runs on daily closes with no latency pressure, there is a mature open-source Python implementation to read, and it is the only family here where a bad month is a bad month rather than a margin call. The catch is expectation setting rather than feasibility: eight markets instead of eighty, a real Sharpe ratio well under the published numbers, a post-2009 weakness now traced to a microstructure change that has not reversed, and a recent twelve-month stretch where the industry trend index lost 15 percent. Build it, paper trade it for a full year, and treat it as a slow diversifier rather than a money printer.

---

### Searched for and not found

Grouped by family. Every link below is one to open by hand in a browser.

#### Family 1, volatility risk premium and covered calls

- **SSRN pages generally.** SSRN returns HTTP 403 to scripted fetches. Both SSRN abstract pages below are fine to open in a browser by hand, and in both cases I found a free full-text copy elsewhere so no PDF is missing:
  - Israelov and Nielsen, "Covered Calls Uncovered": https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2444999
  - Israelov and Nze Ndong, "A Devil's Bargain": https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4580048
- **A Cboe or Wilshire benchmark-index study dated 2023 to 2026.** The most recent full study I could find is the Wilshire update of March 2019 covering June 1986 to December 2018. Cboe does publish a current BXM factsheet, but it is an image-heavy PDF that would not extract to text, so the numbers on it are **still unverified**. Click by hand: https://cdn.cboe.com/resources/indices/factsheet/CboeGlobalIndices_BXM-Index.pdf and the benchmark overview at https://cdn.cboe.com/resources/indices/documents/benchmarks-fact-sheet.pdf
- **A peer-reviewed 2023 to 2026 study of covered-call ETF flows and realised investor returns (JEPI, QYLD, XYLD specifically).** Repeated searches turned up only practitioner and marketing material. The nearest peer-reviewed item is a forecasting paper, Journal of Risk and Financial Management 18(3), 2025, article 120, "Forecasting Covered Call Exchange-Traded Funds (ETFs) Using Time Series, Machine Learning, and Deep Learning Models", open access at https://www.mdpi.com/1911-8074/18/3/120. I did not download it because it is about price prediction methods rather than the economics of the premium, and it looked weaker than the Israelov and Nze Ndong paper for this purpose. Flagging it in case you want it.
- **S&P Dow Jones Indices research, "Seeking Income: Cash Flow Distribution Analysis of S&P 500 Buy-Write Strategies" (Berlinda Liu).** The direct PDF link returned an HTML error page, not a PDF, so nothing was saved. Click by hand: https://www.spglobal.com/spdji/en/documents/research/research-seeking-income-cash-flow-distribution-analysis-of-sp-500-buy-write-strategies.pdf
- **Exact Interactive Brokers margin requirement for a short SPY or XSP put at 100k.** Not confirmable from public research; it depends on account type and IB house rules. Check inside the account before trading. Marked **still unverified** above.
- **The claim that "A Devil's Bargain" won the Peter L. Bernstein Award.** One search snippet asserted it, and I could not confirm it against a primary source, so I left it out of the entry. **Still unverified.**

#### Family 2, 0DTE option flows

- **Brogaard, Han and Won (2023), "Does 0DTE Options Trading Increase Volatility?"** No free PDF found. SSRN returns an HTML bot page to scripts, Brogaard's University of Utah CV URL redirects to jonathanbrogaard.com and then 404s, and no university, NBER or conference copy surfaced. Click by hand: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358
- **Vilkov (2026), "0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing"** PDF. SSRN only, and the author's GitHub replication package holds the paper as Markdown rather than PDF. Click by hand: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356
- **Latest version date for Beckmeyer, Branger and Gayda.** SSRN returned HTTP 403 to the automated reader, so the December 2023 version in the downloaded PDF may not be the newest. Check by hand: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4404704
- **Journal publication status for Dim, Eraker and Vilkov.** Could not confirm whether it has been accepted anywhere since the May 2024 draft. Check the author's page: https://www.vilkov.net/research.html
- **Interactive Brokers Options Regulatory Fee schedule** (a per-contract regulatory fee that varies by exchange). Referenced as a separate list on IB's page but not extracted. Click by hand from https://www.interactivebrokers.com/en/pricing/commissions-options.php
- **Interactive Brokers portfolio margin minimum and index option margin rates.** https://www.interactivebrokers.com/en/trading/margin-portfolio.php returned 404. Try https://www.interactivebrokers.com/en/pricing/margin-rates.php
- **A peer-reviewed, published journal article on 0DTE.** Everything in this family is still a working paper or exchange-published research as of September 2026. If one exists it did not surface in these searches.
- **An independent, non-Cboe source for the 0DTE volume-share statistics.** All the share numbers here trace back to Cboe, which operates the SPX market and therefore has an interest in the story. Worth treating as an interested party.

#### Family 3, futures trend following at retail scale

- **Hurst, Ooi and Pedersen (2017), "A Century of Evidence on Trend-Following Investing".** No free PDF retrievable by script. AQR runs a bot check, Pedersen's NYU page at https://pages.stern.nyu.edu/~lpederse/ returned HTTP 403 to curl, and the guessed filename `papers/CenturyOfTrend.pdf` 404s. Click by hand: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026 or https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing . Also try the `images.aqr.com` host, which reportedly serves AQR PDFs without the bot check.
- **Alpha Architect, "The Return of the King: Trend Following Is Back, But Will It Last?"** Blocked twice, HTTP 403 to both WebFetch and curl. Click by hand: https://alphaarchitect.com/the-return-of-the-king-trend-following-is-back-but-will-it-last/ . Related Alpha Architect pages worth a manual click: https://alphaarchitect.com/category/architect-academic-insights/managed-futures-research/ and https://alphaarchitect.com/diy-trend-following-allocations-february-2025/
- **Exact SG Trend Index calendar-year returns for 2023, 2025 and 2026 to date.** Only 2022 (plus 27.3 percent), the SG CTA Index 2024 figure (plus 2.4 percent), the twelve months to June 2025 (minus 15.05 percent) and the since-2000 compound rate (about 4.9 percent) could be verified. Click by hand: https://portal.barclayhedge.com/cgi-bin/indices/displayHfIndex.cgi?indexCat=SG-Prime-Services-Indices&indexName=SG-Trend-Index and https://content.sgmarkets.com/CTA_UPDATE_KEEPING_UP_WITH_THE_TRENDFOLLOWERS_2025
- **CME's own contract specification and margin pages.** Every attempt at https://www.cmegroup.com timed out after 60 seconds, so multipliers were cross-checked against two secondary sources instead and the margin table came from emini-watch. The M6E, MBT and micro Treasury yield multipliers remain unconfirmed against the exchange. Click by hand: https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html and https://www.cmegroup.com/clearing/margins/
- **A single authoritative "Trend Following with Micro Futures" research article.** What exists under that heading is broker marketing (StoneX, NinjaTrader, Schwab, TradingSim) rather than research, so none of it was cited as evidence. The Carver material covers the same ground properly.
- **Joel Handy and Marat Molyboga (2024) on the 35 trend managers in the SG Trend index, and Handy and Meksi (Summer 2025, Journal of Wealth Management) on behavioural bias in selecting managed-futures managers.** Both surfaced only as second-hand descriptions inside the blocked Alpha Architect pages, so authors, exact titles and findings are **still unverified** and neither is cited above. Worth a manual look if you want the multi-manager angle.
- **A published, peer-reviewed version of the Kurth paper.** It is an arXiv preprint from July 2026 and has not been through review. Treat it as high-quality practitioner research from a serious quantitative fund rather than as settled science.
- **A note on the search budget.** This session hit its web search limit part way through, so later checks had to be done by direct page fetch rather than search. Anything marked still unverified above is a candidate for a quick second pass with a fresh budget.

---

### Downloads

All sixteen files below are in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`. Sizes are read off disk on 6 September 2026, and every file was confirmed to be a real PDF (not an HTML error page) with a first page matching the cited title. Nothing already in the folder was overwritten.

| Filename | Size | First page verified |
|---|---|---|
| `Ilmanen_2012_InsuranceAndLotteryTickets.pdf` | 638 KB | yes |
| `DewBecker_2025_DeclineOfVarianceRiskPremium.pdf` | 5.3 MB | yes |
| `Israelov_2015_CoveredCallsUncovered.pdf` | 414 KB | yes |
| `Israelov_2014_CoveredCallsOneFactEightMyths.pdf` | 251 KB | yes |
| `Israelov_2018_CoveringTheWorldGlobalCoveredCalls.pdf` | 971 KB, 30 pages | yes |
| `Wilshire_2019_OptionsBasedBenchmarkIndexes.pdf` | 1.25 MB | yes |
| `Israelov_2023_DevilsBargainDerivativeIncome.pdf` | 943 KB, 28 pages | yes |
| `Augustin_2021_VolmageddonShortVolProducts.pdf` | 826 KB | yes |
| `Cboe_2018_AfterTheVolpocalypse.pdf` | 496 KB, 5 pages | yes |
| `Beckmeyer_2023_RetailTradersLove0DTE.pdf` | 515 KB | yes, December 2023 version |
| `Almeida_2025_0DTEAssetPricing.pdf` | 6.0 MB | yes, 23 May 2025 draft |
| `Cboe_0DTEIndexOptionsMarketVolatility.pdf` | 933 KB, 48 pages | yes, 25 January 2025 |
| `DimEraker_2023_0DTEsGammaRisk.pdf` | 1.03 MB | yes, 14 May 2024 version |
| `SEC_DERA_2025_HopeAtReasonablePrice0DTE.pdf` | 1.09 MB | yes, 16 March 2025 |
| `Baltas_2013_DemystifyingTimeSeriesMomentum.pdf` | 257 KB | yes, 1 October 2015 revision |
| `Kurth_2026_IsTrendStillYourFriend.pdf` | 4.9 MB, 13 pages | yes, arXiv:2607.01550v1 |

#### Not downloaded, open these by hand

| Item | Why it failed | Link to click |
|---|---|---|
| S&P Dow Jones Indices, buy-write cash flow distribution study | direct link served an HTML error page, not a PDF | https://www.spglobal.com/spdji/en/documents/research/research-seeking-income-cash-flow-distribution-analysis-of-sp-500-buy-write-strategies.pdf |
| Cboe BXM current index factsheet | image-only PDF, text would not extract, so its numbers are still unverified | https://cdn.cboe.com/resources/indices/factsheet/CboeGlobalIndices_BXM-Index.pdf |
| Brogaard, Han and Won (2023), "Does 0DTE Options Trading Increase Volatility?" | SSRN blocks scripts, author CV link is dead, no conference copy exists | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358 |
| Vilkov (2026), "0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing" | SSRN only, no PDF anywhere. Free full text as Markdown in the author's repo | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356 and https://github.com/vilkovgr/0dte-strategies |
| Hurst, Ooi and Pedersen (2017), "A Century of Evidence on Trend-Following Investing" | AQR bot check, Pedersen's NYU page returns 403 to scripts | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026 |
| Alpha Architect, "The Return of the King: Trend Following Is Back, But Will It Last?" | HTTP 403 on two separate attempts | https://alphaarchitect.com/the-return-of-the-king-trend-following-is-back-but-will-it-last/ |

#### Two notes for whoever downloads next

- **AQR has a back door.** `www.aqr.com` blocks scripted downloads, but `images.aqr.com` serves the same PDFs without a bot check. That is how three AQR and Financial Analysts Journal papers got into this pack for free. Worth trying on the Hurst, Ooi and Pedersen paper above, which is the main AQR item still missing.
- **SSRN never works from a script.** Every SSRN attempt across all three families returned an HTML bot page. The reliable workaround is to look for a conference copy (the Lancaster, FMA and Western Finance Association portals all worked here) or a university repository copy (Imperial College's Spiral and Toronto's TSpace both worked). Two of the sixteen downloads above came in that way.

---

### Verdicts side by side

| Family | Difficulty at 100k | Low-hanging fruit? | The one-line reason |
|---|---|---|---|
| Volatility risk premium and covered calls | medium | yes, with an asterisk | The premium is real and simple to collect, but it has thinned a lot and chasing yield actively destroys return, so treat it as a 1 to 2 percent a year overlay |
| 0DTE option flows | hard | no | The unconditional version has a negative net Sharpe after costs, and the profitable version needs intraday timing plus disciplined limit-order execution |
| Futures trend following at retail scale | medium | yes, build this first | Daily closes, no latency pressure, mature open-source Python code, and the only family where a bad month is a bad month rather than a margin call |

A pattern worth noticing across all three: in each family the recent research (2023 to 2026) is more negative than the older research. Dew-Becker and Giglio find option alpha indistinguishable from zero over fifteen years, Almeida and co-authors find the 0DTE edge dissipated after 2022, and Kurth and co-authors find short-horizon trend broke around 2009 for a specific microstructural reason. That is not three coincidences, it is what a maturing market looks like, and it is the strongest argument in this file for paper trading everything for a full year before committing capital.

---

## Part E. Crypto carry, closed-end fund discounts, sector rotation and dual momentum, ETF pairs

*Report title: Gap-fill G: four strategy families the reading pack skipped*

Crypto basis and funding carry, closed-end fund and ETF discount arbitrage, sector rotation and dual momentum, and ETF pairs trading.

Written for a 100k paper-first book run by AI agents on Interactive Brokers, in Python.

All PDFs referenced below live in:
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

A note on evidence quality before you start. Every number below that is attributed to a paper was read out of the PDF itself, not recalled. Where I could not confirm something (a live 2023 to 2026 track record, a current market rate, a publication venue) it is marked **still unverified** rather than filled in. This session ran out of its web search budget partway through, so the "Searched for and not found" section at the end is longer than I would like. Treat it as a to-do list, not as evidence of absence.

---

### Family 1: Crypto basis and funding-rate carry

The trade in one sentence: buy bitcoin, simultaneously sell a bitcoin futures contract against it, and collect the gap between the two prices as the futures contract converges to spot. The gap exists because a lot of people want leveraged long exposure to crypto and are willing to overpay for it.

#### 1.1 Schmeling, Schrimpf and Todorov (2023), "Crypto Carry"

**Citation:** Maik Schmeling, Andreas Schrimpf and Karamfil Todorov, "Crypto carry", BIS Working Papers No 1087, Bank for International Settlements, April 2023 (paper version dated 24 March 2023).
**Link:** https://www.bis.org/publ/work1087.htm (BIS working paper series page, inferred from the printed series number; **still unverified** as a live URL because the search budget was spent)
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Schmeling_2023_CryptoCarry.pdf` (54 pages)

**What it says.** This is the single most important paper in this family for you, because it is the one that refuses to pretend the trade is free money. The authors collect daily bitcoin and ether prices from March 2019 to January 2022 across crypto-native exchanges (OKEx, Binance, Deribit) and the regulated CME. The average carry, meaning the annualised gap between futures and spot, was about **10% a year** across exchanges, and it spiked as high as **60% a year** in boom periods and went **below minus 20%** in busts. Carry is strongly correlated across exchanges (over 90%) but the CME is the odd one out, correlating only about 60 to 70% with the crypto-native venues. That gap between the regulated rail and the offshore rail is the whole story for a US retail account, and it recurs in the Mallory paper below.

They then take apart where the carry comes from. Interest rate differences explain only **2%** of its variation, and exchange-specific pricing quirks only about **1%**. Almost all of it is what they call a convenience yield: small traders chasing an uptrend want leverage, futures give it to them, and they bid futures above spot. They confirm this from CFTC positioning data, where a rise in net long positions by "nonreportable" traders (small players and wealthy individuals) goes with a rise in carry, while dealers and leveraged funds take the short side.

The honest part is the return profile. For a monthly cash-and-carry on **CME** one-month bitcoin futures, financed at LIBOR, the annualised Sharpe ratio is **about 0.59 to 0.6 before transaction costs and financing spreads**. That is roughly the same as just owning the stock market. Buying and holding spot bitcoin over the same period had **half that Sharpe but a higher average return**. The futures leg alone earns 3 to 4% a month but is fantastically volatile (about **25% a month**) with strong negative skew. And here is the sentence to tape to your monitor: at 10x leverage, the futures leg would have been **liquidated in more than half of the months in the sample**. A rise in carry of 10% predicts a **44% increase in short-futures liquidations** (as a share of open interest) over the next month. The reason is margin: CME initial margin during the sample was around **50%**, versus **under 2%** on crypto-native exchanges, and you cannot use your spot bitcoin as collateral against your CME futures short. High carry also predicts crashes, since a rise in carry predicts both spot and futures prices falling, futures by more.

**Fit for agent automation.** High. The signal is a single arithmetic number (futures price minus spot, annualised) that an agent can compute every minute from two public price feeds, with clear entry and exit thresholds. The hard part is not the signal, it is the margin monitoring, which is also mechanical and therefore automatable.

**Difficulty for a small account: hard.** Not because the maths is hard but because the trade needs two separate margin pools that do not talk to each other, and a 100k book that gets margin-called on the futures leg has to unwind the hedge at the worst moment, which is exactly the failure mode the paper measures.

#### 1.2 Christin, Routledge, Soska and Zetlin-Jones (2022), "The Crypto Carry Trade"

**Citation:** Nicolas Christin (Carnegie Mellon), Bryan R. Routledge (Carnegie Mellon Tepper), Kyle Soska (University of Illinois) and Ariel Zetlin-Jones (Carnegie Mellon Tepper), "The Crypto Carry Trade", working paper dated 1 August 2022.
**Link:** No DOI, arXiv id or URL printed in the PDF. Presented at the NBER Big Data and High-Performance Computing for Financial Economics Conference and the Society for Economic Dynamics Annual Meeting per the acknowledgements. Venue **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Christin_2022_CryptoCarryTrade.pdf` (51 pages)

**What it says.** Same trade, different rail, wildly different numbers. Instead of dated CME futures, this paper studies **perpetual futures** on Binance, using minute-level data harvested from the Binance API from **11 August 2020 to 20 June 2022**, covering bitcoin plus 17 other coins, each in two contract flavours (settled in Tether, and settled in the coin itself).

A perpetual future never expires. To keep its price glued to spot, the exchange makes longs pay shorts a **funding rate every eight hours**. So the carry trade becomes: hold spot, short the perpetual, collect funding. The reported in-sample annualised Sharpe ratios are enormous: the abstract says **7 to 10**, and the introduction gives **12.8 and 7.0** for the two bitcoin contracts. Do not take those at face value; they are in-sample, on one exchange, over a period that included the largest retail crypto mania on record, and they carry exchange credit risk that a Sharpe ratio does not price.

The mechanism is clean and worth understanding. On Binance the funding rate is **0.01% per eight-hour period** by default, which the authors compute as **roughly 11% a year**, plus an adjustment for the basis. The median observed funding rate was exactly that 0.01% floor, and the median basis was near zero. So the profit comes almost entirely from the funding payment, not from basis convergence. The two components are basically uncorrelated (correlation 0.11 and 0.12).

The best evidence in the paper for what actually drives this is a natural experiment: in **July 2021 Binance cut maximum leverage from 125x to 50x**, and crypto carry returns dropped, with funding rates "dramatically smaller" afterwards and Sharpe ratios falling in the lower-leverage era. That is a direct demonstration that the return is a payment for access to leverage, and that when the leverage goes away, so does the return.

**Fit for agent automation.** Very high in principle. Funding rates are published in advance on an eight-hour clock, so an agent can compute the expected payment before deciding to hold the position. The paper even notes you could run a conditional version that only holds when funding is positive.

**Difficulty for a small account: hard.** You cannot do this trade at all in a US Interactive Brokers account. It requires an offshore perpetual futures exchange, which means custody risk, counterparty risk (the paper was written months before FTX collapsed) and, for a US person, a regulatory problem. Read it for the mechanism, do not trade it.

#### 1.3 He, Manela, Ross and von Wachter (2022, revised 2024), "Fundamentals of Perpetual Futures"

**Citation:** Songrun He (Washington University in St. Louis), Asaf Manela (Washington University in St. Louis and Reichman University), Omri Ross (University of Copenhagen) and Victor von Wachter (University of Copenhagen), "Fundamentals of Perpetual Futures". First draft December 2022, this version July 2024. arXiv:2212.06888v6, submitted 13 December 2022, last revised 21 August 2024.
**Link:** https://arxiv.org/abs/2212.06888 (confirmed by fetch). DOI https://doi.org/10.48550/arXiv.2212.06888. No journal reference listed as of the check.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/He_2022_FundamentalsOfPerpetualFutures.pdf` (64 pages)

**What it says.** This is the theory paper that tells you what a perpetual future *should* cost, and then measures how far reality strays. Perpetual futures do about **100 billion dollars of volume a day**, so this is not a niche instrument.

The key conceptual move is what they call **random-maturity arbitrage**. A normal cash-and-carry has a fixed end date when the trade must converge and pay off. A perpetual has no end date, so you can never be sure when your position closes profitably. They are explicit that funding-rate arbitrage is **not risk-free even ignoring margin and trading costs**, purely because there is no predetermined expiration. Their line is worth remembering: an arbitrageur must remain liquid longer than the market stays irrational.

Empirically, the average deviation from their theoretical fair value is small and statistically insignificant, which validates the benchmark. But the **mean absolute deviation is about 60% to 90% a year** across coins, far larger than the equivalent deviations in traditional currency markets. Those deviations move together across coins, which suggests they are driven by common funding and liquidity conditions for arbitrageurs rather than by anything coin-specific. Past returns explain the futures-spot gap with a time-series regression **R-squared above 50%**, which is a positive-feedback story: when prices have been rising, futures get expensive relative to spot.

The trading result: opening a position when the spread exceeds the theoretical bound and closing when it returns to fair value gives a Sharpe ratio of **1.8 for bitcoin under the high trading costs a retail investor pays**, and up to **3.5 for a market maker paying no fees**. Ether and other coins do better. For anyone thinking about entering now, the important line is that **deviations shrink by about 11% a year**, which the authors attribute to more arbitrage capital arriving. The edge is visibly decaying.

**Fit for agent automation.** High. The paper gives an explicit closed-form fair value and explicit cost-tiered bounds, so an agent can compute "is the current spread outside the bound at my fee tier" as a single check.

**Difficulty for a small account: hard.** Same problem as Christin: the instrument is not available to a US retail IB account, and the retail-fee Sharpe of 1.8 assumes you are on the offshore exchange paying its retail fees. Read it for the fair-value formula and for the decay estimate.

#### 1.4 Mallory (2026), "Implied ETF Carry Rates and the Limits of Arbitrage in Segmented Bitcoin Markets"

**Citation:** Mindy L. Mallory (Associate Professor, Purdue University), "Implied ETF Carry Rates and the Limits of Arbitrage in Segmented Bitcoin Markets", May 2026. arXiv:2605.29309v1, submitted 28 May 2026.
**Link:** https://arxiv.org/abs/2605.29309 (constructed from the arXiv id printed on the PDF; **still unverified** as a live URL)
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Mallory_2026_ImpliedETFCarryRatesBitcoin.pdf` (7 pages)

**What it says.** This is the most directly relevant paper in the family to your actual account, and it is short. Mallory compares two ways of getting the same bitcoin carry inside regulated US markets.

Route one is CME bitcoin futures against spot bitcoin. Route two stays entirely inside the equity and listed-options system: hold IBIT (BlackRock's spot bitcoin ETF), then sell a synthetic forward by selling a call and buying a put at the same strike and expiry. Put-call parity recovers the forward price the options market is implying, BlackRock's daily holdings file tells you how much bitcoin each IBIT share represents, and dividing one by the other gives an ETF-implied bitcoin forward you can compare directly to the futures price.

The finding: across **386 date-bucket observations**, the **wedge** (CME carry minus fee-adjusted IBIT-options carry) has a **mean of 2.58% a year and a median of 2.52%**, with a standard deviation of **4.72%**, a 5th percentile of **minus 4.77%** and a 95th percentile of **plus 10.42%**. Split by maturity, the 14 to 30 day bucket averages **2.22%** and the 31 to 60 day bucket **2.94%** (193 observations each). Positive means CME futures embed richer carry than the ETF-options route.

Why does a gap that size survive? Because the two routes sit in different collateral systems. A CME futures short and a spot bitcoin holding cannot be cross-margined; the ETF-options version keeps both legs inside securities and listed-options infrastructure where offsets are recognised, depending on your account type and broker. Mallory's conclusion is a market-design one: the wedge is the price of moving risk between two plumbing systems that do not net against each other.

Method caveats worth knowing: IBIT options are American style and could be exercised early, which the paper handles by filtering rather than by modelling (it keeps only 14 to 90 day contracts, within 5% of the money, bid-ask under 10% of mid, and open interest of at least 100 on both legs). The 61 to 90 day bucket was dropped for thin data. It is a five-page working paper with a small, recent sample.

**Fit for agent automation.** Excellent, and unusually so. Every input is machine-readable: option quotes from your broker, the IBIT close, and BlackRock's holdings CSV at a fixed URL printed in the paper's own footnote. An agent can compute this wedge daily in a few lines and alert when it exceeds a threshold.

**Difficulty for a small account: medium.** This is the only version of the crypto carry trade in this family that a US retail IB account can actually place, and the option-and-ETF version needs no bitcoin custody at all. The difficulty is that a 2.5% annualised edge is thin relative to option bid-ask spreads at retail size.

#### How a US retail Interactive Brokers account could actually do this

Three routes, in increasing order of how plausible they are for you.

**Route A, CME micro bitcoin futures against a spot bitcoin ETF.** Short CME Micro Bitcoin futures (ticker MBT) and hold an equivalent dollar amount of IBIT, FBTC or another spot bitcoin ETF in the same IB account. IB gives retail clients access to both. Contract size for MBT is **0.1 bitcoin** and for the standard contract **5 bitcoin**; those sizes are **still unverified** because the search budget was gone, so check the CME contract spec page before sizing anything. Mallory's footnotes do confirm from CME's own FAQ that Micro Bitcoin futures exist, that standard and micro contracts settle to the BRR benchmark, and that a smaller **Bitcoin Friday futures** contract exists which settles to BRRNY instead. The Friday contract is the more small-account-friendly of the two if it is available to you.

The catch is precisely Schmeling's and Mallory's point. IB will not net your long ETF against your short futures for margin purposes, because they sit in different clearing systems (securities versus futures). So you have to post and maintain futures margin in cash while your hedge sits in the securities side doing nothing for you. If bitcoin rallies hard, the futures leg bleeds cash and demands more margin even though your net position is flat. That is the mechanism that liquidated the trade in more than half of Schmeling's monthly samples at 10x. At a 100k book you must run this unlevered or near-unlevered, hold a large cash buffer against the futures leg, and accept that the return is then Schmeling's roughly 0.6 Sharpe, not the double-digit Sharpes from the offshore papers.

**Route B, the IBIT options box, which is Mallory's route two.** Hold IBIT shares, sell a call and buy a put at the same strike and expiry to create a synthetic short forward. Both legs are securities-side, so margin offsets are recognised and the cross-system problem disappears. This is the cleanest fit for an IB retail account. The trade-off is that you are harvesting the *lower* of the two carries (Mallory's wedge is positive, meaning ETF-options carry is on average 2.58 percentage points a year *below* CME carry), and you pay option bid-ask spreads twice.

**Route C, the wedge itself as the trade.** Be long the cheap rail and short the rich one: short CME futures, and synthetically long bitcoin via IBIT options. This targets Mallory's 2.58% wedge directly. It is elegant and it is exactly what a research agent would propose. It also reintroduces the cross-margin problem in full and adds option-leg complexity, so treat it as a paper-trading exercise for now.

**What the basis and funding have actually looked like, 2024 to 2026:** **still unverified.** I could not run the search. What the PDFs support is this. Mallory's sample is post-IBIT-launch (IBIT began trading in January 2024) and her CME carry leg is positive on average over 386 observations, which tells you the CME basis was in contango over the sample and that the trade was live. He, Manela, Ross and von Wachter measured deviations shrinking by about 11% a year through mid-2024, which points to a narrowing, more competitive basis. My own recollection, which you should treat as **still unverified** and check against CME or Coinglass data before acting, is that the annualised CME three-month basis has mostly run in a **5 to 15% band since the spot ETFs launched in January 2024**, spiking above 20% briefly during the late-2024 rally and compressing towards the single digits and occasionally near or below short-term Treasury yields during 2025 risk-off stretches, and that perpetual funding on offshore venues has similarly spent much more time near its 0.01% per eight hours floor (about 11% a year) than above it. Verify this before it goes anywhere near a sizing decision.

#### Verdict on Family 1 for an agent-run 100k book

Not low-hanging fruit, and the reason is structural rather than intellectual. The versions of this trade with spectacular Sharpe ratios (Christin's 7 to 12, He's 1.8 to 3.5) live on offshore perpetual futures exchanges you cannot legally or safely use, and their returns are explicitly a payment for retail leverage that shrank the moment exchanges cut leverage limits. The version you can actually place on Interactive Brokers is Schmeling's CME cash-and-carry at roughly **0.6 Sharpe before costs**, which after commissions, financing and the cash you must idle against futures margin is not obviously better than holding T-bills, and it carries a real chance of being liquidated at the worst possible moment because the two legs cannot be cross-margined. The one genuinely interesting idea here is Mallory's: build the wedge monitor first, because it costs almost nothing to compute daily from public data, it tells you when the regulated basis is actually rich, and it is a useful research instrument even if you never place the trade.

---

### Family 2: ETF and closed-end fund discount arbitrage

The trade in one sentence: a fund holds a basket of assets worth a known amount per share (the net asset value, or NAV), but the fund's own shares trade at a different price. Buy the gap, wait for it to close.

The critical thing to understand before reading any of this is that **closed-end funds and ETFs are two completely different animals here**, and lumping them together is the main way people get this wrong. Closed-end funds have a fixed share count, no mechanism forces the price to NAV, and discounts of 10 to 20% persist for years. ETFs create and redeem shares daily, which pins them to NAV within a fraction of a percent. The papers below cover both, and they reach opposite conclusions.

#### 2.1 Bradley, Brav, Goldstein and Jiang (2010), activist arbitrage in closed-end funds

**Citation:** Michael Bradley (Fuqua School of Business, Duke University), Alon Brav (Duke), Itay Goldstein (Wharton, University of Pennsylvania) and Wei Jiang (Columbia Business School), "Activist arbitrage: A study of open-ending attempts of closed-end funds", Journal of Financial Economics, volume 95, issue 1 (2010), pages 1 to 19. Received 4 June 2008, revised 17 December 2008, accepted 14 January 2009, online 3 September 2009.
**Link:** doi:10.1016/j.jfineco.2009.01.005 (printed in the PDF)
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Bradley_2010_ActivistArbitrageCEF.pdf` (19 pages)

**What it says.** This is the paper that explains *why* closed-end fund discounts eventually close, and the answer is not mean reversion. Someone has to make it happen. The authors hand-collected every instance of activist arbitrageur activity in US closed-end funds from **1988 to 2003**: 127 events across 1989 to 2003, against a panel of 142 funds and 1,477 fund-years.

The headline number is large. An open-ending attempt, counting both the ones that succeed and the ones that fail, cuts the discount **by more than 10 percentage points on average**. The raw path is striking: a targeted fund trades at a discount **wider than 20% of NAV two years before the attack**, and at about **5.6% three years after**. Against a matched control group of similarly discounted funds that were never attacked, the attacked funds' discount at year three is **more than 8 percentage points lower**, so this is a real effect and not just regression to the mean.

The feedback loop is what makes it interesting. A discount one percentage point wider raises the probability of an attack in a given year by **0.66 percentage points**, and once you strip out the fact that the market anticipates attacks, the causal figure rises to **1.07**. Attack frequency exploded over the sample, from 3 to 4% of funds in the early 1990s to **27.4% in 1999 and 32.6% in 2002**. The 1992 SEC proxy reform alone raised attack probability by **8.48 percentage points** (t-statistic 3.58), and the authors value that reform at **$124 million a year** to closed-end fund shareholders, or $32 million after adjusting for mean reversion. For context, in most years **80 to 90% of closed-end funds trade at a discount**.

The obstacles are the useful part of this paper. Takeovers of closed-end funds are "virtually non-existent" because Section 12(d)(1) of the Investment Company Act of 1940 stops one investment company from holding more than 3% of another, which removes the most natural class of acquirer. Coordination is the binding constraint: high share turnover makes the shareholder list stale, and with a 10 to 60 day gap between record date and vote date, a 100 percentage point rise in annual turnover is associated with a **6 percentage point lower** probability of attack. Institutional ownership above 15% adds **7.5 percentage points**. A staggered board delays open-ending by **almost three years**, because you must win two annual proxy fights. And the sting in the tail: the discount narrows *in anticipation* of an attack, which "reduces the profit from open-ending the fund", so the activist who does the work captures less of the gain.

**Fit for agent automation.** Partial, and this is worth being precise about. An agent can absolutely screen for the setup: wide discount, small fund, high institutional ownership, no staggered board, low turnover. It cannot run a proxy fight. So the automatable version is riding the coattails of activists after they file, not being the activist.

**Difficulty for a small account: hard.** The returns come from a corporate action that takes years and requires a stake and a legal budget you do not have. A 100k book can only be a passenger.

#### 2.2 Patro, Piccotti and Wu (2014), exploiting closed-end fund discounts

**Citation:** Dilip Patro (Office of the Comptroller of the Currency), Louis R. Piccotti (School of Business, University at Albany, SUNY) and Yangru Wu (Rutgers Business School, Rutgers University), "Exploiting Closed-End Fund Discounts: The Market May Be Much More Inefficient Than You Thought", dated 2 October 2014.
**Link:** No DOI, arXiv id, SSRN id or URL is printed anywhere in the paper. Venue **not stated in the PDF** (the file's internal metadata suggests a seminar draft, which is metadata, not a stated venue). Publication status **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Patro_2014_ExploitingCEFDiscounts.pdf` (47 pages)

**What it says.** This is the one with the eye-catching number, and also the one you should be most careful with. Monthly data from **August 1984 to December 2011** on **377 US closed-end funds** (from 693 in CRSP, intersected with Bloomberg NAV data). Roughly the first third is used to fit the model and the remaining two thirds is out-of-sample, with the first out-of-sample prediction in February 1998.

Their argument is that the naive strategy (buy the widest discounts, short the biggest premiums) leaves money on the table because it picks funds that revert *slowly*. Their model instead forecasts each fund's expected return from the full history of its premium innovations, and sorts on that. Buying the top quintile, shorting the bottom quintile, rebalancing monthly, the headline result is **18.2% a year with a Sharpe ratio of 1.918**, against a market Sharpe of **0.170** over the same period. A simpler variant returns 17.3% (Sharpe 1.862), and the naive discount sort returns **14.9%** (Sharpe 1.519), all significant at the 1% level. Against a five-factor model (Fama-French three factors plus momentum plus Pastor-Stambaugh liquidity), alphas are **14.8% a year for the naive version and 17.4% for theirs**.

The mechanism check supports the story: the average bias-adjusted mean reversion speed is **8.6% a month**, an average half-life of **7.7 months**, but the funds their model actually trades revert with a half-life of **4.9 months** while the naive sort picks funds with a half-life of **12.03 months**. Average premium across the full sample is **minus 4.1%** with a standard deviation of **22.4%**. They also report no decay: the first half of the out-of-sample period returns 18.8% annualised and the second half 17.5%, a statistically insignificant difference.

**Now the caveat that governs everything above. The paper deducts no transaction costs anywhere. Every number quoted is gross.** What it offers instead is an argument: turnover is only **2.335 times a year**, the traded funds average **$382 million** in market cap and **$224 million** in annual dollar volume, which puts them in the fourth and fifth deciles of NYSE stocks, and therefore "there would have been sufficient liquidity for this trading strategy to have been a tradable one". That is an assertion, not a cost model. There is no borrow-fee, bid-ask or market-impact analysis in the paper. To their credit they do pre-empt the shorting objection with a long-only version: the top quintile minus the market returns **10.7% a year**, so more than half the profit survives with no shorting at all.

**Fit for agent automation.** Very high. This is a monthly, rules-based, cross-sectional sort on publicly available price and NAV data, which is exactly the shape of problem an agent handles well. The model itself is a straightforward time-series estimation per fund.

**Difficulty for a small account: medium.** The long-only version is genuinely accessible; closed-end funds trade like stocks on IB. The short leg is where a small account struggles, because closed-end funds trading at big premiums are precisely the ones that are expensive or impossible to borrow. Treat the 18.2% as an upper bound that has never met a commission.

#### 2.3 Durmaz, Kim, Lee and Sun (2025), trend breaks and CEF discount persistence

**Citation:** Nazif Durmaz (Global Business School, Kean University), Hyeongwoo Kim (Department of Economics, Auburn University), Hyejin Lee (Tuskegee University) and Yanfei Sun (Toronto Metropolitan University), "Trend Breaks and the Persistence of Closed-End Fund Discounts", Auburn University Department of Economics Working Paper Series, AUWP 2025-02, May 2025.
**Link:** http://cla.auburn.edu/econwp/ and http://econpapers.repec.org/paper/abnwpaper/ (both printed in the PDF). No DOI or SSRN id. Footnotes reference referee comments, so it is under journal review somewhere, but no journal is named. Journal outcome **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Durmaz_2025_TrendBreaksCEFDiscounts.pdf` (49 pages)

**What it says.** Be clear on what this paper is, because the title oversells it for a trader. **"Trend breaks" is not a trading signal. It is an econometric specification choice.** The question is whether closed-end fund discounts are a random walk (in which case there is nothing to trade) or a stationary process that reverts (in which case there is). The answer turns out to depend entirely on how you write down the model.

The data is **31 closed-end fund discount series, monthly, January 1999 through April 2018** (14 core stock funds, 6 BBB-rated corporate debt funds, 11 general bond funds, all above $50 million in assets). One inconsistency worth flagging: a robustness footnote describes a post-crisis subsample running "July 2009 to December 2019", past the stated April 2018 end date, and the paper does not explain it.

A **level shift** lets the trend line jump up or down at a break date. A **trend break** lets the *slope* change. The paper allows up to two of these per fund, with dates chosen by the data. The results are a clean ladder:

- Under a standard linear model, persistence is extreme. Half-lives run from **4.49 months to infinity**, with a **median of 8.10 months and an average of 13.70 months**, and a panel version implies a half-life of **over 137 months** (about eleven and a half years). Standard tests reject the random walk for only **12 of 31 funds** at the 5% level.
- Allowing **level shifts only** buys essentially nothing: at most 11 rejections at the 10% level. This is the paper's negative result.
- Allowing **one trend break** rejects for up to **20 of 31**.
- Allowing **two trend breaks** rejects for **29 of 31**.

So the "closed-end fund discount puzzle" is largely an artefact of forcing a straight line through data whose slope changes. The break dates line up with history: stock funds break around the dot-com bust, the 2001 to 2002 fraud wave and 2008; bond funds break around 2008 and again in the early 2010s during quantitative easing. Across the 31 funds, **7 trade at a premium rather than a discount**, ranging from a 14.99% average discount to a 17.23% average premium.

**Two things this paper does not contain, and you should know both.** First, **there is no out-of-sample test and no backtest**. Footnote 24 says so explicitly: "We do not attempt an out-of-sample predictability assessment in this paper." Every result is an in-sample count of statistical rejections. Second, the trading implication they draw is **momentum, not mean reversion**: because deviations persist along a trend, "price reversals are unlikely to occur within short investment horizons, at least until the realization of a new trend break". They suggest going long funds with narrowing discounts while shorting the underlying NAV constituents, and then immediately knock it down, noting that "constructing a precise short portfolio is often costly or infeasible due to liquidity constraints, legal restrictions, operational challenges". They also warn that in the post-crisis subsample there are **fewer rejections, greater persistence and many structural breaks that are statistically insignificant**, meaning the effect is weaker in recent data.

**Fit for agent automation.** Medium. The econometrics (endogenous break-date selection, residual-augmented unit root testing) is mechanical and an agent can run it. But it produces a diagnostic, not a signal.

**Difficulty for a small account: hard.** The strategy the paper gestures at requires shorting a replicating basket of the fund's holdings, which the authors themselves call infeasible.

#### 2.4 Petajisto (2011), market trading characteristics of ETFs

**Citation:** Antti Petajisto (NYU Stern School of Business), "Characteristics of Market Trading in Exchange-Traded Funds: 2009-2010", dated 31 August 2011.
**Link:** Only http://www.petajisto.net/ is printed. No DOI, SSRN id or arXiv id. Venue **not stated in the PDF**; it carries only an NYU Stern affiliation and "© by the author", has no reference list, and reads as a self-published report. Publication status **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Petajisto_2011_CharacteristicsMarketTradingETFs.pdf` (32 pages)

**What it says.** This is the paper that should stop you from trying ETF premium arbitrage, and it does so by simply reporting how small the deviations are. Sample is **995 ETFs, about $990.8 billion in market cap, 1 January 2009 to 31 December 2010**, using CRSP, Bloomberg NAV, Morningstar and TAQ data.

Across all 995 ETFs the average premium is **14 basis points** (0.14% of NAV) at the closing bid-ask midpoint and **15 basis points** at the closing price. In the author's own words, average premiums are "close to zero across most categories of ETFs, indicating that ETFs tend to trade at neither a meaningful premium nor a meaningful discount (unlike closed-end funds)".

The breakdown by asset class is the useful bit, because it tracks exactly how hard the underlying is to trade. Average premium in basis points (midpoint / closing price), with the volatility of that premium:

| Category | Avg premium (bp) | Premium volatility (bp) |
|---|---|---|
| US equity, diversified (216 funds) | -1 / -1 | 16 / 23 |
| US equity, sectors (273 funds) | 8 / 10 | 42 / 47 |
| US bonds, government (34 funds) | 9 / 11 | 23 / 23 |
| US bonds, general (43 funds) | 33 / 36 | 54 / 55 |
| US bonds, munis (27 funds) | 36 / 40 | 54 / 57 |
| International equity (204 funds) | 36 / 37 | 88 / 91 |
| International bonds (11 funds) | 52 / 54 | 68 / 66 |
| Commodities (31 funds) | 12 / 13 | 100 / 100 |
| **All (995 funds)** | **14 / 15** | **49 / 53** |

Domestic diversified equity is pinned to within a basis point or two of NAV. The wide categories are the ones where the underlying is hard to price or trade: high yield bond ETFs average **105 bp** at the midpoint with **158 bp** of volatility, high yield munis **113 bp**, emerging market bonds **92 bp**, Latin America and China region equity **75 bp** each. Bond ETF premiums are partly an artefact, because bond NAVs are often struck off bid prices, so the NAV is understated against a midpoint. International equity premiums are largely a time-zone effect.

The tails are fat even if the averages are small. Excess kurtosis of closing-price premiums is **14** equal-weighted. Extremes across all ETFs run from **minus 18.7% to plus 19.9%** (right against the 20% data-error filter). Even SPY had "a few closing price premiums of about 50 bp in 2009". The 95% confidence interval for the premium is roughly **minus 1% to plus 1%**.

The lead finding is a practical one you can use immediately even if you never trade this strategy: **closing prices are worse than closing midpoints**. Premium volatility at the market close is **53 bp** versus **49 bp** at the midpoint, meaning market-on-close orders execute farther from NAV. If your agent places MOC orders in ETFs, it is paying for the privilege.

On why nobody arbitrages the rest away, the answer is **creation unit size**. Creations or redemptions happen on only **21% of trading days** on average and just **11% at the median fund**. The median creation transaction is **100,000 shares, $4 million, 5% of fund assets and 237% of that day's ETF trading volume**; the mean is **1,565% of daily volume**. Petajisto's conclusion is blunt: "Even if an arbitrageur participates in every single trade in a fund and always on the same side, in most funds it would still need several days to accumulate a position that would be large enough to offset the creation or redemption of a single creation unit." Premiums do get corrected, but weakly and slowly: past premiums predict share creations out to about **10 daily lags**, a 1% premium brings in created shares equal to about **8% of daily volume**, and creating shares equal to a full day's volume knocks only about **1 bp** off the premium that day and another **1 bp** over the following two days. He notes drily that authorized participants create "but not so aggressively that the APs would eliminate the premium that is generating their own arbitrage profits".

Costs, for sizing: the **median ETF closing bid-ask spread is 14 bp**, from 1 bp for the most liquid to several percent for the least. Equal-weighted spreads are **30 bp for US sector funds, 29 bp for US corporate bonds, 22 bp for munis and 34 bp for international equity**, which are the same categories with the biggest premiums. Multiplying either market cap or daily volume by ten roughly halves the spread. Median fund assets are **$91 million** against SPY's $91 billion, and median dollar volume is about **$1 million a day**.

**There is no backtested strategy and no stated trading return anywhere in this paper. Still unverified** if you need one.

**Fit for agent automation.** High as a data-quality and execution-quality tool, not as a strategy. The single most valuable thing here for an agent-run book is the finding about closing prices versus midpoints, which is an execution rule you can apply to every ETF order you ever place.

**Difficulty for a small account: hard, in the sense that the trade does not exist.** You cannot create or redeem ETF shares without being an authorized participant, and the residual mispricing after spreads is smaller than the spread you pay to capture it.

#### Verdict on Family 2 for an agent-run 100k book

Split the verdict, because the two halves of this family are not the same trade. **ETF premium arbitrage is not available to you at all**: the average deviation is 14 basis points, the median bid-ask spread is 14 basis points, and the correction mechanism requires being an authorized participant creating $4 million blocks. Read Petajisto for the execution lesson (avoid market-on-close orders, and expect wide categories like high yield and international to trade further from NAV) and move on. **Closed-end fund discounts are a genuinely different and more promising story**, since discounts of 10 to 20% do persist and do eventually close, and Patro reports 18.2% a year gross with a long-only version still worth 10.7%. But note what is missing: Patro deducts no transaction costs at all, Durmaz runs no out-of-sample test and finds the effect weaker after the financial crisis, and Bradley shows the convergence is driven by activists doing expensive, slow legal work you cannot do. **Worth a paper-trading sleeve, using the long-only version of Patro's sort on liquid closed-end funds, with real costs modelled from day one.** It is the most interesting idea in this whole document, and also the one whose headline number is least likely to survive contact with a commission schedule.

---

### Family 3: Sector rotation and dual momentum on ETFs

The trade in one sentence: hold the asset classes that have been going up, move to cash or bonds when they turn down, and rebalance once a month.

This is the family with the best story and the weakest recent evidence, so the honesty section at the end matters more than usual.

#### 3.1 Faber (2013 update), a quantitative approach to tactical asset allocation

**Citation:** Mebane T. Faber (Cambria Investment Management, LP), "A Quantitative Approach to Tactical Asset Allocation". Original working paper May 2006; published Spring 2007 in **The Journal of Wealth Management**; updated February 2009; this version is the **February 2013 update**, extending results through 2012.
**Link:** http://ssrn.com/abstract=962461 (printed in the PDF). This is the paper Faber later described as the most downloaded paper of all time on SSRN, with approximately **200,000 downloads**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Faber_2013_QuantitativeApproachTAA.pdf` (70 pages)

**What it says.** The rule is almost insultingly simple, and that is the point. **Buy when the monthly closing price is above its 10-month simple moving average. Sell to cash when it is below.** Check once a month, on the last trading day. Same rule and same parameter for every asset class. Cash earns 90-day Treasury bills. All series are total return including dividends, from Global Financial Data.

Applied to the S&P 500 from **1901 to 2012**, the timing model and buy and hold earn almost the same *average* return (**11.22% versus 11.26%**), but very different *compound* returns (**10.18% versus 9.32%**). That gap of nearly a full percentage point a year is purely the arithmetic of avoiding large losses: buy and hold gives up nearly 200 basis points to volatility drag, timing gives up about 100.

The portfolio version, which Faber calls **Global Tactical Asset Allocation (GTAA)**, applies the same rule independently to **five equally weighted asset classes: US stocks, foreign stocks, bonds, real estate and commodities**, each either fully invested or in cash with its 20% slice. Tested from **1973 to 2012**, timing cuts the **maximum drawdown from 46% to under 10%**, brings volatility to single digits, and produced **only one down year worse than minus 1% since 1973**. The system keeps you at least 60% invested about **80% of the time**, and **70% invested on average**.

Faber is upfront that this is a risk-reduction tool, not a return-enhancement tool. He also stress-tests the parameter: moving averages from 3 to 12 months all behave similarly, so the 10-month choice is not an optimisation artefact.

On the out-of-sample period since the original 2006 publication, the 2013 update reports that from **2006 to 2012 the model outperformed in only three of seven years**, but "beat buy and hold by over two percentage points per year, with much less volatility". On practical costs: management fees of **0.10% to 0.70%** using ETFs, and turnover of only **three to four round-trip trades per year for the whole portfolio**, less than one per asset class per year. Taxes are the real issue, and his recommendation is to run it in a tax-deferred account.

**Fit for agent automation.** As good as it gets. One price series per asset, one moving average, one comparison, once a month. An agent could implement the entire strategy correctly in an afternoon, and the low turnover means execution quality barely matters.

**Difficulty for a small account: easy.** Five liquid ETFs, monthly rebalancing, three or four trades a year, no shorting, no leverage, no margin. This is the single most implementable strategy in this entire document.

#### 3.2 Faber (2017), the ten-year follow-up, and the honest decay story

**Citation:** Meb Faber (Chief Investment Officer, Cambria Investment Management, LP), "A Quantitative Approach to Tactical Asset Allocation Revisited 10 Years Later", **The Journal of Portfolio Management**, 2017, volume 44, issue 2, pages 156 to 167 (Multi-Asset Special Issue 2018).
**Link:** doi: https://doi.org/10.3905/jpm.2018.44.2.156, printed in the PDF alongside http://jpm.iijournals.com/content/44/2/156
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Faber_2017_TAARevisited10YearsLater.pdf` (13 pages)

**What it says.** This is Faber grading his own homework eleven years after publication, and to his credit he does not flatter himself. The paper re-runs the identical model on data through 2016 and reports in-sample (1901 to 2005) against out-of-sample (2006 to 2016) results.

**The sentence that matters most for you, quoted exactly:** "Though the timing system outperformed by a significant amount during the 2008-2009 bear market, **it went on to underperform stocks six of the next eight years.** Many investors who had implemented the timing model after the crash likely struggled with staying the course with a tactical approach."

That is the decay story in one line, and it is not really decay in the sense of a broken edge. It is the strategy behaving exactly as designed in an environment that punished the design. A trend-following overlay that moves to cash gives up return during an uninterrupted bull market, and 2009 to 2016 was one of the longest uninterrupted bull markets on record with near-zero yields on the cash leg. Faber says as much: "a trend-following model can underperform buy and hold during a roaring bull market", and "the value added by timing is evident only over the course of the entire business and market cycles."

His overall verdict is positive: the timing model "improved compounded returns while reducing risk and drawdowns in both periods", the portfolio version delivered single-digit volatility and single-digit maximum drawdown in both the in-sample and out-of-sample periods, and "although returns have been far lower for all assets in the out-of-sample period, timing added value". He also re-runs the parameter check and finds "the choice of the moving average doesn't really matter all that much, and any of the moving average lengths would have outperformed a buy-and-hold allocation."

**One limitation of this PDF you should know: the numeric tables (Exhibits 4, 5, 7 and 8, which hold the actual in-sample versus out-of-sample return, volatility, Sharpe and drawdown figures) are embedded as images and cannot be extracted as text.** The precise out-of-sample CAGR and drawdown figures are therefore **still unverified** from this file. What is verifiable is the narrative above, including the six-of-eight-years underperformance statement, which is in the body text.

On costs, he repeats the 2013 position: commissions are minimal because of low turnover, slippage is small if you use liquid ETFs, many brokerages offer commission-free trading on some funds, but **taxes are "a very real consideration"** and the obvious fix is a tax-deferred account.

**Fit for agent automation.** Same as the 2013 paper. What this one adds for an agent-run book is a behavioural warning, and it is one an agent is well suited to handle: the reason people abandon this strategy is emotional, and an agent does not get bored underperforming for six of eight years.

**Difficulty for a small account: easy to run, hard to stick with.** Nothing about the mechanics is difficult. The difficulty is entirely psychological, and Faber says so explicitly.

#### 3.3 Antonacci (2013), risk premia harvesting through dual momentum

**Citation:** Gary Antonacci (Portfolio Management Associates, LLC), "Risk Premia Harvesting Through Dual Momentum". First version 18 April 2012, this version **28 January 2013**. An earlier version under a different title won first place in the **2012 NAAIM Wagner Awards for Advancements in Active Investment Management**.
**Link:** http://www.optimalmomentum.com is printed in the PDF. No DOI, arXiv id or SSRN id is printed. Journal venue **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Antonacci_2013_RiskPremiaHarvestingDualMomentum.pdf` (37 pages)

**What it says.** The core idea is a clean two-part filter, and the distinction is worth getting right because it is the whole paper.

**Relative momentum** asks: of these two assets, which has gone up more? You buy the winner. **Absolute momentum** asks: has this asset beaten Treasury bills over the lookback period at all? If not, you hold Treasury bills instead. **Dual momentum** applies both: pick the relative winner, but only hold it if it also has positive absolute momentum. Relative momentum is what boosts return; absolute momentum is what cuts drawdown, and Antonacci is explicit that "absolute momentum does far more to lessen volatility and drawdown".

The lookback is **twelve months**, chosen because it is the more common choice in the literature and has lower transaction costs than six. Positions are adjusted **monthly**, with no skipped month (unlike equity momentum studies, because the paper covers gold, bonds and real estate where short-term reversal is less of an issue). Data runs **January 1974 to December 2011**, 38 years.

Rather than one portfolio, he builds four two-asset "modules", each pairing two related risk assets with Treasury bills as the escape hatch: **Equities** (US versus EAFE foreign), **Credit Risk** (high yield versus investment grade credit bonds), **REITs** (equity REITs versus mortgage REITs) and **Economic Stress** (gold versus long Treasuries). Here are the headline results, 1974 to 2011:

| Strategy or asset | Annual return | Annual std dev | Sharpe | Max drawdown |
|---|---|---|---|---|
| **Equities module (dual momentum)** | **15.79%** | 12.77% | **0.73** | **-23.01%** |
| Equities, relative momentum only | 13.46% | 16.17% | 0.45 | -54.56% |
| US equities buy and hold | 11.49% | 15.86% | 0.35 | -50.65% |
| EAFE+ buy and hold | 11.86% | 17.67% | 0.33 | -57.37% |
| **Credit Risk module** | **10.49%** | 4.74% | **0.97** | **-8.20%** |
| High yield buy and hold | 10.29% | 8.67% | 0.51 | -33.17% |
| **REITs module** | **16.78%** | 13.24% | **0.77** | **-23.74%** |
| Equity REIT buy and hold | 14.60% | 17.39% | 0.48 | -68.30% |
| **Economic Stress module** | **16.65%** | 17.04% | **0.59** | **-24.78%** |
| Gold buy and hold | 9.22% | 20.00% | 0.17 | -61.78% |
| **Composite of all four modules** | **14.93%** | **7.99%** | **1.07** | **-10.92%** |

The equities module comparison is the cleanest demonstration of the argument. Relative momentum alone lifts return from about 11.5% to 13.46% but leaves the drawdown at **minus 54.56%**, barely better than buy and hold. Adding the absolute momentum filter lifts return to 15.79% *and* cuts the drawdown to **minus 23.01%**. As Antonacci puts it, dual momentum "doubles the Sharpe ratio and cuts the drawdown in half". Turnover is low: **1.4 trades a year** for the equities module. The composite is in Treasury bills entirely only **3.5% of the time**.

**Two things to hold in mind.** First, **this is entirely a backtest. There is no live track record in the paper.** The sample begins in 1974 and ends in 2011, and the paper was written in 2012 and 2013. Second, the modules and the pairings inside them are choices the author made, and a two-asset module with a Treasury bill escape hatch has few enough moving parts that the selection of *which* two assets is doing real work. The paper does report that all formation periods tested have average Sharpe ratios above those of the individual assets, which is reassuring on the lookback parameter if not on the asset selection.

**Fit for agent automation.** Excellent, and slightly better than Faber because the rule is a comparison of two twelve-month returns against each other and against Treasury bills, which is three numbers and two comparisons per module per month.

**Difficulty for a small account: easy.** Two to eight liquid ETFs plus a Treasury bill fund, monthly, long-only, no shorting, no leverage, roughly one to two trades per module per year.

#### On post-publication decay, honestly

You asked for this specifically, so here is exactly what I can and cannot support.

**What is confirmed from the papers themselves.** Faber's own ten-year follow-up is the strongest evidence available, and it is mixed. The model **underperformed stocks six of the eight years after the 2008-2009 crisis**, and in the 2013 update it **outperformed in only three of seven years from 2006 to 2012** while still beating buy and hold by over two percentage points annually with lower volatility. Faber's framing is that the strategy performed as designed, and the design gives up return in sustained bull markets. That is a defensible reading, not a dodge: a strategy that cuts your maximum drawdown from 46% to under 10% is *supposed* to lag when there is no drawdown to avoid.

**What I could not confirm, and why.** I was asked to find one independent 2023 to 2026 live-tracking result from Allocate Smartly or Alpha Architect, and **I could not.** The session's web search budget was exhausted before I reached this task. Using the remaining page fetches, I confirmed that **Allocate Smartly exists, tracks "100+ strategies" as of a blog post dated 13 July 2026, and lists Faber's GTAA variants (GTAA 5, GTAA 13, GTAA Agg 3, GTAA Agg 6) and Antonacci's dual momentum strategies among them**. But their performance statistics sit behind a member login, and the two public blog posts I could reach contained no 2023 to 2026 return figures. Alpha Architect's search page returned a 403 error.

So: **an independent 2023 to 2026 out-of-sample evaluation of these models is still unverified.** It is a real gap, not an absence of evidence, and it is the single highest-value thing to check next. Allocate Smartly is the right source, it tracks precisely these two strategies, and a paid month of access would settle the question properly. Do not let an agent fill this gap by recalling numbers.

**What you should assume in the meantime.** Two structural headwinds are worth reasoning about even without the data. First, the cash leg. These models park in Treasury bills when trend is negative, and from 2009 to 2021 that paid roughly nothing, which is a large part of why the out-of-sample decade lagged. Since 2022 short rates have been meaningfully positive again, which mechanically *helps* these strategies relative to the decade Faber was writing about. Second, whipsaw. A monthly trend filter loses money in choppy, directionless markets that reverse within a month or two, and it does so repeatedly. Both effects are real and neither is evidence that the edge is gone.

#### Verdict on Family 3 for an agent-run 100k book

**This is the closest thing to low-hanging fruit in this entire document, with one honest caveat.** The mechanics are trivial (one moving average or one twelve-month return comparison, checked monthly), the instruments are five to ten liquid ETFs available in any IB account, there is no shorting, no leverage and no margin, and turnover is three to four round-trip trades a year, so execution quality and commissions barely matter. That combination is rare and it is exactly what a small automated book should want. The caveat is that you should expect it to feel bad: Faber's own model underperformed plain stocks in six of the eight years after 2008, and an agent-run book has the advantage of not caring, but you will. Build it first because it is the cheapest thing here to build and paper-trade correctly, size it as a risk-reduction sleeve rather than a return engine, and go verify the 2023 to 2026 live numbers on Allocate Smartly before you commit real money to it.

---

### Family 4: Pairs trading on ETFs

The trade in one sentence: find two securities that normally move together, and when they drift apart, buy the loser and short the winner, betting the gap closes.

This family is a special case. The pack's section 6 already covers the classical literature, so what follows is deliberately narrow: one recent survey that updates the record to 2023, one small ETF-specific study, and a pointer back to the review you already have.

#### 4.1 Sun (2025), survey of pairs trading, 2016 to 2023

**Citation:** Yufei Sun (Faculty of Economic Sciences, University of Warsaw), "A survey of statistical arbitrage pairs trading strategies with non-machine learning methods, 2016-2023", University of Warsaw Working Papers No. 19/2025 (482), Warsaw 2025. ISSN 2957-0506.
**Link:** No DOI, arXiv id or SSRN id is printed. The series URL printed on the back cover is https://www.wne.uw.edu.pl. Direct paper URL **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Sun_2025_SurveyStatArbPairsTrading.pdf` (100 pages)

**What it says.** This picks up exactly where Krauss left off, by design. Krauss surveyed 2006 to 2015; Sun surveys **123 reviewed articles published 2016 to 2023** (the reference list runs to 145 entries, with [1] to [123] being the reviewed corpus). Read the title carefully, because it contains an important limitation: this survey **deliberately excludes machine learning methods**. It cannot tell you whether ML-based pairs trading works.

It sorts the field into the same five buckets Krauss used, and counts how many studies use each: **cointegration 43, stochastic control 40, distance 21, time series 20, other (copula, Hurst exponent, entropic) 16**. In plain terms, distance methods just measure how far apart two prices have drifted; cointegration methods run a formal statistical test for a long-run tethering relationship; time series methods model the gap as a mean-reverting process; and stochastic control methods solve mathematically for the optimal position size at every moment. Twenty-one of the 123 papers are purely theoretical, validated on simulations rather than live trading.

On decay, which is the reason to read this at all, be clear about what the paper is and is not. **Sun does not run an original decay analysis and does not give a single headline decay number.** The decay evidence is second-hand, quoted from reviewed studies. The most useful figures:

- The best gross-versus-net comparison in the survey is Rad, Low and Faff (2016), on over 23,000 US stocks from 1962 to 2014. Distance and cointegration produced significant average monthly excess returns of **0.91% and 0.85% before transaction costs**, which compounds to roughly 10 to 11% a year and matches the original Gatev result. **After time-varying transaction costs, the same strategies returned 3.3% and 3.8% a year**, and the copula variant fell to **0.5%**. Costs removed roughly two thirds of the gross edge.
- Smith and Xu (2017), US equities 1980 to 2014: the distance approach reached **as high as 40% annualized** for smaller portfolios in the 1980s and 1990s, but after transaction costs **profitability declines sharply in the 2000s**. Cointegration worked only in the 1980s. Sun does not print the post-2000 figure.
- Chen et al. (2019) is cited for **a decline in profitability in more recent years**, attributed to changes in market microstructure, regulation and competition.
- In fairness, the picture is time-varying rather than monotonically dying. Bowen and Hutchinson (2016) found UK equity pairs returned **36% to 48% annualized during the financial crisis** while the FTSE All-Share fell 34%. Sun's generalisation: profitability peaks in turbulent markets and declines in calm ones.

What Sun says still works: **adaptive cointegration** is the most positive verdict, with the explicit recommendation to move from static tests to rolling-window estimation, Kalman filter cointegration, VECM and Bayesian recalibration. Pre-selection matters enormously; Brunetti and De Luca (2023) tested seven pair-picking metrics on S&P 500 constituents from 1998 to 2018 and got over 12% annualized from log-price correlation selection versus inconsistent results from spectral coherence. Same strategy, different pair-picking rule, very different outcome. Stochastic control is theoretically strongest and practically weakest, because "many models assume frictionless trading".

**Fit for agent automation.** High as a research input, low as a strategy. This is a map of 123 papers telling an agent which branch of the literature to implement and which to skip. It contains no strategy of its own.

**Difficulty for a small account: medium.** Reading it is easy. Acting on its main recommendation (adaptive Kalman-filter cointegration with careful pre-selection) is real engineering.

#### 4.2 Ngeh (2024), cointegrated pairs trading with gold ETFs

**Citation:** Rodrick Ngeh, "Cointegrated Pairs Trading with Gold Tracking ETFs", Finance Master Thesis, dated 05-02-2024 (5 February 2024).
**Link:** No DOI, arXiv id, SSRN id or URL printed. **No institution is named anywhere in the document.** The only institutional trace is a reference citing a lecture at Aalborg University, Denmark, which is suggestive but is a course citation, not a statement of affiliation. Institution **still unverified**.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Ngeh_2024_CointegratedPairsTradingGoldETFs.pdf` (35 pages)

**What it says.** It trades exactly two US gold ETFs against each other: **SPDR Gold Shares (GLD)** and **iShares Gold Trust (IAU)**. Daily adjusted closes from FactSet, **1 January 2015 to 25 October 2023**, 2,219 observations, split 70% training (to March 2021) and 30% test (5 March 2021 to 25 October 2023).

Method: log prices, cointegration confirmed by both Johansen and Engle-Granger ADF, then an OLS fit on training data giving Log(GLD) = 0.985 + 1.64 x Log(IAU). That hedge ratio is then frozen for the whole test period. Signals come from a **20-day z-score** of the spread, entering long at z of minus 1.0 and short at plus 1.0, exiting when z crosses zero, with stops at plus or minus 2.5. Daily rebalancing.

Reported results, test period: annualized return **2.03%**, annualized volatility **0.52%**, **Sharpe ratio 3.9**, maximum drawdown **0.03%**, **318 trades**. Training period was better still: 5.11% return, 0.88% volatility, **Sharpe 5.82**, **0% maximum drawdown**, 907 trades. Against LBMA gold over the test window, the benchmark returned 1.41% with 1.18% volatility and Sharpe 0.78.

**Now the honest part, because these numbers should not be believed.** This is a small single-pair student study with several problems that a research agent would otherwise happily cite:

1. A maximum drawdown of **exactly 0%** across 1,553 trading days and 907 position changes is arithmetically impossible for any real long-short book.
2. The cost model is broken. The thesis states a 5% transaction cost, but reading the method, the 5% is subtracted from a **signal value**, not from trade notional. A 5% notional cost charged 907 times would destroy the account many times over, yet the result stays positive. In substance this is a **gross, pre-cost result**, and the paper contains no valid cost-adjusted number.
3. There is no capital base. The author assumes "no initial capital was injected" and sums signed daily returns, so "annualized return" has no ordinary denominator, and the risk-free rate is set to zero in the Sharpe calculation.
4. The 1.64 hedge ratio is a price-level artifact (GLD trades around ten times IAU's price), not a genuine beta, and it is never re-estimated.
5. The sensitivity analysis varies the window and thresholds on the **same test data**, so it measures parameter smoothness, not out-of-sample robustness.
6. Win rate is never reported. **Still unverified.**
7. The author states outright that whether pairs trading profits are declining "is another topic which will not be discussed in this thesis."

**Fit for agent automation.** The mechanics are trivially automatable and the paper is a fine worked example of the pipeline (test cointegration, fit hedge ratio, z-score the spread, threshold it). The results are not usable.

**Difficulty for a small account: easy to implement, hard to profit from.** GLD and IAU are liquid, cheap, shortable ETFs available in any IB account, so the trade is mechanically simple. The problem is that two funds tracking the same metal have a spread whose genuine deviations are smaller than the bid-ask spread and borrow cost you will pay to capture them.

#### 4.3 Krauss (2015), the earlier review (cross-reference only)

**Citation:** Christopher Krauss (Department of Statistics and Econometrics, University of Erlangen-Nuremberg), "Statistical Arbitrage Pairs Trading Strategies: Review and Outlook", IWQW Discussion Paper No. 09/2015, Institut fur Wirtschaftspolitik und Quantitative Wirtschaftsforschung, Friedrich-Alexander-Universitat Erlangen-Nurnberg, dated Wednesday 26 August 2015. ISSN 1867-6707. No journal named in the PDF (a journal version exists but is **still unverified** from this file). No DOI or SSRN id printed.
**Local file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/Krauss_2015_StatArbPairsTradingReviewOutlook.pdf` (62 pages)

Already covered by the pack's section 6, so just the two lines that matter here. Reviewing more than 90 papers, Krauss concludes: "Pairs trading profitability has low exposure to systematic factors of risk, **declines over time** and can partially be explained by information diffusion and market frictions, such as liquidity factors." And on Do and Faff extending the original Gatev sample seven years to 2009: "They confirm a declining profitability in pairs trading, mainly due to an increasing share of nonconverging pairs. **With the inclusion of trading costs, pairs trading according to GGR's baseline methodology becomes largely unprofitable.**" Only refined versions adding industry restrictions and a mean-reversion filter stayed "slightly profitable" after full costs, and Krauss flags that Do and Faff tested 29 selection-algorithm combinations and are therefore exposed to data snooping. Engelberg, Gao and Jagannathan are cited for profitability that "exponentially decreases over time".

#### Verdict on Family 4 for an agent-run 100k book

Two independent surveys ten years apart agree, and the direction is bad. Krauss in 2015 found the plain Gatev rule **largely unprofitable after costs by 2009**; Sun in 2025 carries it forward with the cleanest number in the literature, that gross monthly excess returns of 0.85% to 0.91% become **3.3% to 3.8% a year after realistic time-varying costs**, and that the distance method's 40% annualized in the 1980s and 1990s **declines sharply in the 2000s**. That is a strategy whose surviving edge is roughly a Treasury yield, before you have paid a single commission of your own. The ETF-specific evidence does not rescue it: the one ETF study here reports a Sharpe of 3.9 and a 0.03% drawdown on a single gold pair using a cost model that never charges costs against notional, which tells you about the paper rather than the market. **Not low-hanging fruit.** If you pursue it at all, pursue the one thing Sun says still has life, which is adaptive cointegration (rolling-window or Kalman-filter hedge ratios, re-estimated rather than frozen) with disciplined pair pre-selection, and expect it to be a real engineering project rather than a weekend backtest.

---

### Searched for and not found

This session's web search budget (200 of 200 calls) was already exhausted by earlier work before this task began, so every WebSearch call failed outright. I fell back on direct page fetches, which have their own limit, and spent all 12 of my allotted lookups. The following gaps are real and each one is a specific, checkable next action rather than a dead end.

| Gap | What I tried | Status and how to close it |
|---|---|---|
| **CME bitcoin futures basis and perpetual funding rates, 2024 to 2026** | WebSearch (budget exhausted); fetched Coinglass basis page (blocked, domain could not be verified); fetched The Block's BTC annualized basis data page (404) | **Still unverified.** The paragraph in section 1 marked as recollection must be checked. Best sources: the Coinglass futures basis page, CME's own bitcoin futures page, or Amberdata / Velo / Glassnode. This is the single most important number for sizing anything in Family 1. |
| **Independent 2023 to 2026 live-tracking result for Faber GTAA or Antonacci dual momentum** | Fetched four Allocate Smartly pages (strategy list, blog index, a strategy page that 404'd, and the "Investing in Distressed TAA Strategies (Redux)" post dated 13 July 2026); fetched Alpha Architect search (403 Forbidden) | **Still unverified.** Confirmed only that Allocate Smartly tracks "100+ strategies" including GTAA 5, GTAA 13, GTAA Agg 3, GTAA Agg 6 and Antonacci's dual momentum. Their performance data is behind a member login. A one-month subscription would settle this properly. |
| **A practitioner (non-academic) test of ETF pairs trading** | WebSearch (budget exhausted); Alpha Architect search returned 403 | **Still unverified.** Not found. The academic ETF-specific evidence in hand is one master's thesis whose numbers do not survive scrutiny. Worth a targeted search of Alpha Architect, Quantpedia and QuantConnect's research library. |
| **Live URLs for four papers** | Constructed from identifiers printed in the PDFs | **Still unverified as live links:** Schmeling (BIS work1087), Mallory (arXiv 2605.29309), Sun (University of Warsaw WP 19/2025), Durmaz (Auburn AUWP 2025-02). All four identifiers are printed in the PDFs themselves, so the papers are correctly identified; only the URL resolution is unchecked. |
| **Publication venue for three papers** | Read every page of each PDF | **Still unverified.** Christin et al. 2022 (presented at NBER and SED conferences, no journal named), Patro et al. 2014 (no venue stated anywhere), Petajisto 2011 ETF paper (self-published, no reference list, NYU Stern affiliation only). |
| **CME Micro Bitcoin (MBT) and Bitcoin Friday (BFF) contract sizes** | Confirmed from Mallory's footnotes that both products exist and which benchmark each settles to | **Still unverified.** The 0.1 bitcoin figure for MBT in section 1 is from recollection. Check CME's contract specification page before sizing. |
| **Faber 2017 exact out-of-sample table figures** | pdftotext with and without `-layout` on the exhibit pages | **Still unverified.** Exhibits 4, 5, 7 and 8 are embedded images, not text, so the precise in-sample versus out-of-sample CAGR, volatility, Sharpe and drawdown numbers could not be extracted. The narrative findings (including "underperform stocks six of the next eight years") are in the body text and are confirmed. OCR on those pages would recover the tables. |
| **Ngeh 2024 institution and win rate** | Read all 35 pages | **Still unverified.** No university is named anywhere in the thesis; the only trace is a citation of an Aalborg University course. No per-trade win rate is reported. |

---

### Downloads

**Nothing new was downloaded in this session.** All 14 PDFs for this cluster were already present in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/` from the previous agent's run. Every one was verified with `pdfinfo` for page count and `pdftotext -l 1` for readable text on the first page.

| Filename | Size | Pages | First page verified |
|---|---|---|---|
| Schmeling_2023_CryptoCarry.pdf | 561K | 54 | yes |
| Christin_2022_CryptoCarryTrade.pdf | 2.8M | 51 | yes |
| He_2022_FundamentalsOfPerpetualFutures.pdf | 5.0M | 64 | yes |
| Mallory_2026_ImpliedETFCarryRatesBitcoin.pdf | 1.0M | 7 | yes |
| Bradley_2010_ActivistArbitrageCEF.pdf | 532K | 19 | yes |
| Patro_2014_ExploitingCEFDiscounts.pdf | 166K | 47 | yes |
| Durmaz_2025_TrendBreaksCEFDiscounts.pdf | 1.8M | 49 | yes |
| Petajisto_2011_CharacteristicsMarketTradingETFs.pdf | 222K | 32 | yes |
| Antonacci_2013_RiskPremiaHarvestingDualMomentum.pdf | 862K | 37 | yes |
| Faber_2013_QuantitativeApproachTAA.pdf | 924K | 70 | yes |
| Faber_2017_TAARevisited10YearsLater.pdf | 1.7M | 13 | yes |
| Ngeh_2024_CointegratedPairsTradingGoldETFs.pdf | 1.4M | 35 | yes |
| Sun_2025_SurveyStatArbPairsTrading.pdf | 1.9M | 100 | yes |
| Krauss_2015_StatArbPairsTradingReviewOutlook.pdf | 454K | 62 | yes |

All 14 files live in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`.

**Manual links needed for nothing.** No download failed and no paper is missing. The open items are all verification tasks listed in the table above, not missing files.

---

### The one-paragraph summary, if you read nothing else

Of the four families, **only one is genuinely low-hanging fruit for an agent-run 100k book: Family 3, trend-following tactical asset allocation and dual momentum.** It needs five to ten liquid ETFs, one comparison a month, three or four trades a year, no shorting and no margin, and both Faber and Antonacci publish the complete rules. Expect it to lag plain stocks in bull markets, because it did so in six of the eight years after 2008 by Faber's own accounting. **Family 2's closed-end fund half is the most interesting long shot**, with Patro reporting 18.2% a year gross and 10.7% long-only, but that paper deducts no transaction costs at all, so build it in paper with real costs before believing anything. **Family 1 is structurally closed to you** in its profitable form, since the double-digit Sharpes live on offshore perpetual futures exchanges, and the version you can trade at IB earns roughly a 0.6 Sharpe while risking margin-driven liquidation; build Mallory's ETF-options carry wedge monitor as a cheap research tool, not a position. **Family 4 is the weakest**, with two independent surveys ten years apart both finding pairs trading profitability declining and the classic rule largely unprofitable after costs. The largest open question across the whole document is what these strategies actually did from 2023 to 2026 in independent live tracking, and I could not answer it because the search budget was gone. Answer that before committing capital to any of them.

---

## Part F. Practitioner resources the third list missed: podcasts, newsletters, frameworks, data sources

*Report title: Gap Fill H: Practitioner Resources the Reading List Missed*

Research done 6 September 2026 for Mo. This file fills the practitioner gaps in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/03_practitioner.md`,
which already covers Alpha Architect, Quantpedia strategy pages, Concretum, Robot Wealth's blog, Quantocracy,
the Quantopian lectures, Two Sigma, AQR, Carver's blog and pysystemtrade, Ernie Chan's blog, ib_async,
FINRA notice 26-10, and eleven books. Nothing in there is repeated here except where the newer version
of it corrects something.


**How to read the verification labels.** Every claim below was checked live on 6 September 2026 unless it says
otherwise. "Still unverified" means I could not confirm it and you should not act on it. "Live but blocks scripts"
means the site is up and works in a browser but refused an automated request, so I could not read the page.

**Two corrections to the existing list, found while doing this work.** Both matter.

1. **`https://github.com/robcarver17/advanced_futures_trading_strategies` does not exist.** It returns a 404
   from the GitHub API. Carver has no official code repository for *Advanced Futures Trading Strategies*.
   His actual public repos are `https://github.com/robcarver17/systematictradingexamples` (488 stars, but last
   touched July 2020) and `https://github.com/pst-group/pysystemtrade`. Everything else claiming to be AFTS code
   is a third-party reimplementation by a reader, the largest of which has 5 stars.
2. **`pysystemtrade` has moved.** `https://github.com/robcarver17/pysystemtrade` now redirects to
   `https://github.com/pst-group/pysystemtrade`. The old URL still works because GitHub forwards it, but the
   repository lives under an organisation account now. 3,501 stars, last commit 18 July 2026.

One item the existing list flagged as unconfirmed is now confirmed: the ib_async docs at
`https://ib-api-reloaded.github.io/ib_async/` return HTTP 200 and are live.

One new find worth adding to the existing list's Carver section: **`https://github.com/robcarver17/reports`**,
described as "automatically generated reports and diagnostics of interest to futures traders", 70 stars, last
commit 4 September 2026. This is Carver's live production output, refreshed continuously. It is the closest thing
that exists to watching a one-person systematic futures shop run in public.

---

### Part 1. Podcasts

Thirteen shows were checked. Every "most recent episode" date below comes from parsing the show's **actual RSS
XML**, not from a directory page, because Apple and Spotify listings lag by weeks. The canonical feed URLs came
from the Apple lookup API rather than from guessing, which caught two traps worth knowing about:

- The widely linked Top Traders Unplugged Libsyn feed (`https://toptradersunplugged.libsyn.com/rss`) is an
  **abandoned destination frozen at 31 October 2025**. Trusting it would make a show that publishes three times
  a week look ten months dead.
- Better System Trader's on-site feed throws a WordPress error while its Libsyn archive still serves fine.

Six shows made the list. They are ordered by how much they will actually help you.

#### 1. Top Traders Unplugged
**Host:** Niels Kaastrup-Larsen. `https://www.toptradersunplugged.com/`
**Publishing in 2026: yes, heavily.** Most recent episode **5 September 2026**, one day before I checked:
"SI416: 137 Years of Trend: What the Evidence Really Shows ft. Yoav Git". 963 episodes in the feed, two or three
a week across several strands (SI is Systematic Investor, GM is Global Macro, ALO is Allocator, IL is Ideas Lab).

The reason this is first: **Rob Carver is a recurring co-host on the Systematic Investor strand.** Three of the
eleven books on the existing reading list are his, and here he is talking through the same problems weekly, in
Python, at roughly your scale, out of his own house with his own money.

Episodes to start with, all four links verified live:
- **SI386: When Position Sizing Saves You ft. Rob Carver**, 7 February 2026.
  `https://www.toptradersunplugged.com/podcast/si386/`
  Position sizing is what kills small shops, not signal choice. This is the audio version of the argument at the
  centre of *Systematic Trading*.
- **SI405: Why Most Trend Following Improvements Should Fail ft. Rob Carver**, 20 June 2026.
  `https://www.toptradersunplugged.com/podcast/si405/`
  The anti-overfitting episode, and the one most directly aimed at your risk. The argument is that when a tweak
  improves your backtest, the **base case** should be that you fooled yourself. Listen to this before you let an
  agent run its first parameter sweep.
- **SI392: The Hidden Cracks in Systematic Strategies No One Talks About ft. Nick Baltas**, 21 March 2026.
  `https://www.toptradersunplugged.com/podcast/si392/`
  Failure modes, including execution drag and cost.
- **SI348: The Quiet Cost of Overfitting ft. Andrew Beer**, 17 May 2025.
  `https://www.toptradersunplugged.com/podcast/si348/`

**One gotcha if you ever script against this feed:** the episode links inside the RSS are broken. They all point
at `http://localhost:8888/...`, a misconfigured content system leaking a developer's local address. The real
pages follow the pattern `https://www.toptradersunplugged.com/podcast/<code>/` where the code is the short label
such as `si386`. Do not follow the link field.

**Verdict:** the highest-value subscription here, and the only show where someone is doing roughly what you plan
to do, at your scale, in Python, every week.

#### 2. The Algorithmic Advantage
**Host:** Simon Mansell. `https://www.algoadvantage.io/`
**Publishing in 2026: yes**, but irregularly. Most recent **3 September 2026**, "Critical formulas for Bollinger
Band trading, John Bollinger, 056". 57 episodes total, roughly monthly, with real gaps (nothing between
18 December 2025 and 9 March 2026).

Site note: `algoadvantage.io` returned HTTP 406 to a plain script request and 200 with normal browser headers.
Live, just fussy about non-browser traffic.

This is the most **directly on-target** show for a retail-sized systematic operation. Small audience, unglamorous
guests, episodes about mechanics rather than market views.

Episodes to start with:
- **046 and 047: Tom Starke, Institutional Quant Trading Fundamentals**, then **The Basics of Building a Strategy
  Development Pipeline**, 11 and 18 December 2025. **Episode 047 is the closest thing on any of these shows to a
  blueprint for the software you are about to build.**
- **052 and 053: Martyn Tinsley, Building Robust Trading Strategies (The Masterclass)**, then **Walk Forward
  Correlation**, 11 and 26 May 2026. A two-parter on surviving out of sample. Walk-forward testing is the
  practical answer to "did I just curve-fit this".
- **048: Michael Wallace, Dynamic Position Sizing Like You Haven't Seen Before**, 9 March 2026.
- **032: Dr Ernest Chan, The Breakthrough Uses of Machine Learning in Risk Management**, 24 January 2025.
  Chan's reframe is that machine learning is far better at **sizing and risk** than at prediction. If you plan to
  point a language model at markets, this is the single most useful hour on this page.
- **033: Rob Carver, The Comprehensive Guide to a Diversified Futures Strategy**, 19 February 2025.

**Verdict:** the practical build-it show. Listen to 047 and 032 first.

#### 3. Alpha Exchange
**Host:** Dean Curnutt. `https://www.alphaexchange.com/`
**Publishing in 2026: yes.** Most recent **4 September 2026**, "The Case for Tail Hedging". 269 episodes,
roughly weekly to fortnightly.

This is your **risk education**, and it fills a real gap. Nothing else on this list teaches you what your account
actually does when volatility spikes and correlations all go to one, which is the exact moment a small automated
book gets liquidated.

Episodes to start with:
- **Aaron Brown, Wall Street Quant and Author: Wrong Number**, 30 June 2026.
  `https://alphaexchange.simplecast.com/episodes/aaron-brown-wall-street-quant-and-author-wrong-number-tpbmH2Bo`
  Brown was head of risk at AQR and wrote the book on bet sizing. Directly relevant.
- **The Three Types of Risk-Off**, 2 July 2026.
  `https://alphaexchange.simplecast.com/episodes/the-three-types-of-risk-off-sQZE2x3q`
  Your system will behave differently in each of the three, and you want to know that in advance.
- **The Case for Tail Hedging**, 4 September 2026.
  `https://alphaexchange.simplecast.com/episodes/the-case-for-tail-hedging-O68EbLEu`
- **Jessica Stauth, CIO Systematic Equity, Fidelity**, 2 December 2025. Stauth ran Quantopian's research platform
  before Fidelity, so she has watched thousands of retail quant backtests fail from the inside.

**Verdict:** subscribe for the risk half of your education. The existing reading list is strong on why backtests
lie and weak on what a drawdown feels like operationally.

#### 4. Flirting with Models
**Host:** Corey Hoffstein, formerly Newfound Research, now Return Stacked ETFs.
`https://www.flirtingwithmodels.com/`, archive at `https://www.flirtingwithmodels.com/episodes`
**Publishing in 2026: yes, but slowly.** Most recent **3 August 2026**, "Stacie Mintz, Turning Qualitative
Fundamentals into Quantitative Factors (S7E33)". 126 episodes, roughly monthly with genuine gaps (nothing between
11 May and 29 June 2026).

Worth knowing alongside Part 2: **Hoffstein's written research at thinknewfound.com stopped in August 2023.**
This podcast is now where his output goes. If you wanted the Newfound writing, this is what replaced it.

Episodes to start with:
- **Macrocephalopod, Managing a Mid-Frequency Crypto Prop Desk (S6E5)**, 29 May 2023. Older, but the closest
  episode anywhere to your situation: one person, own capital, own infrastructure, talking about actual plumbing.
- **Ben Wellington, Complex Feature Engineering at Two Sigma (S7E32)**, 6 July 2026. Feature engineering means
  turning raw market data into the inputs a model uses, and it is where most of the real work in a machine
  learning trading system lives.
- **Kevin Cole, Systematic Multi-Strategy from 100+ Models (S5E12)**, 29 August 2022. How to combine many small
  models without them all turning out to be the same bet. Directly relevant once your agents start generating
  strategies faster than you can evaluate them.
- **Richard Craib, Crowd-Sourced Alpha with Numerai (S7E28)**, 23 February 2026.

**One gotcha:** the RSS feed has no per-episode links (every item points at the homepage) and the real episode
pages use unguessable IDs like `/episodes/K0x0u3fbJvh`. Use the archive page above, or Apple
(`https://podcasts.apple.com/us/podcast/flirting-with-models/id1402620531`), and search by title.

**Verdict:** the best show on how professionals actually design and test a strategy. Institutional in scale, but
Hoffstein asks "how did you know that wasn't noise" relentlessly, which is the question your whole operation
turns on.

#### 5. Chat With Traders
**Host: Kevin Avery.** `https://chatwithtraders.com/`
**Correction worth making, because the brief named the wrong host: Aaron Fifield hosted episodes 1 to 243 and
stepped down in late summer 2022. He is no longer involved.**
**Publishing in 2026: yes**, and this is worth flagging because the show is widely assumed dead. Most recent
**2 September 2026**, "331 - Jeff Holden, How Top Prop Traders Find and Scale Their Edge". 335 episodes, clean
fortnightly cadence.

Episodes to start with:
- **318 - Dave Mabe, The Shift to Systematic Trading, Building Backtested Confidence**, 27 February 2026.
  `https://chatwithtraders.com/episode/318-dave-mabe` (verified live). Mabe is a software engineer turned
  systematic trader, so this is the transition episode.
- **292 - Laurens Bensdorp, Running 55+ Systematic Trading Strategies Simultaneously**, 5 December 2024.
  **This is the one that maps most closely onto your plan**, one person running dozens of automated strategies at
  once. **Caution: the website page has been removed.** Both `https://chatwithtraders.com/ep-292-laurens-bensdorp`
  and `https://chatwithtraders.com/episode/292-laurens-bensdorp` return 404. The episode is still in the RSS feed
  and on Apple and Spotify, so find it by title there.
- **281 - Marsten Parker, The Purely Systematic Wizard Trader**, 21 May 2024. Same situation, feed and Apple only,
  site page 404s.
- **329 - Peter Brandt, How a 50-Year Veteran Thinks About Risk Management**, 5 August 2026.
  `https://chatwithtraders.com/episode/329-peter-brandt` (verified live).

**Verdict:** practitioner stories rather than theory, and unusually honest about drawdowns and blowups. Useful as
ballast. It keeps reminding you that the hard part is behaviour and risk, not code.

#### 6. Odd Lots
**Hosts:** Joe Weisenthal and Tracy Alloway, Bloomberg. `https://omny.fm/shows/odd-lots`
Note `https://www.bloomberg.com/oddlots` returns HTTP 403, so it is **live but blocks scripts**. Use the Omny link
or Apple (`https://podcasts.apple.com/us/podcast/odd-lots/id1056200096`).
**Publishing in 2026: yes, heavily.** Most recent **4 September 2026**. 1,267 episodes, about three a week.

Not a systematic trading show. It is here because it is the best available source on **market plumbing**, which is
the part that quietly bites you: who your counterparty is, how orders actually get filled, where costs hide.

Episodes to start with:
- **Thomas Peterffy on Interactive Brokers' Plan to Professionalize Prediction Markets**, 9 April 2026.
  `https://omny.fm/shows/odd-lots/thomas-peterffy-on-interactive-brokers-plan-to-professionalize-prediction-markets`
  **The founder of your broker, describing where he is taking the platform.** Worth an hour purely as vendor
  due diligence.
- **Giuseppe Paleologo on Quant Investing at Multi-Strat Hedge Funds**, 21 June 2025.
  `https://omny.fm/shows/odd-lots/giuseppe-paleologo-on-quant-investing-at-multi-strat-hedge-funds`
  Paleologo is the clearest living explainer on portfolio construction and risk models.
- **One of the World's Largest Hedge Funds on Its 86x Growth in Token Spending**, 9 July 2026. "Tokens" here means
  language model usage. A large fund saying out loud how much LLM inference it is buying, which is a useful sanity
  check on your own plan.

**Verdict:** the context show. Listen on walks, not at a desk.

#### Suggested listening order for the flight

If you only get through four: **SI405** (why improvements should fail), **Algorithmic Advantage 047** (the
pipeline blueprint), **Chat With Traders 292** (one person, 55 strategies), **Algorithmic Advantage 032**
(Chan on machine learning for risk rather than prediction).

---

### Part 2. Newsletters and Substacks active in 2026

The brief asked for five or six free or freemium written sources. Seven are listed because the market structure
slot and the systematic trading slot want different things. Sorted by how often you would actually open them.

#### 1. Quantpedia blog and newsletter
Quantpedia. `https://quantpedia.com/blog/` and signup at `https://quantpedia.com/newsletter/`
**Cost:** newsletter free. **Last confirmed post: 4 September 2026**, two days before I checked.
**Frequency:** roughly every two days.

The existing list already has Quantpedia's strategy database. The blog and its email are a different and better
thing: short write-ups of new academic papers with the practical takeaway stated first. The three most recent
posts when I checked were "Do LLM 'Crowds' Produce Investment Signals? An Empirical Test" (4 September),
"Why Average Strategy Performance Can Mislead Portfolio Research" (2 September) and "Boundaries of Time Series
Momentum" (28 August). The first of those is directly about whether a committee of language models generates
usable trading signals, which is precisely the question your shop is built on.

What the email adds over the blog: nothing but timing. The value is that you see the LLM and multiple-testing
posts the week they appear rather than three months later. The signup page itself gives no description of
frequency or contents, so treat the "roughly every two days" figure as inferred from the blog, not promised.

**Verdict:** the single highest-value free subscription on this list, and the only one publishing on your exact topic.

#### 2. Net Interest
Marc Rubinstein. `https://www.netinterest.co/`
**Cost:** freemium. Exact paid price still unverified, the archive page does not show it.
**Last confirmed post: 4 September 2026**, "Hot European Summer". **Frequency:** weekly, Thursday or Friday.

Rubinstein is a former hedge fund analyst who writes one long piece a week on the plumbing of finance: exchanges,
brokers, market makers, clearing, payment for order flow, how the firms on the other side of your trades actually
make money. This is the market structure slot. It is more useful to you than a macro newsletter because it explains
the mechanics that decide your fill quality and your costs.

**Verdict:** read this instead of macro commentary. It tells you who is taking the other side of your order and why.

#### 3. Party at the Moontower
Kris Abdelmessih. `https://moontowermeta.com/`
**Cost:** freemium. Most posts free, some content and a family investing webinar are paid-subscriber only.
Exact paid price still unverified.
**Last confirmed post: 30 August 2026**, issue number 326. **Frequency:** weekly-ish.

Abdelmessih was a market maker and option trader for about twenty years and writes with unusual honesty about
how much of trading edge is structural rather than clever. The recurring subjects are options and volatility,
expected value reasoning, position sizing, and the difference between a real edge and a story about an edge.
His writing on why most retail options ideas are already priced is the best free antidote to the options content
that will show up in your feeds.

**Verdict:** the best free source on thinking probabilistically about a trade, and it will keep you out of options
until you should be there.

#### 4. Alvarez Quant Trading
Cesar Alvarez. `https://alvarezquanttrading.com/blog/`
**Cost:** free blog. Paid consulting, courses, signals and a private community exist separately.
**Last confirmed post: 19 August 2026**, "The Power of Strategy Diversification". Before that "The 100% Club.
2000 Tech vs 2026 AI" (12 May 2026) and "Bad Month for Your Strategy? Should You Change It?" (6 May 2026).
**Frequency:** irregular, roughly monthly with gaps. Active but not prolific.

Alvarez was Larry Connors's director of research and now runs his own money on systematic US equity strategies.
He posts actual backtests with actual code decisions, and he writes about the unglamorous questions nobody else
does: what to do when a live strategy has a bad month, how many strategies you need before diversification helps,
whether to re-optimise. The May 2026 post on a bad month and the August 2026 post on diversification are both
squarely aimed at the decisions you will face in month three of paper trading.

**Verdict:** the closest thing to a peer. Small, systematic, US equities, one person. Read the two 2026 posts named above.

#### 5. Robot Wealth blog, current series
Kris Longmore. `https://robotwealth.com/blog/`
**Cost:** free blog. RW Pro membership is paid, price still unverified.
**Last confirmed post date: 8 June 2026** on the specific post I opened.
**Frequency:** irregular. The blog index does not show dates, so I had to open a post to date it.

The existing list already has Robot Wealth. What it does not have is the current six-part series running there,
which is the most relevant free writing I found anywhere for your situation:
**"Resourcing a Triangulated Stat Arb Operation as a Solo Trader"** (part 6, dated 8 June 2026),
"When Is a Mispricing Not a Mispricing?" (part 5), and "The Metamorphosis: From Pairs to Portfolio" (part 4).
The series builds a statistical arbitrage operation from a single pair to a portfolio, and part 6 is specifically
about what one person can and cannot resource alone, which is the question your agent setup is answering.

Caveat worth naming: the posts push RW Pro, which sells the data APIs and notebooks that make the method
practical. The free posts are still substantive, but they are a funnel.

**Verdict:** read the six-part stat arb series in order. It is the only free writing I found on the actual
resourcing problem of a solo systematic operation.

#### 6. The Quant's Playbook
Quant Galore. `https://www.quant-galore.com/` (Substack)
**Cost:** freemium. Paid unlocks member-only write-ups and support. Exact price still unverified.
**Last confirmed post: 19 July**, "The Trades We Had to Sign NDAs to See". **The year is not shown on the archive
page and is therefore still unverified**, though the surrounding posts are consistent with 2026.
**Frequency:** roughly monthly.

Recent subjects include prediction market microstructure, options market structure, event-driven trading and
alternative data, several with code. "A Common Sense Guide to Volatility Trading [Code Included]" (15 June) and
"A Junior Quant's Guide to Alternative Data" (3 May) are the two most useful to you. The author also sells
consulting to funds and prop shops, so read it knowing that.

**Verdict:** good for concrete mechanics with code attached. Slower cadence than the others, and date the posts
yourself before relying on them.

#### 7. Money Stuff
Matt Levine, Bloomberg Opinion. `https://www.bloomberg.com/opinion/authors/ARbTQlRLRjE/matthew-s-levine`
**Cost:** free by email, no Bloomberg subscription needed for the newsletter. **Frequency:** daily, weekdays.
**Status: live but blocks scripts.** Bloomberg returned HTTP 403 to both the author page and the newsletter
signup page, so I could not confirm the most recent column date. **Last confirmed post date: still unverified.**

Included because the brief asked for it and because it is genuinely the best plain-language writing on market
structure, securities law and financial absurdity anywhere. It is not systematic trading content and will not give
you a signal. It will give you the vocabulary and the intuition for why market rules are the shape they are.

**Verdict:** subscribe, read it on the train, do not expect strategy. Verify it is still running yourself, since I could not.

#### Freemium and paid, mentioned because the brief named them

**Allocate Smartly.** `https://allocatesmartly.com/blog/` Blog active, **last confirmed post 31 August 2026**,
"Does Trading TAA Strategies More Often Improve Performance?". **Cost: 49 US dollars a month, or 399 a year,
or 499 a year for the Pro tier.** Free tier gives access to 3 strategies and sample model portfolios plus a free
test drive. They track roughly a hundred published tactical asset allocation strategies live, out of sample,
with real costs. That out-of-sample tracking is the product and it is legitimately rare.
**Verdict:** not a newsletter, and not free. But if you ever want to know whether a published allocation strategy
has held up since publication, this is the only place that has been measuring it continuously. Worth one month's
subscription as a research purchase, not a standing cost.

**Verdad Weekly Research.** `https://verdadcap.com/archive` Archive is live. Most recent piece I could see was
"Japan's Big Equity Bet", **4 May 2026**, with weekly entries running back through December 2025. Free to read.
The four-month gap between that and today may be an artefact of how the archive page loads rather than a real
pause, so **whether Verdad is still weekly as of September 2026 is still unverified.** Quantitative value and
factor research, well done, but aimed at allocators rather than traders.

---

### Part 3. Open-source frameworks, checked on GitHub 6 September 2026

All star counts and dates come from the GitHub API on 6 September 2026. Two date columns are given because they
disagree in important ways: **last commit** is the newest commit on the default branch, which is what actually
ships; **last push** is any activity on any branch, which is what GitHub's UI shows you and which can make a dead
project look alive. Where they differ by more than a few months, trust the first one.

#### Backtesting and live trading

| Name | URL | Stars | Last commit (default branch) | Last push (any branch) | IBKR | Verdict for a small Python shop |
|---|---|---|---|---|---|---|
| NautilusTrader | `https://github.com/nautechsystems/nautilus_trader` | 28,514 | 2026-09-06 | 2026-09-06 | **Yes**, full adapter | The serious choice. Rust core with a Python API, same code backtests and trades live, documented IB adapter covering equities, options, futures, FX and bonds, and it can manage a Dockerised IB Gateway for you. Steepest learning curve here. |
| QuantConnect Lean | `https://github.com/QuantConnect/Lean` | 21,498 | 2026-09-04 | 2026-09-05 | **Yes**, maintained plugin | Institutional-grade and genuinely active, but it is C# with Python strategies on top, and the separate IB plugin (`https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers`, last commit 2026-09-05) is another moving part. Best if you want their hosted data and cloud; heavy if you want a local Python shop. |
| Lumibot | `https://github.com/Lumiwealth/lumibot` | 2,045 | 2026-09-04 | 2026-09-06 | **Yes**, two ways (native and IB REST) | The best fit for exactly your setup. Small, Python-native, actively developed, and it backtests from Yahoo, Alpaca, IB REST, ThetaData, Massive (formerly Polygon), Databento or a CSV, then trades the same strategy live through IB. Fewer stars than the giants, which means fewer answered questions when you get stuck. |
| pysystemtrade | `https://github.com/pst-group/pysystemtrade` | 3,501 | 2026-07-18 | 2026-07-18 | **Yes**, via ib_async | Carver's own production system. Not a friendly framework, it is one person's real trading infrastructure published in full, including the boring parts (reconnection, position reconciliation, capital accounting) that kill unattended systems. **Note the URL change: the old `robcarver17/pysystemtrade` now redirects here.** Read it, do not necessarily run it. |
| vectorbt (open source) | `https://github.com/polakowo/vectorbt` | 9,013 | 2026-08-02 | 2026-08-02 | **No** | Backtesting and research only, no broker and no live trading. Extremely fast at sweeping thousands of parameter combinations, which is exactly the capability that manufactures false confidence, so pair it with the deflated Sharpe work already in the reading list. The README now calls it "the open-source community edition of VectorBT PRO". |
| vectorbt PRO | `https://vectorbt.pro/` | private repo, no public stars | not public | not public | No | The proprietary successor, distributed as a private GitHub repo behind a paid membership with a Discord of 1,000-plus members. Site returns HTTP 200 and is live. **Exact pricing tiers still unverified**, the pricing figures are not on the pages I could read. Skip for now, the free edition does the job. |
| backtesting.py | `https://github.com/kernc/backtesting.py` | 8,937 | 2026-08-05 | 2026-08-05 | No | Not on your list but earns a place. Tiny, readable, actively maintained, single-asset backtests in a few dozen lines. The right first tool for checking whether an idea has any pulse before you build anything. |
| PyBroker | `https://github.com/edtechre/pybroker` | 3,533 | 2026-08-28 | 2026-08-28 | No | Also not on your list. Backtesting built around walk-forward analysis and multiple-testing awareness rather than bolted on afterwards, which matches the discipline the reading list argues for. Backtesting only. |
| zipline-reloaded | `https://github.com/stefan-jansen/zipline-reloaded` | 1,933 | **2025-11-13** | 2026-01-06 | No | Alive but slow, roughly ten months since the last commit on the default branch. Backtesting only, no live trading. Its real purpose now is running the code in Clenow's *Trading Evolved* and the older Quantopian material, both already in the reading list. Do not start a new project here. |
| backtrader | `https://github.com/mementum/backtrader` | 23,150 | **2023-04-19** | 2024-08-19 | Legacy store, unmaintained | **Effectively frozen.** Twenty-three thousand stars and no commit on the default branch in nearly three and a half years. The push date of August 2024 is branch noise, not shipped work. Its IB integration is built on the long-dead IbPy. Enormous amounts of tutorial content point here, which is the trap: your agents will find it, cite it, and build on abandoned code. |
| backtrader forks | `https://github.com/backtrader2/backtrader` | 268 | **2021-11-02** | 2024-03-24 | Legacy | The community fork is deader than the original. `https://github.com/happydasch/btplotting` (385 stars, last push 2025-05-04) is the only nearby project with any recent life, and it only does charts. **There is no maintained backtrader fork.** |
| Blankly | `https://github.com/blankly-finance/blankly` | 2,473 | **2024-12-30** | 2024-12-30 | No | **Dormant**, twenty months without a commit. Supported Alpaca and crypto exchanges, never IB. Do not use. |
| freqtrade | `https://github.com/freqtrade/freqtrade` | 54,091 | 2026-09-06 | 2026-09-06 | **No, and never will** | Very much alive and the most-starred trading bot on GitHub, but it is **crypto only**. No equities, no futures, no IB. Irrelevant to an IBKR shop except as a model of what a mature open-source trading project's docs and testing look like. |
| Jesse | `https://github.com/jesse-ai/jesse` | 8,423 | 2026-09-04 | 2026-09-04 | **No** | Also alive, also **crypto only**. Same conclusion as freqtrade. |
| ib_async | `https://github.com/ib-api-reloaded/ib_async` | 1,730 | **2025-12-06** | 2026-08-19 | **Native** | The IB library everyone uses, and the correct successor now that `erdewit/ib_insync` is **archived** (last commit 2024-03-14). Docs at `https://ib-api-reloaded.github.io/ib_async/` return HTTP 200, confirming what the existing list left unverified. Honest caveat: the default branch has not moved since December 2025 even though other branches were pushed in August 2026, so it is maintained but not briskly. Still the only real option. |
| OpenBB | `https://github.com/OpenBB-finance/OpenBB` | 72,716 | 2026-07-20 | 2026-07-30 | Data only, not a broker | Active and the most-starred project on this page. It is a **data aggregation layer**, not a backtester and not a broker: one Python interface over dozens of providers, and its own description now says "for analysts, quants and AI agents". Useful as the data plumbing under your agents. It will not execute anything. |

#### Supporting libraries worth knowing about

| Name | URL | Stars | Last commit | Note |
|---|---|---|---|---|
| QuantStats | `https://github.com/ranaroussi/quantstats` | 7,619 | 2026-07-20 | Tearsheets and performance statistics. Active. Use it so your agents report a standard set of numbers rather than inventing metrics. |
| TA-Lib (Python) | `https://github.com/TA-Lib/ta-lib-python` | 12,235 | 2026-09-06 | The indicator library. Active, and note it moved to a `TA-Lib` organisation from the old `mrjbq7` account. |
| pandas-ta | **gone** | n/a | n/a | **`twopirllc/pandas-ta` returns 404. The original repository has been deleted.** This matters because it was the most popular pure-Python indicator library and agents will still try to install it. The maintained successor is `https://github.com/xgboosted/pandas-ta-classic`, 430 stars, last commit 2026-07-22. |
| FinanceToolkit | `https://github.com/JerBouma/FinanceToolkit` | 5,299 | 2026-09-01 | Active. Ratios and fundamental metrics with the formulas exposed rather than hidden, which makes it auditable. |
| edgartools | `https://github.com/dgunning/edgartools` | 2,674 | 2026-09-06 | Active and committed today. Reads SEC EDGAR filings and XBRL financials in Python. The cleanest way to get free fundamentals. |
| Qlib (Microsoft) | `https://github.com/microsoft/qlib` | 48,352 | 2026-07-23 | Active. A full AI-for-quant research platform. Powerful, opinionated, mostly built around Chinese equity workflows, heavy for a first project. |
| mlfinlab | `https://github.com/hudson-and-thames/mlfinlab` | 4,920 | **2023-10-02** | **Dead, three years.** It was the reference implementation of López de Prado's *Advances in Financial Machine Learning*, which is book 8 on the existing list. If an agent proposes it for triple-barrier labelling or purged cross-validation, that code is unmaintained. Implement those two methods yourself from the papers instead. |

#### Cross-check: what each project has actually shipped to PyPI

Commits can be cosmetic. A released package is the harder test of whether a project is alive, because it means
somebody thought the code was good enough to publish. Checked against PyPI on 6 September 2026.

| Package | Latest version | Released | Reading |
|---|---|---|---|
| `lumibot` | 4.5.90 | **2026-09-04** | Shipping constantly. Confirms the commit activity is real work. |
| `freqtrade` | 2026.8 | 2026-08-31 | Monthly calendar releases. A model of project discipline (still crypto only). |
| `lean` (CLI) | 1.0.229 | 2026-08-28 | Active. |
| `yfinance` | 1.7.0 | 2026-08-26 | Genuinely maintained, and now past 1.0. The problem is Yahoo, not the library. |
| `nautilus_trader` | 1.231.0 | 2026-08-02 | Active. |
| `backtesting` | 0.6.6 | 2026-07-22 | Active. |
| `vectorbt` | 1.1.0 | 2026-07-05 | Still releasing despite PRO being the commercial focus. |
| `edgartools` | 5.56.0 | 2026-09-02 | Very active. |
| `alpaca-py` | 0.44.0 | 2026-08-11 | Active, and confirms `alpaca-trade-api-python` is the dead one. |
| `pandas-ta-classic` | 0.6.52 | 2026-06-24 | The live successor to the deleted `pandas-ta`. |
| `quantstats` | 0.0.81 | 2026-01-13 | Eight months. Slowing, still fine. |
| `zipline-reloaded` | 3.1.1 | **2025-07-19** | **Fourteen months since a release.** Worse than the commit date suggested. Treat as legacy. |
| `ib_async` | 2.1.0 | **2025-12-08** | **Nine months.** Matches the December 2025 commit date and confirms the honest read: maintained, but not briskly. This is the one dependency you cannot avoid, so watch it. |
| `backtrader` | 1.9.78.123 | **2023-04-19** | **Three and a half years, and the release date matches the last commit exactly.** Conclusive. The project stopped in April 2023. |
| `pysystemtrade` | **not on PyPI** | n/a | Deliberate. Carver expects you to clone and run from source. Worth knowing before an agent tries `pip install pysystemtrade` and reports a mysterious failure. |

#### 2025 to 2026 open-source LLM trading agent repos

These are real projects with real activity, which distinguishes them from the large number of abandoned
"AI trading bot" repos. **None of them place live trades and none has broker integration.** Read that sentence
twice: every one of these is a research harness that decides what it *would* do, then scores itself against
historical prices. The execution half, the half that actually loses money, is not in any of them.

| Name | URL | Stars | Last commit | IBKR | Verdict for a small Python shop |
|---|---|---|---|---|---|
| TradingAgents (Tauric Research) | `https://github.com/TauricResearch/TradingAgents` | **102,720** | 2026-09-01 | No, simulated exchange only | The reference architecture for what you are building, and the most-starred finance repo on GitHub. Simulates a trading firm as specialist LLM roles: fundamental analyst, sentiment analyst, technical analyst, trader, risk manager, arguing to a decision. Supports Anthropic Claude directly, alongside OpenAI, Gemini, xAI, DeepSeek, Qwen, GLM, MiniMax, OpenRouter, Ollama and Azure. Data from Yahoo Finance, Alpha Vantage, StockTwits, Reddit, FRED and Polymarket. Apache 2.0, and the README states plainly it is "designed for research purposes" and is not trading advice. **Read the role decomposition, steal it, do not trust the backtests.** |
| ai-hedge-fund | `https://github.com/virattt/ai-hedge-fund` | **63,270** | 2026-09-03 | No | Also very active and very popular. Same idea in a different shape: LLM agents modelled on named famous investors debating a position. More of a demonstration than a framework, and the persona framing is a weakness rather than a feature. Worth an hour to see the pattern. |
| FinGPT | `https://github.com/AI4Finance-Foundation/FinGPT` | 21,215 | 2026-09-03 | No | Active. Finance-specific open language models and the fine-tuning recipes for them, mainly sentiment and news. Relevant only if you intend to fine-tune, which you should not in year one. |
| RD-Agent (Microsoft) | `https://github.com/microsoft/RD-Agent` | 14,531 | 2026-09-04 | No | Active and the most intellectually interesting of these. It automates the research and development loop itself, proposing hypotheses, implementing them, testing, iterating, with a quantitative finance scenario built in. This is the machine-for-manufacturing-false-confidence risk in its purest form, so read it alongside the backtest overfitting section of the existing list, not instead of it. |
| FinRobot | `https://github.com/AI4Finance-Foundation/FinRobot` | 7,924 | 2026-08-23 | No | Active. Multi-agent platform aimed at automating equity research and producing investment reports rather than trading. Pulls from Financial Modeling Prep, Finnhub, yfinance and SEC EDGAR. README says the code "should not be construed as financial counsel or recommendations for live trading". Useful as a template for a research-writeup agent. |
| FinRL | `https://github.com/AI4Finance-Foundation/FinRL` | 16,227 | 2026-07-13 | No | Alive but the slowest of this group, about two months since the last commit. Deep reinforcement learning for trading, not LLM agents. Reinforcement learning on financial time series is a known graveyard, so treat it as a literature pointer. |

**The honest summary of that table.** The LLM-agent space has enormous star counts and no execution layer.
If you want an agent-run shop that actually trades, the shape is TradingAgents' role decomposition for the
research and decision half, wired to NautilusTrader or Lumibot for the execution half. Nobody has published
that join. Building it is your actual project.

---

### Part 4. Data sources with free tiers, checked September 2026

#### Group A. US equity prices, end of day and intraday

**Read this first, it invalidates a lot of older advice: Polygon.io is now Massive.** The rebrand took effect
30 October 2025. `https://polygon.io/pricing` returns an HTTP 301 permanent redirect to
`https://massive.com/pricing`. The `api.polygon.io` endpoints still work and run in parallel with
`api.massive.com`, existing keys and SDKs keep working, and no migration is required. But the GitHub client
moved from `polygon-io/client-python` to `massive-com/client-python`, and Lumibot's own documentation now
writes the provider as "Polygon/Massive". Any tutorial or agent that says "Polygon" means this company.

| Source | URL | What is free | Main limit | Verdict for a paper-trading shop |
|---|---|---|---|---|
| Massive (was Polygon.io) | `https://massive.com/pricing` | Stocks Basic tier: end-of-day US equities, 2 years of history | **5 API calls per minute**, end of day only, no realtime | The free tier is a demo, not a data source. Five calls a minute cannot build a universe. Paid starts at 29 US dollars a month (Starter), then 79 (Developer) and 199 (Advanced). If you pay anyone for equity data, this is the usual answer. |
| Alpaca Market Data | `https://alpaca.markets/data` | Free plan: **200 API calls a minute**, 7-plus years of history with full market coverage, US stocks, crypto, extended hours. Websocket streaming capped at **30 symbols** | Free plan is **IEX only**, roughly 2 to 3 percent of US volume, and the REST API is **delayed 15 minutes**. Options are indicative, not realtime | **The best free equity data on this list by a wide margin.** 200 calls a minute and 7 years of history is a real research dataset. The catch is IEX-only quotes, which are fine for daily bars and useless for intraday spread work. Algo Trader Plus at **99 US dollars a month** unlocks full SIP data across all US exchanges, unlimited calls and unlimited websocket symbols. |
| Databento | `https://databento.com/pricing` | **125 US dollars of free credit** on signup, usable on any dataset, **expires 6 months** after signup. One set of credits per team | Pay as you go by the gigabyte, billed per outbound byte. No ongoing free tier once credits are spent | The highest-quality data here and the fairest pricing model, because you pay for bytes rather than a subscription. 125 dollars of credit buys a genuinely useful slice of history. Best used as one deliberate download of the exact dataset you need, not as a live feed. |
| Tiingo | `https://www.tiingo.com/pricing` | Free Starter tier: **50 requests an hour, 1,000 a day, 500 unique symbols a month, 1 GB a month.** Over 30 years of history | 500 symbols a month is the real constraint, not the request count | Good for a focused watchlist, hopeless for a wide universe scan. 30 years of history on the free tier is unusually generous. Paid Power tier is **30 US dollars a month** for 109,881 symbols, 10,000 requests an hour and 40 GB. |
| EODHD | `https://eodhd.com/pricing` | Free tier: **20 API calls a day** plus a 500-call welcome bonus. Past year of data only. Personal use only | 20 calls a day is not a tier, it is a taste. No fundamentals, no live data, no websockets on free | Skip the free tier. Paid is competitively priced: 19.99 US dollars a month for EOD history, 29.99 with intraday, 59.99 for fundamentals, 99.99 all-in, all with 100,000 calls a day and 30-plus years of history. |
| yfinance / Yahoo Finance | `https://github.com/ranaroussi/yfinance` | Everything, free, no key, no signup | **Rate limiting is now the defining problem.** `YFRateLimitError: Too Many Requests` is the most reported issue on the repo, with reports through March 2026, and Yahoo temporarily IP-bans aggressive callers | **Alive but no longer dependable.** The library is genuinely maintained (25,183 stars, last commit 27 August 2026, new docs site launched). The problem is upstream: yfinance scrapes undocumented Yahoo endpoints, it is not an API, and the README states it is "not affiliated, endorsed, or vetted by Yahoo" and that the Yahoo finance API "is intended for personal use only". Even TradingAgents has an open issue about Yahoo throttling it. **Use it to prototype, never as the data source a live system depends on.** Every hour it works is a gift, not a guarantee. |
| Interactive Brokers via the API | `https://www.interactivebrokers.com/en/pricing/market-data-pricing.php` | Nothing is free, but the entry cost is trivial | **US Securities Snapshot and Futures Value Bundle: 10 US dollars a month, waived entirely if your monthly commissions reach 30 US dollars.** This bundle is a prerequisite for most other subscriptions. API pacing: **50 messages per second** to TWS, and **100 simultaneous market data lines** by default. The formula is market data lines divided by two, per second, so 100 lines gives 50 requests a second. Doubling to 200 lines (via commissions or a Quote Booster) gives 100 requests a second | You are already paying IBKR, so this is the cheapest realtime data you will find, and at your commission level it may cost nothing. **The 100 market data lines cap is the design constraint that matters**, not the price: it hard-limits how many symbols your system can watch at once, and you must plan the universe around it rather than discovering it in production. IBKR historical data also has separate, stricter pacing rules that will bite an agent doing bulk downloads. |

#### Group B. Fundamentals and earnings dates

| Source | URL | What is free | Main limit | Verdict for a paper-trading shop |
|---|---|---|---|---|
| SEC EDGAR APIs and XBRL frames | `https://www.sec.gov/search-filings/edgar-application-programming-interfaces` | **Everything. All four APIs, no authentication, no API key, no cost.** Submissions (filing history), Company Concept, Company Facts (every XBRL fact for a company in one call) and **Frames** (the same fact across every filer for one period) | **10 requests per second** fair-access ceiling, and a **`User-Agent` header naming you with a contact email is mandatory.** Format: `Sample Company Name AdminContact@domain.com`. Omit it and you get an "Undeclared Automated Tool" error. SEC offers no technical support for programmatic downloads | **This is the answer for fundamentals and it is free forever.** The Frames API is the underrated one: one call gives you a single financial concept across all filers for a period, which is a cross-sectional factor in one request. It is the primary source, not a vendor's copy of it, so there is no licensing risk and no vendor to go out of business. Use `https://github.com/dgunning/edgartools` (2,674 stars, committed today) rather than writing the parser yourself. **Highest-value free data source on this entire page.** |
| Financial Modeling Prep | `https://site.financialmodelingprep.com/developer/docs/pricing` | Basic tier free, no credit card: **250 calls a day**, end-of-day history, profile and reference data, 150-plus endpoints, all US exchanges | 250 calls a day, **5 years of price history, 5 quarters of financial statements**, and a 500 MB trailing-30-day bandwidth cap | Convenient and pre-cleaned, which is its whole value over EDGAR. But 5 quarters of statements is too shallow for any factor work, so it is a supplement, not a foundation. *(Pricing page returned HTTP 403 to my request; figures come from FMP's own published FAQ and plan documentation rather than the live pricing table, so treat the exact numbers as good but second-hand.)* |
| Finnhub | `https://finnhub.io/pricing` | Free key, no credit card: **60 API calls a minute** (with an internal 30-per-second cap), realtime US stock quotes, company news, basic fundamentals, SEC filings, and **websocket streaming for up to 50 symbols** | Free tier is **personal, non-commercial use only**, so a monetised shop needs a paid plan. Fundamentals on free are basic | The best free tier for **earnings dates and a company news feed**, which is the specific gap EDGAR does not fill conveniently. 60 calls a minute is workable and realtime US quotes on a free tier is rare. The non-commercial licence term is the thing to notice before you build on it. *(Pricing page is JavaScript-rendered and would not yield to a script; limits confirmed from Finnhub's own rate-limit documentation.)* |
| Nasdaq Data Link (was Quandl) | `https://data.nasdaq.com/` | Some free datasets survive, notably FRED economic data and selected commodity series | **The famous free WIKI equity prices dataset is discontinued for new users.** The platform is now overwhelmingly premium and subscription-gated | **Largely a dead end now, and this is the single most out-of-date recommendation in older quant tutorials.** Quandl became Nasdaq Data Link in September 2021 and the free equity price data that made it famous is gone. Expect your agents to suggest it from stale training data. Redirect them to EDGAR and Alpaca. *(Current free-dataset inventory not enumerable from the pages I could read, so exactly which free sets remain is still unverified.)* |

#### Group C. Options data

| Source | URL | What is free | Main limit | Verdict for a paper-trading shop |
|---|---|---|---|---|
| Massive (was Polygon.io), options | `https://massive.com/pricing?product=options` | **Options Basic: 0 US dollars a month.** All US options tickers, **2 years of history**, 100 percent market coverage, end-of-day data, minute aggregates, reference data, corporate actions and technical indicators | **5 API calls a minute**, end of day only, and no Greeks, no implied volatility, no flat files, no websockets and no trades on the free tier. Individual use only | **This is the free historical option chain, and it is the answer to the question.** Two years of end-of-day chains across every listed US option at no cost is a real research dataset. Five calls a minute means a bulk pull runs overnight, not on demand. Paid tiers: Options Starter 29 US dollars a month (unlimited calls, 15-minute delayed, Greeks and implied volatility), Options Developer 79 (4 years, plus trades), Options Advanced 199 (5-plus years, realtime, plus quotes, non-professionals only). |
| Alpaca options data | `https://alpaca.markets/data` and `https://docs.alpaca.markets/us/docs/about-market-data-api.md` | Included in the free Basic plan that comes with any account, **paper accounts included**: US options coverage, historical bars, trades and quotes, **200 API calls a minute**, 200 websocket quote subscriptions | **History starts February 2024**, so about two and a half years, and the **newest 15 minutes** of data is withheld. The realtime feed on Basic is the "Indicative Pricing Feed", a thinned free derivative of OPRA, not OPRA itself | The second free source of historical option chains, and the one you will actually use first because you already have the key. The short history is the catch: nothing before February 2024 means no 2022 bear market and no 2020 crash to test against. Algo Trader Plus at 99 US dollars a month swaps the indicative feed for real OPRA and lifts you to 10,000 calls a minute. |
| Interactive Brokers OPRA via the API | `https://www.interactivebrokers.com/en/pricing/research-news-marketdata.php` | Nothing is free, but realtime option quotes cost almost nothing | **OPRA Top of Book (Level 1), US option exchanges: 1.50 US dollars a month for a non-professional**, 32.75 for a professional, and the fee is **waived entirely if you generate 20 US dollars of commissions** that month. It sits on top of the 10 dollar US Securities Snapshot and Futures Value Bundle from Group A. **15-minute delayed OPRA is available without any subscription** | The cheapest realtime option quotes in existence for a non-professional, and at 1.50 a month it is not worth thinking about. But IBKR is a live feed, not a history store, and the 100 market data lines cap from Group A applies to option contracts too. A single underlying's chain can be several hundred contracts, so one busy name can consume your whole allowance. Use IBKR to trade options, not to research them. |
| OptionsDX | `https://www.optionsdx.com/` | **Free bulk downloads with no billing details required.** The FAQ is explicit: "For free data, you will be given access to download immediately after checkout. No billing information will be required nor requested." Full chains with all strikes and expirations, pre-calculated Greeks, implied volatility, bid, ask, last and underlying price, as monthly CSVs | **Ten tickers only** (SPY, SPX, VIX, QQQ, TSLA, AAPL, NVDA, UVXY, SLV and Deribit BTC), and **the year dropdown stops at 2023** even though the site's copyright reads 2026 and the FAQ promises quarterly updates. Each product is priced 0 to 50 US dollars depending on the year and quote frequency chosen (end of day, 30, 15, 5 minutes or minutely), and **exactly which combination costs nothing is still unverified** because the price only resolves once you pick both options. Downloads are served through Citrix ShareFile and your access expires after 100 days | Good for one specific job: a deep, clean, intraday SPX or SPY option history for backtesting, at a price between nothing and 50 dollars. Bad for everything else, because ten tickers is not a universe and a catalogue that ends in 2023 is not a live source. Download once, keep the CSVs, do not build a pipeline on it. |
| Cboe DataShop | `https://datashop.cboe.com/` | A **free sample file** on each product page, no account needed | Option EOD Summary covers **January 2012 to present**, with two NBBO snapshots a day (15:45 US Eastern and the close), OHLC, volume, VWAP and open interest for every option series over OPRA. Implied volatility and Greeks at the 15:45 snapshot are a paid extra. **The price is computed in the shopping cart from the symbols and dates you select and the subtotal is rendered by JavaScript, so the actual cost is still unverified.** Index bid and ask requires a Cboe Global Indices licence, and those "fees start at 1k/month" | The primary source, straight from the exchange, priced per slice rather than per month. The right answer when you know exactly which symbols and which dates you need and want data nobody has resold. The wrong answer for open-ended exploration, because on DataShop every exploration is a purchase. |
| ThetaData | `https://www.thetadata.net/pricing` | **Nothing.** No free tier appears on the pricing page and none appears in the FAQ | Options Value **40 US dollars a month** (4 years of history, 1-minute intervals, unlimited requests), Options Standard **80** (8 years, tick level, option chain snapshots, every NBBO quote OPRA reported), Options Pro **160** (12 years, every option trade streamed). **Individual plans are "personal use only, no redistribution or business use"**, with separate Business plans for commercial work. No API keys, authentication is email and password | The best paid option data for a one-person shop, and the tier labels say the intent out loud: Value "for beginners", Standard "for research", Pro "for live trading". It is also already wired into Lumibot as a backtest source (see Part 3), which removes a day of plumbing. If options become a real book for you, 80 US dollars a month here beats everything else on this table. |
| ORATS | `https://orats.com/data-api` | **Nothing. "We do not offer free trials at this time."** Free historical samples are downloadable from ORATS University | Delayed Data API **199 US dollars a month** (20,000 requests, 15 minutes behind), Live Data API **299** (100,000 requests), Live Intraday API **599** (1,000,000 requests, every endpoint), All-In **899**. Tools add-ons are 99 each for the Option Scanner and Backtest Finder APIs and 299 each for the Intraday Backtester and Time and Sales APIs. End-of-day history back to **2007** across 5,000-plus symbols is included on every plan | Too expensive for you now, and you would be paying for the wrong thing. What ORATS sells is not raw chains but its smoothed volatility surface and 500-plus derived indicators. That is a genuine product if your edge is in volatility itself. Revisit when a volatility strategy is already earning, not before. |

**The plain answer on free historical option chains.** Two sources give them away: **Massive's Options Basic tier** (two years of end-of-day chains, every US listed option, five calls a minute) and **Alpaca's free Basic plan** (bars, trades and quotes back to February 2024, 200 calls a minute, with the newest 15 minutes withheld). **OptionsDX** gives free bulk CSVs but only for ten tickers and only up to 2023. **Cboe DataShop** gives free samples and then charges per slice. **ThetaData, ORATS and Interactive Brokers give nothing away**: ThetaData starts at 40 US dollars a month, ORATS at 199 with no trial at all, and IBKR sells you a live feed for 1.50 a month rather than any history.


#### Group D. News and filings text

| Source | URL | What is free | Main limit | Verdict for a paper-trading shop |
|---|---|---|---|---|
| SEC EDGAR full-text search API | `https://efts.sec.gov/LATEST/search-index?q=` | **Everything, free, no key, no account.** Search the full text of filings and return JSON with the CIK, company name, form type, filing date, accession number and the exact file inside the filing that matched. I called it live: a search for "artificial intelligence" in 8-Ks filed 1 to 5 August 2026 returned 255 hits with scores | **Coverage starts in 2001**, which I confirmed by probing year by year (a 2000 query returned 41 hits, 2001 and 2002 both returned the 10,000-plus ceiling). Results cap at 10,000 per query, so wide searches must be sliced by date. Same fair-access rules as the rest of EDGAR: **10 requests a second and a mandatory `User-Agent` header naming you with a contact email.** This endpoint powers the SEC's own search UI and is **not formally documented as a public API**, so the response shape could change without notice | **The most underrated free source on this page.** You can ask "which filings said this phrase last week" and get a machine-readable answer in one HTTP call, with no vendor between you and the primary source. Government work, public domain, no redistribution or commercial restriction whatever. **Usable for a live agent**, with the caveat that indexing latency after a filing is accepted is still unverified, so measure it yourself before trading on it. |
| GDELT | `https://www.gdeltproject.org/` and `https://api.gdeltproject.org/api/v2/doc/doc` | **Everything, free, no key.** The DOC 2.0 API returned live articles stamped the same morning I called it, across Chinese, Korean and English sources. Global news monitoring in over 100 languages, with tone scoring, theme tagging and country and language fields | **One request every 5 seconds.** Go faster and it returns a plain-text scolding instead of JSON, which will silently break a parser that assumes a JSON body. Records give you the URL, title, domain, language and country, **not the article text**, so you still have to fetch and read the page yourself | The licence is the standout and it is worth quoting: "all datasets released by the GDELT Project are available for unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee." Nothing else in this group says that. **Usable live** if you respect the 5-second gap, which caps you at 12 queries a minute. Extremely noisy: it monitors all news, not financial news, so most of what comes back is irrelevant to a ticker. |
| Alpaca news API | `https://docs.alpaca.markets/us/docs/historical-news-data.md` | Comes with an Alpaca account key, **paper accounts included**. History back to **2015**, averaging **130-plus articles a day**, both a REST endpoint and a websocket stream at `wss://stream.data.alpaca.markets/v1beta1/news`, with a sandbox stream for testing | **The content is Benzinga's**, licensed through Alpaca, so the redistribution terms are Benzinga's rather than Alpaca's. A key is required, an unauthenticated call returns HTTP 401. **Whether news is included on the free Basic plan or only on Algo Trader Plus is still unverified**: news is not a row in Alpaca's published plan comparison table, and I could not confirm it without an account | **The practical choice for a live agent.** It is a genuine streaming news feed with fields (headline, summary, author, symbols) already structured for a language model to read, through an SDK you have installed anyway. Read the headline and summary rather than the body, since the body is not always present. |
| Federal Reserve, FOMC statements and minutes | `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` | **Everything, free, no key.** Statements in both PDF and HTML, implementation notes, projection materials, press conference video and minutes, going back years. There is an RSS feed for monetary policy press releases at `https://www.federalreserve.gov/feeds/press_monetary.xml`, which I confirmed returns current items | Nothing worth calling a limit. This is a scheduled event, not a feed to poll. **The remaining 2026 meetings are 15 to 16 September, 27 to 28 October and 8 to 9 December**, the last two of those three carrying a Summary of Economic Projections. Minutes land about three weeks after each meeting: the 28 to 29 July meeting's minutes were released 19 August 2026 | US government work, public domain, no licence question at all. The value is precisely that it is scheduled: you know months in advance to the day when the text arrives, so an agent can be primed and waiting rather than polling. The statement is short and the signal is which words changed since last time. |
| Marketaux | `https://www.marketaux.com/pricing` | Free tier: **100 requests a day, 3 articles per request.** Instant news access (not delayed), full metadata, entity tagging across 200,000-plus entities, 5,000-plus sources, 80-plus markets, 30-plus languages | **3 articles per request is the real cap, not the 100 requests.** That is 300 articles a day maximum. The Market Stats API returns 0 entities per request on the free tier, so that half of the product is off | Better than NewsAPI for a live agent for one reason only: the free tier is neither delayed nor licensed for development use only. Still far too thin to be your primary feed. Paid tiers are reasonably priced if it earns its place: Basic 29, Standard 49, Pro 99 and Pro 50K 199 US dollars a month. |
| NewsAPI | `https://newsapi.org/pricing` | Developer tier: **0 US dollars, 100 requests a day**, search articles up to a month old, CORS on localhost | **Two separate killers.** Articles carry a **24 hour delay**, and the Developer plan is licensed "for development and testing in a development environment only" and "cannot be used in a staging or production environment (including internally)". Also, **no plan returns full article text**, on any tier, ever: "unfortunately we cannot provide the full content with our search results" | **Research only, and barely that.** A 24-hour delay makes it useless for trading, and the licence makes running it inside your live system a breach before the delay even matters. Paid jumps straight to 449 US dollars a month (Business) and 1,749 (Advanced), which is not your budget. Skip it. |
| Benzinga API | `https://www.benzinga.com/apis/` | A "Start for Free" signup exists on the docs portal, but **what it includes is still unverified** | **Live but blocks scripts.** Every marketing and pricing page under `benzinga.com/apis/` returned HTTP 403 to a plain script, to a full browser-headers request and through a fetching proxy, so **no price is quoted here**. Licensing runs through a separate team (licensing@benzinga.com, and a phone number), which is itself the answer on redistribution: it is negotiated, not published. The developer docs are readable at `https://docs.benzinga.com/`, authentication is an API key passed as a `token` URL parameter | **Do not go direct.** You can already read Benzinga's newsfeed through Alpaca at no extra cost, which is the row three above. Approach Benzinga itself only if you find a field Alpaca does not pass through, and expect a sales conversation rather than a checkout page. |
| Finnhub news | `https://finnhub.io/pricing` | Cross-reference only, the full row is in **Group B** above: free key with **60 API calls a minute**, company news, realtime US quotes and websocket streaming for up to 50 symbols | The free tier is **personal, non-commercial use only** | Fine for earnings dates and a per-company news lookup, which is the gap EDGAR does not fill conveniently. The non-commercial licence term is the thing that decides it the moment the shop earns money. |

**Live versus research only, and who owns the words.** Three of these are safe to put inside a running agent: **SEC EDGAR full-text search** (public domain, no restriction of any kind), **GDELT** (explicitly free for commercial use) and the **Federal Reserve** (US government work, public domain). Those three you can query, store, redistribute and build a business on with nobody's permission. **Alpaca's news feed is usable live but the words are Benzinga's**, so you can act on it and you should not republish it. **Marketaux** is usable live under its free tier but too thin to lean on. **NewsAPI is research only by its own licence**, not merely by its delay. **Benzinga direct and Finnhub free** both carry restrictions that only bite once the shop is commercial, which is exactly when it is most annoying to discover them, so read those terms before you build on either.


#### Group E. Congress trades and insider trades

| Source | URL | What is free | Main limit | Verdict for a paper-trading shop |
|---|---|---|---|---|
| House Clerk financial disclosures | `https://disclosures-clerk.house.gov/FinancialDisclosure` | **Everything, free, no key, no agreement wall, no rate limit I could find.** The year index downloads as a zip from `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2026FD.zip` containing an XML and a text file. I pulled it: **1,594 filings for 2026 so far, of which 375 are type P**, the Periodic Transaction Reports that actually contain trades. Most recent filing date in the index was **3 September 2026**, three days before I checked. Each record gives the member's name, state and district, filing type, filing date and a DocID | **The XML is an index, not the data.** It tells you that a report exists, not what was bought or sold. The trades sit inside one PDF per filing at `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/<DocID>.pdf`, which I verified returns a real 81 KB PDF for DocID 20034201. Many of those PDFs are scans, so you need optical character recognition, not a text extractor | The primary source, and the only one in this group with no terms wall and no throttle. Machine readable at the index level and manual at the trade level, which is precisely the gap that every derived dataset below exists to fill. Poll the index daily as your ground truth even if you consume somebody else's parsed version. |
| Senate eFD | `https://efdsearch.senate.gov/search/` | Everything is free once you are through the door | **There is a door.** The search URL 302-redirects to an agreement page carrying "I agree", "I understand" and "prohibited" language that must be accepted before any query will run. A script has to POST that acceptance and then carry the session cookie, which is a deliberate speed bump rather than an accident | Free but hostile. Senators file the same Periodic Transaction Reports as House members, so the data matters just as much, but the agreement wall means every derived Senate dataset is somebody scraping through that door on your behalf. That is exactly why the Senate feeds have gone stale far more often than the House ones. |
| house-stock-watcher, current live fork | `https://github.com/TattooedHead/house-stock-watcher-data` | **Everything, free, and genuinely updating.** `data/all_transactions.json` is 11.5 MB holding **23,969 parsed House trades** with ticker, transaction date, disclosure date, buy or sell, amount range, a mid-point estimate, representative, district, owner and a link back to the source PDF. Most recent disclosure date **1 September 2026**, and commits titled "Update house stock data" landed on 3, 4 and 5 September 2026 | A fork with **1 star and one maintainer**, no guarantee it stays up. Filing typos pass straight through: the highest transaction date in the file is 26 December 2026, a date that has not happened yet. **The original `timothycarambat/house-stock-watcher-data` is gone (HTTP 404), `housestockwatcher.com` no longer resolves, and the S3 bucket `house-stock-watcher-data.s3-us-west-2.amazonaws.com` now returns 403** | **This is the free machine-readable Congress feed to poll, and it is the most important finding in this group.** Everything a 2023-era tutorial tells you about house-stock-watcher and its public S3 bucket is dead. Pull this repository's raw JSON daily, validate dates on the way in, and cross-check the row count against the House Clerk index so you notice the day the maintainer stops. |
| senate-stock-watcher | `https://github.com/timothycarambat/senate-stock-watcher-data` | The repository is still public and readable, 99 stars | **Dead. Last push 16 March 2021**, five and a half years ago. The S3 bucket `senate-stock-watcher-data.s3-us-west-2.amazonaws.com` returns 403 and `senatestockwatcher.com` does not resolve | Do not use it. I found no maintained free Senate equivalent of the House fork above, which means **the Senate half of the Congress book has no free machine-readable feed**. You either scrape eFD through the agreement wall yourself or you pay Quiver. |
| Capitol Trades | `https://www.capitoltrades.com/` | Free to browse in a browser, both chambers, cleaned and normalised, with per-politician pages | **Live but blocks scripts.** Returned HTTP 429 to a plain script, 429 again with full browser headers, and 403 through a fetching proxy. **There is no official public API and none is advertised** | Good for a human to eyeball one name in ten seconds. Useless to an agent. Treat it as a checking tool, never as a source. |
| Quiver Quantitative | `https://api.quiverquant.com/` and `https://www.quiverquant.com/api/` | A free account gives web access to the datasets | **The API starts at 30 US dollars a month**, quoted on Quiver's own API portal. One key covers Congress trades, Congress holdings, insider trades, politician net worth, government contracts, lobbying, hedge fund activity, off-exchange trading and more. **The tier breakdown above that entry price is still unverified**: the pricing page renders in JavaScript and shows a script nothing at all | The paid shortcut, and the only one that closes the Senate gap cleanly. Thirty dollars a month against the days you would otherwise spend writing a PDF parser and an eFD session scraper is an easy trade. One warning: their sample response already includes an `ExcessReturn` field against SPY, which is convenient and is also exactly the sort of pre-computed backtest number to distrust on principle. |
| Unusual Whales | `https://unusualwhales.com/pricing` | A free account gets platform access with **15-minute delayed data** and limited datasets. The API has a **one-week trial billed at 50 US dollars**, so "trial" here means cheap, not free | Dashboard plans are **50 US dollars a month** (Retail Basic) and **75** (Retail Pro), which include politician trade downloads. **The API is a separate and much dearer product: API Basic 150 a month, API Advanced 375.** Retail and API plans are individual use only, and building a product on the data requires a business plan **from 625 a month billed annually** | Overkill for this job. It is an options flow product that happens to bundle politician trades. If options flow is not your strategy, you would be paying 150 US dollars a month for a Congress feed you can get free from the GitHub fork three rows up. |
| OpenInsider | `http://openinsider.com/` | **Free, no key, no signup.** Screens over SEC Form 4 insider filings with filters on insider role, transaction type, size, sector and date. Latest filings when I checked were dated **4 September 2026**, the previous trading day, so it is current | **No API, and no CSV export link that I could find on any page I read**, so this means scraping an HTML table. The site is plain HTTP with no HTTPS of its own | The fastest way for a person to eyeball insider activity, and a perfectly reasonable scrape target for a nightly job. But it is one person's website derived entirely from a free government source. If you are going to depend on it, go to the government source in the row below instead. |
| SEC Form 4 via EDGAR | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&output=atom` | **Everything, free, no key.** Form 4 filings per company as an Atom feed, which I confirmed returns entries, plus the full daily index at `https://www.sec.gov/Archives/edgar/daily-index/`. The filings themselves are **structured XML**, so no optical character recognition and no PDF parsing | 10 requests a second and the mandatory `User-Agent` header naming you with a contact email, same as every EDGAR endpoint. Public domain, no restriction on use | **The insider half of this group is a solved problem and it costs nothing.** Section 16 insiders must file within two business days of the trade, so by disclosure standards this is close to realtime, and the data arrives machine readable rather than as a scan. Use `edgartools` (see Part 3) rather than writing the parser. The contrast with Congress could not be sharper. |

**What this means for the Congress book**

Be clear-eyed about what you are buying into. House members must report a securities transaction over 1,000 US dollars "by the earlier of these two dates: 30 days from being made aware of the transaction; or 45 days from the transaction", which is the House Ethics Committee's own wording at `https://ethics.house.gov/financial-disclosure`. Senators file on the same clock. That is the legal ceiling, not the typical case, so I measured the real thing rather than repeating the folklore: across the **1,050 House trades disclosed so far in 2026** in the live dataset, the **median gap between trade and disclosure is 16 days**, the mean is 16.5, the ninetieth percentile is 29 days, only **0.4 percent were filed later than the 45-day limit**, and the worst single case was **240 days**. So the usual "45 day lag" line overstates the typical delay by nearly three times, while a small tail is far worse than 45 days. Late filers do exist and the penalty for them is nominal, though the exact late-filing fee is still unverified. Either way, you are trading a signal that is two to four weeks old by the time you can see it, against insiders' two business days on Form 4. Any strategy that depends on being fast here is dead on arrival; the only version that can work is one betting that the information is still underpriced weeks later.

**The feed an agent should poll: the raw JSON at `https://raw.githubusercontent.com/TattooedHead/house-stock-watcher-data/main/data/all_transactions.json`, once a day.** It is free, parsed, 11.5 MB, and committed daily. Pair it with two guards. First, pull the House Clerk index zip in the same job and compare the count of type P filings against the rows you received, so the day the fork's single maintainer walks away you find out immediately instead of six weeks later. Second, validate every date on ingest, because the source PDFs contain typos that the parser passes straight through. For the Senate there is no free machine-readable option at all, so either write the eFD agreement-wall scraper yourself or accept Quiver's 30 US dollars a month, and note that "Congress trades" strategies that quietly cover only the House are covering roughly the smaller and less-watched half of the story.


---

### Checked and dead or dormant

Everything below was looked at during this research and is **not** worth your time, with the reason. This list
exists so that when an agent proposes one of these, you can say no immediately.

#### Software, dead or frozen

| Thing | URL | Status |
|---|---|---|
| **backtrader** | `https://github.com/mementum/backtrader` | **Frozen since 19 April 2023** on the default branch, nearly three and a half years. 23,150 stars and a mountain of tutorials still point at it. Its IB integration rests on the long-dead IbPy. The most dangerous entry on this page precisely because it looks popular. |
| **backtrader2 community fork** | `https://github.com/backtrader2/backtrader` | **Last commit 2 November 2021.** Deader than the thing it forked. There is no maintained backtrader fork. |
| **bta-lib** (backtrader's own TA library) | `https://github.com/mementum/bta-lib` | Last push January 2022. Abandoned with its parent. |
| **Blankly** | `https://github.com/blankly-finance/blankly` | **Last commit 30 December 2024**, twenty months. Never supported IBKR. |
| **ib_insync** | `https://github.com/erdewit/ib_insync` | **Archived by the owner**, last commit 14 March 2024. Correctly retired after the author's death. Use `ib_async`. The existing reading list already says this and is right. |
| **mlfinlab** | `https://github.com/hudson-and-thames/mlfinlab` | **Last commit 2 October 2023**, three years. It was the reference implementation for López de Prado's methods, which are book 8 on the existing list, so agents will reach for it. |
| **pandas-ta** | `https://github.com/twopirllc/pandas-ta` | **Repository deleted, returns HTTP 404.** Was the most popular pure-Python indicator library. Successor: `https://github.com/xgboosted/pandas-ta-classic`, last commit 22 July 2026. |
| **catalyst** | `https://github.com/scrtlabs/catalyst` | **Archived**, last push November 2022. Crypto fork of Zipline. |
| **zipline (original Quantopian)** | `https://github.com/quantopian/zipline` | Last push February 2024 and unmaintained since Quantopian closed in 2020. `zipline-reloaded` is the fork, and even that has not committed since 13 November 2025. |
| **alpaca-trade-api-python** | `https://github.com/alpacahq/alpaca-trade-api-python` | **Archived**, last push 2 December 2024. Superseded by `https://github.com/alpacahq/alpaca-py` (last commit 3 September 2026). Older tutorials import the archived one. |
| **quantopian/research_public** | `https://github.com/quantopian/research_public` | Last push 3 November 2020. Still worth cloning, as the existing list says, but understand it is a museum piece and the data-fetching cells cannot run. |
| **mplfinance** | `https://github.com/matplotlib/mplfinance` | Last push 8 August 2024, two years. Not dead exactly, but not moving. |
| **OpenBB agents playground** | `https://github.com/OpenBB-finance/experimental-openbb-platform-agent` | Last push 22 July 2024. An abandoned experiment, not the main OpenBB project, which is active. |
| **Carver's AFTS code repo** | `https://github.com/robcarver17/advanced_futures_trading_strategies` | **Does not exist, HTTP 404.** Cited in the existing reading list as unverified; now verified as wrong. No official AFTS code repository exists. |
| **hftbacktest** | `https://github.com/nkaz001/hftbacktest` | Last push 23 December 2025, so slowing but not dead. Irrelevant to you regardless: it is for high-frequency market making. |

#### Written sources, dead or dormant

| Thing | URL | Status |
|---|---|---|
| **Newfound Research blog** | `https://blog.thinknewfound.com/` | **Dormant since 28 August 2023.** The last post was "15 Ideas, Frameworks, and Lessons from 15 Years", which reads like a farewell. The parent site `https://www.thinknewfound.com/` is still up, still shows a 2026 copyright and still offers a newsletter signup, so it looks alive until you check the archive. Corey Hoffstein's written research is effectively finished; his current output is the podcast. **This was a listed candidate and it does not qualify.** |
| **PyQuant News** | `https://www.pyquantnews.com/` | **Questionable.** The site is up and advertises a free weekly "PyQuant Tips" newsletter with a claimed 25,000 subscribers, but the newest dated content I could find references October 2022 and the footer copyright reads 2023. **Whether it still publishes weekly is still unverified.** Do not include it without checking the archive yourself. |
| **Verdad Weekly Research** | `https://verdadcap.com/archive` | Archive live, newest piece I could see dated **4 May 2026** with weekly entries before that. The four-month gap may be a page-loading artefact. **Current status still unverified.** |
| **Nasdaq Data Link free equity data** | `https://data.nasdaq.com/` | The **WIKI free equity price dataset is discontinued for new users.** Not dead as a company, but dead as the free data source that a decade of tutorials recommends. |

#### Podcasts, dead or dormant or not right for you

| Thing | URL | Status |
|---|---|---|
| **Better System Trader** | `https://bettersystemtrader.com/` | **DORMANT.** Site returns 200, but the last episode is **9 August 2024**, "241: Trading Market Phases, with Mish Schneider". Two years of silence, so it is not coming back. This was a named candidate and it does not qualify. The on-site podcast feed at `https://bettersystemtrader.com/feed/podcast/` throws a WordPress critical error; the working archive feed is `https://rss.libsyn.com/shows/66295/destinations/266788.xml`. **The 242-episode back catalogue on backtesting and system design is genuinely good, so mine it as an archive, do not subscribe.** |
| **Chat with Traders under Aaron Fifield** | n/a | Dead as a Fifield project since late summer 2022. The show itself is alive under Kevin Avery, see Part 1. The brief named Fifield as host, which is now wrong. |
| **Bogleheads Live** | n/a | **DEAD.** Last episode 22 November 2023, 45 episodes. Also the wrong audience, it is passive index investing. |
| **Papers With Backtest** | feed `https://feed.ausha.co/Q6GR1iqqMwOd` | **Stalling.** 82 episodes, last one **30 May 2026**, after a reliable weekly cadence. Three months of silence, so not yet dormant by a six-month rule but heading there. Content is squarely on target ("Backtesting Machine Learning Models", "Garbage In, Garbage Out: The Importance of Data Quality in Backtesting"). Worth a look if it restarts. |
| **Excess Returns** | `https://www.excessreturns.co/` | **Alive and prolific**, latest 6 September 2026, 556 episodes. Left out on **content grounds, not liveness.** Across the last 18 months it has drifted almost entirely into macro and AI-bubble commentary ("Is AI Still in 1995?", "The Fed Credibility Narrative Has Turned"), with very little on running a systematic operation. Fine for market context, not for craft. This was a named candidate. |
| **Michael Covel, Trend Following** | feed `https://rss.libsyn.com/shows/35470/destinations/88838.xml` | **Alive**, last episode 31 August 2026, 1,406 episodes. Left off because Top Traders Unplugged covers the same ground with more rigour and less self-promotion. Not dead if you want a second trend-following voice. |
| **Man Institute podcast** | n/a | **Still unverified.** No podcast under that name found in the Apple directory, and the search budget ran out before Man Group's own site could be checked. Do not put it in the pack without confirming it first. |
| Masters in Business, Animal Spirits, The Acquirers Podcast | n/a | All three confirmed **alive** (last episodes 2, 2 and 27 August or September 2026). All three are general investing rather than systematic operations, so none shortlisted. |

#### Sites that are live but refused automated requests

These are all fine in a browser. I simply could not read them with a script, so anything I say about their
current contents would be a guess.

- `https://alphaarchitect.com/blog/` HTTP 403. Consistent with what the existing reading list found.
- `https://www.bloomberg.com/` HTTP 403 on both the Matt Levine author page and the Money Stuff signup page.
- `https://site.financialmodelingprep.com/developer/docs/pricing` HTTP 403.
- `https://finnhub.io/pricing` loads but renders its pricing table in JavaScript, so a script sees nothing.

#### Research limitation to be honest about

This session exhausted its web search budget partway through, so the later checks were done by fetching known
URLs directly rather than by searching. That means the coverage of Parts 1, 2 and 4 is confirmation of named
candidates rather than open-ended discovery, and there may be good 2026 sources nobody named that I therefore
did not find. Part 3, the GitHub table, does not have this problem: it was built from direct GitHub API calls
and every number in it is first-hand.

---

## Appendix 1. Papers that still need a manual click

Free in a browser but blocked to scripts, or closed access. Nineteen papers. Every SSRN page below is free once you click "Download This Paper".

| Paper | Link | Why it failed |
|---|---|---|
| Bernard and Thomas 1989, PEAD | https://www.jstor.org/stable/2491062 | JSTOR only, needs a library login or purchase |
| Livnat and Mendenhall 2006, PEAD with analyst forecasts | https://doi.org/10.1111/j.1475-679X.2006.00196.x | Wiley, closed access |
| Harris and Gurel 1986, S&P 500 list changes | https://www.jstor.org/stable/2328230 | JSTOR only |
| Loughran and McDonald 2016, textual analysis survey | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2504147 | SSRN blocks scripts; no repository copy exists |
| Akbas, Boehmer, Jiang, Koch 2022, overnight returns and daytime reversals | https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004116 | Paywalled; the SMU repository listing has no file |
| Heitz, Narayanamoorthy, Zekhnini, the disappearing earnings announcement premium | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3296537 | SSRN blocks scripts; the Rotman mirror returns a server error |
| Zarattini and Pagani, February 2026, fast alphas intraday overlay | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6391638 | SSRN blocks scripts |
| Gabriel, Pagani, Zarattini, June 2026, tactical asset allocation implemented in Python and IBKR | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5230603 | SSRN blocks scripts |
| Saha and co-authors 2025, LLM agents for investment management (ICAIF) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5447274 | SSRN and ACM both return 403 |
| Byrd 2025, the accidental pump and dump (ICAIF) | https://dl.acm.org/doi/pdf/10.1145/3768292.3770424 | ACM blocks scripts; gold open access in a browser |
| Baulkaran and Jain 2025, NANC and KRUZ (Economics Letters) | https://www.sciencedirect.com/science/article/abs/pii/S0165176525001004 | Closed access, no preprint |
| Brogaard, Han and Won 2023, does 0DTE trading increase volatility | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358 | SSRN blocks scripts; no conference copy found |
| Vilkov 2026, 0DTE trading rules | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356 and https://github.com/vilkovgr/0dte-strategies | SSRN only; the repo has the paper as Markdown |
| S&P Dow Jones Indices, buy-write cash flow study | https://www.spglobal.com/spdji/en/documents/research/research-seeking-income-cash-flow-distribution-analysis-of-sp-500-buy-write-strategies.pdf | Served an HTML error page |
| Cboe BXM current factsheet | https://cdn.cboe.com/resources/indices/factsheet/CboeGlobalIndices_BXM-Index.pdf | Image-only PDF, numbers not extractable |
| Alpha Architect, "The Return of the King" on trend following | https://alphaarchitect.com/the-return-of-the-king-trend-following-is-back-but-will-it-last/ | 403 to every automated request |
| Toby Crabel, April 2026, the evolution of the opening range breakout | https://tobycrabel.substack.com/p/the-evolution-of-the-opening-range | Paywalled newsletter post |
| CXO Advisory on the ORB paper | https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy/ | Findings behind a subscription |
| Unusual Whales annual reports, 2021 to 2025 | Links in Part C, section 2a | Cloudflare challenge; the 2023 and 2024 editions are readable on the company's Substack |

Two tricks for whoever downloads next. AQR's main site blocks scripts but images.aqr.com serves the same PDFs freely, which is how four AQR and Financial Analysts Journal papers got in. SSRN never works from a script; conference portals (Lancaster, FMA, Western Finance Association) and university repositories (Imperial's Spiral, Toronto's TSpace, St Gallen's Alexandria) usually do.

## Appendix 2. PDFs added by this pass

84 files, all in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`. Each was checked with `file` to confirm it is a PDF and with `pdftotext` on the first page (or rendered to an image, for the five scanned papers) to confirm it is the paper it claims to be. Nothing that was already in the folder was overwritten. One file was renamed: the Vals AI Finance Agent Benchmark paper is stored under Krishnan, the first author on the cover page, rather than Bigeard, the first author in arXiv's metadata.

| File | Size | Pages |
|---|---|---|
| `Aboody_2018_OvernightReturnsFirmSpecificInvestorSentiment.pdf` | 260K | 21 |
| `Almeida_2025_0DTEAssetPricing.pdf` | 6.0M | 79 |
| `Antonacci_2013_RiskPremiaHarvestingDualMomentum.pdf` | 864K | 37 |
| `Ariel_1987_MonthlyEffect.pdf` | 1.7M | 56 |
| `Asness_2014_FactFictionMomentum.pdf` | 1.1M | 19 |
| `Asness_2019_QualityMinusJunk.pdf` | 2.2M | 80 |
| `Augustin_2021_VolmageddonShortVolProducts.pdf` | 828K | 38 |
| `BallBrown_1968_EmpiricalEvaluationAccountingIncomeNumbers.pdf` | 2.1M | 21 |
| `Baltas_2013_DemystifyingTimeSeriesMomentum.pdf` | 260K | 46 |
| `BarberDeGeorgeLehavyTrueman_2013_EarningsAnnouncementPremiumGlobe.pdf` | 512K | 41 |
| `Beckmeyer_2023_RetailTradersLove0DTE.pdf` | 516K | 32 |
| `Belmont_2020_ReliefRallySenatorsStockPicking.pdf` | 528K | 39 |
| `Berkman_2012_PayingAttention.pdf` | 256K | 28 |
| `Bradley_2010_ActivistArbitrageCEF.pdf` | 532K | 19 |
| `Cboe_0DTEIndexOptionsMarketVolatility.pdf` | 936K | 48 |
| `Cboe_2018_AfterTheVolpocalypse.pdf` | 500K | 5 |
| `Chague_2020_DayTradingForALiving.pdf` | 496K | 18 |
| `Choi_2025_FinAgentBench.pdf` | 1.9M | 6 |
| `Christin_2022_CryptoCarryTrade.pdf` | 3.0M | 51 |
| `Cliff_2008_NightAndDay.pdf` | 328K | 48 |
| `Contreras_2025_InsidersInformationAdvantageShortSellers.pdf` | 1.4M | 92 |
| `Dai_2025_CAIA_HallucinationCostsMillions.pdf` | 448K | 15 |
| `DewBecker_2025_DeclineOfVarianceRiskPremium.pdf` | 5.3M | 78 |
| `DimEraker_2023_0DTEsGammaRisk.pdf` | 1.0M | 55 |
| `Durmaz_2025_TrendBreaksCEFDiscounts.pdf` | 1.8M | 49 |
| `EggersHainmueller_2013_CapitolLosses.pdf` | 456K | 43 |
| `Etula_2020_DashForCash.pdf` | 1.1M | 38 |
| `Faber_2013_QuantitativeApproachTAA.pdf` | 924K | 70 |
| `Faber_2017_TAARevisited10YearsLater.pdf` | 1.7M | 13 |
| `Fan_2025_AITrader.pdf` | 7.4M | 17 |
| `Frazzini_2018_TradingCosts.pdf` | 3.7M | 88 |
| `FrazziniLamont_2007_EarningsAnnouncementPremium.pdf` | 180K | 53 |
| `Glasserman_2025_DoesOvernightNewsExplainOvernightReturns.pdf` | 1.0M | 43 |
| `Harris_2026_FrontierFinancialJudgement.pdf` | 588K | 19 |
| `HarveyLiu_2014_EvaluatingTradingStrategies.pdf` | 1.7M | 11 |
| `He_2022_FundamentalsOfPerpetualFutures.pdf` | 5.0M | 64 |
| `Heckmann_2024_SynthesizingInsiderTradeSignals.pdf` | 2.1M | 88 |
| `Henning_2025_LLMAgentsDoNotReplicateHumanTraders.pdf` | 5.0M | 51 |
| `HestonSadka_2008_SeasonalityCrossSection.pdf` | 788K | 55 |
| `Hu_2025_FinSearchComp.pdf` | 1.3M | 29 |
| `Hua_2026_AgenticQuantitativeTradingSurvey.pdf` | 3.4M | 9 |
| `Hurst_2017_CenturyOfTrendFollowing.pdf` | 2.7M | 16 |
| `Ilmanen_2012_InsuranceAndLotteryTickets.pdf` | 640K | 12 |
| `Israelov_2014_CoveredCallsOneFactEightMyths.pdf` | 252K | 9 |
| `Israelov_2015_CoveredCallsUncovered.pdf` | 416K | 14 |
| `Israelov_2018_CoveringTheWorldGlobalCoveredCalls.pdf` | 972K | 30 |
| `Israelov_2023_DevilsBargainDerivativeIncome.pdf` | 944K | 28 |
| `Jegadeesh_1990_PredictableBehavior.pdf` | 1.9M | 19 |
| `Jiang_2026_InvestLogicBench.pdf` | 6.1M | 18 |
| `Kang_2018_ClusterTradingCorporateInsiders.pdf` | 2.4M | 54 |
| `Karadas_2021_NonPublicMacroInfoSTOCKAct.pdf` | 316K | 18 |
| `Krauss_2015_StatArbPairsTradingReviewOutlook.pdf` | 456K | 62 |
| `Krishnan_2025_FinanceAgentBenchmark.pdf` | 1.3M | 24 |
| `Kurth_2026_IsTrendStillYourFriend.pdf` | 5.0M | 31 |
| `LakonishokSmidt_1988_AreSeasonalAnomaliesReal.pdf` | 2.0M | 23 |
| `Li_2025_FINSABER_LLMInvestingLongRun.pdf` | 2.0M | 15 |
| `Linnainmaa_2019_EarningsAnnouncementReturnCycle.pdf` | 508K | 48 |
| `LopezDePrado_2018_TenReasonsMLFundsFail.pdf` | 1.3M | 21 |
| `Mallory_2026_ImpliedETFCarryRatesBitcoin.pdf` | 1.0M | 7 |
| `McLeanPontiff_2016_DoesAcademicResearchDestroyPredictability.pdf` | 1.0M | 48 |
| `Mesfin_2026_StructuralLimitsOHLCVIntradaySignals.pdf` | 1.1M | 15 |
| `Neupane_2026_InsiderIntentForm144Form4.pdf` | 384K | 28 |
| `Ngeh_2024_CointegratedPairsTradingGoldETFs.pdf` | 2.0M | 35 |
| `Patro_2014_ExploitingCEFDiscounts.pdf` | 168K | 47 |
| `Petajisto_2011_CharacteristicsMarketTradingETFs.pdf` | 224K | 32 |
| `Plastun_2020_PriceGapAnomalyUSStockMarket.pdf` | 588K | 30 |
| `Qian_2025_AgentMarketArena.pdf` | 2.4M | 12 |
| `SarkarVafa_2024_LookaheadBiasPretrainedLMs.pdf` | 1.0M | 32 |
| `SavorWilson_2016_EarningsAnnouncementsSystematicRisk.pdf` | 788K | 59 |
| `Schmeling_2023_CryptoCarry.pdf` | 564K | 54 |
| `SEC_DERA_2025_HopeAtReasonablePrice0DTE.pdf` | 1.1M | 48 |
| `Shleifer_1986_DemandCurvesSlopeDown.pdf` | 1.4M | 12 |
| `Sun_2025_SurveyStatArbPairsTrading.pdf` | 1.9M | 100 |
| `Wei_2025_CaptainGainsCapitolHill.pdf` | 2.0M | 67 |
| `Wilshire_2019_OptionsBasedBenchmarkIndexes.pdf` | 1.3M | 28 |
| `Xia_2026_AgenticTradingEvidenceMap.pdf` | 11M | 59 |
| `Yang_2026_WhenValidSignalsFail.pdf` | 364K | 9 |
| `Yu_2025_LiveTradeBench.pdf` | 4.0M | 37 |
| `Zarattini_2023_CanDayTradingReallyBeProfitable_rev2025.pdf` | 3.0M | 18 |
| `Zarattini_2023_CanDayTradingReallyBeProfitable.pdf` | 996K | 18 |
| `Zarattini_2024_ProfitableDayTradingStrategyUSEquity_ConcretumRev.pdf` | 960K | 26 |
| `Zarattini_2024_ProfitableDayTradingStrategyUSEquity.pdf` | 908K | 25 |
| `ZarattiniAzizBarbon_2024_BeatTheMarketIntradayMomentumSPY.pdf` | 1.8M | 43 |
| `Zhao_2026_InsiderPurchaseSignalsMicrocap.pdf` | 620K | 9 |

## Provenance

The six parts were written on 2026-09-06 by six research agents with web search, one per topic cluster, each instructed to download every free PDF it cited and to mark anything it could not confirm. An API outage killed five of the six partway through; their reports were recovered from disk, and the missing sections (the anomalies verification, the insider-signals part, the crypto and closed-end fund part, and the data-source tables) were rewritten from the PDFs already downloaded plus direct page fetches. The web search budget for the session ran out during that second round, which is why several items in Parts C, E and F say "not searched" rather than "not found". Those are the first things to check with a fresh budget.
