# Hub status

Written 2026-09-07 about 10:05 New York by the Tuesday worker. Overwritten each
time, so this file is always now and never a history.

## THE ONE THING MO MUST DO BEFORE TUESDAY

**The trading machine is a MacBook Pro on battery, and it slept through this
morning's rehearsal.** `pmset -g log` shows it asleep from about 07:50 to 09:43
New York with a dark wake every fifteen minutes; `pmset -g batt` says 82 percent,
discharging. A `caffeinate -dimsu` keep-awake job is already loaded
(`com.codex.keepawake`), so this was a lid-closed or hand-triggered sleep that
no software can override. While it slept IB Gateway lost its upstream link to
IBKR (warning 2110, every read times out), a tick that started at 07:37 hung
until 09:25 and blocked every pre-open wake-up, and the 09:00 pre-flight hung
for 44 minutes without a verdict. Slack and screen alert sent at 09:50.

Before 07:00 New York on Tuesday: plug it in, lid open or on an external
display. The Mac Mini is not reachable on Tailscale right now, so moving there is
not an option tonight.

## The five rulings

1. **Orphan halt: DONE.** `38912d9` (behaviour, tests, `phantom_position`
   scenario), `dd2800c` (docs, backlog 0b decided), `167b95b` (stamp on A, B, E
   moved 51da883 to 38912d9). Verified directly: an unclaimed SPY share with no
   forgiveness file halts A to E; `{"SPY": 1}` halts nobody; `{"SPY": 2}` halts
   all again. Live file `output/expected_orphans.json` is `{"SPY": 1}`, and a
   live read after the Gateway restart confirmed exactly 1 SPY at 766.15 with
   order 4 (SELL 1) working. Note: `167b95b` also carries the time zone
   generator work under the wrong message; my `git commit` swept in another
   agent's staged files. Content is right, message is not.
2. **Deadman, sheet_sync, backup_db: ARMED.** `7449442`. Nine jobs loaded.
   sheet_sync ran once by hand against the live Sheet
   (https://docs.google.com/spreadsheets/d/18_lzOTkoiJn1tc_WCHE5MheigyfhNc2dQcaZJjUBiP8/edit):
   568 Rules Log rows and 5 Config values written, formulas intact, read back
   through the REST API. Two findings for Mo: the sync wiped two hand-typed
   sheet rows by design (the database is the truth; text is in the launchd
   agent's report in journal/2026-09-07.md), and the 568 rows are alert-test
   noise from 2026-09-06 in `data/trading.sqlite`. Backup wrote a 352K copy.
   Deadman dry run stopped correctly at "market shut".
   **Time zone:** the Mac flipped to Pacific at 22:29 on 2026-09-06 (automatic
   time zone is on), so every job would have fired three hours late. Fixed in
   `scripts/gen_launchd.py`: templates stay in New York time, plists are
   converted to the Mac's zone and stamped, `--check`, the watchdog and the
   pre-flight all fail on a zone change (`8916bba`, `46ce775`). Reinstalled at
   06:55 New York; launchd shows hour 6 for the 09:xx New York wake-ups.
3. **Gateway slow reads: DIAGNOSED AND FIXED TWICE, ROOT CAUSE IS SLEEP.** The
   Gateway had lost upstream connectivity (2110); local login still worked so
   the watchdog said ok. Restarted 04:12 and 09:48 New York; reads go from
   20 minute hangs to under 3 seconds. Write-up:
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/journal/gateway_reads_2026-09-07.md`.
   Follow-ups in flight: (a) wall-clock deadline on MCP reads, a hard cap on a
   tick in run_tick.sh, a deadline on the pre-flight, bounded recorder reads
   (agent running); (b) a watchdog check that does a real bounded read after
   connecting so a Gateway that logs in but cannot answer counts as down and
   gets restarted (not started yet, next).
4. **Monday rehearsal: RUNNING, and it has already paid for itself.** Found:
   the Mac sleep above; reads with no deadline hang jobs for hours; the loop
   treats a holiday as a trading day (book D ran its sweep, momentum books
   waited for a 09:30 open) because only deadman and pdt read
   `schedule.holidays` (agent fixing now, backlog item 9); the pre-flight was
   killed by its 10 minute launchd ExitTimeOut on an earlier run; watchdog
   client id 250 collided with its own hung earlier copy. The deadman ran at
   09:40 and correctly said the market is shut. Next checkpoints 16:43 New York
   today, 09:21 and 09:38 Tuesday.
5. **Tuesday 09:38 checks: scheduled**, not started.

## Stays as ruled
All five books dry_run. Shorting off. Suite 1595 passing at `46ce775`.
