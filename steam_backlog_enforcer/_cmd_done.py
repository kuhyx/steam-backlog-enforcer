"""Done-flow helpers and cmd_done command for Steam Backlog Enforcer."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_cached import fetch_hltb_times_cached
from steam_backlog_enforcer._hltb_confidence import (
    refetch_poll_counts,
)
from steam_backlog_enforcer._hltb_types import (
    load_hltb_polls_cache,
)
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer.game_install import (
    _echo,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State
    from steam_backlog_enforcer.steam_api import GameInfo

_REASSIGN_REFRESH_LIMIT = 50
_SKIP_DAYS = 7
logger = logging.getLogger(__name__)


def _prompt_keep_or_skip(game: GameInfo) -> bool:
    """Ask the user whether to keep the freshly-picked ``game``.

    Returns ``True`` to accept the pick, ``False`` to skip it (which the
    caller will translate into a 7-day skip entry on ``State``). When
    stdin is not a TTY (e.g. background daemon, piped invocation), the
    pick is accepted silently to preserve the legacy non-interactive
    behaviour.
    """
    if not sys.stdin.isatty():
        return True
    hours_str = ""
    if game.completionist_hours > 0:
        hours_str = f" (~{game.completionist_hours:.1f}h leisure+dlc)"
    _echo(f"\n  Next pick: {game.name} (AppID={game.app_id}){hours_str}")
    while True:
        try:
            answer = (
                input(f"  Keep this game? [Y/n] (n = skip for {_SKIP_DAYS} days): ")
                .strip()
                .lower()
            )
        except EOFError:
            return True
        if answer in {"", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        _echo("  Please answer 'y' or 'n'.")


def _backfill_polls_for_finished(
    state: State,
    extra_app_id: int | None = None,
) -> dict[int, int]:
    """Lazily fetch poll counts for already-finished games missing them.

    If ``extra_app_id`` is provided and its poll count is missing, it is
    refreshed alongside finished games (used to populate polls for the
    currently-assigned game on first run after the schema upgrade).
    """
    polls_cache = load_hltb_polls_cache()
    snapshot_data = load_snapshot() or []
    name_by_id = {d["app_id"]: d["name"] for d in snapshot_data}
    candidate_ids = list(state.finished_app_ids)
    if extra_app_id is not None and polls_cache.get(extra_app_id, 0) == 0:
        candidate_ids.append(extra_app_id)
    missing = [
        (aid, name_by_id[aid])
        for aid in candidate_ids
        if aid in name_by_id and polls_cache.get(aid, 0) == 0
    ]
    if not missing:
        return polls_cache

    _echo(f"  Backfilling HLTB poll counts for {len(missing)} game(s)...")
    return refetch_poll_counts(missing)


def _report_assigned_confidence(
    app_id: int,
    state: State,
) -> None:
    """Print HLTB poll-count confidence for the currently-assigned game."""
    polls_cache = _backfill_polls_for_finished(state, extra_app_id=app_id)
    chosen_polls = polls_cache.get(app_id, 0)

    finished_polls = [
        (polls_cache[aid], aid)
        for aid in state.finished_app_ids
        if polls_cache.get(aid, 0) > 0 and aid != app_id
    ]
    snapshot_data = load_snapshot() or []
    name_by_id = {d["app_id"]: d["name"] for d in snapshot_data}

    warning = ""
    if finished_polls:
        min_polls = min(p for p, _ in finished_polls)
        if 0 < chosen_polls < min_polls:
            warning = "  ⚠ NEW LOW — estimate may be unreliable"
        elif chosen_polls == 0:
            warning = "  ⚠ no polls recorded — estimate may be unreliable"
    elif chosen_polls == 0:
        warning = "  ⚠ no polls recorded — estimate may be unreliable"

    _echo(f"  HLTB confidence: {chosen_polls} polled completionist times{warning}")
    if finished_polls:
        min_polls, min_aid = min(finished_polls)
        min_name = name_by_id.get(min_aid, f"AppID={min_aid}")
        _echo(f"  Historical min among finished: {min_polls} ({min_name})")


def _apply_cached_hours_to_games(
    games: list[GameInfo],
    hltb_cache: dict[int, float],
) -> None:
    """Overlay cached HLTB hours onto games (including cached misses)."""
    for game in games:
        if game.app_id in hltb_cache:
            game.completionist_hours = hltb_cache[game.app_id]


def _refresh_uncached_shortlist_hours(
    games: list[GameInfo],
    hltb_cache: dict[int, float],
    skip: set[int],
    *,
    upper_bound_hours: float | None = None,
) -> None:
    """Refresh likely-short uncached games to avoid stale snapshot decisions."""
    shorter_uncached = [
        (g.app_id, g.name)
        for g in sorted(
            (
                game
                for game in games
                if not game.is_complete
                and game.app_id not in skip
                and game.completionist_hours > 0
                and game.app_id not in hltb_cache
                and (
                    upper_bound_hours is None
                    or game.completionist_hours < upper_bound_hours
                )
            ),
            key=lambda game: game.completionist_hours,
        )[:_REASSIGN_REFRESH_LIMIT]
    ]
    if shorter_uncached:
        refreshed = fetch_hltb_times_cached(shorter_uncached)
        hltb_cache.update(refreshed)
