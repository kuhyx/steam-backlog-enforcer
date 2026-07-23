#!/bin/bash
# Checks for depotdownloader and steamcmd on PATH. steamcmd is AUR-only and
# needs an interactive license/sudo prompt, so it's never installed for you --
# this just tells you the command to run.

set -euo pipefail

missing=0

if ! command -v depotdownloader >/dev/null 2>&1; then
	echo "missing: depotdownloader (see ~/depotdownloader)" >&2
	missing=1
fi

if ! command -v steamcmd >/dev/null 2>&1; then
	echo "missing: steamcmd -- run: yay -S steamcmd" >&2
	missing=1
fi

if [[ "$missing" -eq 0 ]]; then
	echo "All dependencies present."
fi

exit "$missing"
