#!/bin/bash
# Download and unpack IBC (the IB Gateway auto-login helper) into ibc/, which is gitignored.
# Pin the version so a rebuild gives the same thing.
set -euo pipefail
# Where the project lives. AGENTIC_TRADING_ROOT wins when it is set; otherwise
# this script works it out from its own location, so a plain clone anywhere on
# any Mac just works with nothing configured.
PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VERSION="3.24.2"
URL="https://github.com/IbcAlpha/IBC/releases/download/$VERSION/IBCMacos-$VERSION.zip"
mkdir -p "$PROJECT/ibc" "$PROJECT/output"
curl -sL -o "$PROJECT/output/IBCMacos-$VERSION.zip" "$URL"
unzip -q -o "$PROJECT/output/IBCMacos-$VERSION.zip" -d "$PROJECT/ibc"
chmod +x "$PROJECT/ibc"/*.sh "$PROJECT/ibc"/scripts/*
echo "IBC $VERSION installed at $PROJECT/ibc"
