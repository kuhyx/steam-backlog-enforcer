"""Total gaming block: the lock, its status, and the lifecycle that drives it.

This module owns the *state* of a total block -- the guard-lib-protected lock
file and the status derived from it -- and orchestrates the two independent
mechanisms that enforce it:

* :mod:`steam_backlog_enforcer._total_block_purge` makes Steam not installed;
* :mod:`steam_backlog_enforcer._total_block_hosts` and
  :mod:`steam_backlog_enforcer._total_block_iptables` make it unreachable.

There is no in-app command to lift a block early. Tamper-resistance comes
from guard-lib (~/guard-lib): the lock file's ``until`` timestamp is
protected by a bind-mounted, chattr-immutable file-guard instance, and pacman
itself refuses to reinstall/upgrade the ``steam`` package while the lock is
active (package-block).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import shutil
import subprocess

from steam_backlog_enforcer._total_block_hosts import (
    apply_total_block_hosts,
    remove_total_block_hosts,
)
from steam_backlog_enforcer._total_block_iptables import (
    apply_total_block_iptables,
    remove_total_block_iptables,
)
from steam_backlog_enforcer._total_block_launchers import LAUNCHER_PROCESS_NAMES
from steam_backlog_enforcer._total_block_purge import (
    STEAM_PACKAGE,
    is_steam_installed,
    kill_steam_and_launchers,
    purge_steam_and_proton,
    uninstall_steam_package,
)
from steam_backlog_enforcer.config import CONFIG_DIR
from steam_backlog_enforcer.store_blocker import flush_dns_cache

logger = logging.getLogger(__name__)

TOTAL_BLOCK_LOCK_FILE = CONFIG_DIR / "total_block_lock.json"

_PACKAGE_BLOCK_NAME = "steam-block"

_SUDO = shutil.which("sudo") or "/usr/bin/sudo"
_GUARDCTL = shutil.which("guardctl") or "/usr/local/bin/guardctl"


@dataclass
class TotalBlockStatus:
    """Snapshot of the total-block lock state."""

    active: bool
    started_at: datetime | None
    until: datetime | None
    days: int
    days_remaining: float


def _read_lock() -> dict[str, object] | None:
    """Read and parse the total-block lock file, or None if absent/invalid."""
    if not TOTAL_BLOCK_LOCK_FILE.exists():
        return None
    try:
        data = json.loads(TOTAL_BLOCK_LOCK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError, ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_total_block_active() -> bool:
    """Return True if a total gaming block is currently in force."""
    data = _read_lock()
    if data is None:
        return False
    until = data.get("until")
    if not isinstance(until, int | float):
        return False
    return datetime.now(UTC).timestamp() < until


def total_block_needs_cleanup() -> bool:
    """True if a total-block lock file exists on disk but has expired.

    Distinguishes "never started" (no lock file - nothing to do) from
    "expired, not yet cleaned up" (lock file present, `until` has passed) -
    the latter needs :func:`end_total_block_cleanup` called exactly once.
    ``guardctl package-block end`` deletes the lock file, so this is
    naturally self-terminating once cleanup has run.
    """
    return _read_lock() is not None and not is_total_block_active()


def get_total_block_status() -> TotalBlockStatus:
    """Return a snapshot of the current total-block lock state."""
    data = _read_lock()
    if data is None:
        return TotalBlockStatus(
            active=False, started_at=None, until=None, days=0, days_remaining=0.0
        )

    started_at = data.get("started_at")
    until = data.get("until")
    days = data.get("days")

    started_dt = (
        datetime.fromtimestamp(started_at, tz=UTC)
        if isinstance(started_at, int | float)
        else None
    )
    until_dt = (
        datetime.fromtimestamp(until, tz=UTC)
        if isinstance(until, int | float)
        else None
    )

    now = datetime.now(UTC)
    active = until_dt is not None and now < until_dt
    days_remaining = (
        (until_dt - now).total_seconds() / 86400 if active and until_dt else 0.0
    )

    return TotalBlockStatus(
        active=active,
        started_at=started_dt,
        until=until_dt,
        days=days if isinstance(days, int) else 0,
        days_remaining=max(0.0, days_remaining),
    )


def start_total_block(days: int) -> bool:
    """Start a total gaming block for *days* days.

    Registers the package-block lock (bind-mounted, tamper-resistant) via
    guard-lib first - that is the actual enforcement mechanism and must
    succeed for the block to be considered active. Killing processes,
    uninstalling Steam, and applying domain blocks are best-effort follow-up
    steps (logged on failure, re-attempted every enforce tick via
    :func:`enforce_total_block_tick`), since none of them being instantly
    perfect should prevent the lock itself from engaging.

    Returns:
        True if the package-block lock was successfully registered.
    """
    result = subprocess.run(
        [
            _SUDO,
            _GUARDCTL,
            "package-block",
            "start",
            _PACKAGE_BLOCK_NAME,
            "--package",
            STEAM_PACKAGE,
            "--lock-file",
            str(TOTAL_BLOCK_LOCK_FILE),
            "--days",
            str(days),
            "--bind-mount",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        logger.error("Failed to start package-block lock: %s", result.stderr)
        return False

    killed = kill_steam_and_launchers(LAUNCHER_PROCESS_NAMES)
    if killed:
        logger.info("Total block: killed %d process(es): %s", len(killed), killed)

    if not uninstall_steam_package():
        logger.warning("Total block: failed to uninstall steam (will retry each tick)")

    purge_steam_and_proton()

    # iptables MUST be applied before hosts: it resolves real upstream IPs,
    # and once the hosts block is written, local resolution for these same
    # domains collapses to 0.0.0.0 (see _apply_total_block_iptables).
    if not apply_total_block_iptables():
        logger.warning("Total block: failed to apply iptables rules")
    if not apply_total_block_hosts():
        logger.warning("Total block: failed to apply hosts entries")

    flush_dns_cache()
    return True


def enforce_total_block_tick() -> None:
    """Re-assert the total block.

    Called every enforce-loop iteration while :func:`is_total_block_active`
    is True.
    """
    kill_steam_and_launchers(LAUNCHER_PROCESS_NAMES)

    if is_steam_installed():
        logger.warning("Steam reappeared during total block - removing again")
        uninstall_steam_package()

    purge_steam_and_proton()

    apply_total_block_iptables()
    apply_total_block_hosts()


def end_total_block_cleanup() -> None:
    """Clean up after the total-block lock has naturally expired.

    Ends the package-block lock (guard-lib), removes total-block-specific
    hosts/iptables entries, leaving normal ``config.block_store`` state
    untouched. Does *not* reinstall Steam or restore killed processes -
    the user is free to reinstall/relaunch once the block has expired.
    """
    result = subprocess.run(
        [_SUDO, _GUARDCTL, "package-block", "end", _PACKAGE_BLOCK_NAME],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "package-block end failed (may already be ended): %s", result.stderr
        )

    if not remove_total_block_hosts():
        logger.warning("Failed to remove total-block hosts entries")
    if not remove_total_block_iptables():
        logger.warning("Failed to remove total-block iptables rules")

    flush_dns_cache()
    logger.info("Total gaming block ended - normal enforcement resumes.")
