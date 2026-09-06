# Practitioner Layer: How a Small Systematic Shop Actually Runs

Reading list for Mo, September 2026. This is the practitioner slice: books, blogs, papers and rules that teach how a small systematic trading operation is actually run day to day, plus the honest evidence on why most people who try this lose money.

Companion folder of downloaded PDFs: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`
This file: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/03_practitioner.md`

**Two labels used throughout:**
- **Flight reading** means you can read it front to back on a plane and come off knowing something.
- **Reference** means dip in when you hit the specific problem. Reading it cover to cover is a waste of a flight.

---

## Section 1. Books

### The core three, in the order I would read them

#### 1. Inside the Black Box: A Simple Guide to Quantitative and High-Frequency Trading
Rishi K. Narang, 2nd edition, 2013.
Where to get it: no free PDF. Wiley store, `https://www.wiley.com/en-us/Inside+the+Black+Box%3A+A+Simple+Guide+to+Quantitative+and+High+Frequency+Trading%2C+2nd+Edition-p-9781118362419`. Also on Amazon and Kindle.

This is the only book on the list written for someone who runs or funds a quant shop rather than someone who codes one. Narang breaks a systematic trading firm into its parts (alpha model, risk model, transaction cost model, portfolio construction, execution, data, research) and explains what each part does and how they fail, with almost no maths. It is short, roughly 300 pages, and the second edition adds a plain section on high frequency trading that clears up most of the noise around it.

Why it matters for an agent-run shop: the six-box structure is the cleanest mental model for deciding which parts your agents own and which parts you personally sign off on.

Skip: the appendices on specific HFT market structure debates. They date from 2013 and the market has moved.

**Flight reading.** Read this one first, on the way out.

#### 2. Systematic Trading: A Unique New Method for Designing Trading and Investing Systems
Robert Carver, 2015.
Where to get it: no free PDF. Harriman House store, `https://harriman-house.com/systematictrading`. Carver's own site with errata and code, `https://qoppac.blogspot.com/p/systematic-trading-book.html`.

Carver ran systematic funds at AHL and then went home and ran the same ideas on his own money, which is exactly your situation. The book's central argument is that most retail systematic traders lose not because their signal is bad but because their position sizing, diversification and rule count are wrong, so he spends most of the pages on risk targeting, volatility scaling and how few rules you actually need. It has a genuinely useful framework for deciding how much to trade based on how confident you are, which he calls forecast scaling.

Why it matters for an agent-run shop: this is the book that tells your risk agent what numbers to enforce, and its "don't optimise, use sensible defaults" stance is the correct posture when a machine can generate a thousand variants overnight.

Skip: chapter-by-chapter derivations of the forecast scalar if the algebra slows you. Take the defaults he gives, they are the point.

**Flight reading**, though it is denser than Narang. Budget four hours.

#### 3. Leveraged Trading: A Professional Approach to Trading FX, Stocks on Margin, CFDs, Spread Bets and Futures
Robert Carver, 2019.
Where to get it: no free PDF. Harriman House store, `https://harriman-house.com/leveragedtrading`.

This is Systematic Trading rewritten for a smaller account and a reader who has not done this before, and it is arguably the better first Carver. It builds up from one instrument and one rule to a small diversified system, and it is unusually honest about how leverage kills small accounts even when the underlying strategy is fine. The starter system it describes is a legitimate thing to actually run, not a toy.

Why it matters for an agent-run shop: it gives you a defensible minimum viable strategy that you can hand to an agent to implement and paper trade in week one, rather than starting from a blank page.

Skip: the sections on spread betting and CFDs. Those are UK retail products, not relevant with Interactive Brokers.

**Flight reading.**

### The rest, ranked by how likely you are to open them

#### 4. Advanced Futures Trading Strategies: 30 Fully Tested Strategies for Multiple Trading Styles and Time Frames
Robert Carver, 2023.
Where to get it: no free PDF. Harriman House store, `https://harriman-house.com/advancedfuturestrading`. Python code is free at `https://github.com/robcarver17/advanced_futures_trading_strategies` (link unverified in this session).

Carver's third book takes the framework from the first two and runs 30 concrete strategies through it, reporting real costs and real Sharpe ratios rather than backtest fantasies. The strategies escalate from a single moving average to carry, skew, seasonality and relative value, each with the sizing already worked out. The value is less in any one strategy and more in seeing the same disciplined evaluation applied 30 times.

Why it matters for an agent-run shop: it is the closest thing to a strategy catalogue your agents can work through systematically, with the author's own honest cost estimates attached.

Skip: nothing, but read it as a catalogue, not a narrative.

**Reference**, with a flight-readable first third.

#### 5. Quantitative Trading: How to Build Your Own Algorithmic Trading Business
Ernest P. Chan, 2nd edition, 2021.
Where to get it: no free PDF. Wiley store, `https://www.wiley.com/en-us/Quantitative+Trading%3A+How+to+Build+Your+Own+Algorithmic+Trading+Business%2C+2nd+Edition-p-9781119800064`.

Chan's first book is the operational one: how to pick a broker, get data, avoid survivorship bias, size an account, and decide whether to trade your own money or raise. It is thin on strategy depth and thick on the plumbing and business decisions nobody else writes down. The second edition refreshes the broker and data recommendations and adds a light chapter on machine learning.

Why it matters for an agent-run shop: the checklists on data cleanliness, survivorship bias and broker selection are exactly the things an agent will get wrong silently if nobody wrote the rule down.

Skip: the MATLAB examples in the older edition, and treat the strategy examples as illustrations, not as strategies to run. Several are well known to have decayed.

**Flight reading**, and short.

#### 6. Algorithmic Trading: Winning Strategies and Their Rationale
Ernest P. Chan, 2013.
Where to get it: no free PDF. Wiley store, `https://www.wiley.com/en-us/Algorithmic+Trading%3A+Winning+Strategies+and+Their+Rationale-p-9781118460146`.

The sequel goes deeper on two families, mean reversion and momentum, and explains why each works when it works. The cointegration and pairs material is the best plain-language treatment of that idea I know of. The book's honest framing is that these are rationales for strategies, not turnkey money.

Why it matters for an agent-run shop: the "rationale" discipline, meaning you must be able to say why a pattern should exist before you trade it, is the single best guard against an agent handing you an overfitted backtest.

Skip: the specific strategy parameters. They are more than a decade old.

**Reference.**

#### 7. Trading Evolved: Anyone Can Build Killer Trading Strategies in Python
Andreas F. Clenow, 2019.
Where to get it: no free PDF. Amazon or `https://www.followingthetrend.com/trading-evolved/`.

Clenow teaches Python and backtesting from zero using Zipline, aimed squarely at someone who is not a programmer. The trading content is solid trend following, and the writing is blunt about how much of retail trading advice is nonsense. The catch is dating: Zipline was effectively abandoned after Quantopian shut in 2020, and the maintained fork is `zipline-reloaded` at `https://github.com/stefan-jansen/zipline-reloaded`.

Why it matters for an agent-run shop: it is the best book for understanding what your Python agent is actually doing when it runs a backtest, so you can read its output critically.

Skip: the installation chapters, they are stale. Have your agent set up the environment and read the book for the concepts.

**Flight reading** if you skip the code-along parts.

#### 8. Advances in Financial Machine Learning
Marcos López de Prado, 2018.
Where to get it: no free PDF. Wiley store, `https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086`.

This is the most cited modern quant book and it is not for a non-programmer founder to read cover to cover. Its lasting contributions are a handful of specific ideas: labelling with the triple barrier method, sample uniqueness and purged cross validation, fractional differentiation, and the meta-labelling idea of using one model to decide whether to act on another. The rest is dense and assumes comfortable Python plus statistics.

Why it matters for an agent-run shop: the purged and embargoed cross validation chapter is the correct answer to "our agent got a Sharpe of 3 in the backtest", because standard cross validation leaks information in time series and inflates results.

Skip: most of it, on a first pass. Read chapter 7 on cross validation, chapter 3 on labelling, and chapter 11 on the dangers of backtesting. Hand the rest to an agent as a reference.

**Reference.** Do not put it in the flight bag.

#### 9. Machine Learning for Asset Managers
Marcos López de Prado, 2020.
Where to get it: no free PDF. Cambridge University Press, `https://www.cambridge.org/core/elements/machine-learning-for-asset-managers/6D9211305EA2E425D33A9F38D0AE3545`.

A 190 page Cambridge Element that is far more approachable than Advances, covering denoising covariance matrices, distance metrics, clustering and the false strategy theorem. It is the readable version of the same author's worldview. The false strategy theorem section is the one to read.

Why it matters for an agent-run shop: it gives you the arithmetic for how much a Sharpe ratio must be discounted when a machine tried many strategies, which is precisely your risk.

**Reference**, but a short and readable one.

#### 10. Trading Systems and Methods
Perry J. Kaufman, 6th edition, 2019.
Where to get it: no free PDF. Wiley store, `https://www.wiley.com/en-us/Trading+Systems+and+Methods%2C+6th+Edition-p-9781119605355`.

This is the encyclopedia, roughly 1,200 pages covering essentially every published technical trading system with formulas. Nobody reads it end to end and nobody should. Its use is as a lookup: when an agent proposes an indicator, Kaufman tells you where it came from and what its known weaknesses are.

Why it matters for an agent-run shop: it is a defence against agents reinventing a 1970s indicator and presenting it as novel.

Skip: everything until you need it.

**Reference only.**

#### 11. Volatility Trading / Positional Option Trading
Euan Sinclair, 2013 and 2020.
Where to get it: no free PDF. Wiley store for Volatility Trading, `https://www.wiley.com/en-us/Volatility+Trading%2C+2nd+Edition-p-9781118347133`.

Sinclair is the most intellectually honest options trader who writes books, and Positional Option Trading in particular is unusually clear that most option edges are small, crowded and hard to hold. It is only worth your time if options are in scope for the first year. If you are trading equities and futures with Interactive Brokers, it is not.

Why it matters for an agent-run shop: only if you go anywhere near options, in which case Sinclair's chapters on position sizing and the Kelly criterion under uncertainty are the safest treatment available.

**Reference, and probably not yet.** Defer until options are actually on the roadmap.

---

## Section 2. The best free long-form sources

All of these are free and most are worth pulling down before the flight if you want offline copies. Use your browser's reader or print-to-PDF on the specific articles you want.

#### Alpha Architect blog
Wesley Gray and team, ongoing since roughly 2012. `https://alphaarchitect.com/blog/`
Note: the site returned a bot-block to my command line request, so I could not enumerate articles, but the site is live.

Alpha Architect summarise academic finance papers into readable posts with the practical takeaway stated plainly, and they run real money so the takeaways are grounded. Their recurring theme is that most published anomalies do not survive real costs and real implementation, which is the correct scepticism. Their series on trend following and on value investing are the deepest free treatments online.

Why it matters for an agent-run shop: it is the fastest way to check whether a strategy your agent found in a paper has already been shown to fail in practice.

**Flight reading** if you save a dozen posts first.

#### Quantpedia free strategy summaries
Quantpedia, ongoing. `https://quantpedia.com/strategies/`

Quantpedia catalogues published trading strategies from academic papers, each with a one-page summary, the source paper, the reported Sharpe, the markets and the complexity. A meaningful subset is free without a subscription and the free screener alone is a good afternoon. Treat every reported Sharpe as an upper bound produced under ideal conditions.

Why it matters for an agent-run shop: this is a structured, machine-readable-ish idea backlog that an agent can work through, rather than having the agent invent strategies from nothing.

**Reference**, browsed rather than read.

#### Concretum Group research
`https://concretumgroup.com/research/` and `https://concretumgroup.com/articles/`

Concretum publish detailed research write-ups on intraday and short horizon equity strategies, often with the full methodology and honest cost assumptions. Their work on opening range breakouts and on intraday momentum is some of the few free material that actually models slippage properly. They also run a podcast at `https://rss.com/podcasts/concretumresearch/`.

Why it matters for an agent-run shop: it is a model for what a research write-up should contain before you let a strategy go live.

**Flight reading**, article by article.

#### Robot Wealth
Kris Longmore, ongoing. `https://robotwealth.com/blog/`

Robot Wealth is written by a former prop trader for people building systematic strategies at small scale, and the tone is practical rather than academic. The posts on statistical significance of backtests, on trading costs, and on why you should not trust your own results are the ones to read. There is a paid community but the free blog archive is substantial.

Why it matters for an agent-run shop: it is the closest thing online to a mentor for exactly your setup, small account, systematic, Python.

**Flight reading.**

#### Quantocracy
`https://quantocracy.com/`

Quantocracy is a daily aggregator of quant trading blog posts, running since 2014, which makes its archive the single best index of the free practitioner literature. It does not write anything itself. Use it to discover blogs, then read the blogs.

Why it matters for an agent-run shop: point an agent at the archive and you have a decade of practitioner writing to mine for ideas and for known failure modes.

**Reference.**

#### Quantopian lecture series
Quantopian, archived. `https://github.com/quantopian/research_public`

Quantopian shut down in 2020 but its lecture series survives on GitHub as Jupyter notebooks, and it remains the best free structured course in quant finance for a beginner. It covers statistics, hypothesis testing, factor models, risk, and specifically the ways backtests lie, with runnable code. Some data-fetching cells will not run because the Quantopian platform is gone, but the explanations stand.

Why it matters for an agent-run shop: it is a free curriculum you can hand to an agent to teach from, and the lectures on multiple comparison bias and on overfitting are directly on point.

**Reference**, but the overfitting and hypothesis testing lectures are flight reading. Clone the repo before you fly:
`git clone https://github.com/quantopian/research_public.git`

#### Two Sigma Insights
`https://www.twosigma.com/insights/`

Two Sigma publish short, well-edited pieces on market structure, machine learning applied to markets, and risk. They are marketing in the sense that they never give away real alpha, but they are honest about method and the writing is clear. Their venture and street view series on factor performance are useful for context.

Why it matters for an agent-run shop: it calibrates you on what a serious firm considers a solved problem versus an open one.

**Reference.**

#### AQR research library
`https://www.aqr.com/Insights/Research`

AQR publish full journal-quality papers for free, and Cliff Asness in particular writes with unusual bluntness about what does and does not work. The essential ones are "Fact, Fiction and Momentum Investing", "Value and Momentum Everywhere", "Betting Against Beta" and "Trading Costs" by Frazzini, Israel and Moskowitz. The trading costs paper matters most for you because it measures real implementation costs at scale.

Why it matters for an agent-run shop: AQR are the most credible public source on the gap between a paper's backtest and a live portfolio, which is the gap that will kill you.

Note: `https://www.aqr.com/Insights/Research` responds normally in a browser but returned a bot-block to my command line download attempts, so the individual PDFs are not in the local folder. Download by hand before the flight.

**Flight reading**, one paper at a time.

#### Robert Carver's blog
`https://qoppac.blogspot.com/`

Carver has blogged since 2014 about running his own systematic futures portfolio, with real results, real mistakes and open source code (`pysystemtrade` at `https://github.com/robcarver17/pysystemtrade`). It is the single most useful free account of a one-person systematic operation that exists.

Why it matters for an agent-run shop: `pysystemtrade` is a working reference implementation of everything the books describe, including the boring parts like broker reconnection and position reconciliation, which is exactly where an autonomous system breaks.

**Reference**, but read his annual review posts as flight reading.

#### Ernie Chan's blog
`https://epchan.blogspot.com/`

Chan's blog predates his books and has continued intermittently. The posts on backtest pitfalls, on data snooping and on why a strategy stopped working are worth an evening. Less active now than it was.

**Reference.**

---

## Section 3. The honest evidence on retail outcomes

This is the section to read before you fund anything. All four papers below are downloaded.

#### Trading Is Hazardous to Your Wealth: The Common Stock Investment Performance of Individual Investors
Brad M. Barber and Terrance Odean, Journal of Finance, 2000.
Local: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/BarberOdean_2000_TradingIsHazardous.pdf` (10 pages excerpt version)
Source: `https://faculty.haas.berkeley.edu/odean/papers/returns/individual_investor_performance_final.pdf`

The founding paper of the field. Across 66,465 US households at a discount broker from 1991 to 1996, the households that traded most earned 11.4% a year while the market returned 17.9%, and the average household earned 16.4% while turning over 75% of its portfolio annually. The gap is almost entirely explained by trading costs plus bad selection, and the authors attribute the excessive trading to overconfidence.

Why it matters for an agent-run shop: the mechanism that destroys retail returns is turnover, so every extra trade your agents want to make has to clear a bar, not just look good.

**Flight reading.** Short and readable.

#### Just How Much Do Individual Investors Lose by Trading?
Brad M. Barber, Yi-Tsung Lee, Yu-Jane Liu, Terrance Odean, Review of Financial Studies, 2009.
Local: `.../pdfs/BarberLeeLiuOdean_2009_JustHowMuchDoInvestorsLose_Taiwan.pdf` (24 pages)
Source: `https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/JustHowMuchDoIndividualInvestorsLose_RFS_2009.pdf`

Using the complete trading history of every investor in Taiwan, the authors find individuals suffer an annual performance penalty of 3.8 percentage points, and that aggregate individual losses equal 2.2% of Taiwan's GDP. Institutions gain 1.5 percentage points a year, with foreign institutions taking nearly half of institutional profits. The finding that should stop you short is that virtually all individual losses trace to aggressive orders, meaning orders that cross the spread and pay for liquidity.

Why it matters for an agent-run shop: the finding that losses come from aggressive orders is a direct instruction to your execution agent, which should default to passive limit orders and treat marketable orders as a cost to be justified.

**Flight reading.**

#### The Cross-Section of Speculator Skill: Evidence from Day Trading
Brad M. Barber, Yi-Tsung Lee, Yu-Jane Liu, Terrance Odean, Journal of Financial Markets, 2014.
Local: `.../pdfs/BarberLeeLiuOdean_2014_CrossSectionSpeculatorSkill_Taiwan.pdf` (24 pages)
Source: `https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf`

This is the paper that answers "is anyone good at this". Sorting Taiwanese day traders by prior-year returns from 1992 to 2006, the top 500 went on to earn 61.3 basis points a day before fees and 37.9 after, while the bottom-ranked went on to earn negative 11.5 before fees and negative 28.9 after. The conclusion the authors state plainly is that less than 1% of the day trader population can predictably and reliably earn positive abnormal returns net of fees.

Why it matters for an agent-run shop: skill is real and persistent, and it is also present in under 1% of participants, so the honest planning assumption is that you are not in that 1% until many months of live results say otherwise.

**Flight reading.** This is the single most important paper in this section.

#### Do Day Traders Rationally Learn About Their Ability?
Brad M. Barber, Yi-Tsung Lee, Yu-Jane Liu, Terrance Odean, Ke Zhang, working paper, 2017 and later revisions, widely cited as 2020.
Local: `.../pdfs/BarberLeeLiuOdeanZhang_2020_DayTradingAndLearning_Taiwan.pdf` (34 pages)
Source: `https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf`

The same Taiwan dataset, asking whether people sensibly quit once they learn they are bad. Unprofitable traders are indeed more likely to quit, which is rational, but aggregate day trader performance is negative, the vast majority are unprofitable, and many persist despite extensive experience of losses. In other words the learning process works, just far too slowly and far too weakly to save most people.

Why it matters for an agent-run shop: a machine will not quit on its own, so you need a written, numeric stop condition decided before you start, because the human tendency is to keep going.

**Flight reading.**

#### Day Trading for a Living?
Fernando Chague, Rodrigo De-Losso, Bruno Giovannetti, SSRN working paper 3423101, 2020.
Where to get it: `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101` (store link, free to download from SSRN in a browser).
**Download failed.** SSRN returns 403 to command line requests, the FGV institutional repository at `https://repositorio.fgv.br/dspace/handle/10438/28162` sits behind a bot-protection wall, and neither OpenAlex nor Semantic Scholar lists an open-access copy. Get it manually from SSRN in a browser.

The Brazilian counterpart to the Taiwan studies, and the more brutal one. The authors follow every individual who began day trading equity index futures on the Brazilian exchange between 2013 and 2015, and among those who persisted for at least 300 days almost all lost money, with only a tiny fraction earning more than a bank teller's salary. The headline finding, that roughly 97% of persistent day traders lost money, is the number most often quoted from this paper.

Note: I am reporting the headline figures from memory here because I could not download the PDF to verify them. Treat the exact percentages as approximate until you have read the paper.

Why it matters for an agent-run shop: it tests persistence specifically, so it rules out the comforting story that people fail because they quit too early.

**Flight reading** once you have the PDF.

---

## Section 4. Backtest overfitting, or how not to fool yourself

If you read only one section of this list, read this one. An agent that can run ten thousand backtests overnight is a machine for manufacturing false confidence, and these papers are the antidote.

#### Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance
David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu, Notices of the American Mathematical Society, volume 61 number 5, 2014.
Local: `.../pdfs/Bailey_2014_PseudoMathematics.pdf` (14 pages)
Source: `https://www.ams.org/notices/201405/rnoti-p458.pdf`

Four mathematicians explain, in a mathematics society journal, that publishing a backtest without saying how many variants you tried is a form of charlatanism. Their key result is the minimum backtest length: given a number of trials, they compute how long a backtest must be before a given in-sample Sharpe ratio means anything at all, and the answer is usually longer than the data you have. They also show that overfit strategies do not merely fail out of sample, they tend to be actively negative because the overfitting fits mean reverting noise.

Why it matters for an agent-run shop: this gives you a hard rule to hand your research agent, which is that it must report the number of configurations tried alongside every result, and results without that number are inadmissible.

**Flight reading.** Fourteen pages, no heavy maths, genuinely enjoyable.

#### The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality
David H. Bailey and Marcos López de Prado, Journal of Portfolio Management, 2014.
Local: `.../pdfs/Bailey_2014_DeflatedSharpe.pdf` (22 pages)
Source: `https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf`

This paper gives you the actual formula. The deflated Sharpe ratio takes a reported Sharpe and discounts it for three things: how many strategies were tried, how short the track record is, and how non-normal the returns are, particularly negative skew and fat tails. The output is a probability that the true Sharpe is above zero, which is a far more honest number than the raw Sharpe.

Why it matters for an agent-run shop: this is a single computable gate you can put in your pipeline, so no strategy goes to paper trading unless its deflated Sharpe clears a threshold you set in advance.

**Reference**, but read the first eight pages on the flight. Then have an agent implement it.

#### The Probability of Backtest Overfitting
David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu, Journal of Computational Finance, 2017.
Local: `.../pdfs/Bailey_2017_ProbabilityBacktestOverfitting.pdf` (34 pages)
Source: `https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf`

The longer, more technical sibling of the Notices article. It defines a combinatorially symmetric cross validation procedure that estimates the probability that the strategy you selected as best in sample will underperform the median out of sample. That probability is the number you actually want, and for typical retail research processes it is uncomfortably close to one half or worse.

Why it matters for an agent-run shop: it converts "are we overfitting" from a vibe into a measured probability your agent can report each research cycle.

**Reference.** Skim the maths, read the definitions and the examples.

#### ... and the Cross-Section of Expected Returns
Campbell R. Harvey, Yan Liu, Heqing Zhu, Review of Financial Studies, 2016.
Local: `.../pdfs/Harvey_2016_CrossSectionExpectedReturns.pdf` (64 pages)
Source: `https://faculty.fuqua.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.pdf`

Harvey and coauthors count the factors that academic finance has claimed predict stock returns, find 316 of them, and point out that with that many tests the conventional significance threshold is meaningless. Their recommendation is that a new factor should need a t-statistic above roughly 3.0, not 2.0, to be believed, and that even that is generous because unpublished failed tests are invisible. The title is a joke about how every paper announces one more factor.

Why it matters for an agent-run shop: it sets the evidential bar for accepting any signal your agents propose, and the raised t-statistic threshold is a rule you can enforce mechanically.

**Flight reading** for the first fifteen pages and the conclusion. The middle is a literature census.

#### Evaluating Trading Strategies
Campbell R. Harvey and Yan Liu, Journal of Portfolio Management, 2014.
Where to get it: `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2474755` (store link, free on SSRN in a browser).
**Download failed.** SSRN blocks command line requests with a 403.

The short, practical companion to the paper above, aimed at practitioners rather than academics. It lays out three multiple-testing corrections (Bonferroni, Holm, Benjamini Hochberg Yekutieli) and shows how to apply each to a set of candidate trading strategies. It also gives a simple haircut formula for Sharpe ratios based on the number of tests.

Why it matters for an agent-run shop: it is the most implementable of the multiple-testing papers, so it is the one your agent should code first.

**Flight reading** once downloaded. Around 20 pages.

#### The 10 Reasons Most Machine Learning Funds Fail
Marcos López de Prado, Journal of Portfolio Management, 2018.
Where to get it: `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816` (store link, free on SSRN in a browser).
**Download failed.** SSRN blocks command line requests, and the author's own site at `https://www.quantresearch.org/` serves its publications page through frames with no extractable direct links.

A list-shaped paper enumerating ten specific, common and fatal errors, including the sisyphus paradigm of having one person do every job, backtesting through resampling that ignores time ordering, using inappropriate performance metrics, and chasing false discoveries. It is written from the position of someone who has watched many funds die. Each item is a paragraph or two, so it reads fast.

Why it matters for an agent-run shop: item one, the failure of the lone quant doing everything, is precisely the failure mode a multi-agent setup is supposed to fix, and the paper tells you what the specialised roles should be.

**Flight reading** once downloaded.

---

## Section 5. Operations for an autonomous system

This is the part almost nobody writes a book about, which is why it is mostly documentation and regulation rather than literature.

#### FINRA Regulatory Notice 26-10: FINRA Adopts New Intraday Margin Standards to Replace the Day Trading Margin Requirements
FINRA, issued 20 April 2026, effective 4 June 2026 with an optional phase-in period ending 20 October 2027.
Where to get it: `https://www.finra.org/rules-guidance/notices/26-10`
Note: verified by fetching the notice page in this session. FINRA blocks plain command line downloads, so there is no local copy. Print it to PDF from a browser before the flight.

This is the biggest structural change to retail trading rules in twenty five years and it happened three months ago. FINRA has eliminated both the pattern day trader designation, meaning the old count of four day trades in five business days, and the $25,000 minimum equity requirement that went with it, replacing them with an intraday margin standard under FINRA Rule 4210 that watches account equity against exposure in real time rather than counting trades. The new mechanism is an intraday margin deficit, triggered when a transaction reduces withdrawal power below the maintenance requirement, which must be satisfied within five business days or the account is restricted from creating or increasing short positions or debit balances for 90 calendar days.

Why it matters for an agent-run shop: your account size no longer caps how often the system can trade intraday, which removes a constraint you may have planned around, but it replaces a rule you could count in code with a continuous margin condition your risk agent has to monitor and never breach.

Practical consequences to design for:
- There is no longer a trade-frequency check to implement. Delete it from the plan if it is there.
- There is now a continuous check to implement: available withdrawal power against maintenance margin, evaluated after every fill, not at end of day.
- The failure mode is now a 90 day freeze rather than a 90 day trade restriction, and 90 days of not being allowed to open short positions would end a strategy season. Treat any intraday margin deficit as a kill-switch event, not a warning.
- The phase-in to October 2027 means Interactive Brokers may apply the old rules, the new rules, or its own stricter house rules during the transition. **Confirm with IBKR directly what applies to your account before you size anything.** Brokers are permitted to be stricter than FINRA and usually are.

**Flight reading.** It is short and it is the current law.

#### Interactive Brokers order types and algos documentation
Interactive Brokers, ongoing. `https://www.interactivebrokers.com/en/trading/orders.php`

The full catalogue of order types IBKR supports, each with a description of behaviour and the products it works on. The ones to actually understand are limit, market, marketable limit, stop, stop limit, trailing stop, midprice, and the adaptive algo. The distinction that matters most is which order types guarantee price versus which guarantee execution, because an autonomous system will eventually hit a gap where it wanted one and got the other.

Why it matters for an agent-run shop: the Taiwan research says aggressive orders cause the losses, so your execution agent's default order type is a policy decision with measurable profit consequences, and this page is where you learn the options.

**Reference.** Read the page on the six order types you will actually use.

#### ib_async (formerly ib_insync) documentation
Ewald de Wit originally, now community maintained. `https://github.com/ib-api-reloaded/ib_async` and docs at `https://ib-api-reloaded.github.io/ib_async/`
Note: URLs unverified in this session.

The Python library nearly everyone uses to talk to Interactive Brokers, because the official IBKR API is awkward. Its docs cover connection handling, order placement, position reconciliation and the event-driven patterns you need. The original `ib_insync` was retired after its author's death in 2024 and `ib_async` is the maintained continuation, so make sure agents use the current one.

Why it matters for an agent-run shop: connection drops and stale position state are the two things that actually break unattended trading systems, and this library's docs are where the handling patterns are written down.

**Reference.**

#### Optimal Execution of Portfolio Transactions
Robert Almgren and Neil Chriss, Journal of Risk, 2000.
Local: `.../pdfs/AlmgrenChriss_2000_OptimalExecution.pdf`
Source: `https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf` (mirror, the original NYU link is dead)

The founding paper on how to break a large order into pieces, and the origin of the efficient frontier of trading strategies, which trades off market impact against timing risk. Trading fast costs you impact, trading slow costs you volatility risk, and the paper solves for the optimal schedule given your risk aversion. It is the intellectual basis for VWAP and TWAP execution algorithms.

Why it matters for an agent-run shop: at your size impact is small, but the framework is what makes "measure slippage" a well-defined activity rather than a slogan, and you will need it if the account grows.

**Reference.** Read the introduction and the conclusion, skip the stochastic calculus.

#### Algorithmic Trading and DMA: An Introduction to Direct Access Trading Strategies
Barry Johnson, 2010.
Where to get it: no free PDF. `https://www.algo-dma.com/` or Amazon.

The most complete single reference on order types, market microstructure by asset class, and execution algorithms, written before the current era but still the standard. It explains what a broker's algo is actually doing when you select it, which no broker's own documentation will tell you. It is dated on venues and regulation, current on mechanics.

Why it matters for an agent-run shop: it is the book to consult when you need to know what an order type really does at the exchange rather than what the broker's tooltip says.

**Reference only.** Dated in parts, expensive, still the standard.

#### The Science of Algorithmic Trading and Portfolio Management
Robert Kissell, 2013 (2nd edition 2021 as Algorithmic Trading Methods).
Where to get it: no free PDF. Elsevier store, `https://www.elsevier.com/books/algorithmic-trading-methods/kissell/978-0-12-815630-8`.

Kissell is the standard reference on transaction cost analysis, meaning how you measure whether your execution was good or bad after the fact. The core concept is implementation shortfall, the difference between the price you decided to trade at and the price you actually got, decomposed into delay, impact, timing and opportunity cost. This decomposition is what turns "slippage" into four numbers you can each act on.

Why it matters for an agent-run shop: without implementation shortfall measurement your agents cannot tell a strategy that stopped working from an execution process that got worse, and those need opposite responses.

**Reference.**

### Operational topics with no single good source

These matter more than any book on this list, and the honest answer is that the literature is thin. Notes on each so you know what you are looking for.

**Risk limits.** The three that matter for a small autonomous system are a per-position size cap, a portfolio-level volatility target, and a daily loss limit that halts trading. Carver's Systematic Trading is the best written source on the first two. The third is not in any book because it is a business decision, not a research one, so decide the number before you start and write it into config, not into an agent's judgment.

**Kill switches.** An autonomous system needs at least three independent stops: a loss-based stop, a behaviour-based stop that halts on anomalies like unexpected order rejections or position drift, and a human stop that you can hit from your phone. The important design property is that the kill switch must not depend on the same code path as the trading logic, because the most likely reason you need it is that the trading logic is misbehaving.

**Position reconciliation.** Every cycle, compare what your system thinks it holds against what IBKR says it holds, and halt on any mismatch. This is the single highest value piece of operational code you will write and it appears in almost no book. Carver's `pysystemtrade` repository has a real implementation.

**Slippage measurement.** Record, for every fill, the mid price at decision time, the mid price at submission, the fill price, and the timestamps. Those four numbers give you implementation shortfall. Do it from day one of paper trading, because you cannot reconstruct it later.

**Paper trading limits.** Paper fills at IBKR are optimistic, particularly for limit orders which often fill in paper when they would not in live. Assume your paper results overstate performance and plan to lose a meaningful chunk of the edge on going live.

---

## Section 6. Suggested flight order

If the flight is roughly eight hours and you want maximum value:

1. Bailey, Borwein, López de Prado and Zhu, Pseudo-Mathematics, 14 pages. Sets the correct scepticism.
2. Barber, Lee, Liu and Odean, The Cross-Section of Speculator Skill, 24 pages. Sets the correct expectation.
3. Narang, Inside the Black Box. Gives you the vocabulary and the shape of the machine.
4. Carver, Leveraged Trading or Systematic Trading. Gives you a system you could actually run.
5. FINRA Regulatory Notice 26-10. Short, current, changes your constraints.
6. Whatever Alpha Architect and Concretum posts you saved.

The three books above are not free, so buy the ebooks before you leave.

---

## Appendix A. PDFs downloaded to the local folder

Folder: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

Note that this folder is shared with other research agents working the same reading list, so it contains more files than the nine below. These nine are the ones this practitioner list cites.

| File | Paper | Pages |
|---|---|---|
| `BarberOdean_2000_TradingIsHazardous.pdf` | Barber and Odean 2000, Trading Is Hazardous to Your Wealth | 10 |
| `BarberLeeLiuOdean_2009_JustHowMuchDoInvestorsLose_Taiwan.pdf` | Barber, Lee, Liu, Odean 2009, Just How Much Do Individual Investors Lose by Trading? | 24 |
| `BarberLeeLiuOdean_2014_CrossSectionSpeculatorSkill_Taiwan.pdf` | Barber, Lee, Liu, Odean 2014, The Cross-Section of Speculator Skill | 24 |
| `BarberLeeLiuOdeanZhang_2020_DayTradingAndLearning_Taiwan.pdf` | Barber, Lee, Liu, Odean, Zhang, Do Day Traders Rationally Learn About Their Ability? | 34 |
| `Bailey_2014_PseudoMathematics.pdf` | Bailey, Borwein, López de Prado, Zhu 2014, Pseudo-Mathematics and Financial Charlatanism | 14 |
| `Bailey_2014_DeflatedSharpe.pdf` | Bailey and López de Prado 2014, The Deflated Sharpe Ratio | 22 |
| `Bailey_2017_ProbabilityBacktestOverfitting.pdf` | Bailey, Borwein, López de Prado, Zhu, The Probability of Backtest Overfitting | 34 |
| `Harvey_2016_CrossSectionExpectedReturns.pdf` | Harvey, Liu, Zhu 2016, ... and the Cross-Section of Expected Returns | 64 |
| `AlmgrenChriss_2000_OptimalExecution.pdf` | Almgren and Chriss 2000, Optimal Execution of Portfolio Transactions | short |

Every one of these was opened and the first page checked against the expected title, so none are wrong-file downloads.

## Appendix B. Downloads that failed

Four items could not be downloaded automatically. All four are free to download by hand in a browser.

1. **Chague, De-Losso and Giovannetti, Day Trading for a Living?** SSRN returns 403 to command line requests. The FGV institutional repository sits behind an Anubis bot-protection wall. Neither OpenAlex nor Semantic Scholar lists an open-access copy. Get it at `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101`.
2. **Harvey and Liu, Evaluating Trading Strategies.** SSRN 403. Get it at `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2474755`.
3. **López de Prado, The 10 Reasons Most Machine Learning Funds Fail.** SSRN 403, and the author's own site serves its publications page through HTML frames with no extractable links. Get it at `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816`.
4. **AQR research papers** including Fact, Fiction and Momentum Investing and Trading Costs. The aqr.com PDF paths return an HTML bot-block to command line requests. Browse to `https://www.aqr.com/Insights/Research` and download in a browser.

FINRA Regulatory Notice 26-10 is also not stored locally for the same reason, but its content was fetched and verified in this session, so the summary in Section 5 is from the notice itself rather than from memory.

## Appendix C. Link verification status

Checked live in this session and responding normally: `quantpedia.com/strategies/`, `concretumgroup.com/research/`, `concretumgroup.com/articles/`, `robotwealth.com/blog/`, `quantocracy.com`, `twosigma.com/insights/`, `aqr.com/Insights/Research`, `github.com/quantopian/research_public`, `finra.org/rules-guidance/notices/26-10`.

Responded with a bot-block rather than content, meaning the site is live but would not talk to a script: `alphaarchitect.com/blog/`, SSRN, `repositorio.fgv.br`.

**Not verified in this session, treat as unconfirmed:** the `ib_async` GitHub and docs URLs, the `robcarver17/advanced_futures_trading_strategies` GitHub URL, and all publisher store links for the books (Wiley, Harriman House, Cambridge, Elsevier, algo-dma.com). Those are written from knowledge, not checked, so a couple may have moved.
