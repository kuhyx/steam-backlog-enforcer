"""Steam Web API surface: data models and the HTTP client.

The implementation lives in :mod:`_steam_models` (dataclasses) and
:mod:`_steam_api_client` (HTTP); this module re-exports both so the 47
call sites that import from ``steam_api`` keep working. Split to keep every
file under the 250-line cap.
"""

from __future__ import annotations

from steam_backlog_enforcer._steam_api_client import SteamAPIClient, SteamAPIError
from steam_backlog_enforcer._steam_models import AchievementInfo, GameInfo

__all__ = [
    "AchievementInfo",
    "GameInfo",
    "SteamAPIClient",
    "SteamAPIError",
]
