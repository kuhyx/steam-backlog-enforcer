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

from steam_backlog_enforcer._achievement_skip import (
    is_no_stats_answer,
    record_scan,
    skippable_app_ids,
)
from steam_backlog_enforcer._progress import current_progress
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
        # Games Steam answered "no stats" for during the current scan.
        self._no_stats: set[int] = set()

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

    def get_achievement_details(
        self, app_id: int, *, strict: bool = False
    ) -> list[AchievementInfo]:
        """Fetch per-achievement detail for a game.

        ``strict``: only Steam's "no stats" answer is empty; failures raise.
        """
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
        except SteamAPIError as exc:
            if strict and not is_no_stats_answer(exc):
                raise
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

        achievements = self.get_achievement_details(app_id, strict=True)
        if not achievements:
            self._no_stats.add(app_id)  # set.add is atomic under the GIL
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
        """Build full game list with achievement data (parallel).

        Games recently found to have no achievements are not asked about
        again (see :mod:`._achievement_skip`).
        """
        owned = self.get_owned_games()
        now = time.time()
        skip = skippable_app_ids(self.steam_id, owned, now)
        to_fetch = [g for g in owned if g["appid"] not in skip]
        if skip:
            logger.info("Skipping %d games known to have no achievements.", len(skip))
        self._no_stats = set()
        games = self._fetch_games(to_fetch, progress_callback)
        # Only games Steam actually answered for: a timeout or a 5xx must not
        # be remembered as "no achievements" and hidden from scans for a month.
        found = {g.app_id for g in games}
        answered = [g for g in to_fetch if g["appid"] in found | self._no_stats]
        record_scan(self.steam_id, answered, found, now)
        games.sort(key=lambda g: g.name.lower())
        return games

    def _fetch_games(
        self,
        owned: list[dict[str, Any]],
        progress_callback: Callable[[int, int], None] | None,
    ) -> list[GameInfo]:
        """Fetch achievements for *owned* in parallel, reporting each game."""
        games: list[GameInfo] = []
        done_count = 0
        total = len(owned)
        lock = threading.Lock()
        progress = current_progress()
        progress.phase("Scanning Steam achievements", total)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(self._fetch_one_game, g): g for g in owned}
            try:
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
                        progress.advance(
                            str(futures[future].get("name", "")), step=done_count
                        )
                        if progress_callback:
                            progress_callback(done_count, total)
                    if result is not None:
                        games.append(result)
            except BaseException:
                # A cancelled job must not wait for the whole queue to drain:
                # drop what has not started, leaving only requests in flight.
                pool.shutdown(wait=False, cancel_futures=True)
                raise
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
