#!/bin/bash
# Stop the IBC-managed IB Gateway without telnet (macOS no longer ships it).
#
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh            stop it
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh --dry-run  say what would happen, touch nothing
#
# Order of attempts:
#   1. IBC command port (CommandServerPort in config/ibc.ini), spoken to with a Python
#      socket, which asks IBC to log out and exit cleanly.
#   2. If the port is off or does not answer, or the process is still alive after the
#      grace period, send TERM to the IBC-launched Gateway java process, then KILL.
# Exit 0 only when no Gateway process remains.
set -uo pipefail

# Where the project lives. AGENTIC_TRADING_ROOT wins when it is set; otherwise
# this script works it out from its own location, so a plain clone anywhere on
# any Mac just works with nothing configured.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
INI="$PROJECT/config/ibc.ini"
PATTERN="ibcalpha.ibc.IbcGateway"
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1

port=$(grep -E '^CommandServerPort=' "$INI" 2>/dev/null | cut -d= -f2 | tr -d ' \r')
pids=$(pgrep -f "$PATTERN" || true)

if [[ -z "$pids" ]]; then
  echo "Gateway is not running."
  rm -f "$PROJECT/output/gatewaystart.filled.sh"
  exit 0
fi
echo "Gateway process(es): $pids"

if [[ -n "$port" && "$port" != "0" ]]; then
  echo "Attempt 1: IBC command port $port (STOP)"
  if [[ $DRY -eq 1 ]]; then
    echo "  dry run: would send STOP to 127.0.0.1:$port"
  else
    python3 - "$port" <<'EOF' || echo "  command port did not answer"
import socket, sys
port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
    s.sendall(b"STOP\n")
    s.settimeout(3)
    try:
        print("  IBC said:", s.recv(200).decode(errors="replace").strip())
    except socket.timeout:
        pass
    s.sendall(b"EXIT\n")
EOF
    for i in $(seq 1 30); do pgrep -f "$PATTERN" >/dev/null || break; sleep 1; done
  fi
else
  echo "Attempt 1 skipped: CommandServerPort is off in $INI (takes effect after the next Gateway start)"
fi

if pgrep -f "$PATTERN" >/dev/null; then
  echo "Attempt 2: TERM the Gateway process"
  if [[ $DRY -eq 1 ]]; then
    echo "  dry run: would pkill -TERM -f $PATTERN, wait 15s, then pkill -KILL"
  else
    pkill -TERM -f "$PATTERN" || true
    for i in $(seq 1 15); do pgrep -f "$PATTERN" >/dev/null || break; sleep 1; done
    if pgrep -f "$PATTERN" >/dev/null; then
      echo "  still alive, sending KILL"
      pkill -KILL -f "$PATTERN" || true
      sleep 2
    fi
  fi
fi

rm -f "$PROJECT/output/gatewaystart.filled.sh"
if [[ $DRY -eq 1 ]]; then
  echo "dry run complete, nothing was stopped"
  exit 0
fi
if pgrep -f "$PATTERN" >/dev/null; then
  echo "FAILED: Gateway still running: $(pgrep -f "$PATTERN" | tr '\n' ' ')"
  exit 1
fi
echo "Gateway stopped."
