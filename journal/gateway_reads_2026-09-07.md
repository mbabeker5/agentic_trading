# Why IB Gateway reads hung, and what fixed it (2026-09-07, 04:00 to 04:20 ET)

Written by the Tuesday worker after diagnosing the 45 second timeouts the
previous worker saw on 2026-09-06 with the market shut.

## What was measured before

Through the MCP server at `http://127.0.0.1:8765/mcp`, the loop's own path
(`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py`):

| Read | First call | Later calls |
|---|---|---|
| account_summary | 128 s, then failed | connection refused |
| portfolio | 1,240 s, then failed | connection refused |
| open_orders | 92 s, then failed | connection refused |
| executions | 10 s, failed | connection refused |

The MCP server's own log at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/mcp_logs/mcp_ibkr.log`
showed the cause on every connection since 22:35 Pacific on 2026-09-06:

```
Warning 2110: Connectivity between Trader Workstation and server is broken. It will be restored automatically.
Warning 2103: Market data farm connection is broken:usfarm
Warning 2105: HMDS data farm connection is broken:ushmds
Warning 2157: Sec-def data farm connection is broken:secdefnj
Warning 2151: Positions info is not available yet.
ERROR positions request timed out
ERROR account updates for DUT077572 request timed out
ERROR executions request timed out
```

A direct read only API connection on client id 289 saw the same thing: the
login handshake succeeded in under a second and then `reqPositions` and the
account update never answered.

## What the cause was

The Gateway process (pid 14792, started 2026-09-06 around 11:42 ET) had lost
its upstream connection to IBKR's servers and never got it back, even though
IBKR's own message says it will. Its API port stayed open and accepted logins,
so every local health check passed: the watchdog's `gateway_process`,
`gateway_port` and `ib_connect` all said ok at 01:00 ET while no request could
be answered. The Sunday IBC log showed a 1100 (connectivity lost) at 15:40 ET
on 2026-09-06, a 1102 (restored) three minutes later, and then the 2110 state
from 22:35 Pacific on. That is the same failure shape as the 2026-09-03 outage,
except that time the process died and this time it stayed up and useless.

The MCP server is not the slow part. Once the Gateway answered, the MCP path
answered in seconds.

## What was done

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh
   (IBC command port refused, so it fell through to TERM; process gone, port shut)
nohup /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh &
   IBC log ibc-3.24.2_GATEWAY-10.45_Monday.txt: login attempt 1 at 04:11:57 ET,
   a "Re-login is required" dialog answered by IBC, "Login has completed" at 04:12:27 ET.
```

## What was measured after

Direct read only, client id 289, three repeats each: connect and sync 0.3 s,
positions 0.0 s, open orders 0.0 s, executions 0.0 s, account summary 0.1 s.

MCP path, three repeats each: account_summary 0.5 s, portfolio 2.9 s,
open_orders 0.3 s, executions 0.3 s.

The account holds exactly 1 SPY at an average cost of 766.15, and one working
order, id 4, SELL 1 SPY, placed from client id 100. That confirms the
forgiveness file quantity `{"SPY": 1}`.

## What is still open

1. **The watchdog cannot see this failure.** `ib_connect` proves the handshake,
   not that the Gateway can answer. It needs a bounded real read (positions or
   account summary with a 20 second cap) after connecting, and a timeout there
   must count as a dead Gateway so the existing restart path fires. Handed to
   the launchd agent as a follow-up once its time zone work lands.
2. **`McpClient(timeout=60)` did not bound a call.** The portfolio call above
   ran 1,240 seconds with a 60 second timeout set, because the timeout is a
   socket read timeout and the server keeps the HTTP response alive while it
   waits on the Gateway. The loop's own 45 second figure came from the server
   side, not the client. A wall clock deadline on the client is the fix.
3. Why the Gateway lost upstream at 22:35 Pacific is unknown. That is the same
   minute the Mac's time zone flipped to Pacific (see docs/LAUNCHD.md), which
   may be a coincidence or may be a network change on this Mac. Worth watching
   for a repeat.
