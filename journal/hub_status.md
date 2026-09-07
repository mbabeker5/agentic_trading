# Hub status

Written 2026-09-06 by the momentum and brackets worker. Overwritten each time,
so this file is always now and never a history. One line per question asked.

1. **Native OCA brackets placed for every entry: YES.** Commit `7937e78`. A
   limit parent plus a stop-limit child in one OCA group (`ocaType` 1), the
   child carrying `parentId`, the parent sent untransmitted so the child's
   transmit releases the pair. `submit()` in
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
   routes an entry through `bracket_order` whenever it has a stop, and an entry
   without a stop is refused upstream, so no entry can reach the broker naked.
   Not via the server's `ibkr_bracket_order`, whose `takeProfitPrice` has no
   default and which item A2 therefore made unusable; built from the plain order
   tool instead, which is what IBKR does underneath. Never yet called against a
   real account.

2. **Stop and target set at fill time and clamped: YES, with one caveat.**
   Commits `273e928` (the Momentum v2 stop and the removal of the target) on top
   of `e093551` (setting them at fill time at all). `record_fill` calls
   `fill_levels`, which re-measures against the price actually paid, not the
   price planned, and clamps through `gr.stop_price_for`, so a model may tighten
   a stop and can never widen one. Target is always 0 on the three momentum
   books now, which is item A2. The caveat, because it is real: if the rule stop
   itself raises, `fill_levels` returns a zero stop rather than inventing one.
   That path is commented and looks unreachable with a positive fill price, but
   it is not proved unreachable.

3. **Kill switch on live account ids behind a flag, and a heartbeat: YES to
   both.** Live ids: commit `9e095d6`.
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.py`
   refuses any account id not starting with DU unless BOTH the
   `--live-account-ok` flag and the environment variable are set, deliberately
   two because a flag alone is one typo. Heartbeat: commit `7937e78`. Every tick
   that finishes touches `output/heartbeat`, written last so a tick that fell
   over halfway cannot leave a fresh one behind saying all is well, and
   `agent/deadman.py` (`b151446`) prefers that file over guessing from logs.
   WARNING, see line 8: the dead man's handle is not a loaded launchd job, so
   nothing is reading that heartbeat on a schedule today.

4. **Replay gate re-run after the fixes: 5 pass, 4 fail, 3 slow skipped.**
   Passing: `daily_loss_cap`, `kill_switch`, `gateway_down`, `rejected_order`,
   `two_books_one_symbol`. Failing, all four real loop gaps and all four in
   backlog item 0:
   - `flatten_at_close`, and this one is NEW and the most serious. An entry now
     goes out as a parent plus a resting stop child and NOTHING CANCELS EITHER
     at the 15:45 flatten. `agent/loop.py` calls `cancel_order` in exactly two
     places, moving a stop and the sixty second backstop, and neither runs at
     the close. Live that is a stop resting overnight for a position that no
     longer exists, plus an unfilled entry that could fill on the next open into
     a book that believes it is flat. Not fixed here because another agent is
     editing `agent/loop.py` right now.
   - `phantom_position`: an unclaimed position halts nobody, because
     `agent/reconcile.py` gives an orphan no book id.
   - `day_trade_counter`: book C never opens a position, so its allowance is
     never tested.
   - `competing_session_delayed_data`: `snapshot_by_symbol` swallows every
     snapshot failure into a note, so IBKR code 10197 reaches no log and no
     alert, and no book halts.
   Two of the four failures I found earlier were mine and were HIDING these: the
   fake broker reported no halted tick and the replay's synthetic shortlist had
   no industry, so the `halted` and `sector_cap` rules were refusing every entry
   in every scenario and the gate was testing a missing field rather than the
   loop. Both fixed in `0049aa9`.

5. **rules_commit stamp moved to 03e5318: YES.** Commit `0049aa9`. Books A, B
   and E. The rule is now written into
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`:
   before the first trade the stamp follows any commit that changes guardrail
   behaviour, and after the first trade it becomes a version with its own
   changelog entry. `promoted_on` is still empty on all five books and all five
   are still `dry_run`.

6. **launchd one-minute pre-open wake-ups: DONE, by another agent, commit
   `9d2dee7`.** I made no change and there was nothing blocking me. Verified
   rather than trusted: `tick.template` carries
   `every 1 minute from 09:00 to 09:26 on weekdays`, the generated plist holds
   27 one-minute wake-ups from 09:00 to 09:26 and a five minute grid after, 110
   wake-ups a day, and `gen_launchd.py --check` reports all six plists in step
   with their templates.

7. **SQLite system of record: BUILT.** Commit `c231d06`. `agent/db.py`,
   `data/schema.sql`, `data/migrations/0001_initial.sql`, `data/trading.sqlite`,
   plus `scripts/migrate_db.py` and `scripts/backup_db.sh`.
   **Nightly Sheet sync: the script is built, the job is NOT.**
   `ledger/sync_sheet.py` exists and a template exists at
   `config/launchd/templates/sheet_sync.plist.tmpl`, but no plist was ever
   generated from it, so nothing runs it on a schedule. The cause is a file
   extension: `scripts/gen_launchd.py` line 438 globs `*.template`, and three
   templates are named `*.plist.tmpl` instead, so the generator has never seen
   them. See line 8, because one of the three is the dead man's handle.

8. **Still open before Tuesday, worst first.**
   - **NO LAUNCHD JOB IS LOADED AT ALL.** `launchctl list` shows nothing
     matching `agentic`. Six plists are generated and in step, and zero are
     bootstrapped, so on Tuesday morning nothing wakes up: no tick, no
     pre-flight, no watchdog. The load command is in `docs/LAUNCHD.md` and it is
     a Tuesday runbook step, not a code change.
   - **Three launchd jobs cannot even be generated,** for the extension reason
     in line 7: `sheet_sync`, `backup_db` and `deadman`. The last one is the
     dead man's handle that pulls the kill switch when the loop dies holding a
     position, so the heartbeat in line 3 currently has no reader. Either rename
     the three templates to `*.template` or widen the glob in
     `scripts/gen_launchd.py`. I have not touched it: it is one line either way,
     but it is somebody else's file and it deserves a test.
   - **The bracket's working orders are not cancelled at the flatten,** line 4.
     This is the one I would fix first in the code.
   - **Book D's data question is a statute, not a licence,** and it is Mo's to
     decide. Every byte comes from the House Clerk and the Senate eFD, so no
     third party licence applies anywhere. What applies is 5 U.S.C. 13107(c):
     unlawful to use the filings for "any commercial purpose, other than by news
     and communications media". Undefined term, no carve-out for personal
     investment, and the sweep already POSTs the Senate's
     `prohibition_agreement` on every run, so an unaware position is not
     available. The deciding fact is whether anything derived ever leaves Mo's
     own account. Nothing does today.
   - **A10 shorting is still pending Mo's decision** and stays switched off.
   - **The stamp may need moving again** if anything lands before Tuesday that
     changes guardrail behaviour, per the rule in line 5.

Suite at the time of writing: 1527 passed, 0 failed.
