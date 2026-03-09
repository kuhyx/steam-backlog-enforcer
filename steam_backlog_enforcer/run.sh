#!/usr/bin/env bash
# Launcher for the Steam Backlog Enforcer.
# Usage: ./run.sh [command]  (defaults to "done" if no command given)
set -euo pipefail

cd "$(dirname "$0")/../.."
exec python -m python_pkg.steam_backlog_enforcer.main "${1:-done}"
