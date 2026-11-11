"""``total-block-refresh``: apply the current domain list to a live total block.

The domain list (and the itch.io exception in it) is read at block start, so a
change does not reach an already-active block by itself. This command reconciles
/etc/hosts and the iptables chain to the list without ending the lock or
touching the guard-lib package-block. It is root-only, idempotent, and
fail-closed: the hosts step runs first (so the exempt names resolve again for
the firewall step) and a failure stops the run; nothing here ever adds a
domain to the block's exceptions except TOTAL_BLOCK_EXEMPT_DOMAINS.
"""

from __future__ import annotations

import os

from steam_backlog_enforcer._total_block import is_total_block_active
from steam_backlog_enforcer._total_block_hosts import refresh_total_block_hosts
from steam_backlog_enforcer._total_block_iptables import refresh_total_block_iptables
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.store_blocker import flush_dns_cache


def cmd_total_block_refresh(args: list[str]) -> int:
    """Reconcile the live total block with the current domain list.

    Args:
        args: Arguments after the command name (none are accepted).

    Returns:
        Process exit code: 0 done or nothing to do, 1 failed, 2 bad usage.
    """
    if args:
        _echo(f"Unknown argument(s): {' '.join(args)}")
        return 2
    if os.geteuid() != 0:
        _echo("total-block-refresh requires root (it edits /etc/hosts, iptables).")
        return 1
    if not is_total_block_active():
        _echo("No active total block; nothing to refresh.")
        return 0

    if not refresh_total_block_hosts():
        _echo("Failed to refresh /etc/hosts; block left as it was.")
        return 1
    flush_dns_cache()
    if not refresh_total_block_iptables():
        _echo("Failed to refresh iptables (hosts done); rerun is safe.")
        return 1
    _echo("Total block refreshed.")
    return 0
