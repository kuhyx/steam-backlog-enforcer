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

# git against the utils checkout. A pre-commit run inherits the committing
# repo's git location variables, which would point these commands at the wrong
# repository, so they are cleared first.
utils_git() {
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
        -u GIT_PREFIX git -C "$UTILS" "$@"
}

# Print a gate directory that can read the Proton lock, or nothing.
#
# kuhy's ~/src/utils can lag origin/main (local commits not yet pushed, so it
# cannot fast-forward). Then the gate runs a read-only snapshot of utils'
# origin/main from the cache instead: the checkout itself is never touched.
gate_root_for_lock() {
    if [[ -f "$PACMAN_PARSER" ]]; then
        echo "$UTILS"
        return
    fi
    local sha snapshot
    local -a paths=(scripts/check_dependency_freshness.sh dep_freshness)
    utils_git cat-file -e origin/main:dep_freshness/parsers/pacman_lock.py 2>/dev/null ||
        return 0
    sha="$(utils_git rev-parse origin/main)"
    snapshot="${XDG_CACHE_HOME:-$HOME/.cache}/steam-game-installer/utils-gate/$sha"
    if [[ ! -f "$snapshot/dep_freshness/parsers/pacman_lock.py" ]]; then
        rm -rf "$snapshot.tmp"
        mkdir -p "$snapshot.tmp"
        # The fleet allowlist lives beside the gate, when utils has one.
        if utils_git cat-file -e origin/main:dependency-freshness.allowlist.yaml 2>/dev/null; then
            paths+=(dependency-freshness.allowlist.yaml)
        fi
        utils_git archive origin/main "${paths[@]}" | tar -x -C "$snapshot.tmp"
        rm -rf "$snapshot"
        mv "$snapshot.tmp" "$snapshot"
    fi
    echo "dependency-freshness: $UTILS lacks the pacman adapter; using its origin/main ${sha:0:12}" >&2
    echo "$snapshot"
}

main() {
    if [[ ! -x "$SHARED_GATE" ]]; then
        echo "Error: shared dependency-freshness gate not found at $SHARED_GATE" >&2
        echo "       Clone github.com/kuhyx/utils to ~/src/utils, or set" >&2
        echo "       UTILS_ROOT to where it lives." >&2
        exit 1
    fi

    local root="$UTILS"
    # An older utils checkout skips a manifest it has no parser for and exits
    # 0, which would wave any Proton pin through. Fail closed instead.
    if needs_pacman_adapter "$@"; then
        root="$(gate_root_for_lock)"
        if [[ -z "$root" ]]; then
            echo "Error: $UTILS has no dep_freshness/parsers/pacman_lock.py, so it" >&2
            echo "       cannot check steam_installer/data/proton-native.lock." >&2
            echo "       Update it: git -C $UTILS pull --ff-only" >&2
            exit 1
        fi
    fi

    exec bash "$root/scripts/check_dependency_freshness.sh" "$@"
}

main "$@"
