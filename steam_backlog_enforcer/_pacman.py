"""Thin, reusable wrappers around the pacman package manager.

These operations (query owner, query installed, remove, install) carry no
total-block policy of their own -- they are the generic primitives the
total-block purge is written in terms of, which is why they live here
rather than inside it.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_SUDO = shutil.which("sudo") or "/usr/bin/sudo"

# Call pacman.orig directly (bypassing pacman_wrapper's interactive
# word-unscramble challenge for "steam") - this is the tool's own
# authorized action, not a user bypass attempt, and enforce_total_block_tick
# must be able to run unattended.
PACMAN = shutil.which("pacman.orig") or shutil.which("pacman") or "/usr/bin/pacman.orig"


# pacman's own default hook directories, spelled out because a --hookdir on the
# command line REPLACES them (proved in a throwaway Arch guest, pacman 7.1).
# Later directories win over earlier ones for a hook of the same name, so a
# /dev/null symlink in a directory listed last switches that one hook off.
_HOOK_DIRS = ("/usr/share/libalpm/hooks", "/etc/pacman.d/hooks")
_INSTALL_TIMEOUT_SECONDS = 900


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


def install_package(package: str, *, masked_hooks: Sequence[str] = ()) -> bool:
    """Install *package* via pacman, with the named hooks off for this call only.

    The mask lives in a temporary hook directory, so the masked hook file is
    never edited, moved or removed: the very next pacman call sees it exactly as
    before. Every other hook (guard-lib unlock/relock, the playtime mount
    release, ...) still runs.

    Args:
        package: Package to install (``--needed``: a present one is a no-op).
        masked_hooks: Hook file names to disable for this one transaction.

    Returns:
        True when pacman exited 0; False on any failure, which is logged.
    """
    with tempfile.TemporaryDirectory(prefix="pacman-mask-") as mask_dir:
        hookdirs: list[str] = []
        if masked_hooks:
            for name in masked_hooks:
                (Path(mask_dir) / name).symlink_to("/dev/null")
            dirs = (*_HOOK_DIRS, mask_dir)
            hookdirs = [arg for d in dirs for arg in ("--hookdir", d)]
        try:
            result = subprocess.run(
                [_SUDO, PACMAN, "-S", "--needed", "--noconfirm", *hookdirs, package],
                capture_output=True,
                text=True,
                timeout=_INSTALL_TIMEOUT_SECONDS,
                check=False,
            )
        except OSError, subprocess.SubprocessError:
            logger.exception("Failed to run pacman -S %s", package)
            return False
    if result.returncode == 0:
        return True
    logger.error(
        "pacman -S %s failed (rc=%d): %s",
        package,
        result.returncode,
        result.stderr[-500:] if result.stderr else "",
    )
    return False
