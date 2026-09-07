# IBKR MCP server: how it runs

The agent talks to Interactive Brokers through two local pieces:

1. **IB Gateway** (IBKR's own program) logged into the paper account, API on port 4002. Started by `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh`.
2. **The MCP server** (patrickpxp/ibkr-mcp-server, pinned by commit in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/requirements-312.txt`), which turns Gateway's API into 34 tools Claude can call. Started by `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_mcp.sh`.

Claude Code finds the server through `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.mcp.json`, which points at `http://127.0.0.1:8765/mcp`. Any Claude Code session opened in the project folder gets the `ibkr` tools once both pieces are running.

## Start and stop

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_mcp.sh

/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_mcp.sh
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh
```

Gateway restarts itself at 2 AM daily without a new login. IBKR expires the session on Sundays at 1 AM Eastern, so expect one fresh login a week. Logs: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/ibc_logs/` for Gateway, `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/mcp_logs/mcp_ibkr.log` for the server.

## Settings

All in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/mcp_ibkr.env`. Three matter:

- `IBKR_PORT=4002`. Paper. The start script refuses to run on a live port.
- `MCP_BIND_HOST=127.0.0.1`. The server has no password, so it must only listen to this Mac. The start script refuses anything else.
- `IBKR_ENABLE_TRADING=false`. Every order tool is locked until this is true. It stays false until the strategy and the guardrail layer exist.

## What was verified on 2026-09-02

Through the server, against the live paper Gateway:

- Account summary for DUT077572: $1,000,000 simulated cash, buying power $4,000,000.
- SPY snapshot (delayed, live data not yet subscribed) and hourly historical bars.
- A dry-run order returns notes and sends nothing.
- A real order attempt with trading disabled is refused with `TRADING_DISABLED: live trading is disabled; set IBKR_ENABLE_TRADING=true to enable mutating tools`. Open orders afterwards: none.

## The client's timeout is a deadline, not a read timeout

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py` takes a `timeout`, 45 seconds by default, and it means wall clock: every tool call comes back, with an answer or with an `McpError`, inside that many seconds of being made. The handshake and the tool call share the one budget, so a first call is no slower than a later one.

It has to be a deadline because a socket read timeout does not bite here. The server keeps the HTTP response open and alive while it waits on IB Gateway, so a Gateway that has lost its upstream link to IBKR (warning 2110) produces a response that never finishes and is never silent either. Measured on 2026-09-07: a `portfolio()` call made with `timeout=60` ran for 1,240 seconds, the tick that started at 07:37 New York finished at 09:25, and every one-minute pre-open wake-up in between was lost because launchd will not start a second copy of a running job.

So the round trip is done on a worker thread that is joined with a deadline, and the socket is shut when the deadline passes, which is what stops the server writing into a connection nobody is reading. The error is the same `McpError` and the same sentence the old socket timeout produced, so nothing downstream changed: `the MCP server took longer than 45 seconds to answer tools/call`.

## Tool argument shapes

Contracts and orders are passed as plain objects with IBKR's own field names, for example:

```
contract: {"symbol": "SPY", "secType": "STK", "exchange": "SMART", "currency": "USD"}
order:    {"action": "BUY", "totalQuantity": 1, "orderType": "LMT", "lmtPrice": 700.0, "tif": "DAY"}
```

Historical bars want `endDateTime` (empty string for now), `durationStr` like `"1 D"`, `barSizeSetting` like `"1 hour"`, `whatToShow` like `"TRADES"`, and `useRTH`. Snapshots take a list of contracts and an optional `market_data_type` (1 live, 3 delayed).

## Known gaps

- **A market order that fills instantly comes back as an error.** Verified 2026-09-02 with the first real paper buy (1 SPY, order 8, filled at $765.15 on ARCA): the order filled, but the server's response failed its own validation (`TradeSnapshotModel fills.0: Input should be a valid dictionary`) and the tool reported `isError=true`. The agent must never read an error from `ibkr_place_order` as "nothing happened". Always confirm with `ibkr_get_executions` and `ibkr_get_open_orders` afterwards. Limit orders that rest do not hit this bug.

- No modify-order tool. Cancel and re-place.
- Orders default to `transmit=false`, which parks them in Gateway waiting for a click. The agent must pass `transmit=true` deliberately when we enable trading.
- No built-in position or dollar caps. Those live in our own guardrail layer, not in the server.
- The server labels port 4002 as "custom" rather than "paper" in its health output. The connection is still the paper one; the smoke test checks the account id starts with DU.
