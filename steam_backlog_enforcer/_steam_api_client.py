"""HTTP client for the Steam Web API.

Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import requests

from steam_backlog_enforcer._steam_models import (
    MAX_WORKERS,
    STEAM_API_BASE,
    AchievementInfo,
    GameInfo,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class SteamAPIError(Exception):
    """Raised when the Steam API returns an error."""


class SteamAPIClient:
    """Client for interacting with the Steam Web API."""

    def __init__(self, api_key: str, steam_id: str) -> None:
        """Initialize the Steam API client.

        Args:
            api_key: Steam Web API key.
            steam_id: Steam64 ID of the user.
        """
        self.api_key = api_key
        self.steam_id = steam_id
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_maxsize=MAX_WORKERS,
            pool_connections=MAX_WORKERS,
        )
        self.session.mount("https://", adapter)
        self.session.headers["Accept"] = "application/json"
        self._rate_lock = threading.Lock()
        self._request_times: list[float] = []
        self._max_rps = 18

    def _rate_limit(self) -> None:
        """Enforce rate limit across threads."""
        while True:
            with self._rate_lock:
                now = time.time()
                self._request_times = [t for t in self._request_times if now - t < 1.0]
                if len(self._request_times) < self._max_rps:
                    self._request_times.append(now)
                    return
            time.sleep(0.06)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Rate-limited GET request."""
        self._rate_limit()
        if params is None:
            params = {}
        params["key"] = self.api_key
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
        except requests.RequestException as e:
            msg = f"Steam API request failed: {e}"
            raise SteamAPIError(msg) from e
        else:
            return result

    def get_owned_games(self) -> list[dict[str, Any]]:
        """Fetch all games owned by the user."""
        url = f"{STEAM_API_BASE}/IPlayerService/GetOwnedGames/v1/"
        data = self._get(
            url,
            {
                "steamid": self.steam_id,
                "include_appinfo": "true",
                "include_played_free_games": "true",
                "format": "json",
            },
        )
        games: list[dict[str, Any]] = data.get("response", {}).get("games", [])
        logger.info("Found %d owned games.", len(games))
        return games

    def get_achievement_details(self, app_id: int) -> list[AchievementInfo]:
        """Fetch per-achievement detail for a game."""
        url = f"{STEAM_API_BASE}/ISteamUserStats/GetPlayerAchievements/v1/"
        try:
            data = self._get(
                url,
                {
                    "steamid": self.steam_id,
                    "appid": str(app_id),
                    "l": "english",
                    "format": "json",
                },
            )
        except SteamAPIError:
            return []

        stats = data.get("playerstats", {})
        if not stats.get("success", False):
            return []

        raw: list[dict[str, Any]] = stats.get("achievements", [])
        return [
            AchievementInfo(
                api_name=a.get("apiname", ""),
                display_name=a.get("name", a.get("apiname", "")),
                achieved=bool(a.get("achieved", 0)),
                unlock_time=a.get("unlocktime", 0),
            )
            for a in raw
        ]

    def _fetch_one_game(self, game_dict: dict[str, Any]) -> GameInfo | None:
        """Fetch achievement data for one game. Thread-safe."""
        app_id = game_dict["appid"]

        achievements = self.get_achievement_details(app_id)
        if not achievements:
            return None

        name = game_dict.get("name", f"Unknown ({app_id})")
        total = len(achievements)
        unlocked = sum(1 for a in achievements if a.achieved)

        return GameInfo(
            app_id=app_id,
            name=name,
            total_achievements=total,
            unlocked_achievements=unlocked,
            playtime_minutes=game_dict.get("playtime_forever", 0),
            achievements=achievements,
        )

    def build_game_list(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GameInfo]:
        """Build full game list with achievement data (parallel)."""
        owned = self.get_owned_games()
        games: list[GameInfo] = []
        done_count = 0
        total = len(owned)
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(self._fetch_one_game, g): g for g in owned}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    SteamAPIError,
                    requests.RequestException,
                ):
                    result = None
                with lock:
                    done_count += 1
                    if progress_callback:
                        progress_callback(done_count, total)
                if result is not None:
                    games.append(result)

        games.sort(key=lambda g: g.name.lower())
        return games

    def refresh_single_game(
        self, app_id: int, name: str, playtime: int = 0
    ) -> GameInfo | None:
        """Re-fetch achievement data for one game."""
        achievements = self.get_achievement_details(app_id)
        if not achievements:
            return None
        total = len(achievements)
        unlocked = sum(1 for a in achievements if a.achieved)
        return GameInfo(
            app_id=app_id,
            name=name,
            total_achievements=total,
            unlocked_achievements=unlocked,
            playtime_minutes=playtime,
            achievements=achievements,
        )
