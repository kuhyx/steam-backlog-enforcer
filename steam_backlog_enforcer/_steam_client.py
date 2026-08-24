"""Starting the Steam client as the desktop user, and install-state queries.

Split out of :mod:`steam_backlog_enforcer.game_install` to keep it under the
250-line cap. The enforcer runs as root, so everything here is about resolving
*which* user to become before touching the desktop session.
"""

from __future__ import annotations

import logging
import os
import pwd
import subprocess
import time

from steam_backlog_enforcer._desktop_env import (
    desktop_env_args,
    desktop_runtime_dir,
    desktop_session_ready,
    resolve_desktop_user,
)
from steam_backlog_enforcer._steam_launch import steam_is_installed
from steam_backlog_enforcer._steam_state import STEAMAPPS_PATH

logger = logging.getLogger(__name__)


def _get_real_user() -> str | None:
    """Get the desktop user to drop privileges to.

    Delegates to the shared resolver so this module honours
    STEAM_ENFORCER_DESKTOP_USER. Reading only SUDO_USER/USER returned None
    under systemd (which sets neither), so every ``geteuid() == 0 and
    real_user`` guard below silently fell through to running as root.
    """
    return resolve_desktop_user()


def _get_uid_gid_for_user(username: str) -> tuple[int, int]:
    """Get (uid, gid) for a username."""
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return 1000, 1000
    else:
        return pw.pw_uid, pw.pw_gid


def is_game_installed(app_id: int) -> bool:
    """Check if a game is installed by looking for its appmanifest.

    A manifest with StateFlags != 4 (FullyInstalled) means the game is
    still downloading or queued, which still counts as "install triggered".
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    return manifest.exists()


def _ensure_steam_running() -> None:
    """Start the Steam client if it is not already running.

    Does nothing if Steam is not installed - there is no client to start, and
    trying anyway only sleeps 15s waiting on a process that died on exec.
    """
    if not steam_is_installed():
        logger.info("Steam is not installed — skipping client start.")
        return

    # Check if any steam process is running (main client, not just helpers).
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-f", "steam.sh"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logger.debug("Steam client already running")
            return
    except FileNotFoundError:
        pass

    real_user = _get_real_user()
    logger.info("Starting Steam client...")

    try:
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, _ = _get_uid_gid_for_user(real_user)
            # Defer rather than launch a Steam that would come up without a
            # runtime dir, and so without working audio, for the session.
            if not desktop_session_ready(uid):
                logger.info(
                    "Deferring Steam start: %s does not exist yet.",
                    desktop_runtime_dir(uid),
                )
                return
            cmd = [
                "sudo",
                "-u",
                real_user,
                "env",
                *desktop_env_args(real_user, uid),
                "steam",
                "-silent",
            ]
        else:
            cmd = ["steam", "-silent"]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give Steam time to initialize and start scanning manifests.
        time.sleep(15)
    except FileNotFoundError:
        logger.exception("Steam executable not found")


# Latches the "no Steam library" warning so a 3s enforce loop logs it once
# rather than once per game per pass. A set (rather than a module-level bool
# reassigned via `global`) keeps the mutation local to the container.
_LIBRARY_WARNED: set[str] = set()
