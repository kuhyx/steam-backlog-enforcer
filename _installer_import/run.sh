#!/bin/bash

# ============================================================================
# Install a Steam game from whatever you happen to have: an AppID, a Steam URL,
# or the game's name.
#
#   ./run.sh 284160
#   ./run.sh https://steamcommunity.com/app/284160/guides/
#   ./run.sh BeamNG.drive
#   ./run.sh BeamNG
#
# Dependencies install themselves on first run. Every other argument is passed
# straight through to the CLI, so `./run.sh --help` lists the full set.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly VENV_PY="${SCRIPT_DIR}/.venv/bin/python"
readonly STAMP="${SCRIPT_DIR}/.venv/.deps-ok"
readonly INSTALLER="${SCRIPT_DIR}/install.sh"

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
	if [[ -x "$VENV_PY" ]]; then
		"$VENV_PY" -m steam_installer.cli --help
	fi
	exit 0
}

# Dependencies are only re-checked when the stamp is missing or older than the
# files that decide what gets installed, so a normal run adds no startup cost.
deps_are_current() {
	[[ -x "$VENV_PY" ]] || return 1
	[[ -f "$STAMP" ]] || return 1
	[[ "$STAMP" -nt "$INSTALLER" ]] || return 1
	[[ "$STAMP" -nt "${SCRIPT_DIR}/pyproject.toml" ]] || return 1
	"$VENV_PY" -c 'import steam_installer' >/dev/null 2>&1
}

main() {
	if [[ "$SKIP_DEPS" != "1" ]] && ! deps_are_current; then
		"$INSTALLER"
	fi

	if [[ "$DEPS_ONLY" -eq 1 ]]; then
		exit 0
	fi

	[[ -x "$VENV_PY" ]] || {
		echo "error: no virtualenv at ${VENV_PY}. Run ./install.sh" >&2
		exit 1
	}

	# `-m` rather than the console script, so a stale .venv shim can never
	# shadow the working tree.
	exec "$VENV_PY" -m steam_installer.cli "${ARGS[@]}"
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
