"""Interactive pick prompt and assignment of the chosen game.

Split out of :mod:`steam_backlog_enforcer.scanning` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``scanning``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._scanning_candidates import (
    _pick_next_shortest_candidate,
    _sort_key,
)
from steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _report_poll_confidence,
)
from steam_backlog_enforcer.game_install import (
    _echo,
    install_game,
    is_game_installed,
    uninstall_other_games,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer.config import Config, State
    from steam_backlog_enforcer.steam_api import GameInfo

logger = logging.getLogger(__name__)

_NO_CONF_MSG = (
    "\nNo assignable games found "
    "(HLTB confidence thresholds: comp_100 polls>=3, "
    "count_comp>=15, sum>=18)."
)


def _prompt_user_pick(qualified: list[GameInfo]) -> int:
    """Present numbered list, return 0-based index of user's choice."""
    for i, g in enumerate(qualified, 1):
        hours_str = (
            f" (~{g.completionist_hours:.1f}h)" if g.completionist_hours > 0 else ""
        )
        _echo(f"  {i}. {g.name} (AppID={g.app_id}){hours_str}")
    while True:
        raw = input("Select game number: ")
        try:
            idx = int(raw)
        except ValueError:
            _echo(f"Invalid input: {raw!r}")
            continue
        if idx < 1 or idx > len(qualified):
            _echo(f"Out of range: {idx}")
            continue
        return idx - 1


def _assign_chosen_game(
    chosen: GameInfo,
    games: list[GameInfo],
    state: State,
    config: Config,
) -> None:
    """Save assignment, announce it, and handle install/uninstall."""
    state.current_app_id = chosen.app_id
    state.current_game_name = chosen.name
    if not state.enforcement_started_at:
        state.enforcement_started_at = datetime.now(timezone.utc).isoformat()
    state.save()
    hours_str = (
        f" (~{chosen.completionist_hours:.1f}h leisure+dlc)"
        if chosen.completionist_hours > 0
        else ""
    )
    _echo(f"\n>>> ASSIGNED: {chosen.name} (AppID={chosen.app_id}){hours_str}")
    _echo(
        f"    Progress: {chosen.unlocked_achievements}/{chosen.total_achievements}"
        f" ({chosen.completion_pct:.1f}%)"
    )
    _report_poll_confidence(chosen, games, state)
    if config.uninstall_other_games:
        count = uninstall_other_games(chosen.app_id)
        if count:
            _echo(f"\n  Uninstalled {count} non-assigned games")
    if not is_game_installed(chosen.app_id):
        _echo(f"\n  Auto-installing {chosen.name}...")
        install_game(
            chosen.app_id, chosen.name, config.steam_id, use_steam_protocol=True
        )


def _pick_next_game_sequential(
    games: list[GameInfo],
    state: State,
    config: Config,
    on_select: Callable[[GameInfo], bool],
) -> None:
    """Pick the next-shortest playable game, asking the user per candidate.

    ``on_select`` is called with each prospective pick. Returning ``True``
    accepts the assignment; returning ``False`` records a 7-day skip on
    ``state`` for that game and the next candidate is evaluated.
    """
    while True:
        skip = set(state.finished_app_ids) | state.active_skipped_ids()
        candidates = [g for g in games if not g.is_complete and g.app_id not in skip]
        if not candidates:
            _echo(_NO_CONF_MSG)
            state.current_app_id = None
            state.current_game_name = ""
            state.save()
            return

        candidates.sort(key=_sort_key)
        _apply_cached_confidence_to_candidates(candidates)
        chosen, confidence_skipped, linux_skipped = _pick_next_shortest_candidate(
            candidates
        )
        if chosen is None:
            _echo(
                _NO_CONF_MSG
                if confidence_skipped > 0 and linux_skipped == 0
                else "\nNo playable games left (all have poor ProtonDB ratings)!"
            )
            state.current_app_id = None
            state.current_game_name = ""
            state.save()
            return

        if not on_select(chosen):
            state.skip_for_days(chosen.app_id, 7)
            state.save()
            _echo(f"\n  Skipped {chosen.name} for 7 days; picking next...")
            continue

        _assign_chosen_game(chosen, games, state, config)
        return
