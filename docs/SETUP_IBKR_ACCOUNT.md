# Opening the IBKR account and paper login

Mo's checklist, in order. This is the part only Mo can do. The software side is already done and listed at the bottom.

**Status (2026-09-02):** Step 1 done. Live account under mtalib.personal@gmail.com approved 2026-09-02 12:45 PM ET, account U28440091, IBKR Pro. Paper account enabled the same day, paper account number DUT077572. Next: step 4, paper login into .secrets.

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
2. Subscribe to **US Securities Snapshot and Futures Value Bundle**. $10 a month, waived in any month you pay $30 or more in commissions. This is the consolidated national best bid and offer the agent prices from.
3. If the strategy trades options, also add **OPRA Top of Book (L1)**, $1.50 a month.

## 4. Hand the login to the agent

Create a file at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/ibkr_paper.env` with two lines:

```
IBKR_PAPER_USER=your_paper_username
IBKR_PAPER_PASSWORD=your_paper_password
```

That folder is gitignored, so it never reaches GitHub. Do not paste the credentials into chat. Once the file exists, say so and the Gateway login test can run.

## 5. Two-factor authentication

IBKR sends a two-factor prompt to the IBKR Mobile app on most logins. Paper accounts are usually gentler about it, and the auto-login helper (IBC) holds the session and restarts it daily. If the prompt keeps coming back, enable IBKR Mobile Authentication (IB Key) in the app and keep the phone nearby.

## Already done on the software side

- IB Gateway 10.45 stable, native Apple silicon build, installed at `/Users/mtalib/Applications/IB Gateway 10.45/`.
- Python environment with `ib_async` (the maintained fork of `ib_insync`) at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv/`.
- Guardrail template at `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.example.yaml`.
