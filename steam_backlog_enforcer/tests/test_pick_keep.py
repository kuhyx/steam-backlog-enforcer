"""``pick`` keeps the games already allowed; ``--replace`` and ``done`` swap.

Drives :func:`steam_backlog_enforcer.scanning.pick_next_game` end to end with
every filesystem, network and Steam effect patched out, and asserts on the
allowed set (``allowed_app_ids``), which is what the daemon, the hider, the
uninstall guard and the auto-installer all read.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._actions import active_manual_picks, allowed_app_ids
from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer._scanning_assign import _assign_chosen_game
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_ASSIGN = "steam_backlog_enforcer._scanning_assign"
_SCAN = "steam_backlog_enforcer.scanning"
_RELEASED = {"released_at": STARTED_AT}


def _game(app_id: int, name: str) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=10,
        unlocked_achievements=1,
        playtime_minutes=60,
        completionist_hours=5.0,
    )


OLD, NEW = _game(1, "Old"), _game(2, "New")


def _config() -> Config:
    return Config(steam_api_key="k", steam_id="i", max_manual_picks=2)


def _state_on(
    app_id: int = 1,
    name: str = "Old",
    *,
    manual_picks: list[dict[str, Any]] | None = None,
) -> State:
    state = State(manual_picks=manual_picks or [])
    state.current_app_id = app_id
    state.current_game_name = name
    state.current_assigned_at = STARTED_AT
    state.last_assigned_at[str(app_id)] = STARTED_AT
    return state


class _Effects:
    """Every side effect of an assignment, patched; the mocks for asserts."""

    def __init__(self, stack: ExitStack, *, installed: bool) -> None:
        def p(target: str, **kw: object) -> MagicMock:
            return stack.enter_context(patch(target, **cast("dict[str, Any]", kw)))

        p(f"{_SCAN}._collect_qualified_candidates", side_effect=lambda c: (c, 0, 0))
        p(
            f"{_ASSIGN}._pick_next_shortest_candidate",
            side_effect=lambda c: (c[0], 0, 0),
        )
        p(f"{_ASSIGN}._apply_cached_confidence_to_candidates")
        p(f"{_ASSIGN}._report_poll_confidence")
        p(f"{_ASSIGN}._echo")
        p(f"{_ASSIGN}.is_game_fully_installed", return_value=installed)
        self.uninstall = p(f"{_ASSIGN}.uninstall_other_games", return_value=0)
        self.install = p(f"{_ASSIGN}.install_game")
        stack.enter_context(patch.object(State, "save"))


@contextmanager
def _effects(*, installed: bool = True) -> Iterator[_Effects]:
    with ExitStack() as stack:
        yield _Effects(stack, installed=installed)


def _pick(
    state: State,
    prompter: FakePrompter,
    *,
    keep: bool = False,
    on_select: Callable[[GameInfo], bool] | None = None,
) -> _Effects:
    with _effects(installed=False) as effects, use_prompter(prompter):
        pick_next_game([OLD, NEW], state, _config(), keep=keep, on_select=on_select)
    return effects


class TestKeep:
    def test_old_game_stays_allowed_and_is_not_uninstalled(self) -> None:
        state = _state_on()
        effects = _pick(state, FakePrompter(choices=["0"]), keep=True)
        assert state.current_app_id == 2
        assert allowed_app_ids(state) == {1, 2}
        effects.uninstall.assert_called_once_with({1, 2})
        effects.install.assert_called_once_with(2, "New", "i", use_steam_protocol=True)

    def test_kept_game_is_a_released_pick_holding_no_lock(self) -> None:
        state = _state_on()
        _pick(state, FakePrompter(choices=["0"]), keep=True)
        [kept] = state.manual_picks
        assert kept["app_id"] == 1
        assert kept["game_name"] == "Old"
        assert kept["started_at"] == STARTED_AT
        assert kept["released_at"]
        assert active_manual_picks(state) == []
        assert state.finished_app_ids == []
        assert state.released_at == {}

    def test_allowed_games_are_not_offered(self) -> None:
        state = _state_on()
        prompter = FakePrompter(choices=["0"])
        _pick(state, prompter, keep=True)
        assert prompter.asked[0][1] == ["0", "own"]

    def test_own_pick_search_excludes_allowed_games(self) -> None:
        state = _state_on()
        with patch(f"{_ASSIGN}.prompt_own_pick", return_value=NEW) as own:
            _pick(state, FakePrompter(choices=["own"]), keep=True)
        assert [g.app_id for g in own.call_args.args[0]] == [2]

    def test_pick_manual_then_pick_does_not_duplicate_the_active_pick(self) -> None:
        state = _state_on(
            manual_picks=[{"app_id": 1, "game_name": "Old", "started_at": STARTED_AT}]
        )
        _pick(state, FakePrompter(choices=["0"]), keep=True)
        assert state.manual_picks == [
            {"app_id": 1, "game_name": "Old", "started_at": STARTED_AT}
        ]
        assert [p["app_id"] for p in active_manual_picks(state)] == [1]
        assert allowed_app_ids(state) == {1, 2}

    def test_released_entry_for_the_current_game_is_not_duplicated(self) -> None:
        entry = {"app_id": 1, "game_name": "Old", "started_at": STARTED_AT}
        state = _state_on(manual_picks=[entry | _RELEASED])
        _pick(state, FakePrompter(choices=["0"]), keep=True)
        assert [p["app_id"] for p in state.manual_picks] == [1]

    def test_earlier_kept_games_survive_another_keep(self) -> None:
        entry = {"app_id": 9, "game_name": "Kept", "started_at": STARTED_AT}
        state = _state_on(manual_picks=[entry | _RELEASED])
        effects = _pick(state, FakePrompter(choices=["0"]), keep=True)
        assert allowed_app_ids(state) == {1, 2, 9}
        effects.uninstall.assert_called_once_with({1, 2, 9})

    def test_choosing_an_allowed_game_changes_nothing(self) -> None:
        state = _state_on()
        with _effects() as effects:
            _assign_chosen_game(OLD, [OLD, NEW], state, _config(), keep=True)
        assert state.manual_picks == []
        assert state.current_app_id == 1
        effects.uninstall.assert_not_called()


class TestReplace:
    def test_replace_drops_old_and_released_games(self) -> None:
        entry = {"app_id": 9, "game_name": "Kept", "started_at": STARTED_AT}
        state = _state_on(manual_picks=[entry | _RELEASED])
        effects = _pick(state, FakePrompter(choices=["0"]))
        assert state.current_app_id == 2
        assert allowed_app_ids(state) == {2}
        effects.uninstall.assert_called_once_with({2})

    def test_done_path_still_replaces(self) -> None:
        """``done``/``check`` reach the sequential picker; it never keeps."""
        state = _state_on()
        state.skip_for_days(1, 7)
        effects = _pick(state, FakePrompter(), on_select=lambda _g: True)
        assert state.current_app_id == 2
        assert state.manual_picks == []
        effects.uninstall.assert_called_once_with({2})
