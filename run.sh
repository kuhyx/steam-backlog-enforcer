#!/usr/bin/env bash
# Launcher for the Steam Backlog Enforcer.
# Usage: ./run.sh            open the web UI (the primary interface)
#        ./run.sh <command>  run a CLI command (backend / recovery path)
set -euo pipefail

cd "$(dirname "$0")"
if [[ $# -eq 0 ]]; then
    exec scripts/open_ui.sh
else
    exec python -m steam_backlog_enforcer.main "$@"
fi
