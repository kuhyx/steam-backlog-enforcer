"""Pace-vs-HLTB calibration for the web dataset.

Split out of :mod:`steam_backlog_enforcer._web_dataset` to keep both files
under the 250-line cap. Leaf helpers: nothing here calls back into it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._web_models import PaceVsHLTB

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo


def _collect_calibration_pairs(
    raw_games: list[GameInfo],
    raw_cache: dict[int, dict[str, Any]],
) -> tuple[list[tuple[float, float]], list[tuple[float, float, float]]]:
    """Separate complete games into rush-only and rush+leisure sample sets."""
    rush_pairs: list[tuple[float, float]] = []
    both_pairs: list[tuple[float, float, float]] = []
    for game in raw_games:
        if not game.is_complete or game.playtime_minutes <= 0:
            continue
        entry = raw_cache.get(game.app_id, {})
        rush = float(entry.get("rush_hours", -1))
        leisure = float(entry.get("leisure_100h", -1))
        actual = game.playtime_minutes / 60.0
        if rush > 0:
            rush_pairs.append((actual, rush))
        if rush > 0 and leisure > 0:
            both_pairs.append((actual, rush, leisure))
    return rush_pairs, both_pairs


def _interpolate_from_both(
    both_pairs: list[tuple[float, float, float]],
) -> tuple[float, float]:
    """Return (ratio_vs_leisure, interpolation_t) from (actual, rush, leisure) triples.

    Returns -1.0 for interpolation_t when leisure <= rush (degenerate data).
    """
    sum_actual = sum(p[0] for p in both_pairs)
    sum_rush = sum(p[1] for p in both_pairs)
    sum_leisure = sum(p[2] for p in both_pairs)
    ratio_vs_leisure = round(sum_actual / sum_leisure, 3)
    if sum_leisure > sum_rush:
        t = round((sum_actual - sum_rush) / (sum_leisure - sum_rush), 3)
    else:
        t = -1.0
    return ratio_vs_leisure, t


def _classify_player_style(interpolation_t: float, ratio_vs_rush: float) -> str:
    """Map calibration metrics to a player-style label."""
    if interpolation_t != -1.0:
        if interpolation_t < 0:
            return "faster_than_rush"
        if interpolation_t <= 1.0:
            return "rush_to_leisure"
        return "slower_than_leisure"
    return "faster_than_rush" if ratio_vs_rush < 1.0 else "unknown"


def compute_pace_vs_hltb(
    raw_games: list[GameInfo],
    raw_cache: dict[int, dict[str, Any]],
) -> PaceVsHLTB | None:
    """Compute player pace relative to HLTB rush/leisure averages.

    Uses completed games (100 % achievements, positive playtime) as calibration
    samples.  Steam playtime includes idle time, so ratios > 1 are expected for
    most players.

    Args:
        raw_games: All games from the snapshot (completed + incomplete).
        raw_cache: The full HLTB cache (from ``_read_raw_cache()``).

    Returns:
        A ``PaceVsHLTB`` when at least one completed game has rush data,
        ``None`` when there is no calibration data at all.
    """
    rush_pairs, both_pairs = _collect_calibration_pairs(raw_games, raw_cache)
    if not rush_pairs:
        return None

    ratio_vs_rush = round(
        sum(p[0] for p in rush_pairs) / sum(p[1] for p in rush_pairs), 3
    )
    if both_pairs:
        ratio_vs_leisure, interpolation_t = _interpolate_from_both(both_pairs)
    else:
        ratio_vs_leisure = -1.0
        interpolation_t = -1.0

    return PaceVsHLTB(
        calibration_count=len(rush_pairs),
        ratio_vs_rush=ratio_vs_rush,
        ratio_vs_leisure=ratio_vs_leisure,
        interpolation_t=interpolation_t,
        player_style=_classify_player_style(interpolation_t, ratio_vs_rush),
    )
