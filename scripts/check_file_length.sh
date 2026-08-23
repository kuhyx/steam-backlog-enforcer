#!/bin/bash

# ============================================================================
# Fail if any file exceeds the shared 250-line cap.
#
# A file that cannot be read in one piece forces re-reads and partial edits,
# which is the largest avoidable cost in an LLM-assisted workflow. The cap
# applies to code AND prose; generated files, markup and data are exempt.
#
# This is a VENDORED copy of ~/utils/file_length/. It is vendored rather than
# referenced because pre-commit's `entry:` is not shell-expanded and CI
# runners have no ~/utils -- an external reference would pass locally and
# silently skip on push.
#
# Usage:
#   scripts/check_file_length.sh <file> [<file> ...]   # pre-commit passes these
#   scripts/check_file_length.sh --all                 # whole tree, from cwd
# ============================================================================

set -euo pipefail

SCRIPTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPTS_ROOT
readonly CHECKER="$SCRIPTS_ROOT/file_length/check.py"

main() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: $(basename "$0") <file>... | --all" >&2
        exit 1
    fi
    if [[ ! -f "$CHECKER" ]]; then
        echo "Error: checker not found at $CHECKER" >&2
        exit 1
    fi

    PYTHONPATH="$SCRIPTS_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
        python3 "$CHECKER" "$@"
}

main "$@"
