"""Backfilling and reporting HLTB poll confidence for finished games.

Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._hltb_types import (
    load_hltb_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.hltb import fetch_hltb_confidence_cached

if TYPE_CHECKING:
    from steam_backlog_enforcer._steam_models import GameInfo
    from steam_backlog_enforcer.config import State

logger = logging.getLogger(__name__)


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
