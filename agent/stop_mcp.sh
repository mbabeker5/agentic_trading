#!/bin/bash
# Stop the IBKR MCP server started by start_mcp.sh.
# Where the project lives. AGENTIC_TRADING_ROOT wins when it is set; otherwise
# this script works it out from its own location, so a plain clone anywhere on
# any Mac just works with nothing configured.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PIDFILE="$PROJECT/output/mcp_ibkr.pid"
if [[ -f "$PIDFILE" ]]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped pid $(cat "$PIDFILE")" || echo "not running"
  rm -f "$PIDFILE"
else
  pkill -f "venv312/bin/mcp-ibkr" && echo "stopped" || echo "not running"
fi
