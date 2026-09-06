# Backlog

Improvements ranked by how much risk they remove, highest first. Operational items ship the same day they are built and tested. Strategy or parameter items wait for Mo's approval through the hub and are stamped into the run registry when applied.

| Rank | Item | Risk it removes | Type | Status |
|---|---|---|---|---|
| 1 | Replay harness as the promotion gate (full five-book loop against recorded data with a fake broker) | Shipping a loop that breaks on its first live day | operational | building |
| 2 | Reconciliation on every tick with per-book halt | Trading a book against the wrong picture of what it holds | operational | building |
| 3 | Watchdog with Gateway restart and Mo alert | Silent multi-day outage, seen 2026-09-03 to 09-06 | operational | building |
| 4 | Pre-flight at 9:00 with no-trade-today file | Trading on delayed data or an unreconciled book | operational | building |
| 5 | Kill switch: cancel all, flatten all, disable loop | No fast way to stop a runaway book | operational | building |
| 6 | Per-book day-trade counter, hard limit on books C and D | Live-money account lock under the pattern day trader rule | operational | building |
| 6b | Watchdog verifies a restart by new pid and fresh login time, not by the start script's exit code | A dead Gateway reported as restarted | operational | queued |
| 7 | Portability: single project root, generated launchd, MIGRATION.md | Cannot move to the Mac Mini without a rewrite | operational | queued |
| 8 | Fill quality tracking: decided price versus fill price per book | Paper results that hide slippage | operational | queued |
| 9 | Holiday calendar in guardrails | Loop treats a market holiday as a trading day | operational | queued |
| 10 | Consolidated quote feed ($10 IBKR bundle) | Pricing limit orders off a fifth of the market | data, Mo's call | proposed |
| 11 | Second free data source for Congress trades | Single volunteer-run mirror going stale | data | proposed |
