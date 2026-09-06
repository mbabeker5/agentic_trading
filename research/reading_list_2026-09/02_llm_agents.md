# Reading list 02: language models and AI agents in trading

Compiled 6 September 2026 for the agentic trading project.

**Where this lives:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/02_llm_agents.md`
**PDFs:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/pdfs/`

Every paper below with a PDF filename is already downloaded to that folder, so the whole list reads offline. Filenames are given in full so you can open one straight from the folder without hunting.

## How to read this on a flight

If you only have time for six papers, read them in this order and you will have the whole argument:

1. Ding et al 2024 (the survey), for the map of the field.
2. Lopez-Lira and Tang 2023, the paper that started the excitement.
3. Glasserman and Lin 2023, the paper that explains why the excitement might be an illusion.
4. Chen et al 2025 (StockBench), the honest scorecard.
5. Chen et al 2025 (Standard Benchmarks Fail), the risk view.
6. Na et al 2026 (Poisoning Agentic Alpha), the security view.

That sequence takes you from "this looks like free money" to "here is exactly how it breaks", which is the correct emotional arc before you put a single dollar in.

## Honesty ratings used below

- **Peer-reviewed**: published in a refereed journal or a refereed conference.
- **Preprint**: on arXiv or SSRN or a working paper series, not yet through refereeing. Treat the headline number as the authors' best case.
- **Preprint, author-flagged caution**: the authors themselves have marked the results as provisional.
- **Vendor or promotional**: written partly to sell something, whether a product, a lab, or a research agenda.

A note on the whole field before you start. Almost everything in sections F and G is a preprint written by an AI lab or a computer science group, not a finance group, and most of it reports a backtest the authors designed and ran themselves. That is not fraud, but it is the same setup that produced a decade of overfitted quant papers. Read the returns as upper bounds.

---

## Section A. Start here, to get the shape of the field

### 1. Ding, Li, Wang et al 2024, "Large Language Model Agent in Financial Trading: A Survey"
- PDF: https://arxiv.org/pdf/2408.06361 (local: `Ding_2024_LLMAgentInFinancialTradingSurvey.pdf`)
- This surveys the LLM agents people have built for trading, sorting them by what data they read, what memory they keep, and what actions they take. The evidence is a structured review of the published systems rather than any new experiment of its own. Its most useful contribution is the honest observation that the field's evaluation practices are inconsistent enough that cross paper comparisons of returns are close to meaningless.
- **Copy this:** use its taxonomy of agent components (data, memory, reflection, action) as the architecture checklist for your own system, so you know which piece you are actually building at any moment.
- **Honesty: preprint.**

### 2. Nie, Kong, Dong et al 2024, "A Survey of Large Language Models for Financial Applications: Progress, Prospects and Challenges"
- PDF: https://arxiv.org/pdf/2406.11903 (local: `Nie_2024_SurveyLLMsForFinancialApplications.pdf`)
- A wider survey covering everything finance-adjacent that people point language models at, from filings analysis to advisory chatbots to trading. The evidence base is again a literature review, with a useful catalogue of which financial datasets and benchmarks exist. Read it for the section on challenges, where the authors are blunt about hallucination and data contamination.
- **Copy this:** the dataset appendix tells you which free financial text corpora exist, which saves you a week of hunting.
- **Honesty: preprint.**

---

## Section B. Can a language model predict returns from news?

This is the section that makes people quit their jobs. Read section C immediately afterwards.

### 3. Lopez-Lira and Tang 2023 (latest revision October 2025), "Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models"
- PDF: https://arxiv.org/pdf/2304.07619 (local: `LopezLira_2023_CanChatGPTForecastStockPriceMovements.pdf`)
- The authors hand news headlines to ChatGPT with no financial fine-tuning at all and ask whether the news is good or bad for the stock, then trade on the answer. Using headlines from after the model's knowledge cutoff, GPT-4 gets roughly 90 percent portfolio-day hit rates on the initial, non-tradable market reaction, and the scores also predict the subsequent drift, most strongly in small stocks and on negative news. The 2025 revision adds the finding that most matters to you: strategy returns decline as more of the market adopts language models, which is exactly what you would expect if the edge is real and being competed away.
- **Copy this:** the core prompt design, which is deliberately simple, plus the discipline of testing only on headlines dated after the model's training cutoff.
- **Honesty: peer-reviewed** (the acknowledgements name a journal editor and two anonymous referees; earlier versions circulated as a preprint, so make sure you are reading the current one).

### 4. Chen, Kelly and Xiu 2024, "Expected Returns and Large Language Models"
- PDF: https://mgmt675-2025.kerryback.com/assets/ExpectedReturns_LLMs.pdf (local: `Chen_2024_ExpectedReturnsAndLargeLanguageModels.pdf`)
- Rather than asking a chatbot for a verdict, this team pulls the numerical representations that a language model builds internally when reading a news article and feeds those into a return prediction model. Across 16 global equity markets and 13 languages, these representations beat both simple bag-of-words sentiment and standard technical signals, with the advantage largest in articles containing negation or complicated narratives. Their reading is that prices respond slowly to news, and that the language model's edge comes from actually understanding context rather than counting positive words.
- **Copy this:** the idea of using embeddings as a feature rather than asking the model for a buy or sell verdict, which is cheaper, faster, and much easier to backtest honestly.
- **Honesty: preprint** (the Chicago Booth and Wharton copies circulating online are presentation slides, so check you have the full paper; the local copy is the full paper).

### 5. Ke, Kelly and Xiu 2019, "Predicting Returns with Text Data"
- PDF: https://www.nber.org/system/files/working_papers/w26186/w26186.pdf (local: `Ke_2019_PredictingReturnsWithTextData.pdf`)
- This predates the language model era and builds a sentiment score by supervised learning: it picks the words that actually predict returns, weights them, and aggregates them, all trained against the return outcome rather than against a generic sentiment dictionary. Tested on Dow Jones Newswires, it substantially outperforms both dictionary methods and commercial vendor sentiment scores. The theoretical guarantees the authors derive are unusual for this literature and make the method easy to trust.
- **Copy this:** run it as your baseline. If your language model pipeline cannot beat this much simpler and much cheaper method, you have not found anything.
- **Honesty: peer-reviewed** (published in the Review of Financial Studies; the NBER working paper version linked here is free).

### 6. Kirtac and Germano 2024, "Sentiment trading with large language models"
- PDF: https://arxiv.org/pdf/2412.19245 (local: `Kirtac_2024_SentimentTradingWithLLMs.pdf`)
- The authors run OPT, BERT, FinBERT and the Loughran-McDonald dictionary over 965,375 US financial news articles from 2010 to 2023 and compare them head to head. The GPT-3-based OPT model reaches 74.4 percent directional accuracy, and a long-short strategy on its scores reports a Sharpe ratio of 3.05 after 10 basis points of transaction cost, with a 355 percent gain from August 2021 to July 2023. Those numbers are extraordinary, and the sample period overlaps the models' training data, so read this alongside section C rather than on its own.
- **Copy this:** the horse race design, comparing four methods on identical data, is the right way to decide whether a bigger model is worth its cost.
- **Honesty: peer-reviewed** (Finance Research Letters), **but treat the Sharpe ratio as an upper bound** for the leakage reasons below.

### 7. Bybee 2023, "The Ghost in the Machine: Generating Beliefs with Large Language Models"
- PDF: https://lelandbybee.com/files/LLM.pdf (local: `Bybee_2023_GhostInTheMachine.pdf`)
- Instead of asking a model to predict returns, Bybee asks it to role-play as a survey respondent reading historical news and to state its expectations, then compares those synthetic expectations to real recorded survey data from the same dates. The model reproduces documented human forecasting patterns, including the systematic errors, which suggests it has absorbed how people react to news rather than what actually happened next. This is a different and rather deeper use of a language model: as a cheap simulator of market sentiment rather than as an oracle.
- **Copy this:** the technique of generating expectations rather than predictions, which gives you a sentiment input that does not require the model to know the future.
- **Honesty: preprint.**

### 8. Fatouros, Soldatos, Kouroumali et al 2023, "Transforming Sentiment Analysis in the Financial Domain with ChatGPT"
- PDF: https://arxiv.org/pdf/2308.07935 (local: `Fatouros_2023_TransformingSentimentAnalysisFinance.pdf`)
- A practical study of prompt engineering for financial sentiment, testing several prompt formats on foreign exchange news and comparing against FinBERT. The finding is that a carefully written prompt matters a great deal, with well-designed zero-shot prompts beating the fine-tuned specialist model. It is a small paper on a small dataset, so treat the size of the improvement lightly and the direction of it seriously.
- **Copy this:** the prompt templates themselves, which are reproduced in the paper and are a reasonable starting point for your own.
- **Honesty: preprint.**

---

## Section C. The leakage problem, or why section B might be an illusion

This is the most important section in the list for someone about to build a system. A language model trained through 2024 has read what happened in 2019. If you backtest it on 2019, you are not testing prediction, you are testing memory. The field has spent three years working out how badly this contaminates results, and the answer is: quite badly, but in more interesting ways than you would guess.

### 9. Glasserman and Lin 2023, "Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis"
- PDF: https://arxiv.org/pdf/2309.17322 (local: `Glasserman_2023_LookAheadBiasGPTSentiment.pdf`)
- The authors separate two distinct problems: look-ahead bias, where the model remembers what the stock did after that news, and a distraction effect, where the model's general knowledge of a well-known company drowns out the actual sentiment of the text. They test both by stripping company names out of the headlines and comparing performance. The surprising result is that inside the training window, the anonymised headlines perform better, which means distraction hurts more than memory helps, and the effect is strongest for large well-known companies.
- **Copy this:** anonymise company identifiers in your prompts. It is a one-line change, it removes the leakage argument, and on this evidence it may improve live performance too.
- **Honesty: preprint,** from two Columbia authors with a strong track record.

### 10. Gao, Jiang and Yan 2025, "Detecting Lookahead Bias in LLM Forecasts"
- PDF: https://arxiv.org/pdf/2512.23847 (local: `Gao_2025_DetectingLookaheadBiasInLLMForecasts.pdf`)
- The authors build a statistical test: for each firm and date, they ask the model a date-only recall question to estimate how likely it is that the model already knows the outcome, a number they call Lookahead Propensity. That number is materially positive throughout the training window and collapses to almost zero immediately after the training cutoff, which is exactly the fingerprint of contamination. When they apply the test to news headlines predicting returns and to earnings calls predicting capital expenditure, the model's apparent skill is concentrated in the high-propensity cases and vanishes out of sample.
- **Copy this:** run their recall probe on any historical period before you trust a backtest on it. It is cheap and it will save you from your own results.
- **Honesty: preprint.**

### 11. Li, Wang and Ma 2026, "Summoning the Oracle to Slay It: Mitigating Look-Ahead Bias in Financial Backtesting with Large Language Models"
- PDF: https://arxiv.org/pdf/2605.24564 (local: `Li_2026_SummoningTheOracleLookAheadBiasBacktesting.pdf`)
- The authors name the problem parametric look-ahead bias, meaning the future is baked into the model's weights rather than into your data, and they propose a fix that runs at inference time without retraining anything. Across five models between 7 and 14 billion parameters and five mega-cap stocks, their correction cuts the largest inflated in-sample return by 67.1 percent while leaving genuine out-of-sample performance broadly intact. On an eleven-model leaderboard, applying the correction raises the correlation between in-sample and out-of-sample rankings from 0.78 to 0.85, meaning backtest rank becomes a more honest guide to live rank.
- **Copy this:** the headline number to remember is that two thirds of an in-sample return can be memory. Assume that about your own results until you have proved otherwise.
- **Honesty: preprint.**

### 12. Roy and Roy 2026, "MemGuard-Alpha: Detecting and Filtering Memorization-Contaminated Signals in LLM-Based Financial Forecasting"
- PDF: https://arxiv.org/pdf/2603.26797 (local: `Roy_2026_MemGuardAlpha.pdf`)
- Rather than fixing the model, this filters the signals: it scores each generated signal for how likely it is to be memorised, using membership inference tests and, more cleverly, disagreement between models with different training cutoff dates. Across seven models, 50 S&P 100 stocks and 42,800 prompts over 2019 to 2024, filtered signals produce a Sharpe ratio of 4.11 against 2.76 unfiltered, and clean signals earn 14.48 basis points a day against 2.13 for tainted ones. The single most damning chart in the whole reading list is here: as contamination rises, in-sample accuracy climbs from 40.8 to 52.5 percent while out-of-sample accuracy falls from 47 to 42 percent.
- **Copy this:** the cross-model disagreement trick is genuinely cheap for a small shop. Ask two models with different cutoff dates the same question, and distrust the answer where the older one is suspiciously confident.
- **Honesty: preprint,** and the reported Sharpe ratios are high enough that you should treat the method as promising rather than proven.

### 13. Zhu, Zhao, Sun et al 2026, "From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents on Stock Markets"
- PDF: https://arxiv.org/pdf/2605.28359 (local: `Zhu_2026_FromKnowingToDoingMemoryControlledBenchmark.pdf`)
- This benchmark attacks two problems at once: it masks tickers, dates and prices so the model cannot recognise the period, and it decomposes returns into market exposure, style exposure and genuine stock selection. Testing ten frontier models on Chinese CSI300 data over 2024 to 2026, masking visibly changes how the agents reason, pushing them towards generic factor logic. The conclusion is the one you should carry into your own project: once leakage is controlled, the agents' returns are largely explained by passive market and style exposure, with little evidence of persistent stock-picking skill.
- **Copy this:** always decompose your own returns into market, style and selection before celebrating. Most apparent alpha is beta you did not notice you were buying.
- **Honesty: preprint.**

### 14. Ludwig, Mullainathan and Rambachan 2024, "Large Language Models: An Applied Econometric Framework"
- PDF: https://arxiv.org/pdf/2412.07031 (local: `Ludwig_2024_LLMsAppliedEconometricFramework.pdf`)
- Three serious economists ask, formally, when it is valid to use a language model's output as data in an empirical study. They show that using a model to construct a variable and then using that variable in a prediction task requires assumptions that often fail, particularly training leakage, and they set out testable conditions for when it is safe. It is more abstract than the other papers here and worth the effort, because it tells you which of your own uses are defensible and which are not.
- **Copy this:** their distinction between using a model to measure something (often fine) and using it to predict an outcome it may have memorised (often not).
- **Honesty: preprint,** by authors whose applied econometrics work is peer-reviewed and widely cited.

### 15. Sarkar and Vafa 2024, "Lookahead Bias in Pretrained Language Models"
- Link: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4754678 and https://openreview.net/forum?id=fn9cJkB86T
- **PDF NOT DOWNLOADED.** SSRN and OpenReview both refused automated download (HTTP 403). The paper's existence, title, authors and 2024 date are verified through OpenAlex, but the links above are **unverified** in the sense that I could not open them to confirm they resolve for you. It appeared at ICML 2025, so a proceedings copy may exist by the time you look.
- The paper demonstrates that pretrained models leak future information even on tasks where you would not expect it, and proposes a masking approach for financial text. I have summarised it from its abstract record rather than from the full text, so treat this entry as a pointer rather than a review.
- **Honesty: preprint** (conference paper).

---

## Section D. Reading filings and earnings calls

The pre-LLM work in this section is the foundation. It is also better science than most of the newer material, because it was done by finance academics with proper out-of-sample discipline.

### 16. Tetlock 2007, "Giving Content to Investor Sentiment: The Role of Media in the Stock Market"
- PDF: https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf (local: `Tetlock_2007_GivingContentToInvestorSentiment.pdf`)
- The paper that founded this whole literature, using a simple count of negative words in the Wall Street Journal's daily "Abreast of the Market" column. High pessimism predicts downward pressure on prices followed by a reversion to fundamentals, and unusually high or low pessimism predicts higher trading volume. It is a beautifully clean study, and it is worth reading purely to see how much can be done with word counting and care.
- **Copy this:** the reversal structure. Sentiment moves price temporarily and then unwinds, which tells you the holding period for a sentiment signal is short.
- **Honesty: peer-reviewed** (Journal of Finance).

### 17. Loughran and McDonald 2011, "When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks"
- PDF: https://www.uts.edu.au/globalassets/sites/default/files/adg_cons2015_loughran-mcdonald-je-2011.pdf (local: `LoughranMcDonald_2011_WhenIsALiabilityNotALiability.pdf`)
- The authors show that the general-purpose Harvard psychological dictionary badly misclassifies financial writing, because words like liability, tax, cost and capital are negative in ordinary English but neutral in a 10-K. They build a finance-specific word list instead and show it produces stronger and more sensible links between filing tone and returns, volatility and trading volume. The Loughran-McDonald word lists that came out of this paper are free and are still the standard baseline that every new method has to beat.
- **Copy this:** use the free word lists as your zero-cost benchmark. Their 2016 survey, "Textual Analysis in Accounting and Finance: A Survey" in the Journal of Accounting Research, is the natural follow-up, though I found no free PDF for it.
- **Honesty: peer-reviewed** (Journal of Finance).

### 18. Araci 2019, "FinBERT: Financial Sentiment Analysis with Pre-trained Language Models"
- PDF: https://arxiv.org/pdf/1908.10063 (local: `Araci_2019_FinBERT.pdf`)
- Takes BERT and further trains it on financial text, then fine-tunes it for sentiment classification, reporting clear gains over general-purpose models on standard financial sentiment datasets. It is a masters thesis in origin and modest in scope, but the released model became the workhorse of the field. Read it mainly to understand what FinBERT actually was trained on, which matters when you are deciding whether to trust it on your data.
- **Copy this:** FinBERT itself. It is free, it runs on a laptop, and it costs nothing per call, which makes it the right first pass before you spend money on a frontier model.
- **Honesty: preprint.**

### 19. Yang, UY and Huang 2020, "FinBERT: A Pretrained Language Model for Financial Communications"
- PDF: https://arxiv.org/pdf/2006.08097 (local: `Yang_2020_FinBERT_FinancialCommunications.pdf`)
- A separate and larger effort under the same name, pretrained on a much bigger corpus of corporate reports, earnings call transcripts and analyst reports. It reports better performance than both general BERT and the earlier FinBERT on financial sentiment tasks. The confusing part is that two different models share the name, so check which one a paper means before you compare results.
- **Copy this:** this is the version to use if your inputs are filings and call transcripts rather than news headlines.
- **Honesty: preprint.**

### 20. Kim, Muhn and Nikolaev 2024, "Financial Statement Analysis with Large Language Models"
- PDF: https://arxiv.org/pdf/2407.17866v2 (local: `Kim_2024_FinancialStatementAnalysisWithLLMs.pdf`)
- The authors hand GPT-4 standardised and anonymised financial statements, with no company name, no industry and no narrative, and ask it to say whether earnings will go up or down. It beats human analysts at directional prediction, matches a purpose-built machine learning model, and does best in exactly the cases where analysts struggle. Because the statements are anonymised, the usual memorisation objection is much weaker here than elsewhere in this list, and the trading strategies built on its predictions show higher Sharpe ratios than the comparison models.
- **Copy this:** the anonymisation protocol. It is the cleanest demonstration in the literature that a model can reason about numbers rather than recall an outcome.
- **Honesty: preprint,** and among the most careful in this list.

### 21. Kim, Muhn and Nikolaev 2023, "From Transcripts to Insights: Uncovering Corporate Risks Using Generative AI"
- PDF: https://arxiv.org/pdf/2310.17721 (local: `Kim_2023_FromTranscriptsToInsights.pdf`)
- The same team uses GPT to read earnings call transcripts and produce firm-level measures of exposure to political, climate and AI risk, then shows those measures predict firm volatility and corporate choices better than existing risk measures. They report that the model's assessments beat its own summaries, which they read as evidence that general world knowledge is doing real work. **Read the front page carefully:** the current version carries an explicit caveat notice from the authors saying the findings are preliminary and that they are re-evaluating their data, methods and conclusions.
- **Copy this:** the idea of extracting a risk exposure score rather than a direction, since risk is a much easier thing for a model to read off a transcript than a return is.
- **Honesty: preprint, author-flagged caution.** This is the one paper in the list whose own authors have publicly hedged it.

### 22. Jha, Qian, Weber and Yang 2024, "ChatGPT and Corporate Policies"
- PDF: https://www.nber.org/system/files/working_papers/w32161/w32161.pdf (local: `Jha_2024_ChatGPTAndCorporatePolicies.pdf`)
- The authors build a firm-level investment score from conference calls, capturing what managers seem to expect to do with capital spending, and validate it against actual CFO survey responses. The score predicts capital expenditure up to nine quarters ahead after controlling for the standard determinants, and also forecasts intangible and R&D spending. For a trader the relevant line is that high-investment-score firms go on to earn significantly negative abnormal returns.
- **Copy this:** the validation step. They checked their model-derived measure against an independent human survey before trusting it, which is the discipline most of section F skips.
- **Honesty: preprint** (NBER working paper, not refereed), by established finance academics.

### 23. Hansen and Kazinnik 2023, "Can ChatGPT Decipher Fedspeak?"
- PDF: https://www.newyorkfed.org/medialibrary/media/research/conference/2023/FinTech/400pm_Hansen_Paper_Kazinnik_2023.pdf (local: `Hansen_2023_CanChatGPTDecipherFedspeak.pdf`)
- Two Richmond Fed researchers test whether GPT models can classify the policy stance of FOMC announcements against human assessments, and find a considerable improvement over the methods central bank watchers normally use. GPT-4 also produces explanations for its classifications that the authors judge comparable to human reasoning, and it can identify macroeconomic shocks using an established narrative method. It is a narrow task done properly, which makes it more convincing than most broader claims.
- **Copy this:** FOMC statements arrive on a known schedule at a known minute, which makes this the single most automatable reading task in markets.
- **Honesty: preprint** (Federal Reserve working paper), from a central bank research group with no product to sell.

### 24. Tong, Zhang, Tang et al 2026, "Are the Financial Reasoning from LLMs Credible? A Real World Test over Long-Horizon Statements"
- PDF: https://arxiv.org/pdf/2607.28661 (local: `Tong_2026_AreFinancialReasoningFromLLMsCredible.pdf`)
- This builds a benchmark over uncropped financial statements up to 32,000 tokens long and tests whether models can actually compute financial indices rather than pattern-match to familiar-looking tables. Two failures show up sharply: remove the explicit formula hint and performance collapses, with one frontier model dropping from 70.7 to 38.2 percent on table tasks, and asking for multi-metric multi-period tables drains the model's reasoning so badly that it regresses to grabbing the wrong adjacent column. It is the strongest available evidence that apparent financial competence is often shallow.
- **Copy this:** never ask an agent for a table of derived metrics in one shot. Ask for one number at a time, and supply the formula.
- **Honesty: preprint.**

---

## Section E. Event-driven strategies where reading speed matters

You asked which strategies gain most from an agent that can read around the clock. The honest answer from the literature is: fewer than you would hope, because the obvious ones have been arbitraged away. Two papers make that concrete.

### 25. Meursault, Liang, Routledge and Scanlon 2021 (revised 2022), "PEAD.txt: Post-Earnings-Announcement Drift Using Text"
- PDF: https://www.philadelphiafed.org/-/media/frbp/assets/working-papers/2021/wp21-07.pdf (local: `Meursault_2021_PEADtxt.pdf`)
- The authors build an earnings surprise measure from the text of the earnings call alone, without using the reported earnings number at all. That text-based surprise generates a drift larger than the classic post-earnings-announcement drift, and, crucially, it remains sizeable in recent years when the classic version has decayed to near zero. Their analysis of what the text is picking up suggests it is detail behind the headline number and firm fundamentals, not the number itself.
- **Copy this:** this is the best case in the entire list for an agent that reads. The numeric version of the signal is dead and the textual version is not, which is precisely the gap a reading agent fills.
- **Honesty: preprint** (Federal Reserve Bank of Philadelphia working paper), from a central bank research department.

### 26. Greenwood and Sammon 2022, "The Disappearing Index Effect"
- PDF: https://www.nber.org/system/files/working_papers/w30748/w30748.pdf (local: `Greenwood_2022_DisappearingIndexEffect.pdf`)
- The abnormal return from being added to the S&P 500 has fallen from 3.4 percent in the 1980s and 7.6 percent in the 1990s to 0.8 percent in the last decade, and the deletion effect has shrunk similarly to minus 0.6 percent. This happened despite index-linked assets growing enormously, which is the opposite of what a simple demand-curve story predicts. The authors work through the possible causes and discuss what it implies for market efficiency.
- **Copy this:** read this as a warning, not a strategy. Index announcement trading is the textbook example of a reading-speed edge, and it is gone. Assume the same has happened to any event strategy you can name in one sentence.
- **Honesty: preprint** (NBER working paper), subsequently published in the Journal of Finance.

A note on FDA decisions, which you asked about specifically. I did not find a strong recent open-access paper on trading FDA approval announcements, and I am not going to invent one. The general finding in that literature is that approval decisions move biotech prices sharply but that the PDUFA action dates are public in advance, so the edge is in interpreting the advisory committee documents rather than in learning the outcome first. Treat that as my summary of the area rather than as a cited finding, and if it matters to the project it deserves its own search.

---

## Section F. Multi-agent trading frameworks

This is where the field is loudest and the evidence is weakest. Every paper here reports beating a baseline. Almost none of them were tested by anyone other than their authors. Read the architectures, discount the returns.

### 27. Xiao, Sun, Luo and Wang 2024, "TradingAgents: Multi-Agents LLM Financial Trading Framework"
- PDF: https://arxiv.org/pdf/2412.20138 (local: `Xiao_2024_TradingAgents.pdf`)
- Models a trading firm as a set of specialised agents: fundamental, sentiment and technical analysts, then bull and bear researchers who debate, then a trader, then a risk manager. The debate structure is the interesting part, forcing the system to argue both sides before committing. The authors report improvements over baselines in cumulative return, Sharpe ratio and maximum drawdown, on their own backtest, with the usual training-window overlap problem unaddressed.
- **Copy this:** the bull versus bear debate step. It is the cheapest available guard against a single agent talking itself into a position.
- **Honesty: preprint,** and note it comes from Tauric Research, which makes it partly **promotional**.

### 28. Yu, Li, Chen et al 2023, "FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design"
- PDF: https://arxiv.org/pdf/2311.13743 (local: `Yu_2023_FinMem.pdf`)
- Introduces a layered memory system, splitting what the agent remembers into short, medium and long-term stores with different decay rates, plus a configurable risk personality. The design deliberately mirrors how a human trader's attention works, and the authors argue this makes the agent's decisions more interpretable. Reported performance beats the comparison agents, again on the authors' own setup.
- **Copy this:** the layered memory idea is the most reusable thing in this section, and it maps directly onto a small shop's need to keep context windows affordable.
- **Honesty: preprint.**

### 29. Yu, Yao, Li et al 2024, "FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement"
- PDF: https://arxiv.org/pdf/2407.06567 (local: `Yu_2024_FinCon.pdf`)
- The successor to FinMem from largely the same group, adding a manager-analyst hierarchy and a mechanism where the system critiques its own past decisions in words and feeds that critique forward. The claim is that this verbal self-correction improves both single-stock trading and portfolio management. It is a genuinely interesting idea and, as with the rest of the section, an unaudited one.
- **Copy this:** verbal self-critique after losing trades is easy to implement and costs one extra model call per decision.
- **Honesty: preprint.**

### 30. Zhang, Zhao, Xia et al 2024, "A Multimodal Foundation Agent for Financial Trading" (FinAgent)
- PDF: https://arxiv.org/pdf/2402.18485 (local: `Zhang_2024_FinAgent_MultimodalFoundationAgent.pdf`)
- Adds visual input to the mix, so the agent can look at price charts as images alongside reading news and numbers, and equips it with external tools including established trading rules. The authors report gains across six datasets covering stocks and crypto. Whether the chart images add anything beyond the numeric price series is not convincingly separated out.
- **Copy this:** the tool-augmentation pattern, where the agent calls a conventional technical indicator rather than trying to eyeball it.
- **Honesty: preprint.**

### 31. Zhang, Liu, Zhang et al 2024, "When AI Meets Finance (StockAgent)"
- PDF: https://arxiv.org/pdf/2407.18957 (local: `Zhang_2024_StockAgent.pdf`)
- Rather than trying to make money, this builds a simulated market populated by many LLM investor agents in order to study how external factors like macroeconomic news and policy changes propagate into trading behaviour. The authors explicitly design it to avoid the leakage that plagues historical backtests, which is a point in its favour. Its value to you is diagnostic rather than directly profitable.
- **Copy this:** the simulation approach is a safe sandbox for testing whether your prompt design produces sensible behaviour before you point it at real money.
- **Honesty: preprint.**

### 32. Wang, Yuan, Zhou et al 2023, "Alpha-GPT: Human-AI Interactive Alpha Mining for Quantitative Investment"
- PDF: https://arxiv.org/pdf/2308.00016 (local: `Wang_2023_AlphaGPT.pdf`)
- Positions the model as a collaborator in formula-based alpha mining, turning a human's stated trading intuition into candidate mathematical expressions, then feeding backtest results back for refinement. The loop keeps a human in the judgement seat, which is a more defensible division of labour than full autonomy. The paper comes out of an industry quant group, so read the reported results as a product demonstration.
- **Copy this:** the human-in-the-loop structure, which is very likely the right shape for a one-person shop.
- **Honesty: preprint, and substantially promotional.**

### 33. Yang, Liu and Wang 2023, "FinGPT: Open-Source Financial Large Language Models"
- PDF: https://arxiv.org/pdf/2306.06031 (local: `Yang_2023_FinGPT.pdf`)
- Describes an open-source pipeline for financial data ingestion and model fine-tuning, positioned as a free alternative to closed commercial financial models. The contribution is mostly infrastructure, covering data sourcing and cheap adapter-based fine-tuning, rather than a new empirical finding. It is useful precisely because it is free and documented.
- **Copy this:** the data-ingestion layer, which handles a lot of tedious plumbing you would otherwise write yourself.
- **Honesty: preprint, and promotional** for the authors' open-source project.

### 34. Yang, Zhang, Wang et al 2024, "FinRobot: An Open-Source AI Agent Platform for Financial Applications"
- PDF: https://arxiv.org/pdf/2405.14767 (local: `Yang_2024_FinRobot.pdf`)
- The same group's agent platform, layering financial workflows, multi-source data and model routing on top of the FinGPT work. It is a systems paper rather than a results paper, describing how to wire the pieces together. Useful as a reference architecture and as running code.
- **Copy this:** the model-routing idea, sending cheap queries to a small model and expensive judgement to a large one, which directly controls your API bill.
- **Honesty: preprint, and promotional.**

### 35. Gao, Wen, Zhu et al 2024, "Simulating Financial Market via Large Language Model based Agents"
- PDF: https://arxiv.org/pdf/2406.19966 (local: `Gao_2024_SimulatingFinancialMarketLLMAgents.pdf`)
- Another agent-based market simulation, this one focused on whether LLM-driven agents reproduce known stylised facts of real markets such as fat-tailed returns and volatility clustering. The authors report that they largely do, which is mildly reassuring about the realism of these sandboxes. It does not tell you anything about profitability.
- **Copy this:** use its stylised-fact checks as a sanity test on any simulation you build, so you know your sandbox is not producing a market that could not exist.
- **Honesty: preprint.**

### 36. Lopez-Lira 2025, "Can Large Language Models Trade? Testing Financial Theories with LLM Agents in Market Simulations"
- PDF: https://arxiv.org/pdf/2504.10789 (local: `LopezLira_2025_CanLargeLanguageModelsTrade.pdf`)
- Builds a properly specified simulated market with a persistent order book, limit orders, partial fills, dividends and equilibrium clearing, then populates it with LLM agents given different strategies and information. The agents stick to their assigned strategies consistently and the resulting market shows price discovery, bubbles, underreaction and strategic liquidity provision. The finding most relevant to risk is the last one: prompts that are similar to each other generate correlated behaviour, which affects market stability.
- **Copy this:** that last warning. If you run several agents off similar prompts, you have not diversified, you have built one agent with extra steps.
- **Honesty: preprint,** by the author of the paper that started section B, and noticeably more careful than the framework papers above.

---

## Section G. Do LLM trading agents actually make money out of sample?

The short answer from the best available evidence is: mostly no, and where they do, the returns look like market and style exposure rather than skill.

### 37. Chen, Yao, Liu et al 2025, "StockBench: Can LLM Agents Trade Stocks Profitably In Real-world Markets?"
- PDF: https://arxiv.org/pdf/2510.02209 (local: `Chen_2025_StockBench.pdf`)
- A deliberately contamination-free benchmark placing agents in multi-month trading environments where they get daily prices, fundamentals and news and must make buy, sell or hold decisions. Performance is scored on cumulative return, maximum drawdown and Sortino ratio, so risk is priced in rather than ignored. The headline result is that most state-of-the-art models, open and closed, fail to beat simple buy-and-hold, though a few show promise on risk management.
- **Copy this:** the benchmark itself is open source, so you can run your own agent through it before risking capital.
- **Honesty: preprint,** and one of the more trustworthy entries because the result is unflattering to the field.

### 38. Li, Shi, Luo and Tang 2025, "Will LLMs be Professional at Fund Investment? DeepFund: A Live Arena Perspective"
- PDF: https://arxiv.org/pdf/2503.18313 (local: `Li_2025_DeepFundLiveArena.pdf`)
- The authors identify four specific problems with existing financial benchmarks, which they name data leakage, navel-gazing, over-intervention and maintenance difficulty, and build a live arena that evaluates models forward in time instead. Because it runs live, no model can have memorised the outcomes. The platform and code are public, and the comparative results are visualised across market conditions.
- **Copy this:** the live-forward evaluation principle. For your own shop this means paper trading forward is worth more than any historical backtest you can construct.
- **Honesty: preprint.**

### 39. Li, Cao, Yu et al 2024, "InvestorBench: A Benchmark for Financial Decision-Making Tasks with LLM-based Agent"
- PDF: https://arxiv.org/pdf/2412.18174 (local: `Li_2024_InvestorBench.pdf`)
- A broader benchmark covering stock, cryptocurrency and exchange-traded fund decisions across a range of models, designed so that different agent architectures can be compared on identical footing. Its main service is standardisation, since before it every paper used its own setup. The results show wide variation across models and asset classes, with no architecture dominating.
- **Copy this:** use it as the shared yardstick when you compare your own agent against a published one, since like-for-like comparison is otherwise impossible.
- **Honesty: preprint.**

### 40. Zhang, Ge, Jiang et al 2026, "OpenFinGym: A Verifiable Multi-Task Gym Environment for Evaluating Quant Agents"
- PDF: https://arxiv.org/pdf/2606.26350 (local: `Zhang_2026_OpenFinGym.pdf`)
- Argues that evaluating agents on isolated tasks overstates their competence, because real financial work is multi-stage: forecast, then build a strategy, then manage risk, then trade. It provides a containerised environment with a host-side verifier specifically designed to prevent train-test leakage at runtime, plus a paper trading engine. It also includes deferred resolution for long-horizon forecasts, which matters if your agent makes calls that take months to settle.
- **Copy this:** the containerised verifier pattern, which is the right way to stop your own agent from accidentally seeing future data through a tool call.
- **Honesty: preprint.**

### 41. Park, Liu, Ozdaglar and Zhang 2024, "Do LLM Agents Have Regret? A Case Study in Online Learning and Games"
- PDF: https://arxiv.org/pdf/2403.16843 (local: `Park_2024_DoLLMAgentsHaveRegret.pdf`)
- Not a trading paper, but the sharpest theoretical account of whether an LLM agent actually learns from repeated interaction, measured by regret, which is the formal gap between what it earned and what the best fixed strategy would have earned. In some settings the agents achieve low regret, but in others, including simple ones, they fail, and the authors construct explicit cases where they do not converge. They also propose a training objective that improves the situation.
- **Copy this:** the regret framing. It gives you a principled way to ask whether your agent is learning or just varying, which raw profit-and-loss cannot answer.
- **Honesty: preprint,** from a serious MIT and Maryland optimisation group.

---

## Section H. Known failure modes

### 42. Chen, Chen, Chen and Sra 2025, "Standard Benchmarks Fail: Auditing LLM Agents in Finance Must Prioritize Risk"
- PDF: https://arxiv.org/pdf/2502.15865 (local: `Chen_2025_StandardBenchmarksFailAuditingLLMAgentsInFinance.pdf`)
- The authors argue that accuracy scores and return figures give an illusion of reliability while hiding hallucinated facts, stale data and vulnerability to adversarial prompts. They audit six models on three high-impact financial tasks and surface failures that conventional benchmarks miss entirely. Their proposal is a three-level stress-testing agenda at the model, workflow and system levels, with a "safety budget" treated as a primary success criterion.
- **Copy this:** their stress-test agenda, more or less directly, as the pre-deployment checklist for your own system.
- **Honesty: preprint,** explicitly written as a position paper, which makes it argumentative by design.

### 43. Greshake, Abdelnabi, Mishra et al 2023, "Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection"
- PDF: https://arxiv.org/pdf/2302.12173 (local: `Greshake_2023_IndirectPromptInjection.pdf`)
- The foundational paper on indirect prompt injection, showing that any application which feeds retrieved content to a model can be hijacked by instructions hidden inside that content. The authors demonstrate working attacks on real deployed systems, including data theft and manipulated outputs, with no access to the application's internals. For a trading agent the implication is direct: a news article, a press release or a social media post is untrusted input that can carry instructions.
- **Copy this:** treat every piece of text your agent reads as hostile. Strip instruction-shaped language before it reaches the model, and never let a document's content decide whether an order is placed.
- **Honesty: peer-reviewed** (appeared at the ACM AISec workshop), and the most widely cited paper in its area.

### 44. Na, Ni, Szpruch et al 2026, "Poisoning Agentic Alpha: Adversarial Vulnerabilities Across Roles and Architectures in Multi-Agent Trading Systems"
- PDF: https://arxiv.org/pdf/2608.24069 (local: `Na_2026_PoisoningAgenticAlpha.pdf`)
- The first systematic study of attacking a multi-agent trading system through the only channel an outsider actually has, which is the source data and prompts the agents consume. They break a standard pipeline into Analyst, Researcher, Trader and Risk Manager roles, design an attack matched to each role's interface, and trace how far a poisoned signal survives towards the final decision across four communication topologies, five assets and two model backbones. The central finding is stark: no architecture is inherently robust, and adding more agents does not fix it.
- **Copy this:** the finding that a corrupted input at the Analyst stage can propagate all the way to a real order. Put a deterministic, non-LLM check between any agent's conclusion and the broker.
- **Honesty: preprint,** from a group including a well-known mathematical finance researcher.

### 45. Dou, Goldstein and Ji 2024, "AI-Powered Trading, Algorithmic Collusion, and Price Efficiency"
- PDF: https://conferences.fuqua.duke.edu/assetpricing/wp-content/uploads/sites/2/2025/08/p9_DouGoldsteinJi.pdf (local: `Dou_2025_AIPoweredTradingAlgorithmicCollusion.pdf`)
- Models what happens when many informed traders all use reinforcement learning, and shows they can learn to collude without any agreement, communication or awareness that they are colluding. It happens through two separate mechanisms, one where the algorithms learn price-trigger punishment strategies, and one the authors dryly call artificial stupidity, where homogenised learning biases produce the same under-reaction across everyone. The second mechanism persists even in efficient, liquid markets, and the result is worse price informativeness and worse liquidity.
- **Copy this:** the warning that running the same model everyone else runs, on the same data, produces correlated behaviour you did not choose. This is the herding mechanism, and it is a real risk to your positions, not just a market-structure curiosity.
- **Honesty: preprint** (NBER working paper w34054 and an SSRN version), by three well-regarded finance academics.

---

## Section I. Following insiders and politicians

### 46. Cohen, Malloy and Pomorski 2010, "Decoding Inside Information"
- PDF: https://www.nber.org/system/files/working_papers/w16454/w16454.pdf (local: `Cohen_2010_DecodingInsideInformation.pdf`)
- The key insight is that most insider trading is boring: executives sell shares on a schedule for diversification and tax reasons, and those trades predict nothing. The authors separate routine traders from opportunistic ones using nothing more than the historical timing pattern of each insider's own trades, and find that routine trades, over half the universe, carry zero information. The opportunistic remainder carries all of it, delivering 82 basis points a month of value-weighted abnormal return and predicting future firm news and events.
- **Copy this:** the routine-versus-opportunistic filter is simple, mechanical, needs no language model at all, and runs off free SEC Form 4 filings. This is probably the single most implementable idea in the entire list.
- **Honesty: peer-reviewed** (published in the Journal of Finance; the free NBER working paper version is linked here).

### 47. Ziobrowski, Cheng, Boyd and Ziobrowski 2004, "Abnormal Returns from the Common Stock Investments of the U.S. Senate"
- PDF: https://consumerwatchdog.org/sites/default/files/resources/abnormalreturnsziobrowski.pdf (local: `Ziobrowski_2004_AbnormalReturnsUSSenate.pdf`)
- The paper that made congressional stock trading a public issue, finding that a portfolio mimicking senators' purchases beat the market by a substantial margin over 1993 to 1998. The evidence is a standard event-study calendar-time portfolio built from the senators' own disclosure filings. It is worth reading for the method, but be aware that this result has been directly contested by later work.
- **Copy this:** the disclosure-mimicking portfolio construction, which is the template every congressional-trading tracker still uses.
- **Honesty: peer-reviewed** (Journal of Financial and Quantitative Analysis), **but contested.** Eggers and Hainmueller's 2013 "Capitol Losses: The Mediocre Performance of Congressional Stock Portfolios" in the Journal of Politics reaches the opposite conclusion using a larger sample. I could not find a free PDF of the Eggers and Hainmueller paper, so that link is **unverified** and it is not in the folder.

### 48. Roodman, Sy, Atero Vázquez et al 2026, "Detecting Information Channels in Congressional Trading via Temporal Graph Learning"
- PDF: https://arxiv.org/pdf/2602.05514 (local: `Roodman_2026_CongressionalTradingTemporalGraph.pdf`)
- Rather than asking whether politicians beat the market on average, this asks which specific trades look informed, by building a dynamic graph linking congressional transactions, lobbying relationships, campaign finance contributions and geographic ties to companies. The task is framed as classifying edges in that graph, labelling trades that significantly outperform the S&P 500 over long horizons. The authors use a two-step walk-forward validation designed specifically to prevent look-ahead bias, which is more methodological care than this sub-literature usually gets.
- **Copy this:** the framing shift from "do politicians beat the market" to "which relationships predict which trades will", which is the question a small automated shop could actually act on.
- **Honesty: preprint.**

---

## What I could not get

- **Sarkar and Vafa 2024, "Lookahead Bias in Pretrained Language Models"**: SSRN and OpenReview both returned HTTP 403 to automated download. The paper is real and verified through OpenAlex, but the PDF is not in the folder and the links are unverified in the sense that I could not open them.
- **Loughran and McDonald 2016, "Textual Analysis in Accounting and Finance: A Survey"** (Journal of Accounting Research): no free PDF found. The 2011 paper in the folder covers the essential idea.
- **Eggers and Hainmueller 2013, "Capitol Losses"** (Journal of Politics): no free PDF found, and it matters because it is the main rebuttal to Ziobrowski.
- **A good open-access paper on trading FDA decisions**: I did not find one I would stand behind, so I have not cited one.

## The bottom line for a one-person shop

Six things worth carrying off the plane.

**The reading edge is real but narrow.** The strongest evidence for an agent that reads is PEAD.txt, where the numeric earnings signal has decayed to nothing but the textual one has not, and Cohen, Malloy and Pomorski, where a trivially simple filter on free SEC filings still produces real abnormal returns. Both are pre-LLM ideas that a language model can execute at scale.

**Most reported LLM trading returns are memory, not skill.** Li, Wang and Ma measure a 67 percent correction to in-sample returns. Roy and Roy show accuracy rising in-sample and falling out-of-sample as contamination increases. Zhu et al show that once you control leakage properly, what is left is market and style exposure.

**Anonymise everything.** Glasserman and Lin, Kim, Muhn and Nikolaev, and Zhu et al all independently arrive at the same fix. Strip tickers, company names and dates from the prompt. It costs nothing and it removes the largest single objection to your own results.

**Forward paper trading beats backtesting.** DeepFund, StockBench and OpenFinGym all converge on this. Since you are starting on paper anyway, you are already doing the right thing. Give it real elapsed time.

**Do not let an agent talk to the broker.** Greshake et al and Na et al together make the case: a news article is untrusted input, and a poisoned input at one end of a multi-agent pipeline reaches the order at the other end. Put a deterministic rules layer, with no language model in it, between the agent's conclusion and any order.

**Your diversification may be fake.** Lopez-Lira 2025 shows that similar prompts produce correlated behaviour, and Dou, Goldstein and Ji show that similar learning algorithms produce correlated under-reaction across an entire market. Several agents running similar prompts are one position, not several.
