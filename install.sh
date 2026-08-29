#!/usr/bin/env bash
# Install script for Steam Backlog Enforcer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Steam Backlog Enforcer Installer ==="
echo

# Install Python deps.
echo "Installing Python dependencies..."
pip3 install --break-system-packages requests howlongtobeatpy 2>/dev/null \
    || pip3 install requests howlongtobeatpy

# 'block-gaming' depends on guard-lib (guardctl) for tamper-resistant
# locking. Not fatal if missing - the rest of this tool works without it.
echo
echo "Checking for guard-lib (required by 'block-gaming')..."
if command -v guardctl >/dev/null 2>&1; then
    echo "guardctl found on PATH."
elif [[ -x "$HOME/utils/guard-lib/install.sh" ]]; then
    echo "guardctl not found - installing guard-lib from $HOME/utils/guard-lib..."
    if [[ $EUID -eq 0 ]]; then
        bash "$HOME/utils/guard-lib/install.sh"
    else
        echo "guard-lib install needs root: sudo bash \"$HOME/utils/guard-lib/install.sh\""
        echo "('block-gaming' will not work until that is done; the rest of this tool is unaffected.)"
    fi
else
    echo "Warning: guardctl not found and ~/utils/guard-lib is not present."
    echo "'block-gaming' requires guard-lib - set up ~/utils/guard-lib and run its install.sh, then re-run this installer."
    echo "(The rest of this tool is unaffected.)"
fi

# Install the web-UI user unit. No root needed: it serves read-only views and
# needs no privilege. Automated rather than documented, because the whole
# reason this unit exists is that a hand-started server outlived its own code.
install_web_user_unit() {
    local target_user home_dir dst src
    target_user="${SUDO_USER:-$USER}"
    home_dir="$(getent passwd "$target_user" | cut -d: -f6)"
    if [[ -z $home_dir ]]; then
        echo "Warning: cannot resolve home for $target_user; skipping web unit."
        return 0
    fi
    src="$SCRIPT_DIR/steam-backlog-enforcer-web.service"
    dst="$home_dir/.config/systemd/user/steam-backlog-enforcer-web.service"
    mkdir -p "$(dirname "$dst")"
    sed "s|__REPO_DIR__|$SCRIPT_DIR|g" "$src" > "$dst"
    if [[ $EUID -eq 0 ]]; then
        chown "$target_user" "$dst"
        sudo -u "$target_user" \
            XDG_RUNTIME_DIR="/run/user/$(id -u "$target_user")" \
            systemctl --user daemon-reload
        sudo -u "$target_user" \
            XDG_RUNTIME_DIR="/run/user/$(id -u "$target_user")" \
            systemctl --user enable --now steam-backlog-enforcer-web || true
    else
        systemctl --user daemon-reload
        systemctl --user enable --now steam-backlog-enforcer-web || true
    fi
    echo "Installed and enabled: $dst"
}

install_web_user_unit

# Install systemd service (system-level, runs as root).
#
# Non-interactive callers (install_core_system.sh, CI, `vm run`) have no stdin,
# where a bare `read` fails and -- under `set -e` -- aborts this whole installer
# with exit 1 after the Python deps are already in place. That made the module
# permanently un-installable from the documented install path. Default to "no"
# when there is no terminal, and let STEAM_ENFORCER_INSTALL_SERVICE=y opt in.
ans="${STEAM_ENFORCER_INSTALL_SERVICE:-}"
if [[ -z $ans ]]; then
    if [[ -t 0 ]]; then
        read -rp "Install systemd enforce service? [y/N] " ans
    else
        ans="n"
        echo "No terminal: skipping the systemd enforce service."
        echo "(Install it later with: sudo STEAM_ENFORCER_INSTALL_SERVICE=y bash install.sh)"
    fi
fi
if [[ "${ans,,}" == "y" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "Error: systemd service install needs root. Re-run with sudo."
        exit 1
    fi

    SERVICE_SRC="$SCRIPT_DIR/steam-backlog-enforcer.service"
    SERVICE_DST="/etc/systemd/system/steam-backlog-enforcer.service"

    # Set the correct working directory, PYTHONPATH, and desktop user (the
    # user whose Steam/X11 session the service should drive) in the service
    # file. install.sh requires root, so it's invoked via `sudo` and
    # SUDO_USER holds the real desktop user.
    DESKTOP_USER="${SUDO_USER:-$USER}"
    sed "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|; \
         s|PYTHONPATH=.*|PYTHONPATH=$SCRIPT_DIR|; \
         s|__DESKTOP_USER__|$DESKTOP_USER|" \
        "$SERVICE_SRC" > "$SERVICE_DST"

    # Daily-gaming-budget pacman hook. While the budget is exhausted a refusal
    # stub is bind-mounted over /usr/bin/steam and friends; a bind mount makes
    # package extraction fail EBUSY, so the mounts must be dropped before any
    # transaction touching those packages.
    HOOK_SRC="$SCRIPT_DIR/pacman-hooks/50-steam-backlog-playtime-unblock.hook"
    HOOK_DST="/etc/pacman.d/hooks/50-steam-backlog-playtime-unblock.hook"
    mkdir -p /etc/pacman.d/hooks
    install -m 644 "$HOOK_SRC" "$HOOK_DST"
    echo "Installed pacman hook: $HOOK_DST"

    systemctl daemon-reload
    systemctl enable steam-backlog-enforcer
    echo "Service installed and enabled."
    echo "  Start now:  sudo systemctl start steam-backlog-enforcer"
    echo "  Check:      sudo systemctl status steam-backlog-enforcer"
    echo "  Logs:       sudo journalctl -u steam-backlog-enforcer -f"
fi

echo
echo "Done! Run manually with:"
echo "  python3 -m steam_backlog_enforcer.main enforce"
