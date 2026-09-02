#!/bin/bash
# Start the IBKR MCP server (HTTP, localhost only) against the running IB Gateway.
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_mcp.sh
# Stop with:
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_mcp.sh
set -euo pipefail
PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
ENV_FILE="$PROJECT/config/mcp_ibkr.env"
BIN="$PROJECT/venv312/bin/mcp-ibkr"
LOG_DIR="$PROJECT/output/mcp_logs"
PIDFILE="$PROJECT/output/mcp_ibkr.pid"

[[ -x "$BIN" ]] || { echo "mcp-ibkr not installed in venv312. Run: $PROJECT/venv312/bin/pip install -r $PROJECT/requirements-312.txt"; exit 1; }
set -a; source "$ENV_FILE"; set +a
if [[ "${MCP_BIND_HOST:-}" != "127.0.0.1" ]]; then
  echo "Refusing to start: MCP_BIND_HOST must be 127.0.0.1, the server has no authentication."; exit 1
fi
if [[ "${IBKR_PORT:-}" == "4001" || "${IBKR_PORT:-}" == "7496" ]]; then
  echo "Refusing to start: IBKR_PORT $IBKR_PORT is a LIVE port."; exit 1
fi
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "MCP server already running, pid $(cat "$PIDFILE")"; exit 0
fi
mkdir -p "$LOG_DIR"
nohup "$BIN" >> "$LOG_DIR/mcp_ibkr.log" 2>&1 &
echo $! > "$PIDFILE"
echo "IBKR MCP server started, pid $(cat "$PIDFILE"), endpoint http://$MCP_BIND_HOST:$MCP_PORT/mcp, trading enabled: $IBKR_ENABLE_TRADING"
echo "log: $LOG_DIR/mcp_ibkr.log"
