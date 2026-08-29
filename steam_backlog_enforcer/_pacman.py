"""Thin, reusable wrappers around the pacman package manager.

These three operations (query owner, query installed, remove) carry no
total-block policy of their own -- they are the generic primitives the
total-block purge is written in terms of, which is why they live here
rather than inside it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

_SUDO = shutil.which("sudo") or "/usr/bin/sudo"

# Call pacman.orig directly (bypassing pacman_wrapper's interactive
# word-unscramble challenge for "steam") - this is the tool's own
# authorized action, not a user bypass attempt, and enforce_total_block_tick
# must be able to run unattended.
PACMAN = shutil.which("pacman.orig") or shutil.which("pacman") or "/usr/bin/pacman.orig"


def pacman_owner(path: str) -> str | None:
    """Return the pacman package name that owns *path*, or None."""
    result = subprocess.run(
        [PACMAN, "-Qo", path],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    marker = " is owned by "
    if marker not in result.stdout:
        return None
    tail = result.stdout.split(marker, 1)[1].strip()
    return tail.split()[0] if tail else None


def is_package_installed(package: str) -> bool:
    """Return True if *package* is currently installed via pacman."""
    result = subprocess.run(
        [PACMAN, "-Qi", package],
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def uninstall_package(package: str) -> bool:
    """Remove *package* via pacman. Returns True on success or if absent."""
    try:
        result = subprocess.run(
            [_SUDO, PACMAN, "-R", "--noconfirm", package],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to run pacman -R %s", package)
        return False
    if result.returncode == 0:
        return True
    if "target not found" in (result.stderr or "").lower():
        return True
    logger.error(
        "pacman -R %s failed (rc=%d): %s",
        package,
        result.returncode,
        result.stderr[-500:] if result.stderr else "",
    )
    return False
