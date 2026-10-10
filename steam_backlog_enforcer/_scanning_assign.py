"""Interactive pick prompt and assignment of the chosen game.

Split out of :mod:`steam_backlog_enforcer.scanning` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``scanning``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._allowed_games import drop_inactive_picks
from steam_backlog_enforcer._assignment_progress import (
    last_assigned_epoch,
    record_assignment,
)
from steam_backlog_enforcer._own_pick import (
    OWN_PICK_OPTION,
    OWN_PICK_VALUE,
    prompt_own_pick,
)
from steam_backlog_enforcer._prompter import PromptOption, current_prompter
from steam_backlog_enforcer._scanning_candidates import (
    _pick_next_shortest_candidate,
    _sort_key,
)
from steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _report_poll_confidence,
)
from steam_backlog_enforcer._steam_state import is_game_fully_installed
from steam_backlog_enforcer.game_install import (
    _echo,
    install_game,
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


def _prompt_user_pick(
    qualified: list[GameInfo], games: list[GameInfo], state: State
) -> GameInfo:
    """Present the ranked list plus "pick my own"; return the chosen game.

    Backing out of the own-game search (empty answer) shows the list again.
    """
    options: list[PromptOption] = []
    for i, g in enumerate(qualified):
        hours_str = (
            f" (~{g.completionist_hours:.1f}h)" if g.completionist_hours > 0 else ""
        )
        label = f"{g.name} (AppID={g.app_id}){hours_str}"
        options.append(PromptOption(value=str(i), label=label))
    options.append(OWN_PICK_OPTION)
    while True:
        picked = current_prompter().choice("Select game number", options)
        if picked != OWN_PICK_VALUE:
            return qualified[int(picked)]
        own = prompt_own_pick(games, state)
        if own is not None:
            return own


def _assign_chosen_game(
    chosen: GameInfo,
    games: list[GameInfo],
    state: State,
    config: Config,
) -> None:
    """Save assignment, announce it, and handle install/uninstall.

    Accepting a new game is the explicit choice that lets enforcement remove
    released picks, so they are dropped here.
    """
    drop_inactive_picks(state)
    record_assignment(state, chosen.app_id, chosen.name)
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
        # The whole allowed set, not just the new assignment: passing a bare
        # int made the `in` test raise TypeError, and would tear down a
        # concurrent manual pick even if it did not. Matches the other four
        # call sites (main/install.py, _cmd_done_finalize.py, main/picks.py,
        # _enforce_steps.py). state.current_app_id is already `chosen` here.
        count = uninstall_other_games(allowed_app_ids(state))
        if count:
            _echo(f"\n  Uninstalled {count} non-assigned games")
    if not is_game_fully_installed(chosen.app_id):
        _echo(f"\n  Auto-installing {chosen.name}...")
        install_game(
            chosen.app_id, chosen.name, config.steam_id, use_steam_protocol=True
        )


def _clear_assignment(state: State, message: str) -> None:
    """Say why nothing could be assigned; keep the current game, if any.

    With no replacement chosen, the game already assigned stays installed and
    playable: only an explicit choice of another game may remove it.
    """
    _echo(message)
    state.save()


def _no_pick_message(confidence_skipped: int, linux_skipped: int) -> str:
    """Why the candidate pass produced nothing: confidence, or ProtonDB."""
    if confidence_skipped > 0 and linux_skipped == 0:
        return _NO_CONF_MSG
    return "\nNo playable games left (all have poor ProtonDB ratings)!"


def _open_candidates(games: list[GameInfo], state: State) -> list[GameInfo]:
    """Unfinished, unskipped games with cached confidence, in pick order.

    Least-recently-assigned first (never-assigned games lead), then shortest
    HLTB time. A game released after one new achievement is still unfinished,
    so without the recency key the same short game would come straight back
    and the user would be locked onto it again.
    """
    skip = set(state.finished_app_ids) | state.active_skipped_ids()
    candidates = [g for g in games if not g.is_complete and g.app_id not in skip]
    if candidates:
        candidates.sort(
            key=lambda g: (last_assigned_epoch(state, g.app_id), *_sort_key(g))
        )
        _apply_cached_confidence_to_candidates(candidates)
    return candidates


def _pick_next_game_sequential(
    games: list[GameInfo],
    state: State,
    config: Config,
    on_select: Callable[[GameInfo], bool | GameInfo],
) -> None:
    """Pick the next-shortest playable game, asking the user per candidate.

    ``on_select`` is called with each prospective pick. Returning ``True``
    accepts the assignment; returning ``False`` records a 7-day skip on
    ``state`` for that game and the next candidate is evaluated; returning a
    game assigns that one instead (the user picked their own).
    """
    while True:
        candidates = _open_candidates(games, state)
        if not candidates:
            _clear_assignment(state, _NO_CONF_MSG)
            return

        chosen, confidence_skipped, linux_skipped = _pick_next_shortest_candidate(
            candidates
        )
        if chosen is None:
            _clear_assignment(
                state, _no_pick_message(confidence_skipped, linux_skipped)
            )
            return

        verdict = on_select(chosen)
        if verdict is False:
            state.skip_for_days(chosen.app_id, 7)
            state.save()
            _echo(f"\n  Skipped {chosen.name} for 7 days; picking next...")
            continue

        _assign_chosen_game(
            chosen if verdict is True else verdict, games, state, config
        )
        return
