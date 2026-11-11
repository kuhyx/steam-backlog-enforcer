"""Making the network and the Steam package match an open research window.

Every pass of an open window calls :func:`reconcile_open_window`, which is
idempotent and cheap once converged (one /etc/hosts read, one ``iptables -S``,
one ``pacman -Qi``). The daemon is the only actor: the command just records the
window, so a daemon that still runs the old code, or a restart half way, cannot
leave two writers fighting over hosts, the firewall and pacman.

The opening is deliberately narrower than "the block is off":

* /etc/hosts keeps the browser-game sites null-routed; only Steam names open
  (:data:`steam_backlog_enforcer._total_block_domains.RESEARCH_BLOCKED_DOMAINS`);
* the normal Steam-store block (hosts lines + its iptables chain) is lifted for
  checkout, and re-lifted whenever the hourly hosts reinstall puts it back;
* the total-block iptables chain is taken down, its IP cache kept for expiry;
* Steam is reinstalled if the block removed it, with only the guard-lib
  package-block pacman hook masked for that one transaction. The hook file, the
  lock file and the lock's end date are never touched.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._pacman import install_package
from steam_backlog_enforcer._total_block import _PACKAGE_BLOCK_NAME
from steam_backlog_enforcer._total_block_hosts import refresh_total_block_hosts
from steam_backlog_enforcer._total_block_iptables import (
    release_total_block_iptables,
    total_block_chain_exists,
)
from steam_backlog_enforcer._total_block_purge import STEAM_PACKAGE, is_steam_installed
from steam_backlog_enforcer.store_blocker import (
    flush_dns_cache,
    hosts_blocks_store,
    unblock_store,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._research_window import ResearchRecord

logger = logging.getLogger(__name__)

DB_LOCK_FILE: Final = Path("/var/lib/pacman/db.lck")
RETRY_AFTER_SECONDS: Final = 60.0

# Next monotonic time each retried action ("steam", "store") may run again.
RETRY: Final[dict[str, float]] = {}
# Windows (by opened_at) whose one-time release this daemon process has done.
RELEASED: Final[set[float]] = set()


def monotonic() -> float:
    """Monotonic seconds (a seam for tests)."""
    return time.monotonic()


def attempt_due(key: str) -> bool:
    """Whether the action *key* may run now (it is not in its backoff)."""
    return monotonic() >= RETRY.get(key, 0.0)


def note_failure(key: str) -> None:
    """Hold the action *key* back for :data:`RETRY_AFTER_SECONDS`."""
    RETRY[key] = monotonic() + RETRY_AFTER_SECONDS


def block_hook_name() -> str:
    """File name of guard-lib's pacman hook for the steam package-block."""
    return f"guard-lib-block-{_PACKAGE_BLOCK_NAME}.hook"


def ensure_steam_installed() -> bool:
    """Reinstall Steam if the total block removed it.

    Returns:
        True when the package is installed afterwards. A running pacman
        transaction is not raced and a failure backs off, so a broken mirror
        cannot turn the 3 s tick into an install loop.
    """
    if is_steam_installed():
        return True
    if DB_LOCK_FILE.exists() or not attempt_due("steam"):
        return False
    if install_package(STEAM_PACKAGE, masked_hooks=(block_hook_name(),)):
        logger.info("Research window: Steam reinstalled")
        return True
    note_failure("steam")
    return False


def reconcile_open_window(record: ResearchRecord) -> None:
    """One idempotent pass making the machine match the open window *record*."""
    first = record.opened_at not in RELEASED
    hosts_ok = refresh_total_block_hosts(steam_open=True)
    if first:
        flush_dns_cache()
    store_ok = True
    if first or hosts_blocks_store():
        store_ok = unblock_store()
    if total_block_chain_exists():
        release_total_block_iptables()
    if first and hosts_ok and store_ok:
        RELEASED.add(record.opened_at)
    ensure_steam_installed()
