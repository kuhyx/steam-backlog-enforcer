"""Game installation and uninstallation management."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from steam_backlog_enforcer._desktop_env import (
    desktop_session_ready,
    desktop_uid,
    desktop_user_cmd,
)
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._fast_install import (
    fast_install,
    is_fast_installing,
    poll_fast_installs,
)
from steam_backlog_enforcer._steam_client import (
    _ensure_steam_running,
    _get_real_user,
    _get_uid_gid_for_user,
    is_game_installed,
)
from steam_backlog_enforcer._steam_restart_guard import fast_install_running
from steam_backlog_enforcer._steam_state import (
    STEAMAPPS_PATH,
    is_game_fully_installed,
    steam_library_ready,
)
from steam_backlog_enforcer.game_uninstall import (
    get_installed_games,
    is_protected_app,
    uninstall_game,
    uninstall_other_games,
)

logger = logging.getLogger(__name__)

# Re-exported for callers that predate the split of this module: many modules
# still do `from ...game_install import _echo`. __all__ is what keeps the
# linter from deleting these as unused -- they exist purely to be re-exported.
__all__ = [
    "_echo",
    "get_installed_games",
    "install_game",
    "is_game_installed",
    "is_protected_app",
    "uninstall_game",
    "uninstall_other_games",
]

# Latches the "no Steam library" warning so a 3s enforce loop logs it once
# rather than once per game per pass.
_LIBRARY_WARNED: set[str] = set()


def _trigger_steam_install(app_id: int, label: str) -> bool:
    """Ask Steam to install a game via the ``steam://install`` URI.

    Returns True if the URI handler was invoked successfully.
    """
    xdg_open = shutil.which("xdg-open") or "/usr/bin/xdg-open"
    real_user = _get_real_user()

    # Without the drop this opens steam://install as root, and Steam answers
    # with a "Cannot run as root user" modal on the user's display.
    if os.geteuid() == 0 and not desktop_session_ready(desktop_uid(real_user)):
        logger.debug("Deferring Steam install for %s: no desktop session.", label)
        return False

    try:
        subprocess.run(
            desktop_user_cmd([xdg_open, f"steam://install/{app_id}"], real_user),
            capture_output=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError, OSError, subprocess.TimeoutExpired:
        return False
    logger.info("Triggered Steam install for %s via protocol handler", label)
    return True


# ──────────────────────────────────────────────────────────────
# Game install management
# ──────────────────────────────────────────────────────────────


def _install_precheck(app_id: int, label: str) -> bool | None:
    """Settle an install without starting one, where that is possible.

    Returns:
        True if the game is installed or already being fast-installed, False
        if no install may start right now, None to go ahead and install.
    """
    # Re-arm the one-shot warning before any early return, so a library that
    # comes back (Steam finally signed in) is reported again if it vanishes.
    if steam_library_ready():
        _LIBRARY_WARNED.discard("missing")

    poll_fast_installs()
    if is_game_fully_installed(app_id):
        logger.info("Game already installed: %s", label)
        return True

    # A live installer holds Steam closed; steam:// would reopen it underneath
    # the manifest the installer is about to write. Wait for it to finish.
    if fast_install_running():
        if is_fast_installing(app_id):
            return True
        logger.info("Deferring install of %s: steam-game-installer busy.", label)
        return False

    # No library means no install can succeed — neither the steam:// handler
    # nor the appmanifest write below. Without this the enforce loop retried
    # every allowed game every pass (measured: 1656 times in 30 minutes).
    if not steam_library_ready():
        if "missing" not in _LIBRARY_WARNED:
            logger.warning(
                "Steam library not initialised (%s missing) — skipping installs "
                "until Steam has been signed in to at least once.",
                STEAMAPPS_PATH,
            )
            _LIBRARY_WARNED.add("missing")
        else:
            logger.debug("Skipping install of %s: no Steam library.", label)
        return False
    return None


def install_game(
    app_id: int,
    game_name: str,
    steam_id: str,
    *,
    use_steam_protocol: bool = False,
) -> bool:
    """Install a game, through steam-game-installer when it can be used.

    The fast path (:mod:`_fast_install`) is always tried first; everything
    below it is the fallback for when it is refused or fails.

    When *use_steam_protocol* is True the ``steam://install`` URI handler
    is used, which lets Steam determine the correct install directory from
    its own metadata.  This avoids mismatches between the display name and
    the canonical ``installdir`` that can cause "Missing game executable"
    errors.  Falls back to writing a fabricated appmanifest if the URI
    handler is unavailable.

    When *use_steam_protocol* is False (the default) a minimal
    appmanifest with StateFlags=1026 is written directly.  This is
    suitable for non-interactive / daemon contexts where opening a Steam
    dialog is undesirable.

    Args:
        app_id: Steam application ID.
        game_name: Human-readable game name.
        steam_id: Steam64 ID of the account that owns the game.
        use_steam_protocol: Prefer the ``steam://install`` URI handler.

    Returns True if the install was triggered successfully.
    """
    label = game_name or f"AppID={app_id}"
    ready = _install_precheck(app_id, label)
    if ready is not None:
        return ready

    if fast_install(app_id, label):
        return True
    # Steam already has a download of its own going: let it carry on, rather
    # than overwrite its manifest with the fabricated one below.
    if is_game_installed(app_id):
        return True

    if use_steam_protocol:
        _ensure_steam_running()
        if _trigger_steam_install(app_id, label):
            return True
        logger.debug("steam:// protocol failed; falling back to manifest")

    # Build a minimal appmanifest.  StateFlags 1026 = UpdateRequired (2) +
    # UpdateStarted (1024), which tells Steam "this app needs downloading".
    manifest_content = (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{app_id}"\n'
        '\t"universe"\t\t"1"\n'
        f'\t"name"\t\t"{game_name}"\n'
        '\t"StateFlags"\t\t"1026"\n'
        f'\t"installdir"\t\t"{game_name}"\n'
        '\t"LastUpdated"\t\t"0"\n'
        '\t"LastPlayed"\t\t"0"\n'
        '\t"SizeOnDisk"\t\t"0"\n'
        '\t"StagingSize"\t\t"0"\n'
        '\t"buildid"\t\t"0"\n'
        f'\t"LastOwner"\t\t"{steam_id}"\n'
        '\t"UpdateResult"\t\t"0"\n'
        '\t"BytesToDownload"\t\t"0"\n'
        '\t"BytesDownloaded"\t\t"0"\n'
        '\t"BytesToStage"\t\t"0"\n'
        '\t"BytesStaged"\t\t"0"\n'
        '\t"TargetBuildID"\t\t"0"\n'
        '\t"AutoUpdateBehavior"\t\t"0"\n'
        '\t"AllowOtherDownloadsWhileRunning"\t\t"0"\n'
        '\t"ScheduledAutoUpdate"\t\t"0"\n'
        '\t"InstalledDepots"\n'
        "\t{\n"
        "\t}\n"
        '\t"UserConfig"\n'
        "\t{\n"
        "\t}\n"
        '\t"MountedConfig"\n'
        "\t{\n"
        "\t}\n"
        "}\n"
    )

    manifest_path = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"

    try:
        with manifest_path.open("w", encoding="utf-8") as fh:
            fh.write(manifest_content)

        # Fix ownership so the Steam client (running as the real user) can
        # read and update the manifest.
        real_user = _get_real_user()
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, gid = _get_uid_gid_for_user(real_user)
            os.chown(manifest_path, uid, gid)

        logger.info("Created appmanifest for %s — Steam will auto-download", label)
    except OSError:
        logger.exception("Failed to create appmanifest for %s", label)
        return False

    # Make sure Steam is running so it picks up the manifest.
    _ensure_steam_running()

    return True
