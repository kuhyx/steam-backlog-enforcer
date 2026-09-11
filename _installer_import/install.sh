#!/bin/bash
# Checks for depotdownloader and steamcmd on PATH. steamcmd is AUR-only and
# needs an interactive license/sudo prompt, so it's never installed for you --
# this just tells you the command to run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

missing=0

if ! command -v depotdownloader >/dev/null 2>&1; then
	echo "missing: depotdownloader (see ~/vendor/depotdownloader)" >&2
	missing=1
fi

if ! command -v steamcmd >/dev/null 2>&1; then
	echo "missing: steamcmd -- run: yay -S steamcmd" >&2
	missing=1
fi

setup_dev_env() {
	# The test suite requires 100% coverage (pyproject: fail_under = 100), and
	# one test runs `python -m steam_installer.cli` in a subprocess. Coverage in
	# a child process is only recorded if it calls coverage.process_startup() at
	# interpreter start, which is what this .pth does. Without it a clean clone
	# reports 99% and the suite fails.
	local venv="${SCRIPT_DIR}/.venv"
	[[ -d "$venv" ]] || return 0

	local python="${venv}/bin/python"
	"$python" -m pip install -q -e "${SCRIPT_DIR}[dev]" 2>/dev/null ||
		"$python" -m pip install -q -e "$SCRIPT_DIR" pytest pytest-cov

	local site_packages
	site_packages="$("$python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
	cat >"${site_packages}/steam_installer_coverage.pth" <<-'PTH'
		import os, coverage; os.environ.get("COVERAGE_PROCESS_START") and coverage.process_startup()
	PTH
	echo "Dev environment ready (subprocess coverage enabled)."
}

if [[ "$missing" -eq 0 ]]; then
	echo "All dependencies present."
fi

setup_dev_env

exit "$missing"
