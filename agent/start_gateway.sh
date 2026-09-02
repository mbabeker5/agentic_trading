#!/bin/bash
# Start IB Gateway (paper) with IBC auto-login.
#
# Reads the paper credentials from .secrets/ibkr_paper.env, never from the command line
# or a committed file. Usage:
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh
# Stop with:
#   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh
set -euo pipefail

PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
SECRETS="$PROJECT/.secrets/ibkr_paper.env"
IBC_DIR="$PROJECT/ibc"
IBC_INI="$PROJECT/config/ibc.ini"
TWS_MAJOR_VRSN="10.45"
TWS_PATH="$HOME/Applications"
SETTINGS_DIR="$PROJECT/output/jts"
LOG_DIR="$PROJECT/output/ibc_logs"

if [[ ! -f "$SECRETS" ]]; then
  echo "Missing $SECRETS"
  echo "Create it with two lines: IBKR_PAPER_USER=... and IBKR_PAPER_PASSWORD=..."
  exit 1
fi
if [[ ! -d "$IBC_DIR/scripts" ]]; then
  echo "IBC not found at $IBC_DIR. Run $PROJECT/agent/install_ibc.sh first."
  exit 1
fi
if [[ ! -d "$TWS_PATH/IB Gateway $TWS_MAJOR_VRSN" ]]; then
  echo "IB Gateway $TWS_MAJOR_VRSN not found under $TWS_PATH"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$SECRETS"
set +a
: "${IBKR_PAPER_USER:?IBKR_PAPER_USER not set in $SECRETS}"
: "${IBKR_PAPER_PASSWORD:?IBKR_PAPER_PASSWORD not set in $SECRETS}"

mkdir -p "$SETTINGS_DIR" "$LOG_DIR"
chmod +x "$IBC_DIR"/*.sh "$IBC_DIR"/scripts/* 2>/dev/null || true

# IBC's own launcher hard-codes its variables at the top of the file, so we make a
# filled-in copy in output/ (gitignored) and run that. The password lives only in
# that temporary copy and in memory.
LAUNCHER="$PROJECT/output/gatewaystart.filled.sh"
sed \
  -e "s|^TWS_MAJOR_VRSN=.*|TWS_MAJOR_VRSN=$TWS_MAJOR_VRSN|" \
  -e "s|^IBC_INI=.*|IBC_INI=$IBC_INI|" \
  -e "s|^TRADING_MODE=.*|TRADING_MODE=paper|" \
  -e "s|^IBC_PATH=.*|IBC_PATH=$IBC_DIR|" \
  -e "s|^TWS_PATH=.*|TWS_PATH=$TWS_PATH|" \
  -e "s|^TWS_SETTINGS_PATH=.*|TWS_SETTINGS_PATH=$SETTINGS_DIR|" \
  -e "s|^LOG_PATH=.*|LOG_PATH=$LOG_DIR|" \
  -e "s|^TWSUSERID=.*|TWSUSERID=$IBKR_PAPER_USER|" \
  -e "s|^TWSPASSWORD=.*|TWSPASSWORD='$IBKR_PAPER_PASSWORD'|" \
  "$IBC_DIR/gatewaystartmacos.sh" > "$LAUNCHER"
chmod 700 "$LAUNCHER"

echo "Starting IB Gateway $TWS_MAJOR_VRSN in PAPER mode as $IBKR_PAPER_USER"
echo "API port 4002, settings in $SETTINGS_DIR, logs in $LOG_DIR"
echo "Watch your phone: IBKR Mobile may ask you to approve the login."
exec "$LAUNCHER"
