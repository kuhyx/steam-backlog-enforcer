"""Owned games known to have no achievements, so a library scan can skip them.

A scan is bound by the Steam request rate (``SteamAPIClient._max_rps``, one
request per owned game), and about a quarter of a typical library has no
achievements at all. A game is skipped only while all three hold:

- Steam does not flag it ``has_community_visible_stats``;
- it is not in the last snapshot (a game can have achievements without the
  flag, so the flag alone is not trusted);
- a scan less than :data:`RECHECK_AFTER_SECONDS` ago found no achievements.

So a game that later gains achievements without gaining the flag is still
picked up, at the latest that long after.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer import config
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer.config import _atomic_write

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

RECHECK_AFTER_SECONDS: Final = 30 * 86_400
_FILE_NAME: Final = "no_achievements_cache.json"
_NO_STATS_STATUS: Final = 400


def _cache_file() -> Path:
    """Resolved per call, so a redirected ``CONFIG_DIR`` is honoured."""
    return config.CONFIG_DIR / _FILE_NAME


def _load_checked(steam_id: str) -> dict[int, float]:
    """Map app id -> when a scan last found it without achievements.

    Returns:
        An empty map when the file is missing, corrupt or for another account.
    """
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    if not isinstance(data, dict) or data.get("steam_id") != steam_id:
        return {}
    checked: dict[int, float] = {}
    for key, when in dict(data.get("checked", {})).items():
        try:
            checked[int(key)] = float(when)
        except TypeError, ValueError:
            continue
    return checked


def is_no_stats_answer(exc: Exception) -> bool:
    """Whether a failed achievements request was Steam saying "no stats".

    ``GetPlayerAchievements`` answers a game without stats with HTTP 400 and
    ``{"playerstats": {"error": "Requested app has no stats", "success":
    false}}``. That is a real answer; any other failure (timeout, 5xx, 429)
    says nothing about the game.
    """
    response = getattr(exc.__cause__, "response", None)
    if response is None or response.status_code != _NO_STATS_STATUS:
        return False
    try:
        stats = response.json().get("playerstats", {})
    except ValueError, AttributeError:
        return False
    return isinstance(stats, dict) and stats.get("success") is False


def _may_have_achievements(game: dict[str, Any]) -> bool:
    """Whether Steam's owned-games entry says the game has stats."""
    return bool(game.get("has_community_visible_stats"))


def skippable_app_ids(
    steam_id: str, owned: list[dict[str, Any]], now: float
) -> set[int]:
    """Return the owned games a scan may skip right now (see module doc).

    Args:
        steam_id: The account the cache must belong to.
        owned: ``GetOwnedGames`` entries.
        now: Current epoch seconds.
    """
    checked = _load_checked(steam_id)
    if not checked:
        return set()
    in_snapshot = {entry.get("app_id") for entry in load_snapshot() or []}
    return {
        game["appid"]
        for game in owned
        if not _may_have_achievements(game)
        and game["appid"] not in in_snapshot
        and now - checked.get(game["appid"], float("-inf")) < RECHECK_AFTER_SECONDS
    }


def record_scan(
    steam_id: str,
    fetched: list[dict[str, Any]],
    with_achievements: set[int],
    now: float,
) -> None:
    """Remember which fetched games came back without achievements.

    Never raises: losing the cache only costs the next scan its shortcut.

    Args:
        steam_id: The account the cache belongs to.
        fetched: The owned-games entries this scan asked Steam about.
        with_achievements: App ids that came back with achievements.
        now: Current epoch seconds.
    """
    checked = _load_checked(steam_id)
    for game in fetched:
        app_id = game["appid"]
        if app_id in with_achievements or _may_have_achievements(game):
            checked.pop(app_id, None)
        else:
            checked[app_id] = now
    payload = {
        "steam_id": steam_id,
        "checked": {str(app_id): when for app_id, when in sorted(checked.items())},
    }
    try:
        _atomic_write(_cache_file(), json.dumps(payload, indent=2) + "\n")
    except OSError:
        logger.warning("Could not save %s", _cache_file(), exc_info=True)
