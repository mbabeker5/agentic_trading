# Trading strategy reading pack, September 2026

Built for Mo's flight. Four annotated lists and 159 downloaded papers (about 314 MB) in the `pdfs/` folder beside this file. The PDFs are not in git; the lists carry every link, so anything missing can be re-downloaded.

**Read the fourth list first if you only read one thing new.** `04_gap_fill.md` was written later on 2026-09-06 by agents that had web search, after the first three lists were written from memory. It fixes 24 errors in the first three (each fix is dated in place), adds seven strategy families the first list skipped, adds the 2025 and 2026 live tests of language-model trading agents, verifies the Congress ETF numbers from SEC filings, and carries a revised flight order that merges everything. Its first three sections take ten minutes.

Folder: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/reading_list_2026-09/`

## The one-paragraph version

The published record says three things at once. First, a handful of simple effects are real, well documented and cheap to trade with an automated system: following executives who buy their own stock, momentum on daily ETF prices, the turn-of-month calendar effect, and the opening-range breakout when it is filtered by unusual volume. Second, the evidence that language-model agents beat buy-and-hold is weak, most of the impressive backtests are contaminated by models that already know how the story ended, and the fix is cheap: hide tickers, names and dates from the model. Third, the honest studies of retail day trading find fewer than one percent of participants earn reliable profits after fees, and nearly all the losses come from crossing the spread. Read the pack with those three facts in mind and the rest falls into place.

## Flight order

The revised order that merges the fourth list is at the end of `04_gap_fill.md`. It runs about six and a half hours. The original five-hour order is kept below; it still works, it just predates the second pass.

Read in this order. Times are rough, for a reader who skims the maths.

### Hour 1. Orientation
1. `03_practitioner.md`, Section 3 (honest evidence on retail outcomes) and Section 4 (how not to fool yourself with a backtest). Twenty minutes. This is the humility that everything else needs.
2. `01_anomalies.md`, Section 12 (the paper to read before believing any anomaly: McLean and Pontiff on how published effects shrink) and the quick summary table at the end. Fifteen minutes.
3. `02_llm_agents.md`, Section A (the shape of the field) and Section G (do LLM agents actually make money out of sample). Twenty minutes.

### Hours 2 and 3. The strategies we are actually building
4. `01_anomalies.md`, Section 11, opening range breakout: the Zarattini, Barbon and Aziz paper is in `pdfs/`. Read the paper itself, especially Table 3 (why only the five-minute range works) and Figure 4 (relative volume is the strategy). This is book A's entire evidence base.
5. `01_anomalies.md`, Section 10, insider buying, then `02_llm_agents.md` Section I: the Cohen, Malloy and Pomorski routine-versus-opportunistic filter is the single best idea in the pack for book C, needs no language model, and runs on free filings.
6. `02_llm_agents.md`, Section I again for the congressional trading evidence, including why the well-known outperformers are hard to follow and why the main rebuttal paper is worth finding.

### Hour 4. Where an agent genuinely helps
7. `02_llm_agents.md`, Sections D and E: reading filings and earnings calls, and event-driven trades where reading speed is the edge. The Philadelphia Fed text-based post-earnings drift result is the best case for a reading agent.
8. `02_llm_agents.md`, Sections C and H: the leakage problem and the failure modes, including the prompt-injection and correlated-agents findings that changed our own design this week.

### Hour 5. Ideas for books five to ten
9. `01_anomalies.md`, Sections 1, 4, 7 and 8: time-series momentum, overnight versus intraday, turn of month, index and ETF rebalancing. Rated easy or medium for a small account.
10. `01_anomalies.md`, Sections 2, 3, 5, 6, 9 for the harder families, to know what to skip and why.

### If there is time left
11. `03_practitioner.md`, Section 1 (books): pick one to buy. For a non-programmer founder the list points at Robert Carver first.
12. `03_practitioner.md`, Section 5, operations for an autonomous system, including the FINRA notice that retired the pattern day trader rule in June 2026.

## What is not in the PDFs folder

After the second pass, most of the papers the first three lists could not fetch are in the folder. Nineteen still need a browser click, and they are listed with links in Appendix 1 of `04_gap_fill.md`. Three of those (Bernard and Thomas 1989, Livnat and Mendenhall 2006, Harris and Gurel 1986) have no free copy anywhere and need a library login.

## Provenance

The first three lists were written on 2026-09-06 by three research agents working mostly from their own knowledge, with web search unavailable for most of the session. Later the same day a second set of agents with web search verified every item the first three lists had marked unverified, fixed 24 errors in place (each marked with the date), and wrote `04_gap_fill.md`. Every PDF was opened and its first page checked against the claimed title. Anything still unconfirmed is marked "still unverified" where it appears. Treat any number not backed by a downloaded PDF as approximate.
