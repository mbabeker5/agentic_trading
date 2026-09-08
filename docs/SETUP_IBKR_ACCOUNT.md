# Opening the IBKR account and paper login

Mo's checklist, in order. This is the part only Mo can do. The software side is already done and listed at the bottom.

**Status (2026-09-02):** Step 1 done. Live account under mtalib.personal@gmail.com approved 2026-09-02 12:45 PM ET, account U28440091, IBKR Pro. Paper account enabled the same day, paper account number DUT077572. Paper login saved to `.secrets/ibkr_paper.env` (username is the live one, mbabeker5; IBC logs it into the paper side). First Gateway login 13:27 ET succeeded in 5 seconds with no two-factor prompt. API confirmed: connects, contract lookup, delayed quotes and historical bars all work. Paper balance appeared the same afternoon: $1,000,000 simulated cash. Live quotes are not subscribed yet (delayed data works). MCP server installed and verified read-only, see docs/MCP_SERVER.md. Next: step 3, buy the $10 data bundle on the live login and tick data sharing.

## 1. Open the live account (done 2026-09-02)

1. Go to https://www.interactivebrokers.com and click **Open Account**. Pick **Individual**.
2. Pricing plan: **IBKR Pro**, not Lite. Lite sells your orders to wholesalers and skips SmartRouting, and good routing is the whole reason we picked IBKR.
3. Account type: **Margin**. This does not mean you borrow anything. It just means the account can short, run options spreads, and trade again without waiting two days for cash to settle. Pick Cash only if you want borrowing to be impossible, and accept that it narrows the strategy.
4. Trading permissions: US stocks and ETFs, plus options if the strategy will use them (level 2 or higher for spreads). Skip futures unless you know you need them. Any permission can be added later, it takes about a day.
5. Have ready: government ID, address, employer details. There is also a short questionnaire about investing experience and net worth.
6. Approval usually lands in 1 to 3 business days, sometimes the same day.

You do not need to fund the account to paper trade. Fund it only when we decide to go live.

## 2. Enable the paper account (after approval, 5 minutes)

1. Log in to Client Portal at https://www.interactivebrokers.com/portal.
2. Settings, Account Settings, then **Paper Trading Account**. Enable it.
3. The paper username and password usually arrive the next morning. The paper account starts with a simulated $1,000,000, which is silly. We will reset it to whatever figure you pick for the test.
4. Still on that page, tick **Share real-time market data with paper trading account**. Miss this and the paper account sees delayed prices, which would make the whole test meaningless.

## 3. Market data subscription (after paper login exists, 5 minutes)

1. Client Portal, Settings, User Settings, **Market Data Subscriptions**.
2. Subscribe to the **streaming NBBO by network**: Network A (NYSE), Network B (NYSE Arca and regionals) and Network C (Nasdaq), $1.50 each, $4.50 a month in total. This is the consolidated national best bid and offer the agent prices from, streaming rather than snapshot. The $10 "US Securities Snapshot and Futures Value Bundle" is the alternative if you also want futures; the hub's research of 2026-09-06 recommends the $4.50 route (`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/quote_feeds_2026-09-06.md`).
3. If the strategy trades options, also add **OPRA Top of Book (L1)**, $1.50 a month.

## 4. Hand the login to the agent

Create a file at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/ibkr_paper.env` with two lines:

```
IBKR_PAPER_USER=your_username   # the live username works, IBC picks the paper side
IBKR_PAPER_PASSWORD=your_paper_password
```

That folder is gitignored, so it never reaches GitHub. Do not paste the credentials into chat. Once the file exists, say so and the Gateway login test can run.

## 4b. Market data: three things to know

- **Sharing is on.** On 2026-09-02 Mo set "Share real-time market data subscriptions with paper trading account" to Yes for paper username futzmp555 (account DUT077572), sharing from live username mbabeker5. IBKR applies it overnight, so the first real-time check is the morning of 2026-09-03 after 9:30 AM Eastern. Note the auto-login still uses the live username mbabeker5 with the paper button; that logs into the same paper account and has worked.
- **Paper fills use IBKR's own quotes.** Whatever feed we buy, the simulator fills against IBKR's data, so the agent decides on IBKR quotes and the ledger's slippage column tracks any gap between decided price and fill.
- **Only one login can hold market data at a time.** IBKR allows one market data session per user, and live and paper share it. While Gateway runs the paper account during market hours, do not keep a quote screen, Client Portal watchlist or the mobile app streaming prices on the live login. It will steal the data session from the agent and its quotes will go stale (Gateway reports error 10197).
- **Subscriber status.** Mo's status showed Professional on 2026-09-02 and IBKR asked for the Non-Professional questionnaire. Professional status triples data fees and can change which feeds are shared to paper. Complete the questionnaire on the live login under Settings, User Settings, Market Data Subscriptions. The smoke test on 2026-09-03 records whether quotes come back flagged professional.

## 4c. Log of checks

- **2026-09-06 11:45 ET (Saturday).** Gateway had been down since Thursday 2026-09-03 01:44 ET: the IBC log shows it stuck at "Connecting to server" through the 2 AM restart window and then exiting. Restarted by hand, logged in again without a two-factor prompt. Live quote request returned error 10197, "No market data during competing live session": the sharing toggle has taken effect, but a live-login session (Client Portal or the mobile app on mbabeker5) was holding the data session, so real-time versus delayed could not be judged. Re-check scheduled for Tuesday 2026-09-08 after 9:30 AM ET. Market-on-open paper order 4 placed to sell the 1 SPY test share at Tuesday's open, Mo's approval via the hub.

- **2026-09-08 09:36 to 09:38 ET (Tuesday, first trading day). Scanner truth comparison, read-only.** All three of Saturday's scans (TOP_PERC_GAIN unfiltered; TOP_PERC_GAIN with priceAbove 5 and stVolume5MinAbove 100000; HOT_BY_VOLUME with marketCapAbove 1e9) returned 0 rows, no error callbacks, and no end-of-scan signal within the 30 second timeout, request ids 3, 4 and 5. That is a different failure from Saturday (control 50 rows clean, filtered scans 0 rows with error 162 "Scanner filter ... is disabled"): today the scanner service did not answer at all. Cause established by a second probe: Gateway is logged in and answers current time and contract lookups in under a second, but every market data request returns IBKR error 10197, "No market data during competing live session", meaning a live login (Client Portal, Trader Workstation or the mobile app on mbabeker5) is holding the account's single data session. The scanner rides on market data, so it hung too. The 09:00 pre-flight had already failed on market_data, scanner and reconcile and written NO_TRADE_TODAY, so no book opens anything today; exits still work. **Verdict: whether the shared subscription enables scanner filters cannot be judged today; the question stays open until a market-hours run happens with no live session competing.** Action for Mo: close every IBKR quote screen and app on the live login during market hours, then the 9:46 scanner run or tomorrow's pre-flight answers it.

## 5. Two-factor authentication

IBKR sends a two-factor prompt to the IBKR Mobile app on most logins. Paper accounts are usually gentler about it, and the auto-login helper (IBC) holds the session and restarts it daily. If the prompt keeps coming back, enable IBKR Mobile Authentication (IB Key) in the app and keep the phone nearby.

## Already done on the software side

- IB Gateway 10.45 stable, native Apple silicon build, installed at `/Users/mtalib/Applications/IB Gateway 10.45/`.
- Python environments: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/` (Python 3.12, used for Gateway work and the MCP server, which refuses newer Pythons) and `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/` (Python 3.14, general scripts).
- Guardrail template at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.example.yaml`.
