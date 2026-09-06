# Moving the shop to another Mac

Draft. The full step list (install IB Gateway, IBC, Python 3.12 environment, copy `.secrets`, load launchd jobs, run pre-flight) is written by the portability work; this file exists now so one rule is on record before anything moves.

**IBKR shares live market data subscriptions with the paper account only when both sessions run on the same machine. After the move to the Mac Mini, Mo must not open a live IBKR session (Client Portal, Trader Workstation or the mobile app) on the laptop during market hours, or the Mini's paper session loses its data and the agent trades blind.** Source: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/quote_feeds_2026-09-06.md`.

Never running on two machines at once: the Gateway paper login, and the trading loop.
