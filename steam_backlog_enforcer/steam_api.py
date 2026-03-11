"""Steam Web API client for fetching games and achievement data."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

STEAM_API_BASE = "https://api.steampowered.com"
MAX_WORKERS = 20


@dataclass
class AchievementInfo:
    """Single achievement state."""

    api_name: str
    display_name: str
    achieved: bool
    unlock_time: int


@dataclass
class GameInfo:
    """Info about an owned Steam game."""

    app_id: int
    name: str
    total_achievements: int
    unlocked_achievements: int
    playtime_minutes: int
    achievements: list[AchievementInfo] = field(default_factory=list)
    completionist_hours: float = -1

    @property
    def completion_pct(self) -> float:
        """Achievement completion percentage."""
        if self.total_achievements == 0:
            return 100.0
        return (self.unlocked_achievements / self.total_achievements) * 100.0

    @property
    def is_complete(self) -> bool:
        """True if all achievements are unlocked."""
        return (
            self.total_achievements > 0
            and self.unlocked_achievements >= self.total_achievements
        )

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "app_id": self.app_id,
            "name": self.name,
            "total_achievements": self.total_achievements,
            "unlocked_achievements": self.unlocked_achievements,
            "playtime_minutes": self.playtime_minutes,
            "completionist_hours": self.completionist_hours,
            "achievements": [
                {
                    "api_name": a.api_name,
                    "display_name": a.display_name,
                    "achieved": a.achieved,
                    "unlock_time": a.unlock_time,
                }
                for a in self.achievements
            ],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> GameInfo:
        """Deserialize from a cached snapshot dict."""
        achievements = [
            AchievementInfo(
                api_name=a["api_name"],
                display_name=a.get("display_name", a["api_name"]),
                achieved=a["achieved"],
                unlock_time=a.get("unlock_time", 0),
            )
            for a in data.get("achievements", [])
        ]
        return cls(
            app_id=data["app_id"],
            name=data["name"],
            total_achievements=data["total_achievements"],
            unlocked_achievements=data["unlocked_achievements"],
            playtime_minutes=data.get("playtime_minutes", 0),
            completionist_hours=data.get("completionist_hours", -1),
            achievements=achievements,
        )


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

    def _fetch_one_game(
        self, game_dict: dict[str, Any], skip: set[int]
    ) -> GameInfo | None:
        """Fetch achievement data for one game. Thread-safe."""
        app_id = game_dict["appid"]
        if app_id in skip:
            return None

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
        skip_app_ids: list[int] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GameInfo]:
        """Build full game list with achievement data (parallel)."""
        skip = set(skip_app_ids or [])
        owned = self.get_owned_games()
        games: list[GameInfo] = []
        done_count = 0
        total = len(owned)
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(self._fetch_one_game, g, skip): g for g in owned}
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
