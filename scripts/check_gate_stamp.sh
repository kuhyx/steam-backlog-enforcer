#!/bin/bash

# ============================================================================
# pre-push gate: is the pushed tree stamped as having passed the local gate?
#
# Thin delegate to the shared tool in ~/src/utils. The pre-push stage used to
# re-run every suite (10+ min under the resource cap); now finish_auto.sh's
# gate leaves a receipt (the tree hash) and this only compares against it.
#
# Usage:
#   scripts/check_gate_stamp.sh check   # pre-commit's pre-push stage (~1 s)
#   scripts/check_gate_stamp.sh full    # the old pre-push suites, then stamp
# ============================================================================

set -euo pipefail

readonly SHARED_GATE="${UTILS_ROOT:-$HOME/src/utils}/scripts/gate_stamp.sh"

main() {
    if [[ ! -x "$SHARED_GATE" ]]; then
        echo "Error: shared gate-stamp tool not found at $SHARED_GATE" >&2
        echo "       Clone github.com/kuhyx/utils to ~/src/utils, or set" >&2
        echo "       UTILS_ROOT to where it lives." >&2
        exit 1
    fi

    exec bash "$SHARED_GATE" "$@"
}

main "$@"
