# Hub status

Written 2026-09-07 at 17:20 New York by the Tuesday worker. Overwritten each
time, so this file is always now and never a history.

## For Mo before 07:00 New York Tuesday

1. **Keep the MacBook plugged in and awake, lid open.** It is charging now (36
   percent at 16:43). It slept on battery from 07:50 to 13:49 New York today and
   that single fact caused every failure in the rehearsal. The Mac Mini is not
   reachable on Tailscale, so the laptop is the trading machine tomorrow.
2. **Check the market data subscription in Client Portal.** IBKR said all day
   that the API is not subscribed to real time data (codes 10168 and 10089).
   If that is still true at 09:36, no book opens anything, by design. The 09:38
   check will report it either way.

## The five rulings

1. **Orphan halt: DONE.** `38912d9`, `dd2800c`, stamp `167b95b`. Live file
   `output/expected_orphans.json` is `{"SPY": 1}`, confirmed against a live
   read (1 SPY at 766.15, order 4 SELL 1 working).
2. **Three jobs armed: DONE.** `7449442`. Nine jobs loaded, converted to the
   Mac's Pacific clock and stamped (`8916bba`, `46ce775`). Sheet sync verified
   against the live Sheet
   (https://docs.google.com/spreadsheets/d/18_lzOTkoiJn1tc_WCHE5MheigyfhNc2dQcaZJjUBiP8/edit).
   Two things for Mo from that: the sync wiped two hand-typed rows by design,
   and the Rules Log carries 568 alert-test rows from Saturday's test database.
3. **Gateway slow reads: DONE.** Cause was upstream loss while the Mac slept;
   restarted twice by hand, then the new watchdog `ib_answers` check restarted
   it by itself at 15:52 and proved the restart in 65 seconds. Every read now
   has a wall-clock deadline, a tick is capped at 240 s, the pre-flight at 10
   minutes. Write-up: `journal/gateway_reads_2026-09-07.md`.
4. **Monday rehearsal: DONE.** Journal `journal/2026-09-07.md` written by the
   16:30 learning job (`80844bf`) with my addendum. Fixed today from what it
   found: holiday handling in the loop (`f8e719a`), the deadlines above, the
   watchdog real read, the time zone conversion, and ten stale Tuesday state
   files quarantined out of `output/`. DONE too: backlog 18 (rehearsal runs
   cannot write real state), 19 (reconciliation says "not checked" when the
   broker is unreadable) and 20 (alert stamps in New York time): `53c69d9`, `7801267`, `5a65b42`, `74f1601`.
5. **Tuesday 09:38 checks: scheduled** (09:21 and 09:38 New York), not started.

## Stays as ruled
All five books dry_run. Shorting off. Suite 1718 passing at `74f1601`. Tree clean, everything pushed.
