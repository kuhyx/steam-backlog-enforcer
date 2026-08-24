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

# The dataclasses live in the _web_models leaf so the helper modules can share
# them, and the pace/game helpers in their own modules; all are re-exported
# here because callers have always imported them from _web_dataset.
__all__ = [
    "HOURS_PER_DAY_PRESETS",
    "DefaultSummary",
    "PaceVsHLTB",
    "WebDataset",
    "WebDefaults",
    "WebGame",
    "WebStateInfo",
    "_build_games",
    "_default_qualifying",
    "_default_summary",
    "_has_any_time",
    "_passes_default_confidence",
    "_sum_positive",
    "_worst_hours",
    "compute_pace_vs_hltb",
    "count_complete_since_start",
]

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._hltb_types import _read_raw_cache
from steam_backlog_enforcer._scanning_confidence import (
    _MIN_COMP_100_POLLS,
    _MIN_CONFIDENCE_SUM,
    _MIN_COUNT_COMP,
)
from steam_backlog_enforcer._web_games import (
    _build_games,
    _default_qualifying,
    _default_summary,
    _has_any_time,
    _passes_default_confidence,
    _sum_positive,
    _worst_hours,
)
from steam_backlog_enforcer._web_models import (
    HOURS_PER_DAY_PRESETS,
    DefaultSummary,
    PaceVsHLTB,
    WebDataset,
    WebDefaults,
    WebGame,
    WebStateInfo,
)
from steam_backlog_enforcer._web_pace import compute_pace_vs_hltb
from steam_backlog_enforcer.config import State, load_snapshot
from steam_backlog_enforcer.protondb import (
    MIN_PLAYABLE_TIER,
)
from steam_backlog_enforcer.steam_api import GameInfo


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
