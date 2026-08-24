"""Build the per-game rows and the CLI-parity summary for the web dataset.

Split out of :mod:`steam_backlog_enforcer._web_dataset` to keep both files
under the 250-line cap. Leaf helpers: nothing here calls back into it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_types import _read_raw_cache
from steam_backlog_enforcer._scanning_confidence import (
    _MIN_COMP_100_POLLS,
    _MIN_CONFIDENCE_SUM,
    _MIN_COUNT_COMP,
)
from steam_backlog_enforcer._web_models import DefaultSummary, WebGame
from steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    _load_cache,
    _rating_from_cache,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo


def _worst_hours(game: GameInfo, cache_hours: float, leisure: float) -> float:
    """Replicate ``_stats`` worst-case selection exactly.

    worst = max of snapshot completionist hours, the HLTB hours-cache value,
    and the leisure-100% time — considering only positive values.
    """
    snap_hours = game.completionist_hours if game.completionist_hours > 0 else -1
    candidates = [v for v in (snap_hours, cache_hours, leisure) if v > 0]
    return max(candidates) if candidates else -1.0


def _passes_default_confidence(game: WebGame) -> bool:
    """True if the game clears all three CLI HLTB-confidence thresholds."""
    if game.comp_100_count < _MIN_COMP_100_POLLS:
        return False
    if game.count_comp < _MIN_COUNT_COMP:
        return False
    return game.comp_100_count + game.count_comp >= _MIN_CONFIDENCE_SUM


def _has_any_time(game: WebGame) -> bool:
    """True if the game has at least one positive time estimate."""
    return game.worst_hours > 0 or game.rush_hours > 0 or game.leisure_hours > 0


def _build_games(games: list[GameInfo], exclude: set[int]) -> list[WebGame]:
    """Project incomplete, non-excluded games into compact rows (no network)."""
    raw = _read_raw_cache()
    protondb_cache = _load_cache()

    rows: list[WebGame] = []
    for game in games:
        if game.is_complete or game.app_id in exclude:
            continue

        entry = raw.get(game.app_id, {})
        rush = float(entry.get("rush_hours", -1))
        leisure = float(entry.get("leisure_100h", -1))
        cache_hours = float(entry.get("hours", -1))
        count_comp = int(entry.get("count_comp", 0))
        comp_100_count = int(entry.get("polls", 0))
        hltb_game_id = int(entry.get("hltb_game_id", 0))

        rating: ProtonDBRating = (
            _rating_from_cache(game.app_id, protondb_cache[str(game.app_id)])
            if str(game.app_id) in protondb_cache
            else ProtonDBRating(app_id=game.app_id)
        )

        rows.append(
            WebGame(
                app_id=game.app_id,
                name=game.name,
                completion_pct=round(game.completion_pct, 1),
                playtime_minutes=game.playtime_minutes,
                rush_hours=rush,
                leisure_hours=leisure,
                worst_hours=_worst_hours(game, cache_hours, leisure),
                count_comp=count_comp,
                comp_100_count=comp_100_count,
                hltb_game_id=hltb_game_id,
                protondb_tier=rating.tier,
                protondb_trending_tier=rating.trending_tier,
                protondb_score=rating.score,
            )
        )
    return rows


def _default_qualifying(rows: list[WebGame]) -> list[WebGame]:
    """Apply the exact CLI default filters (confidence + ProtonDB + has-data)."""
    qualifying: list[WebGame] = []
    for game in rows:
        if not _passes_default_confidence(game):
            continue
        rating = ProtonDBRating(
            app_id=game.app_id,
            tier=game.protondb_tier,
            trending_tier=game.protondb_trending_tier,
        )
        if not rating.is_playable:
            continue
        if not _has_any_time(game):
            continue
        qualifying.append(game)
    return qualifying


def _sum_positive(rows: list[WebGame], attr: str) -> float:
    """Sum a positive-only hour attribute across rows (matches ``_sum_hours``)."""
    total = sum(getattr(g, attr) for g in rows if getattr(g, attr) > 0)
    return round(total, 1)


def _default_summary(rows: list[WebGame]) -> DefaultSummary:
    """Compute the CLI parity totals at default thresholds."""
    qualifying = _default_qualifying(rows)
    return DefaultSummary(
        qualifying=len(qualifying),
        rush_total=_sum_positive(qualifying, "rush_hours"),
        leisure_total=_sum_positive(qualifying, "leisure_hours"),
        worst_total=_sum_positive(qualifying, "worst_hours"),
    )
