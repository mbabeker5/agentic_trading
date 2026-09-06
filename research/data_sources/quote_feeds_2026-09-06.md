# Real-time quote feed options (QuoteFeedScout research, 2026-09-06)

Key facts:
- IBKR paper fills are simulated on IBKR's servers against IBKR's own top-of-book data regardless of any external feed (https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm). An external feed improves decisions, never fills, and adds decision-versus-fill skew.
- IBKR's 10 USD "US Securities Snapshot and Futures Value Bundle" is SNAPSHOT only for equities (plus 0.01 USD per snapshot). Streaming consolidated NBBO is sold per network at 1.50 USD each: Network A (NYSE), B (AMEX/ARCA), C (NASDAQ), so 4.50 USD/month covers all three tapes, Non-Professional (https://www.interactivebrokers.com/en/pricing/research-news-marketdata.php?p=usa).
- Sharing live subscriptions to paper works only when live and paper sessions are on the SAME machine; on different machines the paper session gets no data. Relevant to the Mac Mini migration.
- Free consolidated NBBO alternatives: Schwab API (NBBO quoteType, refresh token expires every 7 days, approval takes days) and Tradier Lite (consolidated L1, one websocket, token never expires). Alpaca free is IEX only and paper-only accounts cannot buy SIP. Massive (Polygon) Advanced 199 USD, Alpaca Algo Trader Plus 99 USD for research history.
- Robinhood: official Agentic Trading MCP at https://agent.robinhood.com/mcp/trading exposes quotes, L2 and watchlists, but quotes are single-venue (Nasdaq Last Sale), bid/ask breaks outside RTH, and the Customer Agreement forbids using its market data for anything not related to the Robinhood account. Not usable as a feed for IBKR execution.
- Quiver Quantitative: alternative data only (Congress trades, insider Form 4, contracts, lobbying, dark pool), official MCP with 18 tools and no quotes. Plans: Premium 25 USD, API Hobbyist 30 USD, Trader 75 USD, no commercial rights. Congress dataset median lag 22 days. Candidate signal source for books C and D.

Recommendation: month one, IBKR 4.50 USD per-network streaming NBBO as the only feed; optional free Schwab or Tradier cross-check. Live money: same. Research history: Massive or Alpaca paid.
