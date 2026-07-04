#!/usr/bin/env bash
# Launcher for the Steam Backlog Enforcer.
# Usage: ./run.sh [command]  (defaults to "done" if no command given)
set -euo pipefail

cd "$(dirname "$0")"
if [[ $# -eq 0 ]]; then
    exec python -m steam_backlog_enforcer.main "done"
else
    exec python -m steam_backlog_enforcer.main "$@"
fi
