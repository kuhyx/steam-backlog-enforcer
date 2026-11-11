#!/bin/bash
# ============================================================================
# ci_mirror.sh — run the exact CI gates locally before a push can leave.
#
# Why: the installed pre-commit hook only checks *staged* files, and the local
# dev environment already has every dependency installed. CI does neither — it
# runs `pre-commit run --all-files` and installs a fresh environment from
# requirements.txt. That gap is why green-locally repos went red in CI
# (missing runtime deps, --all-files lint debt, order-dependent test flakes).
#
# This script reproduces both CI workflows on the developer machine, split
# into parts that each fit the 60 s per-command cap (one gate step each, see
# the ci-mirror-* manual hooks in .pre-commit-config.yaml):
#   venv       a venv built ONLY from requirements.txt (mirrors the Tests
#              workflow's `uv pip install -r requirements.txt`), rebuilt only
#              when requirements.txt changes (hash-gated);
#   precommit  `pre-commit run --all-files` minus pylint (mirrors the
#              pre-commit workflow; pylint runs as the ci-mirror-pylint-*
#              shards, which together check exactly what the pylint hook does);
#   pytest     `python -m pytest` in that clean venv (mirrors Tests), spread
#              over CI_MIRROR_WORKERS xdist workers (default 4); pytest-cov
#              merges the workers and enforces the 100 % gate itself.
# `all` (or no part, or a first argument that is not a part name, the old
# `ci_mirror.sh <pytest args>` form) runs the three in order with the full
# pylint hook: kuhy's terminal, over 60 s, so agents run the gate steps.
# Arguments after the part go to pytest.
#
# Runs on demand (`scripts/check_gate_stamp.sh step <hook-id>`, pre-commit's
# manual stage). It left the pre-push path on 2026-09-20: 10+ minutes per push
# under the resource cap, for work finish_auto.sh had just done.
# ============================================================================

set -euo pipefail

# Requirements file may be overridden (e.g. testsAndMisc uses meta/…).
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-requirements.txt}"
readonly REQUIREMENTS_FILE
readonly WORKERS="${CI_MIRROR_WORKERS:-4}"

ROOT="$(git rev-parse --show-toplevel)"
readonly ROOT
cd "$ROOT"

readonly VENV_DIR="$ROOT/.ci-mirror-venv"
readonly HASH_FILE="$VENV_DIR/.requirements.sha256"
readonly REQ_PATH="$ROOT/$REQUIREMENTS_FILE"

log() { printf 'ci-mirror: %s\n' "$1" >&2; }

fail() {
    log "FAILED — $1"
    log "CI would be red. Fix the above before pushing."
    exit 1
}

require_file() {
    if [[ ! -f "$REQ_PATH" ]]; then
        fail "requirements file not found: $REQ_PATH"
    fi
}

requirements_hash() {
    sha256sum "$REQ_PATH" | cut -d' ' -f1
}

venv_is_fresh() {
    [[ -x "$VENV_DIR/bin/python" && -f "$HASH_FILE" \
        && "$(requirements_hash)" == "$(cat "$HASH_FILE")" ]]
}

# uv when present: the installer CI uses, and fast enough for one gate step.
rebuild_venv() {
    rm -rf "$VENV_DIR"
    if command -v uv >/dev/null 2>&1; then
        uv venv --quiet --python python3 "$VENV_DIR" \
            || fail "uv venv for the clean venv"
        uv pip install --quiet --python "$VENV_DIR/bin/python" -r "$REQ_PATH" \
            || fail "uv pip install -r $REQUIREMENTS_FILE (a dep may be undeclared)"
        return
    fi
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip \
        || fail "pip self-upgrade in the clean venv"
    "$VENV_DIR/bin/python" -m pip install --quiet -r "$REQ_PATH" \
        || fail "pip install -r $REQUIREMENTS_FILE (a dep may be undeclared)"
}

# Rebuild the venv only when requirements.txt changed since the last build.
ensure_venv() {
    if venv_is_fresh; then
        log "venv up to date (requirements.txt unchanged)"
        return
    fi
    log "requirements.txt changed — rebuilding clean venv (mirrors CI install)"
    rebuild_venv
    requirements_hash > "$HASH_FILE"
    log "clean venv ready"
}

# The pytest part never rebuilds: a rebuild would not fit its budget, and a
# stale venv would test the wrong dependencies. Fail closed instead.
require_fresh_venv() {
    venv_is_fresh \
        || fail "clean venv missing or stale; run the ci-mirror-venv step first"
}

run_precommit_all_files() {
    local skip="${1:-}"
    log "pre-commit run --all-files${skip:+ minus $skip} (mirrors the pre-commit workflow)"
    SKIP="${SKIP:+$SKIP,}$skip" pre-commit run --all-files \
        || fail "pre-commit --all-files"
}

run_pytest_clean_venv() {
    log "pytest in the clean venv, $WORKERS workers (mirrors the Tests workflow)"
    "$VENV_DIR/bin/python" -m pytest -n "$WORKERS" "$@" \
        || fail "pytest (clean requirements.txt venv)"
}

run_all() {
    ensure_venv
    run_precommit_all_files
    run_pytest_clean_venv "$@"
}

main() {
    require_file
    case "${1:-all}" in
        venv) ensure_venv ;;
        precommit) run_precommit_all_files pylint ;;
        pytest)
            shift
            require_fresh_venv
            run_pytest_clean_venv "$@"
            ;;
        all)
            [[ $# -gt 0 ]] && shift
            run_all "$@"
            ;;
        *) run_all "$@" ;;
    esac
    log "CI gate passed locally"
}

main "$@"
