#!/usr/bin/env bash
# Deploy steam-backlog-enforcer for real: update the live checkout, sync the
# systemd units, restart what is stale, then health-check the running services.
#
# Both services run straight out of ~/src/steam-backlog-enforcer (system unit:
# the enforce daemon; user unit: the web UI), so "deploy" means: pull that
# checkout, and make sure the processes run the pulled code.
#
# Idempotent: a second run pulls nothing, syncs nothing, leaves the daemon
# alone (restarting it opens a gap in the gaming block) and restarts only the
# web unit. Exits non-zero, naming the failed check, unless every health check
# passes. A failed check after a restart is left running, not rolled back:
# a rollback would restart the daemon a second time.
#
# Overridable for tests: SBE_CHECKOUT, SBE_WEB_URL, SBE_CTL_SOCK.
set -euo pipefail

readonly CHECKOUT="${SBE_CHECKOUT:-$HOME/src/steam-backlog-enforcer}"
readonly WEB_URL="${SBE_WEB_URL:-http://127.0.0.1:8000/}"
readonly CTL_SOCK="${SBE_CTL_SOCK:-/run/steam-backlog-enforcer/ctl.sock}"
readonly DAEMON_UNIT="steam-backlog-enforcer"
readonly WEB_UNIT="steam-backlog-enforcer-web"
readonly DAEMON_DST="/etc/systemd/system/$DAEMON_UNIT.service"
readonly WEB_DST="$HOME/.config/systemd/user/$WEB_UNIT.service"
readonly WAIT_SECONDS=20

die() {
    echo "deploy: FAIL: $*" >&2
    exit 1
}

ok() { echo "deploy: ok: $*"; }

# Epoch seconds of a unit's ActiveEnterTimestamp (0 when never active).
unit_started_at() {
    local scope="$1" unit="$2" usec
    usec="$(systemctl "$scope" show "$unit" -p ActiveEnterTimestampMonotonic --value)"
    [[ $usec =~ ^[0-9]+$ && $usec -gt 0 ]] || { echo 0; return; }
    # Monotonic -> wall clock: now_wall - (now_mono - start_mono).
    local now_mono now_wall
    now_mono="$(cut -d' ' -f1 /proc/uptime)"
    now_wall="$(date +%s)"
    awk -v w="$now_wall" -v m="$now_mono" -v s="$usec" \
        'BEGIN { printf "%d\n", w - (m - s / 1e6) }'
}

preflight() {
    [[ -d $CHECKOUT/.git || -f $CHECKOUT/.git ]] \
        || die "checkout missing: $CHECKOUT"
    local branch
    branch="$(git -C "$CHECKOUT" rev-parse --abbrev-ref HEAD)"
    [[ $branch == main ]] || die "checkout on branch '$branch', not main: $CHECKOUT"
    [[ -z "$(git -C "$CHECKOUT" status --porcelain)" ]] \
        || die "checkout has uncommitted changes: $CHECKOUT"
    git -C "$CHECKOUT" pull --ff-only --quiet || die "git pull --ff-only failed in $CHECKOUT"
    ok "checkout at $(git -C "$CHECKOUT" rev-parse --short HEAD)"
}

# Render the repo units the same way install.sh does.
render_daemon_unit() {
    sed "s|WorkingDirectory=.*|WorkingDirectory=$CHECKOUT|; \
         s|PYTHONPATH=.*|PYTHONPATH=$CHECKOUT|; \
         s|__DESKTOP_USER__|$USER|" "$CHECKOUT/$DAEMON_UNIT.service"
}

render_web_unit() {
    sed "s|__REPO_DIR__|$CHECKOUT|g" "$CHECKOUT/$WEB_UNIT.service"
}

# Install units only when they differ; echo which ones changed.
sync_units() {
    local rendered
    rendered="$(mktemp)"
    trap 'rm -f "$rendered"' RETURN

    render_daemon_unit >"$rendered"
    if ! sudo cmp -s "$rendered" "$DAEMON_DST"; then
        sudo install -m 644 "$rendered" "$DAEMON_DST"
        sudo systemctl daemon-reload
        echo daemon
    fi

    render_web_unit >"$rendered"
    if ! cmp -s "$rendered" "$WEB_DST"; then
        mkdir -p "$(dirname "$WEB_DST")"
        install -m 644 "$rendered" "$WEB_DST"
        systemctl --user daemon-reload
        echo web
    fi
}

restart_services() {
    local changed="$1" pkg_commit_at="$2" daemon_at
    daemon_at="$(unit_started_at --system "$DAEMON_UNIT")"
    if [[ $changed == *daemon* ]] || ((daemon_at <= pkg_commit_at)); then
        sudo systemctl restart "$DAEMON_UNIT"
        ok "daemon restarted"
    else
        ok "daemon current, not restarted"
    fi
    systemctl --user restart "$WEB_UNIT"
    ok "web restarted"
}

wait_for() {
    local i
    for ((i = 0; i < WAIT_SECONDS; i++)); do
        "$@" && return 0
        sleep 1
    done
    return 1
}

web_answers() {
    [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$WEB_URL")" == 200 ]]
}

health_check() {
    local pkg_commit_at="$1" daemon_at web_at wd
    # 1. Web unit active and answering 200 (its stale-source guard refuses
    #    to answer on outdated code, so 200 means it runs the current tree).
    systemctl --user is-active --quiet "$WEB_UNIT" || die "check 1: web unit not active"
    wait_for web_answers || die "check 1: web UI at $WEB_URL did not answer 200 within ${WAIT_SECONDS}s"
    ok "check 1: web UI answers 200"

    # 2. Daemon active and started after the last package commit.
    systemctl is-active --quiet "$DAEMON_UNIT" || die "check 2: daemon unit not active"
    daemon_at="$(unit_started_at --system "$DAEMON_UNIT")"
    ((daemon_at > pkg_commit_at)) \
        || die "check 2: daemon started $(date -d "@$daemon_at"), before last package commit $(date -d "@$pkg_commit_at")"
    ok "check 2: daemon active, started after last package commit"

    # 3. Daemon control socket present.
    wait_for test -S "$CTL_SOCK" || die "check 3: control socket missing: $CTL_SOCK"
    ok "check 3: control socket present"

    # 4. Daemon runs from the checkout; web process started after the commit.
    wd="$(systemctl show "$DAEMON_UNIT" -p WorkingDirectory --value)"
    [[ $wd == "$CHECKOUT" ]] || die "check 4: daemon WorkingDirectory is '$wd', not $CHECKOUT"
    web_at="$(unit_started_at --user "$WEB_UNIT")"
    ((web_at > pkg_commit_at)) || die "check 4: web started before last package commit"
    ok "check 4: daemon runs from checkout, web is fresh"
}

main() {
    preflight
    local pkg_commit_at changed
    pkg_commit_at="$(git -C "$CHECKOUT" log -1 --format=%ct -- steam_backlog_enforcer)"
    changed="$(sync_units)"
    [[ -n $changed ]] && ok "units synced: $(echo "$changed" | tr '\n' ' ')"
    restart_services "$changed" "$pkg_commit_at"
    health_check "$pkg_commit_at"
    echo "deploy: PASS"
}

main "$@"
