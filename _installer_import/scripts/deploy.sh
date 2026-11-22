#!/bin/bash

# ============================================================================
# Deploy origin/main to where this tool runs: kuhy's checkout
# (~/src/steam-game-installer, used through ./run.sh). Refuses a dirty tree,
# fast-forwards it, reruns ./run.sh --deps-only (libibus, depotdownloader, the native Proton,
# editable .venv), then starts the CLI as the health check. Nothing is
# published elsewhere: no package, no service, no release.
# Idempotent; non-zero unless the checkout is at origin/main and the CLI starts.
#   scripts/deploy.sh
#   SGI_DEPLOY_DIR=/path   another checkout (the test uses a fixture)
# ============================================================================

set -euo pipefail

readonly DIR="${SGI_DEPLOY_DIR:-$HOME/src/steam-game-installer}"

die() {
	echo "deploy: FAILED ($1)" >&2
	exit 1
}

main() {
	[[ -d "$DIR/.git" ]] || die "no checkout at $DIR"
	[[ -z "$(git -C "$DIR" status --porcelain)" ]] || die "$DIR has local changes"
	git -C "$DIR" checkout -q main || die "cannot switch $DIR to main"
	git -C "$DIR" pull -q --ff-only origin main || die "cannot fast-forward $DIR"
	local head want
	head="$(git -C "$DIR" rev-parse HEAD)"
	want="$(git -C "$DIR" rev-parse origin/main)"
	[[ "$head" == "$want" ]] || die "$DIR is at ${head:0:7}, origin/main is ${want:0:7}"
	(cd "$DIR" && ./run.sh --deps-only) || die "dependency install failed"
	"$DIR/.venv/bin/python" -m steam_installer.cli --help >/dev/null ||
		die "health check: the CLI does not start"
	echo "deploy: $DIR at ${head:0:7}, deps ok, CLI starts"
}

main "$@"
