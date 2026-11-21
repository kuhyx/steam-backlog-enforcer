"""Control-socket ops for the research game (:mod:`_research_game`).

Instant and not time-locked, by design (kuhy 2026-11-21): game-research calls
``research_game`` right after writing its approval file and
``research_game_revoke`` when the game leaves its list. Both are audited.
Neither needs a phrase: the op can only confirm what the approval file
already says, one game at a time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _research_game
from steam_backlog_enforcer._ctl_context import hold_tick, int_arg
from steam_backlog_enforcer._ctl_protocol import INVALID_PARAMS, CtlError

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._ctl_context import CtlContext

_MAX_APP_ID: Final = 2**31 - 1


def op_research_game(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Register the approval file's game as the research game."""
    app_id = int_arg(args, "app_id", 1, _MAX_APP_ID)
    with hold_tick(ctx):
        try:
            record = _research_game.register(app_id)
        except _research_game.ResearchGameError as exc:
            raise CtlError(INVALID_PARAMS, str(exc)) from exc
    return record


def op_research_game_revoke(
    ctx: CtlContext, _args: dict[str, object]
) -> dict[str, object]:
    """Drop the research game; the next pass treats it like any game."""
    with hold_tick(ctx):
        return {"app_id": _research_game.revoke()}


RESEARCH_GAME_OPS: Final[
    dict[str, Callable[[CtlContext, dict[str, object]], dict[str, object]]]
] = {
    "research_game": op_research_game,
    "research_game_revoke": op_research_game_revoke,
}
