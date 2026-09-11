"""Resolve a game name to a Steam AppID.

Two endpoints, tried in order, because the obvious one does not work here:

1. `steamcommunity.com/actions/SearchApps/<term>` -- an undocumented but stable
   community-side search. Verified working from this machine; "BeamNG" returns
   exactly `284160 BeamNG.drive`.
2. `store.steampowered.com/api/storesearch/` -- the storefront API. It
   TLS-rejects scripted clients from at least some networks (confirmed: even
   its bare homepage fails the handshake for plain curl/urllib here, while
   every other Steam domain works -- storefront-specific bot detection, not an
   outage). Kept as a fallback, never relied on.

`ISteamApps/GetAppList` is deliberately not used: it now answers
`404 Method 'GetAppList' not found in interface 'ISteamApps'`.

Either way this is best-effort. search() can fail, and callers fall back to
asking for a numeric AppID rather than treating a search failure as fatal.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

COMMUNITY_SEARCH_URL = "https://steamcommunity.com/actions/SearchApps/{term}"
STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/?term={term}&cc=us"

# urllib's default identifies itself as Python-urllib, which Steam's edge
# sometimes refuses outright. A plain browser UA gets a normal response.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) steam-game-installer"

DEFAULT_TIMEOUT = 15.0

# DNS here fails transiently often enough to lose roughly one lookup in three.
# A search that dies on a blip sends the user off to find an AppID by hand for
# no reason, so retry briefly before giving up on a backend.
ATTEMPTS = 3
RETRY_DELAY = 1.0


@dataclass
class SearchResult:
    appid: int
    name: str


class ResolveError(Exception):
    pass


class SearchUnavailable(Exception):
    """Neither search endpoint could be reached (network/TLS block, not a code bug)."""


def _fetch_json(url: str, timeout: float, *, attempts: int = ATTEMPTS) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception = RuntimeError("no attempts made")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                # Looked up on the module, not bound as a default, so tests can
                # replace it without waiting out the real delay.
                time.sleep(RETRY_DELAY)
    raise last


def _search_community(term: str, timeout: float) -> list[SearchResult]:
    """Community endpoint. Returns a bare JSON list; appids arrive as strings."""
    payload = _fetch_json(COMMUNITY_SEARCH_URL.format(term=term), timeout)
    if not isinstance(payload, list):
        raise TypeError(f"unexpected community search payload: {type(payload)}")
    return [
        SearchResult(appid=int(item["appid"]), name=item["name"])
        for item in payload
        if str(item.get("appid", "")).isdigit()
    ]


def _search_store(term: str, timeout: float) -> list[SearchResult]:
    """Storefront endpoint. Returns {"items": [{"id": int, "name": str}, ...]}."""
    payload = _fetch_json(STORE_SEARCH_URL.format(term=term), timeout)
    if not isinstance(payload, dict):
        raise TypeError(f"unexpected store search payload: {type(payload)}")
    return [
        SearchResult(appid=int(item["id"]), name=item["name"])
        for item in payload.get("items", [])
    ]


def search(name: str, *, timeout: float = DEFAULT_TIMEOUT) -> list[SearchResult]:
    """Candidate matches for `name`, newest-working backend first. No auth needed."""
    term = urllib.parse.quote(name)
    failures: list[str] = []
    for label, backend in (
        ("steamcommunity", _search_community),
        ("store.steampowered", _search_store),
    ):
        try:
            return backend(term, timeout)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            failures.append(f"{label}: {exc}")
    raise SearchUnavailable("; ".join(failures))


def exact_match(results: list[SearchResult], name: str) -> SearchResult | None:
    """The one result whose title is exactly `name`, case-insensitively.

    Steam's own ranking puts "Portal 2" above "Portal", so preferring an exact
    title is the difference between typing a full name and getting the sequel.
    Ambiguous only in theory: if two apps share a title we refuse to guess.
    """
    wanted = name.strip().casefold()
    hits = [result for result in results if result.name.strip().casefold() == wanted]
    return hits[0] if len(hits) == 1 else None


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
