# Hub status

Written 2026-09-08 at 10:40 New York by the Tuesday worker. Overwritten each
time, so this file is always now and never a history.

## For Mo right now

**Log out of IBKR Mobile, TWS and Client Portal on the mbabeker5 login.** Since
09:00 the paper Gateway has had IBKR error 10197, no market data during
competing live session, on every quote. No quotes, no scanner rows, empty
shortlist, no picks. Still true at 10:33: 363 more 10197 errors after 10:00,
nothing served in 234 quote requests, no shortlist. Nothing is at risk (all
dry_run, account flat), but the first day is producing no decisions until that
session closes, and the subscription cannot be judged. Alerted 09:22 and 09:45.

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
5. **Tuesday 09:38 checks: DONE**, in `journal/2026-09-08.md`. (a) No real-time
   data and no scanner rows, because of the competing live session above, so the
   subscription cannot be judged yet; scanner filters still off. (b) Regime
   reads `new_imd` on the paper account, which is not evidence for the live
   account; setting stays `unknown`. (c) Order 4 filled at 09:30:03, SPY sold at
   769.36, account flat, reconciliation matched, forgiveness file emptied to `{}`.
   The 09:35 pick ran for A, B and E against an empty shortlist, no halts. Also
   today: the pre-flight worked inside its budget and failed the day correctly,
   its reconcile check now honours the forgiveness file (`2c66f0e`), and
   somebody removed NO_TRADE_TODAY at about 09:25 (not the hub's agents).

## Stays as ruled
All five books dry_run. Shorting off. Suite 1726 passing at `2c66f0e`. Tree clean, everything pushed.
