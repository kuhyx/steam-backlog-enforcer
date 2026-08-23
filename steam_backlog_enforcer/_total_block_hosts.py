"""/etc/hosts null-routing for the total gaming block.

Deliberately distinct from :mod:`store_blocker`'s own BLOCKED_DOMAINS /
STEAM_ENFORCER hosts section, so ending a total block never disturbs the
user's normal ``config.block_store`` entries. The iptables half of the same
block lives in :mod:`steam_backlog_enforcer._total_block_iptables`.
"""

from __future__ import annotations

import logging
import subprocess

from steam_backlog_enforcer._total_block_domains import (
    _ALL_TOTAL_BLOCK_DOMAINS,
    NULL_ROUTE_IP,
)
from steam_backlog_enforcer.config import HOSTS_FILE
from steam_backlog_enforcer.store_blocker import (
    _disable_hosts_protection,
    _enable_hosts_protection,
    _sudo_write_hosts,
)

logger = logging.getLogger(__name__)

_HOSTS_BLOCK_BEGIN = "# BEGIN steam-backlog-enforcer total-block\n"
_HOSTS_BLOCK_END = "# END steam-backlog-enforcer total-block\n"


def apply_total_block_hosts() -> bool:
    """Append the total-block domain block to /etc/hosts, if not present."""
    try:
        content = HOSTS_FILE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read /etc/hosts")
        return False

    if _HOSTS_BLOCK_BEGIN in content:
        return True

    block_lines = [_HOSTS_BLOCK_BEGIN]
    block_lines += [
        f"{NULL_ROUTE_IP} {domain}\n" for domain in _ALL_TOTAL_BLOCK_DOMAINS
    ]
    block_lines.append(_HOSTS_BLOCK_END)

    new_content = content if content.endswith("\n") else content + "\n"
    new_content += "".join(block_lines)

    try:
        _disable_hosts_protection()
        _sudo_write_hosts(new_content)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to write total-block hosts entries")
        return False
    finally:
        _enable_hosts_protection()
    return True


def remove_total_block_hosts() -> bool:
    """Remove the total-block domain block from /etc/hosts, if present."""
    try:
        content = HOSTS_FILE.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read /etc/hosts")
        return False

    if _HOSTS_BLOCK_BEGIN not in content:
        return True

    start = content.index(_HOSTS_BLOCK_BEGIN)
    end_marker_at = content.index(_HOSTS_BLOCK_END, start)
    end = end_marker_at + len(_HOSTS_BLOCK_END)
    new_content = content[:start] + content[end:]

    try:
        _disable_hosts_protection()
        _sudo_write_hosts(new_content)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Failed to remove total-block hosts entries")
        return False
    finally:
        _enable_hosts_protection()
    return True
