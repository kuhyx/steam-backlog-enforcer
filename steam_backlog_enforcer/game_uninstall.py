"""Uninstalling games and querying what is installed.

Split out of :mod:`steam_backlog_enforcer.game_install` to keep both files
under the 250-line cap: that module owns getting a game *onto* disk, this one
owns taking it off and reporting what is there.
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
from typing import TYPE_CHECKING

from steam_backlog_enforcer._game_names import _is_protected_name
from steam_backlog_enforcer._protected_apps import PROTECTED_APP_IDS
from steam_backlog_enforcer._steam_state import STEAMAPPS_PATH, _assert_not_real_steam
from steam_backlog_enforcer._whitelist import get_approved_exception_ids

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Game uninstall management
# ──────────────────────────────────────────────────────────────


def get_installed_games() -> list[tuple[int, str]]:
    """Parse appmanifest files to find installed games.

    Returns: list of (app_id, game_name) tuples.
    """
    installed: list[tuple[int, str]] = []

    for manifest_file in STEAMAPPS_PATH.glob("appmanifest_*.acf"):
        with contextlib.suppress(OSError):
            content = manifest_file.read_text(encoding="utf-8")
            app_id_match = re.search(r'"appid"\s+"(\d+)"', content)
            name_match = re.search(r'"name"\s+"([^"]+)"', content)
            if app_id_match:
                app_id = int(app_id_match.group(1))
                name = name_match.group(1) if name_match else f"Unknown ({app_id})"
                installed.append((app_id, name))

    installed.sort(key=lambda x: x[1].lower())
    return installed


def _read_install_dir(manifest: Path) -> Path | None:
    """Read installdir from a game's appmanifest file."""
    if not manifest.exists():
        return None
    try:
        content = manifest.read_text(encoding="utf-8")
        match = re.search(r'"installdir"\s+"([^"]+)"', content)
        if match:
            return STEAMAPPS_PATH / "common" / match.group(1)
    except OSError:
        pass
    return None


def _remove_manifest(manifest: Path, game_name: str, app_id: int) -> bool:
    """Remove a game manifest file.

    Args:
        manifest: Path to the appmanifest file.
        game_name: Human-readable game name for logging.
        app_id: Steam application ID.
    """
    _assert_not_real_steam(manifest)
    try:
        if manifest.exists():
            manifest.unlink()
            logger.info(
                "Removed manifest for %s (AppID=%d)", game_name or app_id, app_id
            )
    except OSError:
        logger.exception("Failed to remove manifest for AppID=%d", app_id)
        return False
    return True


def _remove_game_dirs(install_dir: Path | None, app_id: int) -> bool:
    """Remove game installation directory and cache directories.

    Args:
        install_dir: Path to the game's install directory, or None.
        app_id: Steam application ID.
    """
    success = True
    if install_dir and install_dir.is_dir():
        _assert_not_real_steam(install_dir)
        if _is_protected_name(install_dir.name):
            logger.warning(
                "Refusing to remove %s: name matches an allowed game", install_dir
            )
            return False
        try:
            shutil.rmtree(install_dir)
            logger.info("Removed game files: %s", install_dir)
        except OSError:
            logger.exception("Failed to remove game dir %s", install_dir)
            success = False

    for subdir in ("shadercache", "compatdata"):
        cache_path = STEAMAPPS_PATH / subdir / str(app_id)
        if cache_path.is_dir():
            _assert_not_real_steam(cache_path)
            with contextlib.suppress(OSError):
                shutil.rmtree(cache_path)
                logger.debug("Removed %s/%d", subdir, app_id)

    return success


def uninstall_game(app_id: int, game_name: str = "") -> bool:
    """Uninstall a single game by removing its manifest and game files.

    Uses direct file removal instead of ``steam://uninstall`` URI to avoid
    GUI popups and to work when Steam is not running.
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    install_dir = _read_install_dir(manifest)
    success = _remove_manifest(manifest, game_name, app_id)
    if not _remove_game_dirs(install_dir, app_id):
        success = False
    return success


def uninstall_other_games(allowed_app_ids: set[int]) -> int:
    """Uninstall all installed games except the allowed ones and protected IDs.

    Args:
        allowed_app_ids: Every app id that must survive — the assignment plus
            any concurrent manual picks. Empty means "keep nothing".

    Returns: number of games uninstalled.
    """
    installed = get_installed_games()
    count = 0

    for app_id, name in installed:
        if app_id in allowed_app_ids:
            logger.info("KEEPING allowed game: %s (AppID=%d)", name, app_id)
            continue
        if is_protected_app(app_id):
            logger.debug("Skipping protected: %s (AppID=%d)", name, app_id)
            continue

        logger.info("UNINSTALLING: %s (AppID=%d)", name, app_id)
        if uninstall_game(app_id, name):
            count += 1

    return count


def is_protected_app(app_id: int) -> bool:
    """Return True if *app_id* must never be uninstalled.

    Combines the hardcoded Steam infrastructure set with any app IDs that
    have been approved via the time-locked exception mechanism.

    Args:
        app_id: Steam application ID to check.

    Returns:
        True if the app should be left alone by the enforcer.
    """
    return app_id in PROTECTED_APP_IDS or app_id in get_approved_exception_ids()
