# Backlog

Improvements ranked by how much risk they remove, highest first. Operational items ship the same day they are built and tested. Strategy or parameter items wait for Mo's approval through the hub and are stamped into the run registry when applied.

| Rank | Item | Risk it removes | Type | Status |
|---|---|---|---|---|
| 0 | Loop follow-on from the replay gate: fill ingestion from broker executions into book state (`0590a0c`), no re-send while an order is working (`f840f0f`), the bracket's working orders cancelled at the 15:45 flatten (`0a2edc5`), alerts from the loop (`ec49be0`), a Gateway outage handled without a false halt (`ecd34f8`), halts clearable with a bounded reason (`c482c91`), orphan positions alerted rather than halted (`58dfa67`), IBKR 10197 and delayed data visible (`6166471`), symbol exclusivity back to refusing by default for Mo to decide (`055f289`). The sector, halt and cross-book fields were done earlier (`7937e78`) | Gate found nine bugs; no book could trade until fixed | operational | **SHIPPED 2026-09-06. The gate passes 12 of 12, exit code 0, against `d11323c`.** Stamped as `f840f0f` on books A, B and E (stamp commit `eddf3dd`). Two things from the same pass are NOT in this item and are open below: item 14 (`orders.decision_id`) and item 15 (the four unmeasured summary columns) |
| 0a | Books sharing a strategy (A, B, E) collided under one-ticker-one-book | Eval comparison between A, B and E is meaningless if only A ever gets the top names | decision | DECIDED by the hub 2026-09-06: shared symbols are allowed, attribution is by order reference, and reconciliation now compares the broker's net position per symbol against the sum across books. Mo can overturn it; see journal/2026-09-06.md |
| 1 | Replay harness as the promotion gate (full five-book loop against recorded data with a fake broker) | Shipping a loop that breaks on its first live day | operational | shipped b5571ca; first run 6 pass 6 fail, see item 0 |
| 2 | Reconciliation on every tick with per-book halt | Trading a book against the wrong picture of what it holds | operational | shipped (reconcile.py, loop) |
| 3 | Watchdog with Gateway restart and Mo alert | Silent multi-day outage, seen 2026-09-03 to 09-06 | operational | shipped, launchd job not yet loaded |
| 4 | Pre-flight at 9:00 with no-trade-today file | Trading on delayed data or an unreconciled book | operational | shipped, launchd job not yet loaded |
| 5 | Kill switch: cancel all, flatten all, disable loop | No fast way to stop a runaway book | operational | shipped 9e095d6 plus dead-man b151446 |
| 6 | Per-book day-trade counter, hard limit on books C and D | Live-money account lock under the pattern day trader rule | operational | building |
| 6a | Day-trade rules by regime: read the account's day-trades-remaining on Tuesday, make the counter and hard limit conditional on the old pattern day trader regime, assert no order can create an intraday margin deficit under the new regime (FINRA Notice 26-10) | Enforcing a retired rule, or missing the new one, on live money | operational | building |
| 6b | Watchdog verifies a restart by new pid and fresh login time, not by the start script's exit code | A dead Gateway reported as restarted | operational | shipped c0d29f9 |
| 7 | Portability: single project root, generated launchd, MIGRATION.md | Cannot move to the Mac Mini without a rewrite | operational | shipped |
| 8 | Fill quality tracking: decided price versus fill price per book | Paper results that hide slippage | operational | ledger columns shipped c2e995a; loop passes decision price in the Momentum v2 pass |
| 9 | Holiday calendar in guardrails | Loop treats a market holiday as a trading day | operational | queued |
| 10 | Consolidated quote feed ($10 IBKR bundle) | Pricing limit orders off a fifth of the market | data, Mo's call | proposed |
| 11 | Second free data source for Congress trades | Single volunteer-run mirror going stale | data | proposed |
| 12 | Go live ramp (Mo's decision D4, 2026-09-06): 10 percent of intended size for 10 sessions, then 25, then 50, then full, with an automatic drop back to paper on a cap breach, an unreconciled position, a crash holding a position, two daily cap hits in five sessions, drawdown over 8 percent, or live slippage above twice paper | Going live at full size on a machine that has never handled real money | operational | ladder and demotion triggers written into config/books.yaml as `live_ramp` and a per book `ramp_step`; the code that enforces the session count and the demotion triggers is NOT built |
| 13 | IBKR order precautions (Mo's decision D6, 2026-09-06): never bypass them for API orders, set each just above the matching cap in config/guardrails.yaml, and raise a precaution rejection as an alert rather than retrying it | One layer of caps instead of two | operational | decision recorded in config/books.yaml; the Gateway settings themselves are set when a live account is first funded |
| 14 | `orders.decision_id` is never set. `record_order_row` in `agent/loop.py` does not pass it, so `db.trades_for_date`'s join to `decisions` finds nothing | Every trade row the nightly Sheet sync writes comes out with a blank model, cost, prompt hash and rationale, so a month of results cannot be read against the model that produced it or the price it cost | operational | open. The dry run path is a three line fix (the decision row is written immediately before the order row); the live path needs the link written after the fact, because `submit()` has to have the order row id before the broker's answer is known |
| 15 | Four columns of `daily_book_summaries` are NULL because nothing measures them: `spy_close`, `max_drawdown_pct`, `rule_triggers` and `missed_ticks` | The month end scoreboard is the point of the table, and three of the four are exactly the per book figures the Google Sheet cannot produce | operational | open, and left NULL on purpose in the meantime. NULL means not measured; a zero would mean measured and none. `rule_triggers` is a `COUNT` over the `decisions` table, where every guardrail firing already sits with its rule id; `missed_ticks` needs an expected tick count, which nothing produces yet |

## Research gaps (from the momentum spec critique, 2026-09-06)

| Rank | Item | Why it matters | Type | Status |
|---|---|---|---|---|
| R1 | Second literature pass on opening-range results: the published work traces to one research group with no independent replication or post-2023 out-of-sample test | The strategy's edge rests on it | research | open |
| R2 | Rerun the Congress-trades research with sources that are not script-rendered or rate-limited before any of its figures are used | Unverified numbers in the spec | research | open |
| R3 | Check commission and fee figures in the execution review against IBKR's live schedule | Cost model may be off | research | open |
| R4 | Confirm on Tuesday 2026-09-08 whether scanner filters and real-time quotes reach the paper account after the subscription purchase | Everything downstream depends on it | research | scheduled 9:36 and 9:46 AM ET |

## Dated reminders

Things that are not due yet and must not be forgotten. Each one has a date it
becomes live, and nothing here is actionable before that date.

| Due | Item | Why the date | Status |
|---|---|---|---|
| 2027-03-01 | **Section 475(f) election, mark to market accounting.** Talk to a trader tax CPA about whether to make the election for the 2027 tax year, and file it if the answer is yes (Mo's decision D8, 2026-09-06). | The election has to be filed by the due date of the prior year's return, WITHOUT extensions, and it CANNOT be made retroactively. Miss the date and the earliest it can apply is the year after. 1 March leaves a working month before the usual mid-April deadline, which is enough time to find a CPA who does this and to change your mind. | not due yet |

Two facts to hand the CPA, both from the momentum spec critique of 2026-09-06:
short term gains are taxed as ordinary income, and wash sale rules bite across
the year end, which is exactly what a day trading book generates. The election
is the thing that turns both of those off, at the cost of giving up capital gain
treatment entirely. It is a real decision with real downside, not a formality,
which is why it gets a CPA and not a search engine.
