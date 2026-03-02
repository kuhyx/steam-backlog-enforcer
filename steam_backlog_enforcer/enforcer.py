"""Enforce that only the assigned game may run."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess

logger = logging.getLogger(__name__)


def get_running_steam_game_pids() -> dict[int, int]:
    """Scan /proc to find running Steam game processes.

    Returns: dict mapping PID -> SteamAppId.
    """
    running: dict[int, int] = {}
    proc = Path("/proc")

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()
            pairs = environ.split(b"\x00")
            for pair in pairs:
                if pair.startswith(b"SteamAppId="):
                    value = pair.split(b"=", 1)[1].decode("utf-8", errors="replace")
                    if value.isdigit():
                        running[int(entry.name)] = int(value)
                    break
        except (PermissionError, OSError, ValueError):
            continue

    return running


def enforce_allowed_game(
    allowed_app_id: int | None,
    *,
    kill_unauthorized: bool = True,
) -> list[tuple[int, int]]:
    """Check running games; optionally kill unauthorized ones.

    Returns list of (pid, app_id) that were killed or detected.
    """
    running = get_running_steam_game_pids()
    violations: list[tuple[int, int]] = []

    for pid, app_id in running.items():
        if allowed_app_id is not None and app_id == allowed_app_id:
            continue
        # Skip Steam client itself (app_id 0 or very low IDs).
        if app_id == 0:
            continue

        violations.append((pid, app_id))
        if kill_unauthorized:
            kill_process(pid, app_id)

    return violations


def kill_process(pid: int, app_id: int) -> None:
    """Kill a process by PID."""
    try:
        logger.warning("Killing unauthorized game (AppID=%d, PID=%d)", app_id, pid)
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        logger.debug("Process %d already gone.", pid)
    except PermissionError:
        logger.exception("No permission to kill PID %d.", pid)


def send_notification(title: str, body: str) -> None:
    """Send a desktop notification."""
    _notify_send = shutil.which("notify-send") or "/usr/bin/notify-send"
    try:
        subprocess.run(
            [_notify_send, title, body, "--icon=dialog-warning"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError):
        logger.debug("notify-send not available.")
