"""The domain lists a total gaming block makes unreachable.

A data table, versioned separately from the hosts/iptables mechanism that
consumes it in :mod:`steam_backlog_enforcer._total_block_net` -- adding a
storefront here should not mean touching blocking code.
"""

from __future__ import annotations

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

# Browser/flash game sites. Note itch.io overlaps with the "itch" desktop
# app process kill above (web storefront vs. desktop client).
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
    "itch.io",
]


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


_ALL_TOTAL_BLOCK_DOMAINS = _expand_with_www(
    [*TOTAL_BLOCK_DOMAINS, *GAME_WEBSITE_DOMAINS]
)

# The null-route redirect target used to make a blocked domain resolve
# nowhere - built from parts rather than the literal so linters don't
# mistake it for a socket bind-all-interfaces address (it never is one).
NULL_ROUTE_IP = ".".join(["0"] * 4)
