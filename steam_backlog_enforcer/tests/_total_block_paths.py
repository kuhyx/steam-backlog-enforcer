"""Shared tmp_path redirection for the total-block test modules.

The block's path constants are spread across the modules that own them
(the lock in ``_total_block``, the IP cache in ``_total_block_iptables``,
the purge log and remnant list in ``_total_block_purge``, the hosts file in
``_total_block_hosts``), so the redirect has to patch each at its real home
rather than one module.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

BLOCK = "steam_backlog_enforcer._total_block"
HOSTS = "steam_backlog_enforcer._total_block_hosts"
IPTABLES = "steam_backlog_enforcer._total_block_iptables"
PURGE = "steam_backlog_enforcer._total_block_purge"


@dataclass
class Paths:
    """The tmp_path locations the total-block constants are redirected to."""

    lock_file: Path
    ip_cache_file: Path
    hosts_file: Path
    purge_log_file: Path
    remnant_paths: tuple[Path, ...]


def build_paths(tmp_path: Path) -> Paths:
    """Build the redirected path set rooted at *tmp_path*.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The populated :class:`Paths`.
    """
    remnant_paths = (
        tmp_path / "home" / ".steam",
        tmp_path / "home" / "steam",
        tmp_path / "home" / ".local" / "share" / "Steam",
        tmp_path / "home" / ".steampath",
        tmp_path / "home" / ".steampid",
        tmp_path / "home" / ".config" / "steamtinkerlaunch",
        tmp_path / "home" / ".config" / "CSDSteamBuild",
    )
    return Paths(
        lock_file=tmp_path / "total_block_lock.json",
        ip_cache_file=tmp_path / "total_block_ip_cache.json",
        hosts_file=tmp_path / "hosts",
        purge_log_file=tmp_path / "total_block_purge_log.json",
        remnant_paths=remnant_paths,
    )


def write_lock(
    paths_obj: Paths, started_at: float, until: float, days: int = 1
) -> None:
    """Write a total-block lock file into the redirected location.

    Args:
        paths_obj: The redirected path set.
        started_at: Lock start timestamp.
        until: Lock expiry timestamp.
        days: Configured block length.
    """
    paths_obj.lock_file.parent.mkdir(parents=True, exist_ok=True)
    paths_obj.lock_file.write_text(
        json.dumps({"started_at": started_at, "until": until, "days": days}),
        encoding="utf-8",
    )
