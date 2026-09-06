#!/bin/bash
# Let the agent work again. The undo for the kill switch and for a failed pre-flight.
#
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh
#
# It deletes the three files that hold the agent back, and says which ones were
# actually there:
#
#   output/LOOP_DISABLED   run_tick.sh refuses to run a tick while this exists.
#                          Written by agent/kill_switch.sh.
#   output/STOP            the loop closes positions but opens none while this
#                          exists. Written by agent/kill_switch.sh, and by hand
#                          when you want to pause without stopping the job.
#   output/NO_TRADE_TODAY  written by agent/preflight.py when a 9 AM check failed.
#                          Same effect as STOP, and it does not clear itself
#                          overnight, on purpose: a morning that failed its
#                          checks should need a person to look before the agent
#                          trades again.
#
# It does not restart IB Gateway, reload any launchd job, or re-open any position
# the kill switch closed. It only removes the brakes.

set -uo pipefail

PROJECT="${AGENTIC_TRADING_ROOT:-/Users/mtalib/workspace_repos/personal_repo/agentic_trading}"
OUTPUT="$PROJECT/output"

REMOVED=0
for NAME in LOOP_DISABLED STOP NO_TRADE_TODAY; do
  if [[ -f "$OUTPUT/$NAME" ]]; then
    rm -f "$OUTPUT/$NAME"
    echo "removed $OUTPUT/$NAME"
    REMOVED=$((REMOVED + 1))
  else
    echo "not there  $OUTPUT/$NAME"
  fi
done

echo
if [[ $REMOVED -eq 0 ]]; then
  echo "Nothing was holding the agent back. It was already free to trade."
else
  echo "$REMOVED brake(s) released. The next tick will run as normal."
fi
echo "Check the loop's own job is still loaded:"
echo "  launchctl print gui/\$(id -u)/com.mtalib.agentic-trading.tick"
