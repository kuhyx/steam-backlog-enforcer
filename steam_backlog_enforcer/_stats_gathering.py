"""Game selection and HLTB/completion data top-ups for ``stats``.

Split out of :mod:`steam_backlog_enforcer._stats` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``_stats``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_types import (
    load_hltb_cache,
    load_hltb_game_id_cache,
    load_hltb_leisure_100h_cache,
    load_hltb_rush_cache,
)
from steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _confidence_fail_reasons,
    _refresh_candidate_confidence_batch,
)
from steam_backlog_enforcer._stats_types import _GameTimes
from steam_backlog_enforcer.config import SNAPSHOT_FILE
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.hltb import fetch_hltb_detail_missing
from steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from steam_backlog_enforcer.steam_api import (
    GameInfo,
    SteamAPIClient,
    SteamAPIError,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)


def _filter_qualifying_games(
    games: list[GameInfo],
    state: State,
) -> tuple[list[_GameTimes], int, int, int]:
    """Return qualifying incomplete games with their time estimates.

    Applies the same HLTB-confidence and Linux-compatibility filters as the
    game picker.  The current game and already-finished games are excluded.

    Returns:
        (qualified_list, hltb_skipped, linux_skipped, no_data_skipped)
    """
    rush_cache = load_hltb_rush_cache()
    leisure_100h_cache = load_hltb_leisure_100h_cache()
    game_id_cache = load_hltb_game_id_cache()
    hours_cache = load_hltb_cache()

    exclude = set(state.finished_app_ids)
    if state.current_app_id is not None:
        exclude.add(state.current_app_id)

    candidates = [g for g in games if not g.is_complete and g.app_id not in exclude]
    _apply_cached_confidence_to_candidates(candidates)
    _refresh_candidate_confidence_batch(candidates)

    hltb_skipped = 0
    linux_skipped = 0
    no_data_skipped = 0
    app_ids_to_check: list[int] = []

    conf_ok: list[GameInfo] = []
    for game in candidates:
        if _confidence_fail_reasons(game):
            hltb_skipped += 1
            continue
        conf_ok.append(game)
        app_ids_to_check.append(game.app_id)

    ratings: dict[int, ProtonDBRating] = {}
    if app_ids_to_check:
        ratings = fetch_protondb_ratings(app_ids_to_check)

    qualified: list[_GameTimes] = []
    for game in conf_ok:
        rating = ratings.get(game.app_id, ProtonDBRating(app_id=game.app_id))
        if not rating.is_playable:
            linux_skipped += 1
            continue

        rush = rush_cache.get(game.app_id, -1)
        leisure = leisure_100h_cache.get(game.app_id, -1)

        # worst_hours = max of: snapshot completionist, HLTB hours cache (fallback
        # when snapshot is stale/missing), and leisure_100h (slowest 100% time).
        snap_hours = game.completionist_hours if game.completionist_hours > 0 else -1
        cache_hours = hours_cache.get(game.app_id, -1)
        worst_candidates = [v for v in (snap_hours, cache_hours, leisure) if v > 0]
        worst = max(worst_candidates) if worst_candidates else -1

        if worst <= 0 and rush <= 0 and leisure <= 0:
            no_data_skipped += 1
            continue

        qualified.append(
            _GameTimes(
                game=game,
                worst_hours=worst,
                rush_hours=rush,
                leisure_100h=leisure,
                hltb_game_id=game_id_cache.get(game.app_id, 0),
            )
        )

    return qualified, hltb_skipped, linux_skipped, no_data_skipped


def _ensure_rush_data(qualified: list[_GameTimes]) -> bool:
    """Auto-fetch rush/leisure detail for games that are missing it.

    Returns True when a fetch was performed; the caller should then re-run
    ``_filter_qualifying_games`` to pick up the updated caches.
    """
    total_q = len(qualified)
    missing = sum(1 for e in qualified if e.rush_hours <= 0)
    if not qualified or not missing:
        return False
    _echo(f"Fetching HLTB detail for {missing}/{total_q} games missing rush/leisure...")
    game_pairs = [(e.game.app_id, e.game.name) for e in qualified]
    fetch_hltb_detail_missing(game_pairs)
    return True


def _ensure_completed_rush_data(games: list[GameInfo]) -> bool:
    """Fetch rush/leisure detail for completed games used for pace calibration.

    Completed games aren't processed by ``_ensure_rush_data`` (which only
    handles incomplete qualifying games), so this separate pass fills in
    their rush/leisure data for ``compute_pace_vs_hltb``.

    Returns True when at least one new fetch was performed.
    """
    pairs = [
        (g.app_id, g.name) for g in games if g.is_complete and g.playtime_minutes > 0
    ]
    if not pairs:
        return False
    _echo(
        f"Fetching HLTB detail for {len(pairs)} completed games (pace calibration)..."
    )
    fetched = fetch_hltb_detail_missing(pairs)
    return fetched > 0


def _refresh_recently_played_completions(
    games: list[GameInfo],
    config: Config,
) -> list[GameInfo]:
    """Refresh achievement data for incomplete games played since last scan.

    Makes 1 ``GetOwnedGames`` request + 1 ``GetPlayerAchievements`` per
    recently-played incomplete game.  Finds games newly completed since the
    last ``scan`` without re-scanning the whole library.

    Returns a new list with updated GameInfo objects for any game that was
    played after the snapshot was written; all other games are unchanged.
    """
    try:
        snapshot_mtime = SNAPSHOT_FILE.stat().st_mtime
    except OSError:
        return games

    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned_raw = client.get_owned_games()
    except SteamAPIError:
        logger.debug("Steam API unavailable; skipping completion refresh.")
        return games
    last_played_map = {g["appid"]: g.get("rtime_last_played", 0) for g in owned_raw}

    to_refresh = [
        g
        for g in games
        if not g.is_complete and last_played_map.get(g.app_id, 0) > snapshot_mtime
    ]

    if not to_refresh:
        return games

    _echo(
        f"Refreshing {len(to_refresh)} recently-played game(s)"
        " for up-to-date completion status..."
    )

    game_map = {g.app_id: g for g in games}

    def _refresh_one(game: GameInfo) -> GameInfo:
        achievements = client.get_achievement_details(game.app_id)
        if not achievements:
            return game
        unlocked = sum(1 for a in achievements if a.achieved)
        return GameInfo(
            app_id=game.app_id,
            name=game.name,
            total_achievements=len(achievements),
            unlocked_achievements=unlocked,
            playtime_minutes=game.playtime_minutes,
            achievements=achievements,
            completionist_hours=game.completionist_hours,
            comp_100_count=game.comp_100_count,
            count_comp=game.count_comp,
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_refresh_one, g): g for g in to_refresh}
        for future in as_completed(futures):
            refreshed = future.result()
            game_map[refreshed.app_id] = refreshed

    return list(game_map.values())
