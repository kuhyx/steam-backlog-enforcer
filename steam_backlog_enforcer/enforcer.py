"""Enforce that only the assigned game may run."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess

from steam_backlog_enforcer.game_install import (
    is_protected_app,
)

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


def get_pids_by_process_names(names: frozenset[str]) -> dict[int, str]:
    """Scan /proc/*/comm for processes whose command name is in *names*.

    The kernel truncates ``/proc/[pid]/comm`` to 15 characters (plus a null
    terminator), so *names* longer than that (e.g. ``EpicGamesLauncher``,
    ``gdlauncher-carbon``) are matched against their own first 15 characters
    - matching how the kernel actually stores them, not an exact string
    that could never appear in ``comm``.

    Returns: dict mapping PID -> matched comm string.
    """
    truncated = {name[:15]: name for name in names}
    running: dict[int, str] = {}
    proc = Path("/proc")

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except (PermissionError, OSError, ValueError):
            continue
        if comm in truncated:
            running[int(entry.name)] = truncated[comm]

    return running


def kill_processes_by_name(names: frozenset[str]) -> list[tuple[int, str]]:
    """Kill (SIGTERM) every running process whose name is in *names*.

    Matching is by ``/proc/[pid]/comm`` via :func:`get_pids_by_process_names`,
    not the ``SteamAppId`` environment variable (unlike
    :func:`get_running_steam_game_pids`) - this is for non-Steam processes
    (the Steam client itself, and third-party game launchers) that don't set
    that variable.

    Returns: list of (pid, matched_name) actually killed.
    """
    killed: list[tuple[int, str]] = []
    for pid, name in get_pids_by_process_names(names).items():
        if _kill_pid_by_name(pid, name):
            killed.append((pid, name))
    return killed


def _kill_pid_by_name(pid: int, name: str) -> bool:
    """Send SIGTERM to *pid*. Returns True if the signal was delivered."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        logger.exception("No permission to kill PID %d (%s).", pid, name)
        return False
    else:
        return True


def enforce_allowed_game(
    allowed_app_id: int | None,
    *,
    kill_unauthorized: bool = True,
) -> list[tuple[int, int]]:
    """Check running games; optionally kill unauthorized ones.

    Returns list of (pid, app_id) that were killed or detected.
    """
    if allowed_app_id is None:
        return []
    running = get_running_steam_game_pids()
    violations: list[tuple[int, int]] = []

    for pid, app_id in running.items():
        if allowed_app_id is not None and app_id == allowed_app_id:
            continue
        # Skip Steam client itself (app_id 0 or very low IDs).
        if app_id == 0:
            continue
        if is_protected_app(app_id):
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
