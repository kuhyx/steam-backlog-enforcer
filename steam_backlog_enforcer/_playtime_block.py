"""Make Steam and game launchers unlaunchable once the daily budget is spent.

The block is a **read-only bind mount** of a refusal stub over every launcher
entry point. Nothing else here is negotiable, and future changes must not
substitute an alternative:

* ``chmod 000`` and rename-aside both mutate persistent on-disk state that
  outlives this process. A crash mid-block leaves Steam unexecutable with no
  automatic recovery.
* ``guardctl file-guard`` is an anti-*drift* keeper, not a swapper: it snapshots
  the target as canonical and copies canonical back over the target. Pointing it
  at a stub would permanently overwrite ``/usr/bin/steam``.

A bind mount mutates zero bytes of the real binary, ``umount`` is a perfect
restore, and a reboot clears every mount unconditionally. That last property is
the whole safety argument: the worst case is "reboot fixes it".

Four targets, because the first three are bypasses of one another —
``/usr/bin/steam`` is a two-line ``exec /usr/lib/steam/steam "$@"`` wrapper, and
Steam ships its own executable bootstrap inside the user's home directory.

``/proc/self/mountinfo`` is the authority on what is currently masked, never the
saved state. That is what makes the block self-healing: a stale mount is
released even if the state file was deleted, and a mount lost to a reboot is
re-applied on the next tick.

**The daemon must keep a shared mount namespace.** Adding ``PrivateMounts=``,
``PrivateTmp=`` or ``ProtectSystem=`` to the systemd unit would make these
mounts invisible outside the service, silently turning the block into a no-op
while the counter kept running. :func:`mounts_are_visible` checks for exactly
that at runtime.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from steam_backlog_enforcer._playtime_mountinfo import _mountpoints
from steam_backlog_enforcer._playtime_run import _run

logger = logging.getLogger(__name__)

BLOCK_TARGETS: tuple[Path, ...] = (
    # Every steam.desktop action uses this path; it is only a wrapper.
    Path("/usr/bin/steam"),
    # The real bootstrap. Named directly rather than via the
    # /usr/lib/steam/steam symlink because mount(2) resolves symlinks, so
    # mounting the link would mount here anyway under a misleading name.
    Path("/usr/lib/steam/bin_steam.sh"),
    # Steam's self-updating bootstrap, owned by the user and independently
    # executable.
    Path.home() / ".local" / "share" / "Steam" / "steam.sh",
    Path("/usr/bin/lutris"),
)

# The stub lives on root-owned tmpfs, NOT in CONFIG_DIR. A bind mount shares the
# inode: a stub in a user-writable directory could be rewritten to exec the real
# bootstrap, and the block would evaporate without a single mount changing.
_STUB_DIR = Path("/run/steam-backlog-enforcer")
STUB_PATH = _STUB_DIR / "gaming-blocked"

MOUNTINFO_PATH = Path("/proc/self/mountinfo")
_INIT_MOUNTINFO_PATH = Path("/proc/1/mountinfo")

# pacman holds this for the whole transaction. Re-mounting mid-transaction is
# what would actually cause the EBUSY the PreTransaction hook exists to avoid.
PACMAN_LOCK = Path("/var/lib/pacman/db.lck")

_PROC = Path("/proc")

# Bind mounts stack, so one umount need not be enough. guard-lib's
# collapse_bind_mount() uses the same bounded loop for the same reason.
_MAX_UMOUNT_PASSES = 20

_MOUNTINFO_MIN_FIELDS = 5
_MOUNTPOINT_FIELD = 4


_STUB_MODE = 0o755

_STUB_SCRIPT = """#!/bin/sh
# Installed by steam-backlog-enforcer. Bind-mounted over the real launcher
# while the daily gaming budget is exhausted; removed automatically at 06:00.
echo "Gaming blocked: daily budget used up. Unblocks at 06:00." >&2
exit 1
"""


def block_targets() -> tuple[Path, ...]:
    """Return the launcher paths the block masks.

    An accessor rather than a direct import of ``BLOCK_TARGETS``: module-level
    constants are bound by value at import time, so a second binding elsewhere
    would need its own test patch to stay isolated. Routing every reader through
    one function keeps that to a single patch point.

    Returns:
        The masked launcher paths.
    """
    return BLOCK_TARGETS


def mounted_targets() -> set[Path]:
    """Return the block targets currently masked by a mount.

    Read in-process from mountinfo rather than shelling out to ``findmnt``:
    this runs on every enforce tick, and a fork per tick is exactly the polling
    cost this codebase avoids elsewhere.

    Anything mounted on a block target is treated as ours — nothing else on this
    system mounts over those paths.

    Returns:
        The masked targets.
    """
    return _mountpoints(MOUNTINFO_PATH) & set(block_targets())


def mounts_are_visible() -> bool:
    """Whether mounts made here are visible to the rest of the system.

    A private mount namespace (``PrivateMounts=``, ``ProtectSystem=`` and
    friends) would keep every mount inside the service, so the block would do
    nothing while the counter kept running — a silent fail-open. Compared
    against PID 1's namespace, which is the one that matters.

    Returns:
        True if no mount we made is missing from PID 1's view.
    """
    ours = mounted_targets()
    if not ours:
        return True
    return bool(ours & _mountpoints(_INIT_MOUNTINFO_PATH))


def _ensure_stub() -> bool:
    """Write the refusal stub, replacing any existing copy.

    Returns:
        True if the stub is present and executable.
    """
    try:
        _STUB_DIR.mkdir(parents=True, exist_ok=True)
        STUB_PATH.write_text(_STUB_SCRIPT, encoding="utf-8")
        STUB_PATH.chmod(_STUB_MODE)
    except OSError:
        logger.exception("Could not write the playtime refusal stub.")
        return False
    return True


def apply_block() -> list[Path]:
    """Mask every unmasked block target with the refusal stub.

    Skipped entirely while pacman holds its database lock: re-mounting during a
    transaction is what makes package extraction fail ``EBUSY``. The kill loop is
    not gated this way, so enforcement continues regardless.

    Returns:
        The targets newly masked by this call.
    """
    if PACMAN_LOCK.exists():
        logger.info("pacman transaction in progress; deferring playtime mounts.")
        return []
    if not _ensure_stub():
        return []

    already = mounted_targets()
    newly: list[Path] = []
    for target in block_targets():
        if target in already or not target.exists():
            continue
        if not _run([_mount_bin(), "--bind", str(STUB_PATH), str(target)]):
            continue
        if _run([_mount_bin(), "-o", "remount,ro,bind", str(target)]):
            newly.append(target)
    return newly


def release_block() -> list[Path]:
    """Unmask every masked block target.

    Loops per target because bind mounts stack; bounded so a target that cannot
    be unmounted cannot spin forever.

    Returns:
        The targets released by this call.
    """
    released: list[Path] = []
    for target in mounted_targets():
        for _ in range(_MAX_UMOUNT_PASSES):
            if target not in mounted_targets():
                released.append(target)
                break
            if not _run([_umount_bin(), "-l", str(target)]):
                logger.warning("Could not release playtime mount on %s.", target)
                break
    return released


def reconcile(*, should_block: bool) -> tuple[list[Path], list[Path]]:
    """Drive the on-disk mount state toward *should_block*.

    Idempotent and driven by mountinfo, so it costs one file read per tick when
    nothing needs changing. Because it reads the live mount table rather than
    saved state, it releases a stale block even if the state file was deleted,
    and re-applies a block that a reboot cleared.

    Args:
        should_block: Whether the launchers should currently be masked.

    Returns:
        A ``(newly_masked, newly_released)`` pair.
    """
    if not should_block:
        return [], release_block()

    masked = apply_block()
    if masked and not mounts_are_visible():
        logger.error(
            "Playtime mounts are not visible outside this service — the block "
            "is not in force. Check the unit for PrivateMounts/ProtectSystem.",
        )
    return masked, []


def _mount_bin() -> str:
    """Return the ``mount`` executable path.

    Returns:
        Absolute path to ``mount``.
    """
    return shutil.which("mount") or "/usr/bin/mount"


def _umount_bin() -> str:
    """Return the ``umount`` executable path.

    Returns:
        Absolute path to ``umount``.
    """
    return shutil.which("umount") or "/usr/bin/umount"
