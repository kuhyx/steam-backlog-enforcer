#!/bin/bash

# ============================================================================
# Fail if any dependency in the commit is behind its ecosystem's newest stable.
#
# Thin delegate to the shared gate in ~/src/utils, which owns the registry
# adapters, the pre-release rules and the allowlist semantics. Copying that
# logic here is what lets one repo's idea of "current" drift from every other
# repo's -- so this script only locates the shared checker and forwards its
# arguments.
#
# Usage:
#   scripts/check_dependency_freshness.sh <file> [<file> ...]   # pre-commit
#   scripts/check_dependency_freshness.sh --all --strict        # full local run
#
# Exit: 0 current | 1 behind | 2 allowlist wrong | 3 undeterminable (offline)
# ============================================================================

set -euo pipefail

readonly UTILS="${UTILS_ROOT:-$HOME/src/utils}"
readonly SHARED_GATE="$UTILS/scripts/check_dependency_freshness.sh"
readonly PACMAN_PARSER="$UTILS/dep_freshness/parsers/pacman_lock.py"

# True when this run must judge the native-Proton lock (a full run, or the lock staged).
needs_pacman_adapter() {
    local arg
    for arg in "$@"; do
        [[ "$arg" == "--all" || "$arg" == *proton-native.lock ]] && return 0
    done
    return 1
}

main() {
    if [[ ! -x "$SHARED_GATE" ]]; then
        echo "Error: shared dependency-freshness gate not found at $SHARED_GATE" >&2
        echo "       Clone github.com/kuhyx/utils to ~/src/utils, or set" >&2
        echo "       UTILS_ROOT to where it lives." >&2
        exit 1
    fi

    # An older utils checkout skips a manifest it has no parser for and exits
    # 0, which would wave any Proton pin through. Fail closed instead.
    if needs_pacman_adapter "$@" && [[ ! -f "$PACMAN_PARSER" ]]; then
        echo "Error: $UTILS has no dep_freshness/parsers/pacman_lock.py, so it" >&2
        echo "       cannot check steam_installer/data/proton-native.lock." >&2
        echo "       Update it: git -C $UTILS pull --ff-only" >&2
        exit 1
    fi

    exec bash "$SHARED_GATE" "$@"
}

main "$@"
