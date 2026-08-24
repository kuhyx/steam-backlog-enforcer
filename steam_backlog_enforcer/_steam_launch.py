"""Getting Steam running with its devtools port open.

Split out of :mod:`steam_backlog_enforcer.library_hider` to keep both files
under the 250-line cap: this module owns the Steam *lifecycle* (is it up, does
it have a CDP port, restart it as the desktop user), not what to do with it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import time

from steam_backlog_enforcer._cdp import (
    _CDP_PORT,
    _cdp_result_value,
    _evaluate_js,
    _get_shared_js_ws_url,
)
from steam_backlog_enforcer._desktop_env import (
    desktop_runtime_dir,
    desktop_session_ready,
    desktop_uid,
)
from steam_backlog_enforcer._steam_errors import (
    DesktopSessionNotReadyError,
    SteamUnavailableError,
    SteamUpdateInProgressError,
)
from steam_backlog_enforcer._steam_process import _run_as_user
from steam_backlog_enforcer._steam_state import steam_update_in_progress

logger = logging.getLogger(__name__)

_CDP_TIMEOUT = 120
_STEAM_STARTUP_WAIT = 45
# Real Steam client binary, as shipped by the distro's `steam` package.
#
# Deliberately NOT probed with shutil.which("steam"): a launcher wrapper on
# $PATH (e.g. /usr/local/bin/steam adding -cef-* flags) keeps `which` truthy
# long after the package itself is gone - as happens when a total block
# uninstalls Steam. Checking the real binary is what actually answers
# "can we launch Steam at all?".
_STEAM_BINARY = "/usr/bin/steam"


def steam_is_installed() -> bool:
    """Return True if the real Steam client binary is present."""
    return Path(_STEAM_BINARY).exists()


# Handles for fire-and-forget launches, kept only so they can be reaped.
_SPAWNED: list[subprocess.Popen[bytes]] = []


# ──────────────────────────────────────────────────────────────
# Ensure Steam is running with devtools port
# ──────────────────────────────────────────────────────────────


def _is_steam_running() -> bool:
    """Check whether any Steam process is alive."""
    pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
    result = subprocess.run(
        [pgrep, "-x", "steam"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _steam_has_debug_port() -> bool:
    """Check whether steamwebhelper is listening on the CDP port."""
    return _get_shared_js_ws_url() is not None


def _wait_for_cdp_ready() -> bool:
    """Wait up to *_STEAM_STARTUP_WAIT* seconds for CDP to become ready."""
    for _ in range(_STEAM_STARTUP_WAIT):
        if _get_shared_js_ws_url() is not None:
            return True
        time.sleep(1)
    return False


def _wait_for_collections_ready() -> bool:
    """Wait until ``collectionStore`` is fully initialised.

    Right after Steam starts, the CDP port may be open but the
    internal collection data hasn't loaded yet.  Poll a lightweight
    JS check until ``GetCollection`` stops throwing.
    """
    js = (
        "(() => { try { collectionStore.GetCollection('hidden');"
        " return 'ok'; } catch(e) { return 'not_ready'; } })()"
    )
    for _ in range(_STEAM_STARTUP_WAIT):
        try:
            result = _evaluate_js(js)
            if _cdp_result_value(result) == "ok":
                return True
        except RuntimeError:
            pass
        time.sleep(1)
    return False


def _resolve_desktop_user() -> str | None:
    """Resolve which desktop user owns the Steam/X11 session.

    Prefers the explicit STEAM_ENFORCER_DESKTOP_USER (set by the systemd
    unit, which has no SUDO_USER/USER of its own since it is started
    directly by systemd rather than via `sudo`), then falls back to
    SUDO_USER/USER for interactive `sudo` invocations.
    """
    return (
        os.environ.get("STEAM_ENFORCER_DESKTOP_USER")
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
    )


def _shutdown_steam() -> None:
    """Send ``steam -shutdown`` and wait for the process to exit."""
    real_user = _resolve_desktop_user()
    try:
        _run_as_user(["steam", "-shutdown"], real_user)
    except FileNotFoundError:
        return

    pgrep = shutil.which("pgrep") or "/usr/bin/pgrep"
    for _ in range(30):
        result = subprocess.run(
            [pgrep, "-x", "steam"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return
        time.sleep(1)


def _launch_steam_with_debug() -> None:
    """Launch Steam with CEF debugging enabled."""
    real_user = _resolve_desktop_user()
    _run_as_user(
        [
            "steam",
            "-cef-enable-debugging",
            f"-devtools-port={_CDP_PORT}",
            "-silent",
        ],
        real_user,
    )


def ensure_steam_debug_port() -> None:
    """Make sure Steam is running with the CDP debug port open.

    If Steam is running without the port, it is restarted.
    If Steam is not running, it is launched.

    Raises:
        SteamUnavailableError: If Steam is not installed, or is installed but
            never opens its debug port.
    """
    if _steam_has_debug_port():
        logger.debug("Steam CDP port already available.")
        return

    # Bail out before the ~45s launch-and-wait: with no binary to exec there
    # is nothing to wait for, and retrying every pass only burns time and
    # leaves dead processes behind.
    if not steam_is_installed():
        msg = f"Steam is not installed ({_STEAM_BINARY} does not exist)"
        raise SteamUnavailableError(msg)

    # Never launch Steam into a session that does not exist yet: it would get
    # a missing XDG_RUNTIME_DIR, silently fall back to winealsa, and stay
    # audio-broken until the next restart. Defer instead — the loop retries.
    real_user = _resolve_desktop_user()
    if os.geteuid() == 0 and not desktop_session_ready(desktop_uid(real_user)):
        msg = (
            "Deferring Steam launch: the desktop session's runtime directory "
            f"({desktop_runtime_dir(desktop_uid(real_user))}) does not exist "
            "yet. Launching now would leave Steam without audio; will retry."
        )
        logger.info(msg)
        raise DesktopSessionNotReadyError(msg)

    logger.info("Steam CDP port not available — (re)starting Steam...")
    if _is_steam_running():
        # Never bounce a running Steam while a game update is downloading or
        # committing: the shutdown suspends it and can leave a partially
        # written install (the root cause of the AoE2 launch crash). Defer and
        # retry on the next enforce pass.
        if steam_update_in_progress():
            msg = (
                "Deferring Steam restart: a game update is in progress. "
                "Restarting now would interrupt and can corrupt it; will "
                "retry once the update settles."
            )
            logger.info(msg)
            raise SteamUpdateInProgressError(msg)
        _shutdown_steam()

    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        msg = "Timed out waiting for Steam CDP port to become ready"
        raise SteamUnavailableError(msg)
    logger.info("Steam CDP port ready.")

    if not _wait_for_collections_ready():
        msg = "Timed out waiting for Steam collections to initialise"
        raise SteamUnavailableError(msg)
    logger.info("Steam collection store ready.")


# ──────────────────────────────────────────────────────────────
# Steam restart helper
# ──────────────────────────────────────────────────────────────


def restart_steam() -> None:
    """Gracefully restart the Steam client with CEF debugging enabled.

    Skips the restart if a game update is downloading or committing, so the
    update is not interrupted (interrupting it can corrupt the install).
    """
    if steam_update_in_progress():
        logger.warning(
            "Skipping Steam restart — a game update is in progress; "
            "restarting now could corrupt it.",
        )
        return

    logger.info("Restarting Steam client with debug port...")
    _shutdown_steam()
    _launch_steam_with_debug()

    if not _wait_for_cdp_ready():
        logger.warning("Steam restarted but CDP port not ready.")
    else:
        logger.info("Steam restarted with CDP port ready.")
