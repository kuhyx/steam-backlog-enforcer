#!/usr/bin/env bash
# Open the Steam Backlog Enforcer web UI in its own Chromium app window.
#
# The server is the steam-backlog-enforcer-web user unit; this only makes
# sure it is up and points an --app window at it. A dedicated profile keeps
# the window free of the main browser's tabs and extensions and gives it its
# own WM class, so i3 can treat it like a native app.
set -euo pipefail

readonly UNIT="steam-backlog-enforcer-web"
readonly URL="${SBE_UI_URL:-http://127.0.0.1:8000/}"
readonly PROFILE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/steam-backlog-enforcer/ui-profile"
readonly WM_CLASS="steam-backlog-enforcer"
readonly WAIT_SECONDS=15

find_browser() {
    local candidate
    for candidate in chromium google-chrome-stable; do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    echo "Error: no chromium or google-chrome-stable on PATH." >&2
    return 1
}

# Start the unit if it is not running; Restart=always keeps it up after.
ensure_server() {
    if ! systemctl --user is-active --quiet "$UNIT"; then
        systemctl --user start "$UNIT"
    fi
    local waited=0
    until curl --silent --fail --max-time 1 --output /dev/null "$URL"; do
        if ((waited >= WAIT_SECONDS)); then
            echo "Error: $URL did not answer within ${WAIT_SECONDS}s." >&2
            echo "Check: journalctl --user -u $UNIT -n 50" >&2
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

main() {
    local browser
    browser="$(find_browser)"
    ensure_server
    mkdir -p "$PROFILE_DIR"
    # setsid + nohup: the window must outlive the terminal that ran run.sh.
    setsid nohup "$browser" \
        --app="$URL" \
        --class="$WM_CLASS" \
        --user-data-dir="$PROFILE_DIR" \
        --no-first-run \
        --no-default-browser-check \
        >/dev/null 2>&1 &
    echo "Opened $URL"
}

main "$@"
