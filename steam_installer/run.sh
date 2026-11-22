#!/bin/bash

# ============================================================================
# Install a Steam game from whatever you happen to have: an AppID, a Steam URL,
# or the game's name. Part of steam-backlog-enforcer; the root daemon launches
# `python3 -m steam_installer.cli` itself, so this is the by-hand entry point.
#
#   steam_installer/run.sh 284160
#   steam_installer/run.sh https://steamcommunity.com/app/284160/guides/
#   steam_installer/run.sh BeamNG.drive
#   steam_installer/run.sh BeamNG
#
# Dependencies install themselves on first run. Every other argument is passed
# straight through to the CLI, so `run.sh --help` lists the full set.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly REPO_DIR="${SCRIPT_DIR%/*}"
readonly PYTHON="${SGI_PYTHON:-/usr/bin/python3}"
readonly STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/steam-game-installer"
readonly STAMP="${STATE_DIR}/.deps-ok"
readonly INSTALLER="${SCRIPT_DIR}/install_deps.sh"
readonly PROTON_LOCK="${SCRIPT_DIR}/data/proton-native.lock"

# The package lives in this checkout, not in site-packages.
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:$PYTHONPATH}"

SKIP_DEPS="${SGI_SKIP_DEPS:-0}"
DEPS_ONLY=0
ARGS=()

usage() {
	echo "Usage: run.sh [TARGET] [OPTIONS]"
	echo
	echo "TARGET is any of:"
	echo "  284160                                        an AppID"
	echo "  https://steamcommunity.com/app/284160/...     a Steam URL"
	echo "  BeamNG.drive                                  the exact name"
	echo "  BeamNG                                        part of the name"
	echo
	echo "run.sh options:"
	echo "  --no-deps      Skip the dependency check (also: SGI_SKIP_DEPS=1)"
	echo "  --deps-only    Install dependencies and exit"
	echo "  -h, --help     Show this help, then the installer's own options"
	echo
	"$PYTHON" -m steam_installer.cli --help
	exit 0
}

# Dependencies are only re-checked when the stamp is missing or older than the
# files that decide what gets installed, so a normal run adds no startup cost.
deps_are_current() {
	[[ -f "$STAMP" ]] || return 1
	[[ "$STAMP" -nt "$INSTALLER" ]] || return 1
	[[ "$STAMP" -nt "${REPO_DIR}/pyproject.toml" ]] || return 1
	[[ "$STAMP" -nt "$PROTON_LOCK" ]] || return 1
	# A bumped pin or a deleted tool folder: the stamp alone would miss both.
	"$PYTHON" -m steam_installer.proton_native --check >/dev/null 2>&1
}

main() {
	if [[ "$SKIP_DEPS" != "1" ]] && ! deps_are_current; then
		"$INSTALLER"
	fi

	if [[ "$DEPS_ONLY" -eq 1 ]]; then
		exit 0
	fi

	# `-m` rather than a console script, so a stale install can never shadow
	# the working tree.
	exec "$PYTHON" -m steam_installer.cli "${ARGS[@]}"
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--no-deps)
		SKIP_DEPS=1
		shift
		;;
	--deps-only)
		DEPS_ONLY=1
		shift
		;;
	-h | --help)
		usage
		;;
	--)
		shift
		ARGS+=("$@")
		break
		;;
	*)
		ARGS+=("$1")
		shift
		;;
	esac
done

main
