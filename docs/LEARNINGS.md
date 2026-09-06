# Learnings register

Confirmed learnings only, one line each, dated, newest first. A learning is confirmed when it has been observed at least once in the live paper run or proven by a test, and it has changed something (a rule, a check, a doc). Proposals live in the journal until then.

Format: `YYYY-MM-DD | area | what we learned | what changed (commit)`

- 2026-09-06 | data | Both Stock Watcher mirrors for Congress trades are dead (403), Capitol Trades rate-limits and errors, and the surviving community mirror invents tickers from corrupted text (it turned Alphabet and Microsoft into "K"). The official House and Senate sources parse cleanly and are two days fresher. | Congress sweep uses the official sources first, the mirror only as a degraded fallback with corrupted rows dropped (8ad68fa)
- 2026-09-06 | data | On this account, IBKR scanner filters fail silently: zero rows plus error 162 "Scanner filter X is disabled" in a callback nobody reads. A control scan with no filters returned 50 rows. | Scanner truth check raises on any 162, 165, 365, short control or timeout (eb74cdb)
- 2026-09-06 | process | A sub-agent narrated findings from research agents it had never heard back from, then corrected itself. Agent narration is not evidence; only measurements in the transcript or files are. | Every agent report with a number is spot-checked against the file or a re-run before it enters a spec
- 2026-09-06 | legal | House and Senate disclosure data carries a statutory clause against use "for any commercial purpose" other than news dissemination. | Flagged to Mo as his decision before the Congress book drives real orders
- 2026-09-06 | data | A live login (Client Portal or mobile) steals IBKR's single market data session from Gateway; the API then returns error 10197 and quotes stop. | Watchdog names it plainly in the alert; setup doc warns Mo (0323fad)
- 2026-09-06 | gateway | Gateway died silently on 2026-09-03 01:44 ET at its 2 AM restart window and stayed down three days unnoticed. | Watchdog with restart and alert built (this batch)
- 2026-09-02 | mcp | An instantly filled market order comes back from the MCP server as isError=true although it filled. | Every order is confirmed by reading executions and open orders afterwards (7cad44d)
- 2026-09-02 | python | ib_async on Python 3.14 hangs on account requests; 3.12 works. | All Gateway code runs in venv312 (679b1ea)
- 2026-09-02 | data | Delayed data makes a 9:35 scan blind: freshest bar is from 9:20. | Real-time data sharing to paper enabled; pre-flight checks data type before any book trades
- 2026-09-02 | account | IBKR provisions the paper balance within hours, not overnight. | Nothing to change
