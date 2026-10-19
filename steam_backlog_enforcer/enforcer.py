"""Enforce that only the assigned game may run."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess

# The /proc scanners live in leisure_watch.procscan (shared with the leisure
# watcher); bound here because the kill/enforce paths below call them.
from leisure_watch.procscan import (
    get_pids_by_process_names,
    get_running_steam_game_pids,
)

from steam_backlog_enforcer._desktop_env import (
    desktop_user_cmd,
    resolve_desktop_user,
)
from steam_backlog_enforcer._store_tools import run_quiet
from steam_backlog_enforcer.game_uninstall import is_protected_app

logger = logging.getLogger(__name__)


def kill_processes_by_name(names: frozenset[str]) -> list[tuple[int, str]]:
    """Kill (SIGTERM) every running process whose name is in *names*.

    Matching is by ``/proc/[pid]/comm`` via ``get_pids_by_process_names``,
    not the ``SteamAppId`` environment variable (unlike
    ``get_running_steam_game_pids``) - this is for non-Steam processes
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
    return True


def enforce_allowed_game(
    allowed_app_ids: set[int],
    *,
    kill_unauthorized: bool = True,
) -> list[tuple[int, int]]:
    """Check running games; optionally kill unauthorized ones.

    Args:
        allowed_app_ids: Every app id the user may play right now — the
            assignment plus any concurrent manual picks. Empty disables the
            check entirely (nothing is assigned, so nothing is unauthorized).
        kill_unauthorized: Whether to kill violating processes.

    Returns list of (pid, app_id) that were killed or detected.
    """
    if not allowed_app_ids:
        return []
    running = get_running_steam_game_pids()
    violations: list[tuple[int, int]] = []

    for pid, app_id in running.items():
        if app_id in allowed_app_ids:
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
    """Send a desktop notification into the real user's session.

    The enforcer runs as root under systemd, where a bare ``notify-send`` has
    no DBUS_SESSION_BUS_ADDRESS and so cannot reach the user's session bus —
    it failed silently for every caller. Dropping to the desktop user supplies
    the session variables it needs.
    """
    _notify_send = shutil.which("notify-send") or "/usr/bin/notify-send"
    cmd = desktop_user_cmd(
        [_notify_send, title, body, "--icon=dialog-warning"],
        resolve_desktop_user(),
    )
    try:
        run_quiet(cmd)
    except FileNotFoundError, OSError:
        logger.debug("notify-send not available.")
    except subprocess.TimeoutExpired:
        # sudo can block where a bare notify-send would not; a dropped
        # notification is better than an exception escaping the enforce loop.
        logger.debug("notify-send timed out.")
