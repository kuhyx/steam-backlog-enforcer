"""Cached lookup of the Steam account's full owned-app list.

Split out of :mod:`steam_backlog_enforcer._enforce_loop` to keep both files
under the 250-line cap. The enforce loop runs every 3s but the owned-games
list changes rarely, so it is cached on disk with a TTL rather than re-fetched
from the Steam Web API each pass.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from steam_backlog_enforcer.config import (
    CONFIG_DIR,
    Config,
    _atomic_write,
    load_snapshot,
)
from steam_backlog_enforcer.steam_api import SteamAPIClient

logger = logging.getLogger(__name__)

_OWNED_IDS_CACHE_FILE = CONFIG_DIR / "owned_app_ids_cache.json"
_OWNED_IDS_CACHE_TTL_SECONDS = 3600


def _load_owned_app_ids_cache(steam_id: str) -> list[int] | None:
    """Return fresh cached owned app IDs for this steam_id, if available."""
    if not steam_id or not _OWNED_IDS_CACHE_FILE.exists():
        return None

    try:
        data: dict[str, Any] = json.loads(
            _OWNED_IDS_CACHE_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return None

    cached_steam_id = str(data.get("steam_id", ""))
    if cached_steam_id != steam_id:
        return None

    fetched_at = float(data.get("fetched_at", 0.0) or 0.0)
    age = time.time() - fetched_at
    if age > _OWNED_IDS_CACHE_TTL_SECONDS:
        return None

    raw_ids = data.get("app_ids", [])
    if not isinstance(raw_ids, list):
        return None

    return [int(app_id) for app_id in raw_ids]


def _save_owned_app_ids_cache(steam_id: str, app_ids: list[int]) -> None:
    """Persist owned app IDs cache for this steam_id."""
    payload = {
        "steam_id": steam_id,
        "fetched_at": time.time(),
        "app_ids": app_ids,
    }
    _atomic_write(_OWNED_IDS_CACHE_FILE, json.dumps(payload, indent=2) + "\n")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def get_all_owned_app_ids(config: Config) -> list[int]:
    """Get all owned game app IDs from Steam API plus snapshot fallback.

    Snapshot data contains only games with achievements, so API data is the
    primary source for library hiding. Snapshot IDs are merged in to keep
    behavior resilient when the API result is partial.
    """
    snapshot = load_snapshot() or []
    snapshot_ids = [int(d["app_id"]) for d in snapshot if "app_id" in d]
    cached_ids = _load_owned_app_ids_cache(config.steam_id)

    if cached_ids is not None:
        merged_ids: list[int] = []
        seen: set[int] = set()
        for app_id in [*cached_ids, *snapshot_ids]:
            if app_id in seen:
                continue
            seen.add(app_id)
            merged_ids.append(app_id)
        logger.info("Using cached Steam owned IDs (%d entries).", len(cached_ids))
        return merged_ids

    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        api_ids = [int(g["appid"]) for g in owned if "appid" in g]
        _save_owned_app_ids_cache(config.steam_id, api_ids)

        merged_ids: list[int] = []
        seen: set[int] = set()
        for app_id in [*api_ids, *snapshot_ids]:
            if app_id in seen:
                continue
            seen.add(app_id)
            merged_ids.append(app_id)
    except (OSError, RuntimeError, ValueError):
        if snapshot_ids:
            return snapshot_ids
        logger.warning("Could not fetch owned game list for hiding.")
        return []
    else:
        return merged_ids


# ──────────────────────────────────────────────────────────────
# Enforce mode (daemon loop)
# ──────────────────────────────────────────────────────────────

# How often the enforce loop runs (seconds).
