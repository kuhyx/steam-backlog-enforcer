"""Which /etc/hosts lines block the Steam store, in both address families.

The hosts installer writes every blocked domain twice: ``0.0.0.0 <domain>``
and ``:: <domain>``. Steam and browsers prefer IPv6, so a block counts while
either line is live: commenting out only the ``0.0.0.0`` line left the store
blocked while the unblock reported success.

A line counts only when its address field is exactly a sinkhole and one of
its hostnames exactly equals a store domain, so ``steamkarta.pl``,
``::1 localhost`` or a prose comment naming a domain are never touched.
"""

from __future__ import annotations

from typing import Final

from steam_backlog_enforcer._store_tools import HOSTS_REDIRECT_IP
from steam_backlog_enforcer.config import BLOCKED_DOMAINS

# The sinkhole addresses (not a bind: these are hosts-file targets).
SINKHOLES: Final = frozenset({HOSTS_REDIRECT_IP, "::"})
# An address and at least one hostname.
_MIN_FIELDS: Final = 2


def _store_hosts(entry: str) -> list[str] | None:
    """Fields of a live hosts *entry* that sinkholes a store domain, else None."""
    fields = entry.split("#", 1)[0].split()
    if len(fields) < _MIN_FIELDS or fields[0] not in SINKHOLES:
        return None
    if any(host in BLOCKED_DOMAINS for host in fields[1:]):
        return fields
    return None


def is_live_store_line(line: str) -> bool:
    """Whether *line* is an uncommented sinkhole entry for a store domain."""
    return _store_hosts(line) is not None


def _commented_entry(line: str) -> str | None:
    """The entry behind a commented-out store line, else None."""
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    entry = stripped.lstrip("#").strip()
    return entry if is_live_store_line(entry) else None


def comment_out_store_line(line: str) -> str | None:
    """*line* commented out if it is a live store line, else None."""
    if not is_live_store_line(line):
        return None
    return f"# {line}" if line.endswith("\n") else f"# {line}\n"


def uncomment_store_line(line: str) -> str | None:
    """*line* made live again if it is a commented-out store line, else None."""
    entry = _commented_entry(line)
    if entry is None:
        return None
    return f"{entry}\n"


def _candidates(content: str) -> list[str]:
    """Lines naming a store domain at all: a cheap prefilter for a 8 MB file."""
    return [
        line.strip()
        for line in content.splitlines()
        if any(domain in line for domain in BLOCKED_DOMAINS)
    ]


def live_store_lines(content: str) -> list[str]:
    """Every live store block line in *content* (stripped)."""
    return [line for line in _candidates(content) if is_live_store_line(line)]


def store_lines(content: str) -> list[str]:
    """Every store block line, live or commented out (for failure reports)."""
    return [
        line
        for line in _candidates(content)
        if is_live_store_line(line) or _commented_entry(line) is not None
    ]


def hosts_fully_blocks_store(content: str) -> bool:
    """Whether every store domain has a live line for both sinkholes."""
    pairs: set[tuple[str, str]] = set()
    for line in live_store_lines(content):
        fields = line.split("#", 1)[0].split()
        pairs.update((fields[0], host) for host in fields[1:])
    return all((ip, d) in pairs for d in BLOCKED_DOMAINS for ip in SINKHOLES)
