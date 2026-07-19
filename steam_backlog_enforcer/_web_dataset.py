"""Read-only projection of cached data for the interactive web UI.

Builds a compact, secrets-free dataset from the on-disk caches (snapshot,
HLTB, ProtonDB, state) so a browser UI can filter games and estimate backlog
completion times entirely client-side.  This module performs **no network
calls** — it only reads caches that previous ``scan``/``stats`` runs populated.

The projection deliberately emits *every* incomplete, non-current,
non-finished game with its raw HLTB-confidence counters and ProtonDB tiers, so
the client can move its filter thresholds *below* the CLI defaults.  The CLI
default thresholds and a parity summary are included so the UI can show
"matches the CLI" and so changes that break parity are easy to spot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._hltb_types import _read_raw_cache
from steam_backlog_enforcer._scanning_confidence import (
    _MIN_COMP_100_POLLS,
    _MIN_CONFIDENCE_SUM,
    _MIN_COUNT_COMP,
)
from steam_backlog_enforcer.config import State, load_snapshot
from steam_backlog_enforcer.protondb import (
    MIN_PLAYABLE_TIER,
    ProtonDBRating,
    _load_cache,
    _rating_from_cache,
)
from steam_backlog_enforcer.steam_api import GameInfo

# Mirrors ``_stats._HOURS_PER_DAY_PRESETS`` but mutable/JSON-friendly.
HOURS_PER_DAY_PRESETS = [2.0, 4.0, 6.0, 8.0]


@dataclass
class WebGame:
    """One incomplete candidate game, with raw filterable fields.

    Hour fields use ``-1`` to mean "no data" (matching the cache convention),
    so the client can choose to include or exclude unknown-length games.
    """

    app_id: int
    name: str
    completion_pct: float
    playtime_minutes: int
    rush_hours: float
    leisure_hours: float
    worst_hours: float
    count_comp: int
    comp_100_count: int
    hltb_game_id: int
    protondb_tier: str
    protondb_trending_tier: str
    protondb_score: float


@dataclass
class WebStateInfo:
    """Pace inputs and current-assignment metadata for the UI."""

    current_app_id: int | None
    current_game_name: str
    games_done: int
    games_done_since_start: int
    days_elapsed: int
    enforcement_started_at: str
    pace_games_per_day: float


@dataclass
class WebDefaults:
    """The CLI's hardcoded filter thresholds, surfaced as editable defaults."""

    min_comp_100_polls: int
    min_count_comp: int
    min_confidence_sum: int
    min_playable_tier: str
    hours_per_day_presets: list[float]


@dataclass
class DefaultSummary:
    """Totals the CLI ``stats`` command would print at default thresholds.

    Used as a parity oracle: the client's own default-filtered totals must
    reproduce these numbers.
    """

    qualifying: int
    rush_total: float
    leisure_total: float
    worst_total: float


@dataclass
class PaceVsHLTB:
    """Player pace calibrated against HLTB rush/leisure averages.

    Derived from completed games that have HLTB detail data.  All ratio /
    interpolation fields use ``-1`` to mean "insufficient data", matching the
    cache convention used elsewhere.

    Fields:
        calibration_count: number of completed games used for calibration.
        ratio_vs_rush: actual_hours / rush_hours across calibration games.
        ratio_vs_leisure: actual_hours / leisure_hours (-1 if no leisure data).
        interpolation_t: position between rush (0.0) and leisure (1.0) speed.
            Negative means faster than rush; >1 means slower than leisure.
            -1 means insufficient data.
        player_style: human-readable style label.
    """

    calibration_count: int
    ratio_vs_rush: float
    ratio_vs_leisure: float
    interpolation_t: float
    player_style: str


@dataclass
class WebDataset:
    """Full payload served to the browser."""

    games: list[WebGame]
    state: WebStateInfo
    defaults: WebDefaults
    default_summary: DefaultSummary
    pace_vs_hltb: PaceVsHLTB | None
    generated_at: str = field(default="")


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


def count_complete_since_start(games: list[GameInfo], started_at: str) -> int:
    """Count complete games whose last achievement was unlocked on/after started_at.

    Games with no achievement timestamp data are excluded — their completion
    date is unknown, and they were most likely finished before Steam began
    recording unlock timestamps (i.e. before the enforcement period).
    Returns 0 when started_at is empty or unparsable.
    """
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    started_ts = int(started.timestamp())
    count = 0
    for game in games:
        if not game.is_complete:
            continue
        achieved_times = [
            a.unlock_time for a in game.achievements if a.achieved and a.unlock_time > 0
        ]
        if not achieved_times:
            continue
        if max(achieved_times) >= started_ts:
            count += 1
    return count


def _state_info(
    state: State, games_done: int, games_done_since_start: int
) -> WebStateInfo:
    """Build pace metadata, mirroring ``_print_pace_scenario`` inputs."""
    days_elapsed = 0
    pace = 0.0
    if state.enforcement_started_at:
        try:
            started = datetime.fromisoformat(state.enforcement_started_at)
        except ValueError:
            started = None
        if started is not None:
            now = datetime.now(timezone.utc)
            days_elapsed = max(1, (now - started).days)
            if games_done_since_start > 0:
                pace = round(games_done_since_start / days_elapsed, 4)
    return WebStateInfo(
        current_app_id=state.current_app_id,
        current_game_name=state.current_game_name,
        games_done=games_done,
        games_done_since_start=games_done_since_start,
        days_elapsed=days_elapsed,
        enforcement_started_at=state.enforcement_started_at,
        pace_games_per_day=pace,
    )


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


def build_web_dataset(state: State) -> WebDataset:
    """Build the full web dataset from on-disk caches (no network calls).

    Args:
        state: The loaded enforcer state (current game, finished IDs, pace).

    Returns:
        A ``WebDataset`` with every incomplete candidate game, the CLI default
        thresholds, and a parity summary.  Raises no exceptions for a missing
        snapshot — it returns an empty game list instead.
    """
    snapshot = load_snapshot()
    raw_games = (
        [GameInfo.from_snapshot(d) for d in snapshot] if snapshot is not None else []
    )
    games_done = sum(1 for g in raw_games if g.is_complete)
    games_done_since_start = count_complete_since_start(
        raw_games, state.enforcement_started_at
    )

    exclude = set(state.finished_app_ids)
    exclude.update(allowed_app_ids(state))

    rows = _build_games(raw_games, exclude)

    raw_cache = _read_raw_cache()
    pace_vs_hltb = compute_pace_vs_hltb(raw_games, raw_cache)

    return WebDataset(
        games=rows,
        state=_state_info(state, games_done, games_done_since_start),
        defaults=WebDefaults(
            min_comp_100_polls=_MIN_COMP_100_POLLS,
            min_count_comp=_MIN_COUNT_COMP,
            min_confidence_sum=_MIN_CONFIDENCE_SUM,
            min_playable_tier=MIN_PLAYABLE_TIER,
            hours_per_day_presets=list(HOURS_PER_DAY_PRESETS),
        ),
        default_summary=_default_summary(rows),
        pace_vs_hltb=pace_vs_hltb,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def dataset_to_payload(dataset: WebDataset) -> dict[str, Any]:
    """Serialize a ``WebDataset`` to a JSON-ready dict."""
    return asdict(dataset)
