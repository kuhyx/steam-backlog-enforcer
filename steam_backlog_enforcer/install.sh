#!/usr/bin/env bash
# Install script for Steam Backlog Enforcer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== Steam Backlog Enforcer Installer ==="
echo

# Install Python deps.
echo "Installing Python dependencies..."
pip3 install --break-system-packages requests howlongtobeatpy 2>/dev/null \
    || pip3 install requests howlongtobeatpy

# Install systemd service (system-level, runs as root).
read -rp "Install systemd enforce service? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "Error: systemd service install needs root. Re-run with sudo."
        exit 1
    fi

    SERVICE_SRC="$SCRIPT_DIR/steam-backlog-enforcer.service"
    SERVICE_DST="/etc/systemd/system/steam-backlog-enforcer.service"

    # Set the correct working directory in the service file.
    sed "s|WorkingDirectory=.*|WorkingDirectory=$REPO_ROOT|" "$SERVICE_SRC" \
        > "$SERVICE_DST"

    systemctl daemon-reload
    systemctl enable steam-backlog-enforcer
    echo "Service installed and enabled."
    echo "  Start now:  sudo systemctl start steam-backlog-enforcer"
    echo "  Check:      sudo systemctl status steam-backlog-enforcer"
    echo "  Logs:       sudo journalctl -u steam-backlog-enforcer -f"
fi

echo
echo "Done! Run manually with:"
echo "  sudo python3 -m python_pkg.steam_backlog_enforcer.main enforce"
