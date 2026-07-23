"""Resolve a game name to a Steam AppID via the public store-search endpoint.

store.steampowered.com is known to TLS-reject scripted clients from at least
some networks (confirmed: even its bare homepage fails the TLS handshake for
plain curl/urllib here, while every other Steam domain works fine -- looks
like storefront-specific bot detection, not a general outage). Treat this as
best-effort: search() can fail, and callers should fall back to asking for a
numeric AppID directly rather than treating a search failure as fatal.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://store.steampowered.com/api/storesearch/?term={term}&cc=us"


@dataclass
class SearchResult:
    appid: int
    name: str


class ResolveError(Exception):
    pass


class SearchUnavailable(Exception):
    """The store search endpoint couldn't be reached (network/TLS block, not a code bug)."""


def search(name: str) -> list[SearchResult]:
    """Query Steam's store search API for candidate matches. No auth needed."""
    url = SEARCH_URL.format(term=urllib.parse.quote(name))
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SearchUnavailable(str(exc)) from exc
    items = payload.get("items", [])
    return [SearchResult(appid=item["id"], name=item["name"]) for item in items]


def prompt_confirm(results: list[SearchResult]) -> SearchResult:
    """Show numbered candidates and require an explicit choice. Never guesses."""
    if not results:
        raise ResolveError("No matches found on Steam.")
    print("Matches found:")
    for i, result in enumerate(results, start=1):
        print(f"  {i}. {result.name} (appid {result.appid})")
    while True:
        choice = input(f"Which one? [1-{len(results)}, or 0 to cancel]: ").strip()
        if choice == "0":
            raise ResolveError("Cancelled by user.")
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            return results[int(choice) - 1]
        print("Invalid choice, try again.")
