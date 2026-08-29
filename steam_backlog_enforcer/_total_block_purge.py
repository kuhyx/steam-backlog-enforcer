"""Removing Steam and Proton: processes, packages and filesystem remnants.

One responsibility -- making Steam and its Proton helpers *not present* --
expressed over the generic pacman primitives in
:mod:`steam_backlog_enforcer._pacman`. The network side of the block lives
in :mod:`steam_backlog_enforcer._total_block_net`; the two are independent.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import shutil

from steam_backlog_enforcer._pacman import (
    is_package_installed,
    pacman_owner,
    uninstall_package,
)
from steam_backlog_enforcer._total_block_launchers import STEAM_CLIENT_PROCESS_NAMES
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write
from steam_backlog_enforcer.enforcer import (
    get_pids_by_process_names,
    kill_processes_by_name,
)

logger = logging.getLogger(__name__)

STEAM_PACKAGE = "steam"

_STEAM_PURGE_LOG_FILE = CONFIG_DIR / "total_block_purge_log.json"

# Fixed allowlist of known Steam/Proton filesystem remnants to delete - NOT
# a recursive "anything whose name contains 'steam'" sweep, which would also
# catch unrelated files (AUR build checkouts, archives, other apps' own save
# data) that merely share the substring. Confirmed present on the reference
# machine: ~/.steam (symlink farm), ~/steam (secondary/portable install),
# ~/.local/share/Steam (the real install - steamapps, userdata, screenshots,
# and compatibilitytools.d's GE-Proton builds all live under here).
_STEAM_REMNANT_PATHS: tuple[Path, ...] = (
    Path.home() / ".steam",
    Path.home() / "steam",
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steampath",
    Path.home() / ".steampid",
    Path.home() / ".config" / "steamtinkerlaunch",
    Path.home() / ".config" / "CSDSteamBuild",
)

# Proton-management helper packages (not Steam itself, not launched by
# STEAM_CLIENT_PROCESS_NAMES) - installed via pacman/AUR, so pacman -R
# is sufficient; no separate process-kill needed as these are short-lived
# CLI/GUI tools, not background daemons.
_PROTON_HELPER_PACKAGES: tuple[str, ...] = (
    "protondb-tags-git",
    "protonhax-git",
    "protontricks-git",
    "protonup-ng-git",
    "protonup-qt",
)


def is_steam_installed() -> bool:
    """Return True if the ``steam`` pacman package is currently installed."""
    return is_package_installed(STEAM_PACKAGE)


def uninstall_steam_package() -> bool:
    """Remove the ``steam`` pacman package.

    Returns True on success or if it was already absent.
    """
    return uninstall_package(STEAM_PACKAGE)


def kill_and_uninstall_launchers(
    launcher_process_names: frozenset[str],
) -> list[tuple[int, str]]:
    """Kill running third-party launchers and uninstall their pacman package.

    Resolves each PID's ``/proc/<pid>/exe`` target *before* sending SIGTERM,
    since the symlink stops resolving once the process has exited. Package
    removal is best-effort: launchers installed outside pacman (flatpak,
    AppImage, a wine prefix) simply have no owning package and are just
    killed again next tick, same as before this existed.

    Args:
        launcher_process_names: Launcher process names to kill.

    Returns:
        The ``(pid, name)`` pairs that were killed.
    """
    pids = get_pids_by_process_names(launcher_process_names)
    exe_paths: dict[int, str] = {}
    for pid in pids:
        with contextlib.suppress(OSError):
            exe_paths[pid] = str(Path(f"/proc/{pid}/exe").resolve(strict=True))

    killed = kill_processes_by_name(launcher_process_names)

    packages: set[str] = set()
    for pid, _name in killed:
        exe_path = exe_paths.get(pid)
        if exe_path is not None:
            package = pacman_owner(exe_path)
            if package is not None:
                packages.add(package)

    for package in packages:
        if not uninstall_package(package):
            logger.warning(
                "Total block: failed to uninstall launcher package %s", package
            )

    return killed


def kill_steam_and_launchers(
    launcher_process_names: frozenset[str],
) -> list[tuple[int, str]]:
    """Kill Steam client and known third-party launcher processes.

    Args:
        launcher_process_names: Launcher process names to kill.

    Returns:
        The ``(pid, name)`` pairs that were killed.
    """
    steam_killed = kill_processes_by_name(STEAM_CLIENT_PROCESS_NAMES)
    launcher_killed = kill_and_uninstall_launchers(launcher_process_names)
    return steam_killed + launcher_killed


def _uninstall_proton_helpers() -> list[str]:
    """Uninstall known Proton-management helper packages that are present.

    Returns the subset of :data:`_PROTON_HELPER_PACKAGES` that were actually
    installed and successfully removed (for logging), not the full fixed
    list.
    """
    removed: list[str] = []
    for package in _PROTON_HELPER_PACKAGES:
        if not is_package_installed(package):
            continue
        if uninstall_package(package):
            removed.append(package)
        else:
            logger.warning("Total block: failed to uninstall proton helper %s", package)
    return removed


def _remove_steam_remnants() -> list[str]:
    """Delete the curated Steam/Proton filesystem remnants that exist.

    Symlinks are unlinked directly rather than following them into
    :func:`shutil.rmtree`, since e.g. ``~/.steampath`` -> a file inside
    ``~/.steam``, which this same pass may already have removed.
    """
    removed: list[str] = []
    for path in _STEAM_REMNANT_PATHS:
        if not (path.is_symlink() or path.exists()):
            continue
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        except OSError:
            logger.exception("Failed to remove steam remnant %s", path)
            continue
        removed.append(str(path))
    return removed


def _log_steam_purge(removed_paths: list[str], removed_packages: list[str]) -> None:
    """Append a timestamped record of a Steam/Proton purge to disk.

    A no-op when nothing was actually removed, so the log only grows on
    ticks that did real work (this runs every enforce tick while the block
    is active - see ``enforce_total_block_tick``).
    """
    if not removed_paths and not removed_packages:
        return
    try:
        existing = json.loads(_STEAM_PURGE_LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except OSError, json.JSONDecodeError, ValueError:
        existing = []
    existing.append(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "removed_paths": removed_paths,
            "removed_packages": removed_packages,
        }
    )
    _atomic_write(_STEAM_PURGE_LOG_FILE, json.dumps(existing, indent=2) + "\n")


def purge_steam_and_proton() -> None:
    """Remove curated Steam/Proton filesystem remnants and helper packages.

    Best-effort and re-run every enforce tick, same as the Steam-package
    reappearance check: a stat() per fixed path and a ``pacman -Qi`` per
    helper package are cheap even when there is nothing left to do.
    """
    removed_paths = _remove_steam_remnants()
    removed_packages = _uninstall_proton_helpers()
    if removed_paths or removed_packages:
        logger.info(
            "Total block: purged steam path(s) %s, proton package(s) %s",
            removed_paths,
            removed_packages,
        )
    _log_steam_purge(removed_paths, removed_packages)
