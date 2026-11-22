"""Steam app ids that use anti-cheat, from AreWeAntiCheatYet's `games.json`.

Fetched on every run; the last good copy is kept so a flaky network does not
change any decision. With neither a fetch nor a copy the answer is "unknown",
and an unknown list maps nothing. Every listed game counts, whatever its
status: kuhy's library has 54 such games (CS2, Garry's Mod, TF2, ...), and VAC
runs inside Valve's client, so those stay on Valve's own setup.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

URL = (
    "https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/"
    "HEAD/games.json"
)
CACHE = Path.home() / ".cache" / "steam-game-installer" / "anticheat-games.json"


def _download() -> bytes:
    with urllib.request.urlopen(URL, timeout=20) as response:
        return response.read()


def _ids(raw: bytes | str) -> set[int]:
    """Steam ids in a games.json; ValueError/TypeError when it is not one."""
    games = json.loads(raw)
    if not isinstance(games, list):
        raise TypeError("games.json is not a list")
    ids: set[int] = set()
    for game in games:
        stores = game.get("storeIds") if isinstance(game, dict) else None
        steam = stores.get("steam") if isinstance(stores, dict) else None
        if isinstance(steam, str) and steam.isdigit():
            ids.add(int(steam))
    return ids


def steam_ids(cache: Path = CACHE) -> set[int] | None:
    """Anti-cheat Steam app ids, or None when no list can be had."""
    try:
        raw = _download()
        ids = _ids(raw)
    except (OSError, ValueError, TypeError):
        try:
            return _ids(cache.read_bytes())
        except (OSError, ValueError, TypeError):
            return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f"{cache.name}.tmp{os.getpid()}")
    tmp.write_bytes(raw)
    os.replace(tmp, cache)
    return ids
