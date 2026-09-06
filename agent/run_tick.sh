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
#   1. refuses to run at all while output/LOOP_DISABLED exists
#   2. checks IB Gateway is listening on port 4002, the paper port
#   3. checks the MCP server answers on http://127.0.0.1:8765/mcp, and starts it
#      with agent/start_mcp.sh if it does not
#   4. runs one tick of agent/loop.py, which is one tick for every enabled book
#      in config/books.yaml: A, B and E on the momentum clock, C on insider
#      filings and D on Congress filings
#   5. keeps ticking, in this same run, while the loop says it wants looking at
#      again sooner than launchd will wake it. See THE FAST WINDOW below.
#   6. writes everything to output/tick_YYYY-MM-DD.log
#
# THE FAST WINDOW (Momentum v2, item A14, Mo 2026-09-06)
# ------------------------------------------------------
# The momentum books need looking at every 30 seconds between 09:35 and 11:00
# while they are holding something, because their stop is now measured off the
# stock's own daily swing and is roughly five times tighter than it used to be.
# A stop that tight needs sub-minute resolution even with the stop resting at
# the broker, because the stop child is a stop-limit and a triggered one that
# does not fill has to be noticed and marketed out inside a minute.
#
# launchd cannot be told to speed up half way through a morning. Its timetable
# is fixed when the job is loaded. So the loop decides instead: at the end of
# every tick it writes how many seconds it wants to wait into
# output/next_tick_seconds, which is the smallest number any of the five books
# asked for, and this script reads it. When it says less than the launchd gap
# this script sleeps that long and ticks again, in the same run, until the next
# launchd wake up is due. When it says 300, this run is over and launchd handles
# the next one exactly as before.
#
# So the launchd job stays on its five minute timetable and never changes, and
# the 30 second cadence costs nothing but this loop below.
#
# THERE IS NO --dry-run FLAG HERE ANY MORE, and that is not a loosening. Each
# book carries its own mode in config/books.yaml and all five say dry_run, so
# the loop writes down the order it would have sent and stops. A book cannot
# even be set to tiny or full without a promoted_on date and a rules_commit
# hash from the hub beside it, which is a hand edit by Mo.
#
# AGENTIC_TRADING_LIVE_ORDERS IS DELIBERATELY NOT SET BELOW. It is the second
# of the four locks on the live order path, and this script must never set it.
# See the note at the top of agent/loop.py for all four.

set -uo pipefail

# Where the project lives. AGENTIC_TRADING_ROOT wins when it is set; otherwise
# this script works it out from its own location, so a plain clone anywhere on
# any Mac just works with nothing configured.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV="$PROJECT/venv312"
LOG_DIR="$PROJECT/output"
LOG="$LOG_DIR/tick_$(date +%Y-%m-%d).log"

GATEWAY_HOST="127.0.0.1"
GATEWAY_PORT="4002"          # IB Gateway paper. Live is 4001 and must never appear here.
MCP_URL="http://127.0.0.1:8765/mcp"

mkdir -p "$LOG_DIR"

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" >> "$LOG"; }

# Kill switch. agent/kill_switch.sh writes this file; while it exists no tick runs at all.
[[ -f "$LOG_DIR/LOOP_DISABLED" ]] && { say "LOOP_DISABLED exists, so this tick did nothing. Clear it with $PROJECT/agent/reenable.sh"; exit 0; }

say "----- tick starting, all enabled books, dry run per books.yaml -----"

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

# AGENTIC_TRADING_LIVE_ORDERS stays unset on purpose. Do not export it here.
unset AGENTIC_TRADING_LIVE_ORDERS

# How long launchd leaves between wake ups. This script must never still be
# running when the next one starts, so the sub-loop below stops short of it.
LAUNCHD_GAP_SECONDS="${AGENTIC_TRADING_LAUNCHD_GAP:-300}"

# The most sub-ticks one run may do, as a belt and braces stop. At 30 seconds
# apiece, nine of them plus the first is four and a half minutes, which is
# inside the five minute gap with room to spare. If the loop ever wrote a
# nonsense number this is what stops this script running forever.
MAX_SUB_TICKS=9

# How soon the loop wants looking at again, in whole seconds, or the launchd gap
# when it did not say. Anything that is not a plain number is ignored.
next_tick_seconds() {
  local raw
  raw="$(cat "$LOG_DIR/next_tick_seconds" 2>/dev/null | tr -d '[:space:]')"
  if [[ "$raw" =~ ^[0-9]+$ ]] && (( raw > 0 )); then
    echo "$raw"
  else
    echo "$LAUNCHD_GAP_SECONDS"
  fi
}

python "$PROJECT/agent/loop.py" >> "$LOG" 2>&1
STATUS=$?

# The fast window. Only ever entered when the tick above finished cleanly: a
# loop that fell over should be looked at, not run again nine more times.
SUB_TICKS=0
ELAPSED=0
while [[ $STATUS -eq 0 ]] && (( SUB_TICKS < MAX_SUB_TICKS )); do
  WAIT="$(next_tick_seconds)"
  (( WAIT >= LAUNCHD_GAP_SECONDS )) && break
  (( ELAPSED + WAIT >= LAUNCHD_GAP_SECONDS )) && break

  sleep "$WAIT"
  ELAPSED=$(( ELAPSED + WAIT ))
  SUB_TICKS=$(( SUB_TICKS + 1 ))

  # The kill switch is checked again every time round, because a person pulling
  # the handle should not have to wait out a five minute run.
  if [[ -f "$LOG_DIR/LOOP_DISABLED" ]]; then
    say "LOOP_DISABLED appeared, so the fast window stopped after $SUB_TICKS sub-tick(s)."
    break
  fi

  say "fast window: sub-tick $SUB_TICKS, $WAIT seconds after the last one"
  python "$PROJECT/agent/loop.py" >> "$LOG" 2>&1
  STATUS=$?
done

if [[ $STATUS -eq 0 ]]; then
  say "----- tick finished cleanly, $SUB_TICKS extra sub-tick(s) in the fast window -----"
else
  say "----- tick finished BADLY, exit code $STATUS -----"
fi
exit $STATUS
