#!/bin/bash
# Download and unpack IBC (the IB Gateway auto-login helper) into ibc/, which is gitignored.
# Pin the version so a rebuild gives the same thing.
set -euo pipefail
PROJECT="/Users/mtalib/workspace_repos/personal_repo/agentic_trading"
VERSION="3.24.2"
URL="https://github.com/IbcAlpha/IBC/releases/download/$VERSION/IBCMacos-$VERSION.zip"
mkdir -p "$PROJECT/ibc" "$PROJECT/output"
curl -sL -o "$PROJECT/output/IBCMacos-$VERSION.zip" "$URL"
unzip -q -o "$PROJECT/output/IBCMacos-$VERSION.zip" -d "$PROJECT/ibc"
chmod +x "$PROJECT/ibc"/*.sh "$PROJECT/ibc"/scripts/*
echo "IBC $VERSION installed at $PROJECT/ibc"
