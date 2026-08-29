"""iptables egress blocking for the total gaming block.

The belt to the hosts file's braces: /etc/hosts only stops name resolution,
so an app with a hard-coded IP (or its own resolver) would still connect.
This chain drops the traffic itself, which is why the resolved IPs are
cached -- once the hosts block is applied, the domains no longer resolve to
their real addresses and could not be re-derived.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import socket
import subprocess

from steam_backlog_enforcer._total_block_domains import (
    _ALL_TOTAL_BLOCK_DOMAINS,
    NULL_ROUTE_IP,
)
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

logger = logging.getLogger(__name__)

_IPTABLES = shutil.which("iptables") or "/usr/sbin/iptables"
_SUDO = shutil.which("sudo") or "/usr/bin/sudo"

IPTABLES_CHAIN = "STEAM_TOTAL_BLOCK"

_IPTABLES_IP_CACHE_FILE = CONFIG_DIR / "total_block_ip_cache.json"


def _load_cached_ips() -> set[str]:
    """Return the accumulated set of previously-resolved total-block IPs."""
    if not _IPTABLES_IP_CACHE_FILE.exists():
        return set()
    try:
        data = json.loads(_IPTABLES_IP_CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError, ValueError:
        return set()
    if not isinstance(data, list):
        return set()
    return {str(ip) for ip in data}


def _save_cached_ips(ips: set[str]) -> None:
    """Persist the accumulated total-block IP set to disk."""
    _atomic_write(_IPTABLES_IP_CACHE_FILE, json.dumps(sorted(ips)) + "\n")


def _iptables_chain_intact(expected_ips: set[str]) -> bool:
    """Cheap check for whether the chain and its OUTPUT hook are intact.

    One `-S` + one `-C` call (two forks), versus the ~30 forks a full
    rebuild costs - this is what keeps :func:`_apply_total_block_iptables`
    from re-resolving DNS and re-forking a subprocess per IP on every
    3-second enforce tick.
    """
    listing = subprocess.run(
        [_SUDO, _IPTABLES, "-S", IPTABLES_CHAIN],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if listing.returncode != 0:
        return False

    current_ips: set[str] = set()
    for line in listing.stdout.splitlines():
        parts = line.split()
        if "-d" in parts:
            idx = parts.index("-d")
            if idx + 1 < len(parts):
                current_ips.add(parts[idx + 1].split("/")[0])

    if not expected_ips.issubset(current_ips):
        return False

    hook = subprocess.run(
        [_SUDO, _IPTABLES, "-C", "OUTPUT", "-j", IPTABLES_CHAIN],
        capture_output=True,
        timeout=5,
        check=False,
    )
    return hook.returncode == 0


def apply_total_block_iptables() -> bool:
    """Ensure the total-block iptables chain blocks the known domain IPs.

    Resolves domains and (re)builds the chain only when a cheap check
    (:func:`_iptables_chain_intact`) shows it's actually needed - an
    already-intact chain returns immediately. This matters for two
    reasons: re-resolving via DNS every enforce tick (every 3s) would
    otherwise fork ~30 subprocesses/tick indefinitely for a multi-day
    block, and once /etc/hosts's entries take effect, these same domains
    resolve to 0.0.0.0 locally, which would collapse a from-scratch
    rebuild to that one trivial address and silently drop the real
    upstream IPs blocked on the first, pre-hosts-block resolution -
    resolving only when actually needed keeps the accumulated IP cache
    from growing unboundedly too.

    Callers MUST call this before :func:`_apply_total_block_hosts` the
    first time (see :func:`start_total_block`): once the hosts entries
    are in place, DNS resolution for every blocked domain returns 0.0.0.0
    right here on this machine, and no real upstream IP is ever learned.
    """
    cached = _load_cached_ips()
    if cached and _iptables_chain_intact(cached):
        return True

    resolved_ips: set[str] = set()
    try:
        subprocess.run(
            [_SUDO, _IPTABLES, "-N", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-F", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=True,
        )

        for domain in _ALL_TOTAL_BLOCK_DOMAINS:
            with contextlib.suppress(socket.gaierror):
                for _, _, _, _, addr in socket.getaddrinfo(domain, 443, socket.AF_INET):
                    resolved_ips.add(str(addr[0]))

        blocked_ips = (cached | resolved_ips) - {NULL_ROUTE_IP}
        _save_cached_ips(blocked_ips)

        for ip in blocked_ips:
            subprocess.run(
                [_SUDO, _IPTABLES, "-A", IPTABLES_CHAIN, "-d", ip, "-j", "DROP"],
                capture_output=True,
                timeout=5,
                check=True,
            )

        result = subprocess.run(
            [_SUDO, _IPTABLES, "-C", "OUTPUT", "-j", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            subprocess.run(
                [_SUDO, _IPTABLES, "-I", "OUTPUT", "-j", IPTABLES_CHAIN],
                capture_output=True,
                timeout=5,
                check=True,
            )
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to apply total-block iptables rules")
        return False
    else:
        logger.info(
            "Total block: %d domain IP(s) blocked via iptables.", len(blocked_ips)
        )
        return True


def remove_total_block_iptables() -> bool:
    """Remove the total-block iptables chain and its OUTPUT hook."""
    try:
        subprocess.run(
            [_SUDO, _IPTABLES, "-D", "OUTPUT", "-j", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-F", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
        subprocess.run(
            [_SUDO, _IPTABLES, "-X", IPTABLES_CHAIN],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to remove total-block iptables rules")
        return False
    else:
        _IPTABLES_IP_CACHE_FILE.unlink(missing_ok=True)
        return True
