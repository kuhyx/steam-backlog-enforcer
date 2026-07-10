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

# Install systemd service (system-level, runs as root).
read -rp "Install systemd enforce service? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "Error: systemd service install needs root. Re-run with sudo."
        exit 1
    fi

    SERVICE_SRC="$SCRIPT_DIR/steam-backlog-enforcer.service"
    SERVICE_DST="/etc/systemd/system/steam-backlog-enforcer.service"

    # Set the correct working directory and PYTHONPATH in the service file.
    sed "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|; s|PYTHONPATH=.*|PYTHONPATH=$SCRIPT_DIR|" \
        "$SERVICE_SRC" > "$SERVICE_DST"

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
