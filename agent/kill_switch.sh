#!/bin/bash
# The panic button. Stop the loop, cancel every order, close every position.
#
#   REHEARSAL, safe any time, sends nothing to the broker:
#     /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh
#
#   FOR REAL, cancels and trades:
#     /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really
#
# Both forms stop the loop first, straight away, before anything slower happens.
# They create two files:
#
#   output/STOP           the loop reads this and stops opening positions. It may
#                         still close what is open, because getting out is always
#                         allowed.
#   output/LOOP_DISABLED  run_tick.sh reads this and does not run a tick at all.
#
# Creating those two files is the fast, certain part, and it happens whether or
# not you remembered --really. That is deliberate: the worst outcome would be
# somebody typing this command in a hurry, leaving off --really, and walking away
# believing the agent had been stopped when it had not.
#
# agent/kill_switch.py writes the same two files as its own first step, so on the
# normal path they are written twice with the same content. Either half of the
# panic button on its own stops the loop.
#
# What --really adds is the part that talks to the broker: cancelling working
# orders and selling out of every position at the market. Without it, the script
# reads the account and prints exactly what it would have done.
#
# Every argument is passed straight through to agent/kill_switch.py, so the third
# flag works here too:
#
#   --live-account-ok   allow an account that does not start with DU to be
#                       flattened. It needs AGENTIC_TRADING_KILL_LIVE=yes in the
#                       environment as well, and refuses without both:
#
#     AGENTIC_TRADING_KILL_LIVE=yes .../agent/kill_switch.sh --really --live-account-ok
#
# Turn everything back on with:
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh

set -uo pipefail

# Where the project lives. AGENTIC_TRADING_ROOT wins when it is set; otherwise
# this script works it out from its own location, so a plain clone anywhere on
# any Mac just works with nothing configured.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON="$PROJECT/venv312/bin/python"
OUTPUT="$PROJECT/output"

REALLY=""
for ARGUMENT in "$@"; do
  if [[ "$ARGUMENT" == "--really" ]]; then
    REALLY="yes"
  fi
done

mkdir -p "$OUTPUT"

STAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf 'Written by kill_switch.sh at %s.\nThe loop may close positions but must not open any.\nClear it with %s/agent/reenable.sh\n' \
  "$STAMP" "$PROJECT" > "$OUTPUT/STOP"
printf 'Written by kill_switch.sh at %s.\nrun_tick.sh will not run a tick while this file exists.\nClear it with %s/agent/reenable.sh\n' \
  "$STAMP" "$PROJECT" > "$OUTPUT/LOOP_DISABLED"

echo "The loop is stopped:"
echo "  created $OUTPUT/STOP"
echo "  created $OUTPUT/LOOP_DISABLED"
echo

if [[ ! -x "$PYTHON" ]]; then
  echo "STOPPING: no Python at $PYTHON, so the broker side cannot run."
  echo "The two files above are still in place, so the loop will not trade."
  echo "Rebuild the environment with:"
  echo "  python3.12 -m venv $PROJECT/venv312 && $PROJECT/venv312/bin/pip install -r $PROJECT/requirements-312.txt"
  exit 1
fi

if [[ -z "$REALLY" ]]; then
  echo "REHEARSAL. Nothing will be cancelled and nothing will be traded."
  echo "To do it for real: $0 --really"
  echo
fi

"$PYTHON" "$PROJECT/agent/kill_switch.py" "$@"
STATUS=$?

echo
echo "Turn the loop back on with: $PROJECT/agent/reenable.sh"
exit $STATUS
