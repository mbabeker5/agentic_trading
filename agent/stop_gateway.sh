#!/bin/bash
# Gracefully stop the IBC-managed IB Gateway.
PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
if [[ -x "$PROJECT/ibc/stop.sh" ]]; then
  "$PROJECT/ibc/stop.sh"
else
  pkill -f "ibcalpha.ibc.IbcGateway" || true
fi
rm -f "$PROJECT/output/gatewaystart.filled.sh"
