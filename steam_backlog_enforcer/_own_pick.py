"""Let the user name their own next game instead of taking one from the list.

The ranked list only offers games that clear the HLTB-confidence and ProtonDB
filters. Choosing your own game is a plain assignment, exactly as if it had
been on the list (no manual-pick lock): any owned game that is not 100 %
complete qualifies, confidence or not. Games still in a skip/abandon cooldown
stay out, so abandoning and re-picking cannot become a loop.

:func:`ineligible_reason` is the one rule: the web library greys games with
it, and a job only accepts an answer from the set it leaves eligible. A
front end that can browse the library (:class:`GamePicker`) gets that set;
the CLI keeps its text search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._prompter import (
    GamePicker,
    PromptOption,
    current_prompter,
)
from steam_backlog_enforcer.game_install import _echo

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State
    from steam_backlog_enforcer.steam_api import GameInfo

OWN_PICK_VALUE: Final = "own"
OWN_PICK_OPTION: Final = PromptOption(
    value=OWN_PICK_VALUE,
    label="Pick my own game…",
    detail="Any owned game you have not 100%-completed",
)

# More matches than this and the user is asked to narrow the search.
_MAX_MATCHES: Final = 15
_SEARCH_AGAIN: Final = "search-again"


def ineligible_reason(
    app_id: int, game: GameInfo | None, state: State, skipped: set[int]
) -> str | None:
    """Why *app_id* cannot be picked as your own game, or ``None`` if it can.

    Args:
        app_id: The owned game.
        game: Its scan data; ``None`` when the scan has none (no
            achievements, or not scanned yet), so it could never complete.
        state: The enforcer state.
        skipped: ``state.active_skipped_ids()``, computed once by the caller.
    """
    if game is None:
        return "No achievement data"
    if game.is_complete:
        return "Already 100% complete"
    if app_id in state.finished_app_ids:
        # Older states marked games finished below 100 %; still not pickable.
        return "Marked finished"
    if app_id in skipped:
        until = state.skipped_until.get(str(app_id), "")[:10]
        return f"Skipped until {until}" if until else "Skipped for now"
    return None


def _eligible(games: list[GameInfo], state: State) -> list[GameInfo]:
    """Owned games the user may pick: unfinished and not cooling down."""
    skipped = state.active_skipped_ids()
    return [g for g in games if ineligible_reason(g.app_id, g, state, skipped) is None]


def _matches(query: str, games: list[GameInfo]) -> list[GameInfo]:
    """Exact app_id for a number, else case-insensitive name substring."""
    if query.isdigit():
        return [g for g in games if g.app_id == int(query)]
    needle = query.casefold()
    hits = [g for g in games if needle in g.name.casefold()]
    return sorted(
        hits, key=lambda g: (not g.name.casefold().startswith(needle), g.name)
    )


def _label(game: GameInfo) -> PromptOption:
    """One match as a choice option."""
    detail = f"{game.completion_pct:.0f}% achievements"
    if game.completionist_hours > 0:
        detail += f", ~{game.completionist_hours:.1f}h"
    return PromptOption(
        value=str(game.app_id),
        label=f"{game.name} (AppID={game.app_id})",
        detail=detail,
    )


def _choose_among(hits: list[GameInfo]) -> GameInfo | None:
    """Ask which of several matches was meant; ``None`` means search again."""
    options = [_label(g) for g in hits]
    options.append(PromptOption(value=_SEARCH_AGAIN, label="Search again"))
    picked = current_prompter().choice("Which game?", options)
    if picked == _SEARCH_AGAIN:
        return None
    return next(g for g in hits if str(g.app_id) == picked)


def prompt_own_pick(games: list[GameInfo], state: State) -> GameInfo | None:
    """Search the user's own games until one is chosen.

    Returns:
        The chosen game, or ``None`` when the user leaves the search empty
        to go back to the previous question.
    """
    eligible = _eligible(games, state)
    prompter = current_prompter()
    if isinstance(prompter, GamePicker):
        picked = prompter.game("Pick your next game", [g.app_id for g in eligible])
        return next((g for g in eligible if g.app_id == picked), None)
    while True:
        query = current_prompter().text("Game name or app_id (leave empty to go back)")
        if not query:
            return None
        hits = _matches(query, eligible)
        if not hits:
            _echo(f"No unfinished owned game matches {query!r}.")
            continue
        if len(hits) > _MAX_MATCHES:
            _echo(f"{len(hits)} games match {query!r}; type more of the name.")
            continue
        chosen = hits[0] if len(hits) == 1 else _choose_among(hits)
        if chosen is not None:
            return chosen
