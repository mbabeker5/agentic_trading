# Reading list: classic systematic strategies a small automated shop can trade

Written 2026-09-06 for the agentic trading project.

**This file:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/01_anomalies.md`
**PDFs:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

Nineteen PDFs were downloaded for this list. Where a paper is behind a paywall or behind a bot check that blocks scripted downloads, the entry says so and gives you the page to open by hand.

Note on the pdfs folder: other research agents are writing into the same folder for other parts of this reading pack, so you will see files here that this list does not mention (large language model trading papers, backtest overfitting papers, and so on). Everything this document cites is listed with its exact filename.

---

## How to read this on a plane

Read in this order if you only get through part of it.

1. **Momentum, both kinds** (sections 1 and 2). This is the anchor. Everything else is a variation on "prices carry information that arrives slowly".
2. **Overnight versus intraday** (section 4). The single most useful fact for someone building a bot on a retail broker, because it tells you when the money is actually made.
3. **Opening range breakout** (section 11). The only section built on practitioner backtests rather than peer review, and the only one where day-one execution matters more than the idea.
4. **Everything else**, in whatever order.

Two things to hold in your head the whole time. First, almost every number you will read is a gross number, before commissions, before the bid-ask spread, before borrow fees on the short side, and before the fact that you cannot get filled at the closing price you backtested against. Second, published anomalies decay. McLean and Pontiff measured this across 97 predictors and found returns fall by roughly a third to a half after the paper comes out. Assume the paper is your ceiling, not your expectation.

**Difficulty ratings** in this document mean difficulty for a small account trading through Interactive Brokers with a Python agent, not academic difficulty. Easy means daily bars and a handful of trades a month. Hard means you need intraday data, borrow, or a lot of names at once.

---

## 1. Time-series momentum (trend following)

**Papers**

- Moskowitz, Ooi and Pedersen (2012), "Time Series Momentum", Journal of Financial Economics.
  Free PDF: https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf
  Local: `.../pdfs/Moskowitz_2012_TimeSeriesMomentum.pdf` (downloaded, 976 KB)
- Li, Sakkas and Urquhart (2021), "Intraday time series momentum: Global evidence and links to market characteristics", Journal of Financial Markets. Accepted manuscript, free from the University of Reading repository.
  Free PDF: https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf
  Local: `.../pdfs/Li_2021_IntradayTimeSeriesMomentumGlobal.pdf` (downloaded, 761 KB)
- Hurst, Ooi and Pedersen (2017), "A Century of Evidence on Trend-Following Investing", Journal of Portfolio Management. **Not downloaded.** AQR serves its PDFs behind a bot check that blocks scripts. Open https://www.aqr.com and search the title. **Link unverified.**

**What it says.** An asset that has gone up over the past twelve months tends to keep going up over the next month, and the same holds in reverse, and this is true of the asset against its own history rather than against other assets. Moskowitz and co-authors test 58 futures markets across equities, bonds, currencies and commodities from 1965 to 2009 and find the pattern in essentially all of them, with a diversified version reaching a Sharpe ratio near 1.0 before costs. The effect is old, wide and one of the better documented things in finance, but it has been visibly weaker since roughly 2010, and managed futures funds running exactly this trade have had a thin decade.

**Fit for agent automation.** Excellent fit: daily closes are enough, you rebalance monthly, decision latency is irrelevant, and capacity is effectively unlimited for an account of your size.

**Difficulty for a small account: easy.** The catch is that the clean version wants futures for diversification, and futures margin plus contract sizes are awkward on a small account. A liquid ETF basket is the practical substitute and it will not perform as well.

---

## 2. Cross-sectional momentum

**Papers**

- Jegadeesh and Titman (1993), "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency", Journal of Finance.
  Free PDF: https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf
  Local: `.../pdfs/Jegadeesh_Titman_1993_BuyingWinners.pdf` (downloaded, 623 KB)
- Asness, Moskowitz and Pedersen (2013), "Value and Momentum Everywhere", Journal of Finance.
  Free PDF: https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf
  Local: `.../pdfs/Asness_2013_ValueMomentumEverywhere.pdf` (downloaded, 2.1 MB)
- Daniel and Moskowitz (2014), "Momentum Crashes", NBER Working Paper 20439, later Journal of Financial Economics.
  Free PDF: https://www.nber.org/system/files/working_papers/w20439/w20439.pdf
  Local: `.../pdfs/Daniel_2014_MomentumCrashes.pdf` (downloaded, 8.9 MB)
- Ehsani and Linnainmaa (2019), "Factor Momentum and the Momentum Factor", NBER Working Paper 25551. Useful modern companion: it argues stock momentum is mostly momentum in the factors, not in individual stocks.
  Free PDF: https://www.nber.org/system/files/working_papers/w25551/w25551.pdf
  Local: `.../pdfs/Ehsani_2019_FactorMomentum.pdf` (downloaded, 713 KB)

**What it says.** Rank stocks by their return over the past twelve months skipping the most recent month, buy the top decile and sell the bottom decile, and the spread earned about one percent a month in US stocks from 1965 to 1989. The pattern shows up in every asset class and every country anyone has looked at, which is why the Asness paper is called "everywhere", and it is the hardest anomaly for the efficient-markets camp to explain away. The cost is tail risk: momentum crashes violently when a beaten-down market rebounds, losing more than half its value in a few months in 1932 and again in 2009, and Daniel and Moskowitz show these crashes are forecastable enough to scale exposure down in advance.

**Fit for agent automation.** Good fit on daily data with monthly rebalancing, but the long-short version needs shorting a hundred-plus names, which is where a small account runs into borrow availability and per-ticket commissions.

**Difficulty for a small account: medium.** Long-only momentum on a few hundred liquid US stocks is easy. The academic long-short spread is not realistically reachable below roughly a quarter of a million dollars.

---

## 3. Post-earnings-announcement drift (PEAD)

**Papers**

- Bernard and Thomas (1989), "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?", Journal of Accounting Research 27, pages 1 to 36. DOI 10.2307/2491062. **Not downloaded, no free PDF found.** Available through JSTOR or a university library. **Link unverified.**
- Livnat and Mendenhall (2006), "Comparing the Post-Earnings Announcement Drift for Surprises Calculated from Analyst and Time Series Forecasts", Journal of Accounting Research. DOI 10.1111/j.1475-679X.2006.00196.x. **Not downloaded, no free PDF found.** This is the one that matters practically, because it shows the drift is much stronger when you measure the surprise against analyst forecasts rather than against a naive seasonal model. **Link unverified.**
- Ball and Brown (1968), "An Empirical Evaluation of Accounting Income Numbers", Journal of Accounting Research. The origin of the whole literature. **Not downloaded.** **Link unverified.**

**What it says.** When a company reports earnings that beat expectations, the stock jumps on the day and then keeps drifting in the same direction for roughly the next sixty trading days, which should not happen if prices absorb news instantly. Sorting by standardised unexpected earnings, the top-minus-bottom decile spread was on the order of four to six percent over the drift window in the original work. The effect has shrunk since the 1990s and it lives mostly in smaller, less liquid, less analyst-covered names, which is exactly where your trading costs are worst.

**Fit for agent automation.** Very good fit in principle because it is a scheduled, calendar-driven event and an agent can process hundreds of earnings reports overnight, but you need a clean earnings surprise feed and analyst consensus data, and that is the expensive part.

**Difficulty for a small account: medium.** The trade itself is simple. Getting reliable point-in-time consensus estimates without survivorship or restatement bias is the real work, and free sources are unreliable here.

---

## 4. Overnight versus intraday returns

**Papers**

- Lou, Polk and Skouras (2019), "A tug of war: Overnight versus intraday expected returns", Journal of Financial Economics.
  Free PDF: http://personal.lse.ac.uk/polk/research/tugofwar.pdf
  Local: `.../pdfs/Lou_2019_TugOfWar.pdf` (downloaded, 1.7 MB)
- Cliff, Cooper and Gulen (2008), "Return Differences between Trading and Non-Trading Hours: Like Night and Day", SSRN 1004081, DOI 10.2139/ssrn.1004081. **Not downloaded.** SSRN blocks scripted downloads with a Cloudflare check. Open https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081 in a browser and the PDF is free. **Abstract ID verified through the DOI record; the page itself could not be loaded from this machine.**
- Berkman, Koch, Tuttle and Zhang (2012), "Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open", Journal of Financial and Quantitative Analysis. **Download failed** (Cambridge University Press returned a bot-check page). Search the title on Google Scholar for a free copy. **Link unverified.**

**What it says.** Almost the entire historical equity risk premium in US stocks was earned between the close and the next open, and the trading day itself has contributed close to nothing over long stretches. Lou, Polk and Skouras go further and show that momentum accrues overnight while reversal accrues intraday, and that the size and beta premia actually flip sign between the two sessions, which they attribute to different investor clienteles being active at different times of day. The pattern is large, has held for decades and across markets, but it is not free money: the overnight return is compensation for gap risk you cannot hedge, and the open is the worst-priced moment of the day to buy into.

**Fit for agent automation.** Ideal for an agent because the trade is two scheduled actions a day at fixed times and needs only open and close prices, but be aware that "buy at the close, sell at the open" on a retail broker gives up a lot of the effect to the opening auction spread.

**Difficulty for a small account: easy to medium.** Trading it on a single ETF is easy. Harvesting the cross-sectional version, where you need per-stock overnight and intraday returns separately, is medium.

---

## 5. Short-term reversal

**Papers**

- Lehmann (1990), "Fads, Martingales, and Market Efficiency", Quarterly Journal of Economics. The downloaded copy is NBER Working Paper 2533 from 1988, the pre-publication version of the same paper.
  Free PDF: https://www.nber.org/system/files/working_papers/w2533/w2533.pdf
  Local: `.../pdfs/Lehmann_1988_FadsMartingales.pdf` (downloaded, 918 KB)
- Nagel (2012), "Evaporating Liquidity", Review of Financial Studies. The downloaded copy is NBER Working Paper 17653.
  Free PDF: https://www.nber.org/system/files/working_papers/w17653/w17653.pdf
  Local: `.../pdfs/Nagel_2012_EvaporatingLiquidity.pdf` (downloaded, 450 KB)
- Jegadeesh (1990), "Evidence of Predictable Behavior of Security Returns", Journal of Finance. DOI 10.1111/j.1540-6261.1990.tb05110.x. **Not downloaded, no free PDF found.** **Link unverified.**

**What it says.** Over one week to one month, the pattern reverses: last week's losers beat last week's winners, and the gross spread was on the order of one and a half to two percent a month in the early studies. Nagel's paper is the one to actually read, because it reframes the whole thing: short-term reversal is not a market inefficiency, it is the fee you earn for providing liquidity to people who need to trade right now, and its return moves almost one for one with the VIX. That reframing tells you something important, which is that the strategy pays best exactly when it is most dangerous and when your broker is most likely to raise margin on you.

**Fit for agent automation.** Mechanically a fine fit, daily data and weekly rebalancing, but it is the anomaly most completely destroyed by transaction costs, because you are by construction buying what everyone is dumping.

**Difficulty for a small account: hard.** In large caps the spread is smaller than your round-trip cost. What survives is in small illiquid names where you cannot get size. Read it for the intuition about liquidity provision rather than as a strategy to run.

---

## 6. Pairs trading and statistical arbitrage basics

**Papers**

- Gatev, Goetzmann and Rouwenhorst (2006), "Pairs Trading: Performance of a Relative-Value Arbitrage Rule", Review of Financial Studies. The downloaded copy is NBER Working Paper 7032 from 1999.
  Free PDF: https://www.nber.org/system/files/working_papers/w7032/w7032.pdf
  Local: `.../pdfs/Gatev_1999_PairsTrading.pdf` (downloaded, 163 KB)
- Avellaneda and Lee (2010), "Statistical Arbitrage in the US Equities Market", Quantitative Finance.
  Free PDF: https://www.math.nyu.edu/~avellane/AvellanedaLeeStatArb20090616.pdf
  Local: `.../pdfs/Avellaneda_2010_StatArbUSEquities.pdf` (downloaded, 2.4 MB)
- Krauss (2017), "Statistical Arbitrage Pairs Trading Strategies: Review and Outlook", Journal of Economic Surveys. DOI 10.1111/joes.12153. A survey of the whole field, five families of method, very good for orientation. **Download failed**, the EconStor copy sits behind a consent page. Try https://www.econstor.eu and search the title. **Link unverified.**

**What it says.** Find two stocks whose prices have historically moved together, and when the gap between them opens unusually wide, short the rich one and buy the cheap one and wait for the gap to close. Gatev and co-authors ran the simplest possible version, minimum distance matching on normalised prices, and got about 1.4 percent a month on the top five pairs from 1962 to 2002, though the profit had already fallen close to zero by the end of their sample. Avellaneda and Lee is the more useful modern paper for a builder: it replaces hand-picked pairs with a principal components or ETF factor model and trades the residual, which is how the trade is actually done now, and it too shows decay from a Sharpe near 1.4 in the early 2000s.

**Fit for agent automation.** Good fit, because the whole thing is a statistical loop an agent can run daily on a few hundred names, though the honest version needs shorting and the residual model needs refitting on a rolling window.

**Difficulty for a small account: medium to hard.** The mean-reversion logic is easy to code. The hard parts are borrow on the short leg, position count, and knowing when a spread has stopped mean-reverting because something real changed at the company.

---

## 7. Seasonality and the turn-of-month effect

**Papers**

- Lakonishok and Smidt (1988), "Are Seasonal Anomalies Real? A Ninety-Year Perspective", Review of Financial Studies 1(4), pages 403 to 425. DOI 10.1093/rfs/1.4.403. **Not downloaded, no free PDF found.** An earlier attempt at an NBER copy pulled the wrong paper and was deleted. **Link unverified.**
- Ariel (1987), "A monthly effect in stock returns", Journal of Financial Economics. A free copy exists in the MIT institutional repository at http://hdl.handle.net/1721.1/48463 but the direct file link could not be resolved by script. **Not downloaded. Link unverified.**
- Etula, Rinne, Suominen and Vaittinen (2020), "Dash for Cash: Monthly Market Impact of Institutional Liquidity Needs", Review of Financial Studies 33(1), pages 75 to 111. SSRN 2528692. **Not downloaded**, Oxford University Press returned a bot-check page. This is the modern explanation, so it is worth fetching by hand.  **Link unverified.**
- Heston and Sadka (2008), "Seasonality in the cross-section of stock returns", Journal of Financial Economics. Shows that individual stocks have persistent same-calendar-month patterns. **Not downloaded, no free PDF found. Link unverified.**

**What it says.** Historically, most of the stock market's gain arrived in a narrow window around the turn of the month, roughly the last day and the first three days, with the rest of the month contributing close to nothing. Lakonishok and Smidt checked ninety years of Dow data specifically to see whether such patterns are real or the product of researchers torturing a calendar, and the turn-of-month effect was one of the few that survived. The modern explanation from Etula and co-authors is unglamorous and convincing: institutions have predictable cash needs at month end, they sell to raise cash, prices dip, and then recover, so the effect is a liquidity premium with a calendar attached rather than a mystery.

**Fit for agent automation.** Perfect fit for an agent in the sense that the entry and exit dates are known years in advance and need no data feed at all, which also means there is no edge in your speed or cleverness.

**Difficulty for a small account: easy.** It is the single easiest thing on this list to implement. It is also small in dollar terms, so treat it as a timing overlay on positions you were going to hold anyway rather than as a standalone strategy.

---

## 8. Index inclusion and ETF rebalancing flows

**Papers**

- Petajisto (2009), "Why Do Demand Curves for Stocks Slope Down?", Journal of Financial and Quantitative Analysis.
  Free PDF: https://www.petajisto.net/papers/petajisto%202009%20jfqa%20-%20demand%20curves.pdf
  Local: `.../pdfs/Petajisto_2009_WhyDemandCurvesSlopeDown.pdf` (downloaded, 212 KB)
- Petajisto (2011), "The index premium and its hidden cost for index funds", Journal of Empirical Finance.
  Free PDF: https://www.petajisto.net/papers/petajisto%202011%20jef%20-%20hidden%20cost%20for%20index%20funds.pdf
  Local: `.../pdfs/Petajisto_2011_IndexPremiumHiddenCost.pdf` (downloaded, 600 KB)
- Kappou, Brooks and Ward (2010), "The S&P500 index effect reconsidered: Evidence from overnight and intraday stock price performance and volume", Journal of Banking and Finance. Accepted manuscript from the University of Reading repository.
  Free PDF: https://centaur.reading.ac.uk/18666/1/18666.pdf
  Local: `.../pdfs/Kappou_2010_SP500IndexEffectReconsidered.pdf` (downloaded, 326 KB)
- Shleifer (1986), "Do Demand Curves for Stocks Slope Down?", Journal of Finance, and Harris and Gurel (1986) in the same issue. The two papers that started this. **Not downloaded**, Harvard's repository refused scripted access. **Links unverified.**

**What it says.** When a stock is added to a major index, every index fund has to buy it on the same day regardless of price, and the stock jumps, which is direct evidence that demand curves for individual stocks are not flat. The premium was around three percent in the 1980s and 1990s for S&P 500 additions and larger for Russell 2000 additions, and Petajisto's second paper flips the perspective to show this is a real hidden cost paid by index fund holders, in the range of twenty to fifty basis points a year. The trade has been largely arbitraged away since index providers moved to pre-announcing changes and staggering them, so most of the move now happens on announcement rather than on effective date.

**Fit for agent automation.** Reasonable fit, because index change announcements are public, scheduled and machine-readable, and an agent can watch S&P and FTSE Russell announcement feeds without difficulty.

**Difficulty for a small account: hard.** Not because the code is hard but because you are competing directly with desks whose entire job is this, the events are rare, and the remaining edge sits in the last minutes of the effective-date close where a retail order does badly.

---

## 9. Low volatility and quality factors

**Papers**

- Frazzini and Pedersen (2014), "Betting Against Beta", Journal of Financial Economics.
  Free PDF: https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf
  Local: `.../pdfs/Frazzini_2014_BettingAgainstBeta.pdf` (downloaded, 1.7 MB)
- Baker, Bradley and Wurgler (2011), "Benchmarks as Limits to Arbitrage: Understanding the Low-Volatility Anomaly", Financial Analysts Journal.
  Free PDF: https://pages.stern.nyu.edu/~jwurgler/papers/faj-benchmarks.pdf
  Local: `.../pdfs/Baker_2011_BenchmarksLimitsArbitrage.pdf` (downloaded, 572 KB)
- Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium", Journal of Financial Economics.
  Free PDF: https://mysimon.rochester.edu/novy-marx/research/OSoV.pdf
  Local: `.../pdfs/NovyMarx_2013_GrossProfitability.pdf` (downloaded, 326 KB)
- Asness, Frazzini and Pedersen (2019), "Quality Minus Junk", Review of Accounting Studies 24, pages 34 to 112. DOI 10.1007/s11142-018-9470-2. Marked open access at Springer but the file could not be pulled by script. Open https://link.springer.com/article/10.1007/s11142-018-9470-2 and use the download button. **Not downloaded. Link unverified.**

**What it says.** Boring, low-beta, low-volatility stocks have historically delivered better risk-adjusted returns than exciting high-beta ones, which is the exact opposite of what the textbook predicts. Frazzini and Pedersen's explanation is that many investors cannot use leverage, so they buy high-beta stocks to get returns instead, bidding them up, and their betting-against-beta factor, long leveraged low-beta and short de-leveraged high-beta, has a Sharpe ratio around 0.78 in US stocks from 1926 to 2012. Novy-Marx's gross profitability result is the companion on the quality side: profitable firms outperform unprofitable ones by about as much as cheap firms outperform expensive ones, and the two work well together because profitability is what stops value screens from buying broken companies.

**Fit for agent automation.** Very good fit, because these are slow signals built from annual accounting data and rolling volatility estimates, and an agent can rebalance quarterly with no timing pressure at all.

**Difficulty for a small account: easy long-only, hard long-short.** A long-only low-volatility and high-profitability screen on a few hundred US stocks is genuinely straightforward. The academic factor requires leverage on the long side and shorting on the short side, and without both you get a much weaker version.

---

## 10. Insider buying

**Papers**

- Lakonishok and Lee (2001), "Are Insiders' Trades Informative?", Review of Financial Studies. The downloaded copy is NBER Working Paper 6656 from 1998.
  Free PDF: https://www.nber.org/system/files/working_papers/w6656/w6656.pdf
  Local: `.../pdfs/Lakonishok_1998_AreInsiderTradesInformative.pdf` (downloaded, 1.7 MB)
- Jeng, Metrick and Zeckhauser (2003), "Estimating the Returns to Insider Trading: A Performance-Evaluation Perspective", Review of Economics and Statistics. The downloaded copy is NBER Working Paper 6913, titled "The Profits to Insider Trading: A Performance-Evaluation Perspective".
  Free PDF: https://www.nber.org/system/files/working_papers/w6913/w6913.pdf
  Local: `.../pdfs/Jeng_1998_ProfitsToInsiderTrading.pdf` (downloaded, 265 KB)
- Cohen, Malloy and Pomorski (2012), "Decoding Inside Information", Journal of Finance. The downloaded copy is NBER Working Paper 16454.
  Free PDF: https://www.nber.org/system/files/working_papers/w16454/w16454.pdf
  Local: `.../pdfs/Cohen_2010_DecodingInsideInformation.pdf` (downloaded, 219 KB; this file was already in the folder from a parallel research agent, so this list points at the existing copy rather than making a duplicate)

**What it says.** Company insiders buying their own stock is a mildly positive signal, worth roughly four to six percent of abnormal return over the following year in the older studies, and insider selling tells you almost nothing because insiders sell for a hundred innocent reasons. Jeng, Metrick and Zeckhauser put a cleaner number on the buy side, around six percent a year, and show the sell side is essentially flat. Cohen, Malloy and Pomorski add the single most useful practical refinement in this literature: separate insiders who trade on a predictable routine schedule from opportunistic ones who do not, throw away the routine trades, and the remaining opportunistic buys carry roughly eighty basis points a month.

**Fit for agent automation.** Excellent fit and arguably the best data-availability story on this list, because SEC Form 4 filings are free, structured, and available through the EDGAR full-text and RSS feeds within a day or two of the trade.

**Difficulty for a small account: easy.** Free data, low trade frequency, no shorting, long holding periods. The work is in the classification logic, which is exactly the kind of judgement task a language model agent is genuinely good at.

---

## 11. Opening range breakout (ORB)

**Papers**

- Zarattini and Aziz (2023), "Can Day Trading Really Be Profitable?", SSRN 4416622, DOI 10.2139/ssrn.4416622. **Not downloaded.** SSRN serves a Cloudflare bot check that blocks scripted downloads, so open https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622 in a browser and click the free download. **Title, authors and year verified through the DOI record at OpenAlex; the SSRN page itself could not be loaded from this machine.**
- Zarattini, Barbon and Aziz (2024), "A Profitable Day Trading Strategy For The U.S. Equity Market", SSRN 4729284, DOI 10.2139/ssrn.4729284. **Not downloaded**, same reason. Page: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284. **Title, authors and year verified through the DOI record at OpenAlex, which also lists a copy in the University of St Gallen repository at https://www.alexandria.unisg.ch/handle/20.500.14171/122125, though that record carries no PDF either.**
- For the peer-reviewed cousin of the same idea, read the Li, Sakkas and Urquhart intraday time-series momentum paper listed in section 1, which is downloaded and free.

**What it says.** The opening range breakout rule says: watch the first five minutes of trading, and if price then breaks above that range go long with a stop below it, or below the range go short, exiting at the close. Zarattini and Aziz apply this to the Nasdaq-100 ETF and its leveraged cousin over 2016 to 2023 and report a net Sharpe ratio above one after realistic commissions, and the 2024 paper with Barbon extends it to a filtered universe of individual US stocks screened on relative volume and gap size, reporting very large gross numbers. Treat both as careful practitioner backtests rather than settled science: the results lean heavily on the stock selection filter, on being able to short small caps, and on slippage assumptions that a retail account will not match, and neither paper has been through peer review.

**Fit for agent automation.** This is the one strategy on the list where automation is not optional, because the decision has to be made within seconds of the range completing and no human can screen several thousand tickers at 09:35, but it also demands a real-time intraday data subscription and low-latency order routing.

**Difficulty for a small account: hard.** Intraday minute data, pattern day trader rules if you are under twenty-five thousand dollars in the US, borrow for the short side, and the highest sensitivity to execution quality of anything here. Read it, paper trade it for months, and do not size it until you can reproduce their numbers on your own fills.

---

## 12. The paper to read before you believe any of the above

- McLean and Pontiff (2016), "Does Academic Research Destroy Stock Return Predictability?", Journal of Finance, DOI 10.1111/jofi.12365. **Not downloaded, no free PDF found.** An earlier attempt pulled the wrong NBER working paper and was deleted. **Link unverified.**

They take 97 published predictors, and re-run each one on data after the sample the paper used and again after the paper was published. Returns fall about a quarter out of sample, and about a half after publication. The decay is bigger for anomalies in liquid, easy-to-short, heavily-traded stocks, which is to say, exactly the ones a small account can actually trade.

There is a related paper already sitting in the pdfs folder from a parallel agent, `Harvey_2016_CrossSectionExpectedReturns.pdf`, on why most published factors are probably statistical flukes. Worth reading alongside.

---

## Quick summary table

| Strategy | Difficulty for a small account | Data you need | Rebalance |
|---|---|---|---|
| Time-series momentum | Easy | Daily closes | Monthly |
| Cross-sectional momentum | Medium | Daily closes, wide universe | Monthly |
| PEAD | Medium | Earnings surprise plus analyst consensus | Event driven |
| Overnight versus intraday | Easy to medium | Daily open and close | Twice daily |
| Short-term reversal | Hard | Daily closes | Weekly |
| Pairs and stat arb | Medium to hard | Daily closes, borrow | Daily |
| Turn of month | Easy | A calendar | Monthly |
| Index inclusion | Hard | Index announcement feeds | Event driven |
| Low volatility and quality | Easy long-only | Daily closes plus annual fundamentals | Quarterly |
| Insider buying | Easy | SEC Form 4, free | Weekly |
| Opening range breakout | Hard | Real-time minute bars | Intraday |
