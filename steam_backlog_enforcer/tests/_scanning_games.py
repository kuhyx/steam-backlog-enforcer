"""Shared builders and patch sets for the pick_next_game / scanning tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

_PKG = "steam_backlog_enforcer"
_ASSIGN = f"{_PKG}._scanning_assign"


def make_game(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> GameInfo:
    """Build a game that passes the HLTB confidence floor (3 polls, 15 runs)."""
    return GameInfo(
        app_id,
        name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=3,
        count_comp=15,
    )


def make_config(**overrides: bool) -> Config:
    """Build the minimal Config the scanning tests run against."""
    return Config(steam_api_key="k", steam_id="i", **overrides)


def first_candidate(candidates: list[GameInfo]) -> GameInfo | None:
    """Stand in for ProtonDB: every candidate is playable, take the first."""
    return candidates[0] if candidates else None


def echo_into(echoed: list[str]) -> Callable[..., None]:
    """Return an ``_echo`` replacement that records each first argument."""
    return lambda *a, **_: echoed.append(a[0])


@dataclass
class PickMocks:
    """Mocks started by :func:`pick_env`, keyed by what they replace."""

    pick: MagicMock
    uninstall: MagicMock
    install: MagicMock


@contextmanager
def pick_env(
    *,
    echo: Sequence[str] = ("scanning",),
    echoed: list[str] | None = None,
    installed: bool = True,
    answers: str | list[str] | None = "1",
    playable: Callable[[list[GameInfo]], GameInfo | None] = first_candidate,
) -> Iterator[PickMocks]:
    """Patch everything pick_next_game touches outside the decision itself.

    ``echo`` names the modules (relative to the package) whose ``_echo`` is
    replaced; with ``echoed`` set they record into it, else they are silenced.
    ``install_game`` and ``uninstall_other_games`` (0 games removed) are
    always mocked so no test touches Steam. ``answers=None`` leaves
    ``input`` alone (the ``on_select`` path never prompts).
    """
    with ExitStack() as stack:
        pick = stack.enter_context(
            patch(
                f"{_PKG}._scanning_candidates._pick_playable_candidate",
                side_effect=playable,
            )
        )
        for module in echo:
            target = f"{_PKG}.{module}._echo"
            if echoed is None:
                stack.enter_context(patch(target))
            else:
                stack.enter_context(patch(target, side_effect=echo_into(echoed)))
        stack.enter_context(
            patch(f"{_ASSIGN}.is_game_fully_installed", return_value=installed)
        )
        mocks = PickMocks(
            pick=pick,
            uninstall=stack.enter_context(
                patch(f"{_ASSIGN}.uninstall_other_games", return_value=0)
            ),
            install=stack.enter_context(patch(f"{_ASSIGN}.install_game")),
        )
        if isinstance(answers, str):
            stack.enter_context(patch("builtins.input", return_value=answers))
        elif answers is not None:
            stack.enter_context(patch("builtins.input", side_effect=answers))
        yield mocks


def pick_without_batch_refresh(games: list[GameInfo]) -> State:
    """Pick from ``games`` and assert the batch confidence refresh never ran."""
    state = State()
    with (
        patch(
            f"{_PKG}._scanning_confidence._refresh_candidate_confidence_batch"
        ) as mock_refresh_batch,
        pick_env(),
    ):
        pick_next_game(games, state, make_config())
    mock_refresh_batch.assert_not_called()
    return state
