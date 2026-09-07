# Hub status

Written 2026-09-06 by the momentum and brackets worker. Overwritten each time,
so this file is always now and never a history. One line per question asked.

Suite: **1562 passed, 0 failed.** Replay gate: **11 pass, 0 fail, 2 slow
skipped**, up from 5 pass and 4 fail this morning.

## The six fixes: five done, one reverted by another session

1. **Cancel every working order at the flatten: DONE.** Commit in this pass.
   `cancel_working_orders` in
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
   runs as the FIRST step of the 15:45 flatten and again at the 15:55 market
   backstop, cancelling both bracket parents and resting stop children, and
   removing each from the book's own `working_orders`. Cancel first, close
   second, deliberately: closing first would leave a live stop that could fill
   against a position that is already gone. Safe to call twice and safe with
   nothing working. A new replay scenario, `nothing_left_working`, fails if any
   order is still working after the flatten, and it asserts the ORDER of the two
   steps rather than only the end state.

2. **launchd template glob: DONE, and my earlier diagnosis was WRONG.** I told
   you the three missing jobs were mis-named templates the generator could not
   see. Half right and the wrong half mattered.
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py`
   did only glob `*.template`, and it now reads `*.plist.tmpl` as well and
   derives the job name correctly from both. But the three files are NOT
   templates. They are finished plists, hand written before the generator
   existed, each with `{ROOT}` written through it and a full schedule in XML,
   and each one says inside itself that it is held back ON PURPOSE and lists the
   three steps that arm it. So they still do not generate, and that is correct.
   `--check` now FAILS naming any template without a plist and any plist whose
   template has gone, which is the hole that let this survive.

3. **Unclaimed position halts every book and alerts: NOT IN EFFECT. TWO
   SESSIONS WERE GIVEN OPPOSITE INSTRUCTIONS AND THIS NEEDS YOU TO ARBITRATE.**
   I built it: `agent/reconcile.py` halted every book on an orphan nobody
   claims, handed the alert back on the outcome rather than sending it (that
   module touches nothing outside itself, and is better for it), and the loop
   sent it once for the finding rather than once per book.
   Another session then landed commit `c5c92a2`, "A position nobody claims still
   halts nobody, and the forgiveness file is documented rather than required",
   and that is what is at HEAD. I checked the live behaviour rather than the
   commit message: an unexpected orphan today returns `books_to_halt = ()` and
   raises **zero** alerts.
   I have NOT re-applied my version. Two sessions taking turns reverting each
   other is worse than either answer, and this is a real disagreement rather
   than a mistake. **The argument on each side, so you can settle it in one
   line:** halting is right because something in the account that no strategy
   bought means a book has lost its record or somebody traded by hand, and every
   book is then sizing against a picture that is not true. Not halting is right
   because this account genuinely holds one unclaimed SPY share from the manual
   test on 2026-09-02, so halting on an orphan halts all five books on every
   tick of every day, and a safety rule that fires every five minutes forever is
   noise with a halt attached.
   **The forgiveness file is what reconciles the two, and it now exists either
   way.** `output/expected_orphans.json` is `{"SPY": 1}`, the shape that forgives
   exactly one share and complains if the number changes, with a committed copy
   at `config/expected_orphans.example.json` and a note at
   `config/README_expected_orphans.md` because `output/` is gitignored. With that
   file in place, halting on an orphan costs nothing on an ordinary day and still
   catches the case that matters. That is the version I would keep, and it is
   your call.
   **The quantity of 1 comes from the written record, not a live read: IB Gateway
   would not answer a position read while this was written. Confirm on Tuesday.**

4. **Snapshot failures become events, alerts and halts: DONE.** IBKR code 10197
   (another session has taken the account) now logs, alerts and halts the book
   for the day, because prices we cannot trust are worse than none. A market
   data type of 3 or 4 during market hours means the live subscription lapsed:
   it logs, alerts once, and stops the book OPENING anything while still
   allowing exits, since a stale price is fine to get out on and not fine to get
   in on. Anything else stays a note, because one unreadable quote is not a
   reason to stop the day.

5. **Day trade counter scenario actually opens a position: DONE.** It was
   asserting on a rule that never ran: book C never opened anything, so its
   fourth round trip was never refused and the scenario was passing judgement on
   nothing. Book C now genuinely opens, its fourth round trip in five business
   days is genuinely refused, and book A's fourth is genuinely allowed and
   flagged, which is the comparison the scenario exists to draw.

6. **launchd jobs LOADED: DONE, six of them.** Bootstrapped into `gui/501` as
   user `mtalib`; `launchctl list | grep -i agentic` prints all six as
   `-  0  com.mtalib.agentic-trading.<job>`, the `-` meaning waiting on schedule
   which is correct. The exact commands are recorded in
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/LAUNCHD.md`.
   Loaded: `tick`, `preflight`, `watchdog`, `recorder`, `learning`, `weekly`.

## Still open before Tuesday

- **THE DEAD MAN'S HANDLE IS NOT ON WATCH.** `deadman` is one of the three
  unarmed jobs. The loop writes `output/heartbeat` at the end of every finished
  tick and nothing reads it, so if the loop dies holding a position nothing
  pulls the kill switch. This is the one gap I would close before Tuesday and I
  did not close it, because `agent/deadman.py --really` is the only job in this
  project that can place an order. It is a protective order and it is still an
  order, and the file itself says it waits on Mo. **One word from you and it is
  three minutes' work.**
- The other two unarmed jobs: `sheet_sync` has never run against the real Google
  Sheet, so its first scheduled run would be its first run against Mo's live
  sheet, and `backup_db` has never run on a schedule. Both are safe to arm and
  neither is urgent.
- Confirm the real SPY orphan quantity on Tuesday's pre-flight, per item 3.
- **IB Gateway is answering slowly.** Position and open order reads timed out at
  45 seconds twice today with the market shut. The loop degrades cleanly and
  says so, but if that persists into Tuesday the 09:35 pick will be working from
  less than it should.
- A10 shorting is still pending Mo's decision and stays off.
- The `rules_commit` stamp is `51da883` on books A, B and E, moved there by
  another session, and it is already behind again: this pass changed guardrail
  behaviour after it. Per the rule in `config/books.yaml` it needs moving once
  more before the first trade, and whoever settles item 3 should be the one to
  move it, since that decision changes a guardrail.

## Not done, by your instruction

Item 7, Monday's dress rehearsal, is not started. You said to write the journal
and stop after 1 to 6, and to hand this file to a fresh worker for Tuesday.
