"""Shared patch bundles for the ``main`` CLI test modules.

The pick, pick-manual and done tests all stub the same library-hider calls
and the same confirmed-pick prompt; keeping the bundles here stops each
module from carrying its own copy of the ``with`` block.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import State

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

OWNED_IDS = "steam_backlog_enforcer.library_hider.get_all_owned_app_ids"
HIDE_OTHERS = "steam_backlog_enforcer.library_hider.try_hide_other_games"
# The hide-skip line is printed by the shared hide helper, not the command.
HIDER_ECHO = "steam_backlog_enforcer.library_hider._echo"
PICKS_PKG = "steam_backlog_enforcer.main.picks"


@contextmanager
def library_hider(
    owned: Sequence[int],
    hide: tuple[int, str | None] | None = None,
) -> Iterator[MagicMock | None]:
    """Patch the owned-ids lookup and, when ``hide`` is given, the hide call.

    Args:
        owned: App ids the owned-games lookup returns.
        hide: Return value for ``try_hide_other_games``; None leaves it real.

    Yields:
        The ``try_hide_other_games`` mock, or None when it was not patched.
    """
    with ExitStack() as stack:
        stack.enter_context(patch(OWNED_IDS, return_value=list(owned)))
        hide_mock = None
        if hide is not None:
            hide_mock = stack.enter_context(patch(HIDE_OTHERS, return_value=hide))
        yield hide_mock


def assign_next(app_id: int | None, name: str = "") -> Callable[..., None]:
    """Build a ``pick_next_game`` side effect that assigns one game.

    Args:
        app_id: App id to assign (None clears the assignment).
        name: Game name to assign; empty leaves the name untouched.

    Returns:
        A callable with ``pick_next_game``'s signature.
    """

    def _assign(_games: object, s: State, _c: object, **_kwargs: object) -> None:
        s.current_app_id = app_id
        if name:
            s.current_game_name = name

    return _assign


@contextmanager
def confirmed_pick(
    *,
    owned: Sequence[int] = (),
    installed: bool = True,
    uninstall: int | None = 0,
    answers: Sequence[str] = ("lock in Skyrim SE",),
) -> Iterator[dict[str, Any]]:
    """Patch everything a confirmed ``pick-manual`` of Skyrim SE touches.

    Args:
        owned: App ids the owned-games lookup returns.
        installed: What ``is_game_fully_installed`` reports.
        uninstall: ``uninstall_other_games`` return; None keeps a bare mock.
        answers: Successive ``input()`` answers (one means a fixed answer).

    Yields:
        The mocks by name: echo, save, uninstall.
    """
    uninstall_kwargs = {} if uninstall is None else {"return_value": uninstall}
    input_kwargs: dict[str, Any] = (
        {"return_value": answers[0]}
        if len(answers) == 1
        else {"side_effect": list(answers)}
    )
    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch(f"{PICKS_PKG}._resolve_game_name", return_value="Skyrim SE"))
        mocks = {"echo": enter(patch(f"{PICKS_PKG}._echo"))}
        enter(patch("builtins.input", **input_kwargs))
        mocks["save"] = enter(patch.object(State, "save"))
        mocks["uninstall"] = enter(
            patch(f"{PICKS_PKG}.uninstall_other_games", **uninstall_kwargs)
        )
        enter(patch(f"{PICKS_PKG}.is_game_fully_installed", return_value=installed))
        enter(patch(OWNED_IDS, return_value=list(owned)))
        yield mocks
