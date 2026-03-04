#!/usr/bin/env bash
# Quick launcher for the "done" workflow:
#   check completion → open HLTB → pick next game → uninstall & hide others
set -euo pipefail

cd "$(dirname "$0")/../.."
exec python -m python_pkg.steam_backlog_enforcer.main "done"
