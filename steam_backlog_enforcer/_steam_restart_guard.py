"""When it is *not* safe to bounce a running Steam.

Opening the CDP debug port requires restarting Steam, and a restart is never
free: it takes down whatever the client is currently doing. Two situations make
that unacceptable, and both defer rather than abort — the enforce loop retries
every few seconds, so waiting costs a pass and nothing else.

Split out of :mod:`_steam_launch` to keep it under the 250-line cap, and because
"is a restart safe right now" is a question worth being able to ask on its own.
"""

from __future__ import annotations

import logging
from pathlib import Path

from steam_backlog_enforcer._steam_errors import (
    FastInstallInProgressError,
    GameInProgressError,
    SteamUpdateInProgressError,
)
from steam_backlog_enforcer._steam_state import steam_update_in_progress
from steam_backlog_enforcer.enforcer import get_running_steam_game_pids

logger = logging.getLogger(__name__)


def game_is_running() -> bool:
    """Whether a Steam game is currently running.

    Uses the same ``SteamAppId != 0`` predicate as the playtime budget, which
    excludes the Steam client's own process tree — the client being up is not a
    reason to defer, only an actual game is.

    Returns:
        Whether any game process is live.
    """
    return any(app_id != 0 for app_id in get_running_steam_game_pids().values())


def assert_safe_to_restart() -> None:
    """Refuse to restart Steam while doing so would destroy something.

    Raises:
        GameInProgressError: If a game is running. Bouncing Steam kills it and
            any unsaved progress with it — observed on 2026-08-28, when
            restarting the daemon to deploy an unrelated change ended a live
            session. Library hiding can wait; an afternoon cannot be returned.
        SteamUpdateInProgressError: If a game update is downloading or
            committing. The shutdown suspends it and can leave a partially
            written install (the root cause of the AoE2 launch crash).
    """
    if game_is_running():
        msg = (
            "Deferring Steam restart: a game is running. Restarting now would "
            "kill it and lose unsaved progress; will retry once it exits."
        )
        logger.info(msg)
        raise GameInProgressError(msg)

    if steam_update_in_progress():
        msg = (
            "Deferring Steam restart: a game update is in progress. Restarting "
            "now would interrupt and can corrupt it; will retry once the "
            "update settles."
        )
        logger.info(msg)
        raise SteamUpdateInProgressError(msg)


# Matched against /proc cmdlines, so a run started by hand counts exactly like
# one the enforcer spawned. run.sh as well as the module it execs: the sudo
# and bash wrappers exist the moment Popen returns, the Python process only a
# moment later, and a Steam launch in that gap would race the shutdown.
_INSTALLER_MARKERS = (b"steam-game-installer/run.sh", b"steam_installer.cli")


def fast_install_running() -> bool:
    """Whether a steam-game-installer run is live (and so owns Steam's state).

    Returns:
        True if any process is running the installer's CLI module.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if any(marker in cmdline for marker in _INSTALLER_MARKERS):
            return True
    return False


def assert_no_fast_install() -> None:
    """Refuse to launch Steam while steam-game-installer holds it closed.

    Raises:
        FastInstallInProgressError: If an installer run is live.
    """
    if fast_install_running():
        msg = "Deferring Steam launch: steam-game-installer is running."
        logger.info(msg)
        raise FastInstallInProgressError(msg)
