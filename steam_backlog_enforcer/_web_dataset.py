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
class WebDataset:
    """Full payload served to the browser."""

    games: list[WebGame]
    state: WebStateInfo
    defaults: WebDefaults
    default_summary: DefaultSummary
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


def _state_info(state: State, games_done: int) -> WebStateInfo:
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
            if games_done > 0:
                pace = round(games_done / days_elapsed, 4)
    return WebStateInfo(
        current_app_id=state.current_app_id,
        current_game_name=state.current_game_name,
        games_done=games_done,
        days_elapsed=days_elapsed,
        enforcement_started_at=state.enforcement_started_at,
        pace_games_per_day=pace,
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

    exclude = set(state.finished_app_ids)
    if state.current_app_id is not None:
        exclude.add(state.current_app_id)

    rows = _build_games(raw_games, exclude)

    return WebDataset(
        games=rows,
        state=_state_info(state, games_done),
        defaults=WebDefaults(
            min_comp_100_polls=_MIN_COMP_100_POLLS,
            min_count_comp=_MIN_COUNT_COMP,
            min_confidence_sum=_MIN_CONFIDENCE_SUM,
            min_playable_tier=MIN_PLAYABLE_TIER,
            hours_per_day_presets=list(HOURS_PER_DAY_PRESETS),
        ),
        default_summary=_default_summary(rows),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def dataset_to_payload(dataset: WebDataset) -> dict[str, Any]:
    """Serialize a ``WebDataset`` to a JSON-ready dict."""
    return asdict(dataset)
