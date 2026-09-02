#!/bin/bash
# Stop the IBKR MCP server started by start_mcp.sh.
PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
PIDFILE="$PROJECT/output/mcp_ibkr.pid"
if [[ -f "$PIDFILE" ]]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped pid $(cat "$PIDFILE")" || echo "not running"
  rm -f "$PIDFILE"
else
  pkill -f "venv312/bin/mcp-ibkr" && echo "stopped" || echo "not running"
fi
