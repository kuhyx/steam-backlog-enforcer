"""Confidence-checking and candidate-filtering helpers for scanning."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from python_pkg.steam_backlog_enforcer._hltb_types import (
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.game_install import _echo
from python_pkg.steam_backlog_enforcer.hltb import fetch_hltb_confidence_cached

if TYPE_CHECKING:
    from python_pkg.steam_backlog_enforcer.config import State
    from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

logger = logging.getLogger(__name__)

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

    Only refreshes when both metrics are missing (0), which typically means
    the game was cached before confidence fields were added.
    """
    if game.comp_100_count > 0 or game.count_comp > 0:
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


def _backfill_polls_for_finished(
    state: State,
    games: list[GameInfo],
) -> dict[int, int]:
    """Lazily fetch poll counts for already-finished games missing them.

    Reads the polls cache, identifies finished games whose poll count is
    still ``0`` (typically because the cache predates the polls schema),
    and triggers a one-shot HLTB search to backfill them. Returns the
    refreshed polls cache.
    """
    polls_cache = load_hltb_polls_cache()
    name_by_id = {g.app_id: g.name for g in games}
    missing = [
        (aid, name_by_id[aid])
        for aid in state.finished_app_ids
        if aid in name_by_id and polls_cache.get(aid, 0) == 0
    ]
    if not missing:
        return polls_cache

    logger.info(
        "Backfilling HLTB poll counts for %d already-finished games...",
        len(missing),
    )
    # Force a fresh search by removing the hours entries we want to refetch.
    # (fetch_hltb_times_cached skips entries already in the hours cache.)
    cache = load_hltb_cache()
    preserved_hours = {aid: cache[aid] for aid, _ in missing if aid in cache}
    for aid, _name in missing:
        cache.pop(aid, None)
    save_hltb_cache(cache, polls_cache)

    fetch_hltb_confidence_cached(missing)

    # Restore any previously-known hours that the refetch may have replaced
    # with a worse match (we trust prior leisure+dlc estimates).
    refreshed_hours = load_hltb_cache()
    refreshed_polls = load_hltb_polls_cache()
    for aid, prior_hours in preserved_hours.items():
        if prior_hours > 0 and refreshed_hours.get(aid, -1) <= 0:
            refreshed_hours[aid] = prior_hours
    save_hltb_cache(refreshed_hours, refreshed_polls)
    return refreshed_polls


def _report_poll_confidence(
    chosen: GameInfo,
    games: list[GameInfo],
    state: State,
) -> None:
    """Print HLTB poll-count confidence info for the just-assigned game.

    Shows the chosen game's ``comp_100_count`` (number of polled
    completionist times on HowLongToBeat) and the historical minimum
    among the user's previously-finished games. Marks a new historical
    low so the user can be skeptical of unreliable estimates.
    """
    polls_cache = _backfill_polls_for_finished(state, games)
    chosen_polls = polls_cache.get(chosen.app_id, chosen.comp_100_count)
    chosen.comp_100_count = chosen_polls

    finished_polls = [
        (polls_cache[aid], aid)
        for aid in state.finished_app_ids
        if polls_cache.get(aid, 0) > 0
    ]
    if not finished_polls:
        _echo(f"    HLTB confidence: {chosen_polls} polled completionist times")
        return

    min_polls, min_aid = min(finished_polls)
    name_by_id = {g.app_id: g.name for g in games}
    min_name = name_by_id.get(min_aid, f"AppID={min_aid}")

    warning = ""
    if 0 < chosen_polls < min_polls:
        warning = "  ⚠ NEW LOW — estimate may be unreliable"
    elif chosen_polls == 0:
        warning = "  ⚠ no polls recorded — estimate may be unreliable"

    _echo(f"    HLTB confidence: {chosen_polls} polled completionist times{warning}")
    _echo(f"    Historical min among finished: {min_polls} ({min_name})")
