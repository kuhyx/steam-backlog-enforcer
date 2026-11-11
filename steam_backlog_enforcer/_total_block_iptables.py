"""iptables egress blocking for the total gaming block.

The belt to the hosts file's braces: /etc/hosts only stops name resolution,
so an app with a hard-coded IP (or its own resolver) would still connect.
This chain drops the traffic itself, which is why the resolved IPs are
cached -- once the hosts block is applied, the domains no longer resolve to
their real addresses and could not be re-derived.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import socket
import subprocess

from steam_backlog_enforcer._store_tools import (
    IPTABLES,
    SUDO,
    add_drop_rule,
    create_fresh_chain,
    delete_drop_rule,
    drop_chain,
    ensure_chain_in_output,
)
from steam_backlog_enforcer._total_block_domains import (
    _ALL_TOTAL_BLOCK_DOMAINS,
    NULL_ROUTE_IP,
    TOTAL_BLOCK_EXEMPT_DOMAINS,
)
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

logger = logging.getLogger(__name__)

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


def _chain_ips() -> set[str] | None:
    """IPs the chain currently drops, or None when the chain does not exist."""
    listing = subprocess.run(
        [SUDO, IPTABLES, "-S", IPTABLES_CHAIN],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if listing.returncode != 0:
        return None

    current_ips: set[str] = set()
    for line in listing.stdout.splitlines():
        parts = line.split()
        if "-d" in parts:
            idx = parts.index("-d")
            if idx + 1 < len(parts):
                current_ips.add(parts[idx + 1].split("/")[0])
    return current_ips


def _resolve_exempt_ips() -> set[str]:
    """Real public IPs of the exempt domains (null-routed answers do not count)."""
    ips: set[str] = set()
    for domain in TOTAL_BLOCK_EXEMPT_DOMAINS:
        with contextlib.suppress(OSError):
            for _, _, _, _, addr in socket.getaddrinfo(domain, 443, socket.AF_INET):
                ips.add(str(addr[0]))
    return {ip for ip in ips if ipaddress.ip_address(ip).is_global}


def _iptables_chain_intact(expected_ips: set[str]) -> bool:
    """Cheap check for whether the chain and its OUTPUT hook are intact.

    One `-S` + one `-C` call (two forks), versus the ~30 forks a full
    rebuild costs - this is what keeps :func:`_apply_total_block_iptables`
    from re-resolving DNS and re-forking a subprocess per IP on every
    3-second enforce tick.
    """
    current_ips = _chain_ips()
    if current_ips is None or not expected_ips.issubset(current_ips):
        return False

    hook = subprocess.run(
        [SUDO, IPTABLES, "-C", "OUTPUT", "-j", IPTABLES_CHAIN],
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
        create_fresh_chain(IPTABLES_CHAIN)

        for domain in _ALL_TOTAL_BLOCK_DOMAINS:
            with contextlib.suppress(socket.gaierror):
                for _, _, _, _, addr in socket.getaddrinfo(domain, 443, socket.AF_INET):
                    resolved_ips.add(str(addr[0]))

        # The itch exception wins over a shared IP (TOTAL_BLOCK_EXEMPT_DOMAINS).
        blocked_ips = (cached | resolved_ips) - {NULL_ROUTE_IP} - _resolve_exempt_ips()
        _save_cached_ips(blocked_ips)

        for ip in blocked_ips:
            add_drop_rule(IPTABLES_CHAIN, ip)

        ensure_chain_in_output(IPTABLES_CHAIN)
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to apply total-block iptables rules")
        return False
    logger.info("Total block: %d domain IP(s) blocked via iptables.", len(blocked_ips))
    return True


def refresh_total_block_iptables() -> bool:
    """Release the exempt domains' IPs from a live chain, never opening a gap.

    Rules are deleted one by one (no flush), so every other IP stays dropped
    throughout. The cache is saved first: a half-done run then still looks
    intact to the 3 s tick (cache is a subset of the chain) and the next run
    finishes the deletes. Fails closed: when the exempt names resolve to no
    public IP (hosts still null-route them, or DNS is down) nothing changes.
    A missing chain is rebuilt by :func:`apply_total_block_iptables`.
    """
    exempt = _resolve_exempt_ips()
    if not exempt:
        logger.error("Exempt domains resolve to no public IP; iptables unchanged")
        return False
    try:
        in_chain = _chain_ips()
        cached = _load_cached_ips()
        if in_chain is None:
            _save_cached_ips(cached - exempt)
            return apply_total_block_iptables()
        if not (cached | in_chain) & exempt:
            return True
        _save_cached_ips(cached - exempt)
        failed = [
            ip for ip in in_chain & exempt if not delete_drop_rule(IPTABLES_CHAIN, ip)
        ]
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to refresh total-block iptables rules")
        return False
    if failed:
        logger.error("Could not delete iptables rule(s) for %s", sorted(failed))
        return False
    logger.info("Total block: released %d exempt IP(s).", len(exempt))
    return True


def total_block_chain_exists() -> bool:
    """Whether the total-block chain is present (a single iptables call)."""
    return _chain_ips() is not None


def release_total_block_iptables() -> bool:
    """Take the chain and its OUTPUT hook down but keep the IP cache.

    How a research window opens the firewall. Unlike
    :func:`remove_total_block_iptables` the cache stays, so when the window
    ends :func:`apply_total_block_iptables` rebuilds the chain with every IP it
    dropped before, not only the ones DNS happens to answer that day.

    Returns:
        True once the chain is verifiably gone; False when it is still there or
        iptables cannot be run.
    """
    try:
        drop_chain(IPTABLES_CHAIN)
        return not total_block_chain_exists()
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to release total-block iptables rules")
        return False


def remove_total_block_iptables() -> bool:
    """Remove the total-block iptables chain and its OUTPUT hook."""
    try:
        drop_chain(IPTABLES_CHAIN)
    except OSError, subprocess.SubprocessError:
        logger.exception("Failed to remove total-block iptables rules")
        return False
    _IPTABLES_IP_CACHE_FILE.unlink(missing_ok=True)
    return True
