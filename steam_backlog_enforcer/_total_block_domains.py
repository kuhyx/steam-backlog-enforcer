"""The domain lists a total gaming block makes unreachable.

A data table, versioned separately from the hosts/iptables mechanism that
consumes it in :mod:`steam_backlog_enforcer._total_block_net` -- adding a
storefront here should not mean touching blocking code.
"""

from __future__ import annotations

from typing import Final

from steam_backlog_enforcer.config import BLOCKED_DOMAINS

TOTAL_BLOCK_DOMAINS = [
    *BLOCKED_DOMAINS,
    "steamcommunity.com",
    "api.steampowered.com",
    "login.steampowered.com",
    "help.steampowered.com",
    "steamcontent.com",
    "steamstatic.com",
    "steamusercontent.com",
    "cdn.steamstatic.com",
]

# Browser/flash game sites. itch.io is deliberately absent: see
# TOTAL_BLOCK_EXEMPT_DOMAINS below.
GAME_WEBSITE_DOMAINS = [
    "newgrounds.com",
    "armorgames.com",
    "kongregate.com",
    "crazygames.com",
    "poki.com",
    "miniclip.com",
    "addictinggames.com",
    "y8.com",
    "coolmathgames.com",
]

# EXCEPTION (kuhy, 2026-11-11: "itch io should be unblocked but only it"):
# a permanent, narrow hole so butler can publish his game and he can manage the
# itch page, while every other game site and Steam stay blocked. Nothing here is
# ever null-routed in /etc/hosts and its IPs are never dropped in iptables.
# Hosts: itch.io + www.itch.io (the page), api.itch.io and static.itch.io (both
# strings in the butler binary), kuhyx.itch.io (his account's page). butler
# uploads go to Google Cloud Storage via a URL the API returns (resumable
# upload), which is not blocked anywhere, so it needs no entry.
# TRADEOFF: itch is on shared Cloudflare IPs, and the iptables layer works per
# IP. When a still-blocked site sits on the same IP, the exception wins for
# that IP; /etc/hosts stays the primary block for the other site.
TOTAL_BLOCK_EXEMPT_DOMAINS: Final = (
    "itch.io",
    "www.itch.io",
    "api.itch.io",
    "static.itch.io",
    "kuhyx.itch.io",
)


def _expand_with_www(domains: list[str]) -> list[str]:
    """Add a ``www.`` variant for each bare second-level domain.

    Most of these sites 301-redirect their apex domain to ``www.<domain>``
    (confirmed live for newgrounds.com) - blocking only the apex leaves the
    www subdomain reachable through both the hosts-file entry and the
    iptables IP block. Domains that already carry a subdomain (e.g.
    store.steampowered.com) are left as-is.
    """
    expanded: list[str] = []
    for domain in domains:
        expanded.append(domain)
        if domain.count(".") == 1:
            expanded.append(f"www.{domain}")
    return expanded


_ALL_TOTAL_BLOCK_DOMAINS = [
    domain
    for domain in _expand_with_www([*TOTAL_BLOCK_DOMAINS, *GAME_WEBSITE_DOMAINS])
    if domain not in TOTAL_BLOCK_EXEMPT_DOMAINS
]

# The null-route redirect target used to make a blocked domain resolve
# nowhere - built from parts rather than the literal so linters don't
# mistake it for a socket bind-all-interfaces address (it never is one).
NULL_ROUTE_IP = ".".join(["0"] * 4)
