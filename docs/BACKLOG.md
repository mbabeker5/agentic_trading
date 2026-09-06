# Backlog

Improvements ranked by how much risk they remove, highest first. Operational items ship the same day they are built and tested. Strategy or parameter items wait for Mo's approval through the hub and are stamped into the run registry when applied.

| Rank | Item | Risk it removes | Type | Status |
|---|---|---|---|---|
| 1 | Replay harness as the promotion gate (full five-book loop against recorded data with a fake broker) | Shipping a loop that breaks on its first live day | operational | building |
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

## Research gaps (from the momentum spec critique, 2026-09-06)

| Rank | Item | Why it matters | Type | Status |
|---|---|---|---|---|
| R1 | Second literature pass on opening-range results: the published work traces to one research group with no independent replication or post-2023 out-of-sample test | The strategy's edge rests on it | research | open |
| R2 | Rerun the Congress-trades research with sources that are not script-rendered or rate-limited before any of its figures are used | Unverified numbers in the spec | research | open |
| R3 | Check commission and fee figures in the execution review against IBKR's live schedule | Cost model may be off | research | open |
| R4 | Confirm on Tuesday 2026-09-08 whether scanner filters and real-time quotes reach the paper account after the subscription purchase | Everything downstream depends on it | research | scheduled 9:36 and 9:46 AM ET |
