#!/bin/bash
# One tick of the trading loop, with the plumbing checked first.
#
# This is the script launchd calls every five minutes during market hours. See
# /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist
# and /Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/LAUNCHD.md
#
# Run it by hand any time, it is safe:
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh
#
# What it does, in order:
#   1. checks IB Gateway is listening on port 4002, the paper port
#   2. checks the MCP server answers on http://127.0.0.1:8765/mcp, and starts it
#      with agent/start_mcp.sh if it does not
#   3. runs one tick of agent/loop.py in dry run
#   4. writes everything to output/tick_YYYY-MM-DD.log
#
# DRY RUN IS HARDCODED below. Nothing this script runs can place an order.
# Changing that is a deliberate, separate act: replace --dry-run with --live on
# the MODE line, and the loop will still refuse unless the environment variable
# AGENTIC_TRADING_LIVE_ORDERS is set to yes and the account id starts with DU.
# Do not change it until Mo has approved the numbers in docs/STRATEGY.md.

set -uo pipefail

PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
VENV="$PROJECT/venv312"
LOG_DIR="$PROJECT/output"
LOG="$LOG_DIR/tick_$(date +%Y-%m-%d).log"

GATEWAY_HOST="127.0.0.1"
GATEWAY_PORT="4002"          # IB Gateway paper. Live is 4001 and must never appear here.
MCP_URL="http://127.0.0.1:8765/mcp"

# The one line that decides whether this can trade. Leave it as --dry-run.
MODE="--dry-run"

mkdir -p "$LOG_DIR"

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" >> "$LOG"; }

# Kill switch. agent/kill_switch.sh writes this file; while it exists no tick runs at all.
[[ -f "$LOG_DIR/LOOP_DISABLED" ]] && { say "LOOP_DISABLED exists, so this tick did nothing. Clear it with $PROJECT/agent/reenable.sh"; exit 0; }

say "----- tick starting, mode $MODE -----"

# A live port here would mean real money. Refuse outright.
if [[ "$GATEWAY_PORT" == "4001" || "$GATEWAY_PORT" == "7496" ]]; then
  say "STOPPING: port $GATEWAY_PORT is a LIVE IBKR port. This project is paper only."
  exit 1
fi

# 1. IB Gateway. If it is not up we cannot start it here, because logging in
#    needs a person and IBKR expires the session weekly. Say so and stop.
if nc -z -G 3 "$GATEWAY_HOST" "$GATEWAY_PORT" >/dev/null 2>&1; then
  say "IB Gateway is listening on $GATEWAY_HOST:$GATEWAY_PORT."
else
  say "STOPPING: nothing is listening on $GATEWAY_HOST:$GATEWAY_PORT, so IB Gateway is down."
  say "  Start it and log into the paper account: $PROJECT/agent/start_gateway.sh"
  say "  IBKR ends the session on Sundays at 1 AM Eastern, so one login a week is normal."
  exit 1
fi

# 2. The MCP server. This one we can start.
mcp_answers() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$MCP_URL" 2>/dev/null)"
  # 000 means nothing answered at all. Any real HTTP code means it is alive.
  # A bare GET gets 406 back, which is the server correctly saying it wants a
  # proper MCP request. That still counts as up.
  [[ -n "$code" && "$code" != "000" ]]
}

if mcp_answers; then
  say "MCP server is answering at $MCP_URL."
else
  say "MCP server is not answering. Starting it with agent/start_mcp.sh"
  "$PROJECT/agent/start_mcp.sh" >> "$LOG" 2>&1
  # Give it a moment to bind the port and connect to Gateway.
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if mcp_answers; then
      say "MCP server came up after about $((attempt * 2)) seconds."
      break
    fi
  done
  if ! mcp_answers; then
    say "STOPPING: the MCP server still is not answering at $MCP_URL."
    say "  Look at $LOG_DIR/mcp_logs/mcp_ibkr.log"
    exit 1
  fi
fi

# 3. The tick itself, in the project's own Python.
if [[ ! -x "$VENV/bin/python" ]]; then
  say "STOPPING: no Python at $VENV/bin/python. Rebuild the venv:"
  say "  python3.12 -m venv $VENV && $VENV/bin/pip install -r $PROJECT/requirements-312.txt"
  exit 1
fi

# Activating the venv rather than just calling its python, so that anything the
# loop shells out to (the scanner, for one) gets the same interpreter.
# shellcheck disable=SC1091
source "$VENV/bin/activate"
cd "$PROJECT" || { say "STOPPING: cannot enter $PROJECT"; exit 1; }
export TZ="America/New_York"

python "$PROJECT/agent/loop.py" $MODE >> "$LOG" 2>&1
STATUS=$?

if [[ $STATUS -eq 0 ]]; then
  say "----- tick finished cleanly -----"
else
  say "----- tick finished BADLY, exit code $STATUS -----"
fi
exit $STATUS
