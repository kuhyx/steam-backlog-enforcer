"""Confidence-checking and candidate-filtering helpers for scanning."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_types import (
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.hltb import fetch_hltb_confidence_cached

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

from steam_backlog_enforcer._polls_reporting import (
    _backfill_polls_for_finished,
    _report_poll_confidence,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_backfill_polls_for_finished",
    "_report_poll_confidence",
]

_MIN_COMP_100_POLLS = 3
_MIN_COUNT_COMP = 15
_MIN_CONFIDENCE_SUM = 18


def _apply_cached_confidence_to_candidates(candidates: list[GameInfo]) -> None:
    """Overlay cached confidence counters onto candidate game objects."""
    polls_cache = load_hltb_polls_cache()
    count_comp_cache = load_hltb_count_comp_cache()
    for game in candidates:
        if game.app_id in polls_cache:
            game.comp_100_count = polls_cache[game.app_id]
        if game.app_id in count_comp_cache:
            game.count_comp = count_comp_cache[game.app_id]


def _confidence_fail_reasons(game: GameInfo) -> list[str]:
    """Return threshold-failure reasons for a game's HLTB confidence data."""
    reasons: list[str] = []
    if game.comp_100_count < _MIN_COMP_100_POLLS:
        reasons.append(f"comp_100 polls {game.comp_100_count} < {_MIN_COMP_100_POLLS}")
    if game.count_comp < _MIN_COUNT_COMP:
        reasons.append(f"count_comp {game.count_comp} < {_MIN_COUNT_COMP}")

    total = game.comp_100_count + game.count_comp
    if total < _MIN_CONFIDENCE_SUM:
        reasons.append(f"comp_100+count_comp {total} < {_MIN_CONFIDENCE_SUM}")

    return reasons


def _refresh_candidate_confidence(game: GameInfo) -> None:
    """Refresh confidence metrics for one candidate when cache looks stale.

    Refreshes when either metric is missing (0).  A game with comp_100_count>0
    but count_comp==0 means the detail-page all-playstyles count was not yet
    populated (e.g. the cache predates that field).
    """
    if game.comp_100_count > 0 and game.count_comp > 0:
        return

    _refresh_candidate_confidence_batch([game])


def _force_refresh_candidate_confidence(game: GameInfo) -> None:
    """Force-refresh one candidate's confidence metrics from HLTB."""
    _refresh_candidate_confidence_batch([game], force=True)


def _refresh_candidate_confidence_batch(
    candidates: list[GameInfo],
    *,
    force: bool = False,
) -> None:
    """Refresh missing confidence metrics for candidates in one HLTB batch.

    This prevents O(N) one-game API loops when many snapshot entries predate
    confidence fields and therefore have ``comp_100_count==0`` and
    ``count_comp==0``.
    """
    missing = [
        game
        for game in candidates
        if force or (game.comp_100_count == 0 and game.count_comp == 0)
    ]
    if not missing:
        return

    refresh_slice = missing
    if len(refresh_slice) == 1:
        game = refresh_slice[0]
        _echo(f"  Refreshing HLTB confidence for {game.name} (AppID={game.app_id})...")
    else:
        _echo(f"  Refreshing HLTB confidence for {len(refresh_slice)} candidate(s)...")

    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    count_comp = load_hltb_count_comp_cache()
    app_ids = [game.app_id for game in refresh_slice]
    names = [(game.app_id, game.name) for game in refresh_slice]
    prior_hours = {aid: cache.get(aid, -1) for aid in app_ids}

    for aid in app_ids:
        cache.pop(aid, None)
        polls.pop(aid, None)
        count_comp.pop(aid, None)
    save_hltb_cache(cache, polls, _HLTBExtras(count_comp=count_comp))

    fetch_hltb_confidence_cached(names)

    refreshed_hours = load_hltb_cache()
    refreshed_polls = load_hltb_polls_cache()
    refreshed_count_comp = load_hltb_count_comp_cache()
    for aid, old_hours in prior_hours.items():
        if old_hours > 0 and refreshed_hours.get(aid, -1) <= 0:
            refreshed_hours[aid] = old_hours
    save_hltb_cache(
        refreshed_hours, refreshed_polls, _HLTBExtras(count_comp=refreshed_count_comp)
    )

    for game in refresh_slice:
        game.comp_100_count = refreshed_polls.get(game.app_id, 0)
        game.count_comp = refreshed_count_comp.get(game.app_id, 0)


def _filter_hltb_confident_candidates(
    candidates: list[GameInfo],
) -> list[GameInfo]:
    """Keep only candidates that satisfy HLTB confidence thresholds."""
    _refresh_candidate_confidence_batch(candidates)

    kept: list[GameInfo] = []
    for game in candidates:
        reasons = _confidence_fail_reasons(game)
        if reasons:
            _echo(
                f"  Skipping {game.name} (AppID={game.app_id}): "
                f"HLTB confidence too low ({'; '.join(reasons)})"
            )
            continue
        kept.append(game)
    return kept


def _candidate_passes_hltb_confidence(game: GameInfo) -> bool:
    """Return True if candidate passes confidence with cache-first behavior.

    Only refreshes when confidence fields are missing (both zero), which keeps
    normal runs cache-friendly and avoids repeated refetches for known
    low-confidence entries.
    """
    reasons = _confidence_fail_reasons(game)
    if not reasons:
        return True

    # Re-check once when confidence fields are missing in cache.
    _refresh_candidate_confidence(game)
    reasons = _confidence_fail_reasons(game)
    if reasons:
        _echo(
            f"  Skipping {game.name} (AppID={game.app_id}): "
            f"HLTB confidence too low ({'; '.join(reasons)})"
        )
        return False
    return True
