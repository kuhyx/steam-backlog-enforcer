"""``pick-manual`` keeps the games already allowed, under the ``pick`` cap.

Covers the shared core (:func:`apply_manual_pick`), the CLI
(``cmd_pick_manual``) and the MCP ``pick_manual`` tool. Every Steam,
filesystem and network effect is patched out.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _mcp_actions as mcp_actions
from steam_backlog_enforcer._actions import allowed_app_ids, apply_manual_pick
from steam_backlog_enforcer._allowed_games import active_manual_picks
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import cmd_pick_manual
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT

PKG = "steam_backlog_enforcer.main.picks"


def _kept(app_id: int, name: str) -> dict[str, str | int]:
    return {
        "app_id": app_id,
        "game_name": name,
        "started_at": STARTED_AT,
        "released_at": STARTED_AT,
    }


def _state(*kept: tuple[int, str], current: tuple[int, str] = (1, "Current")) -> State:
    """An auto assignment (not a stored pick) plus released, kept games."""
    return State(
        current_app_id=current[0],
        current_game_name=current[1],
        current_assigned_at=STARTED_AT,
        manual_picks=[_kept(a, n) for a, n in kept],
    )


def _entries(state: State, app_id: int) -> list[dict[str, object]]:
    return [p for p in state.manual_picks if p.get("app_id") == app_id]


class TestApplyManualPickKeeps:
    def test_kept_games_and_outgoing_assignment_stay_allowed(self) -> None:
        state = _state((2, "KeptA"))
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 5, "New", max_picks=2) is None
        assert allowed_app_ids(state) == {1, 2, 5}
        assert [p["app_id"] for p in active_manual_picks(state)] == [5]
        assert state.current_app_id == 5

    def test_over_cap_is_refused_naming_the_games(self) -> None:
        state = _state((2, "KeptA"), (3, "KeptB"))
        with patch.object(State, "save") as save:
            refused = apply_manual_pick(state, 5, "New", max_picks=2)
        assert refused is not None
        for name in ("Current (AppID=1)", "KeptA (AppID=2)", "KeptB (AppID=3)"):
            assert name in refused
        assert "abandon-pick 2" in refused
        assert "--replace" not in refused
        save.assert_not_called()
        assert state.current_app_id == 1
        assert [p["app_id"] for p in state.manual_picks] == [2, 3]

    def test_repicking_a_kept_game_activates_it_without_duplicating(self) -> None:
        # At the cap, but re-picking a game already allowed adds nothing.
        state = _state((2, "KeptA"), (3, "KeptB"))
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 2, "KeptA", max_picks=2) is None
        assert len(_entries(state, 2)) == 1
        assert "released_at" not in _entries(state, 2)[0]
        assert [p["app_id"] for p in active_manual_picks(state)] == [2]
        assert allowed_app_ids(state) == {1, 2, 3}

    def test_repicking_the_kept_current_game_does_not_duplicate(self) -> None:
        state = _state((2, "KeptA"), current=(2, "KeptA"))
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 2, "KeptA", max_picks=2) is None
        assert len(state.manual_picks) == 1
        assert active_manual_picks(state) == state.manual_picks

    def test_finished_pick_is_kept_too(self) -> None:
        state = _state((2, "Done"))
        state.finished_app_ids = [2]
        with patch.object(State, "save"):
            assert apply_manual_pick(state, 5, "New", max_picks=2) is None
        assert 2 in allowed_app_ids(state)


def _cli_effects(stack: ExitStack, *, confirm: bool = True) -> dict[str, MagicMock]:
    mocks = {
        "echo": stack.enter_context(patch(f"{PKG}._echo")),
        "confirm": stack.enter_context(
            patch(f"{PKG}.confirm_phrase", return_value=confirm)
        ),
        "uninstall": stack.enter_context(
            patch(f"{PKG}.uninstall_other_games", return_value=0)
        ),
    }
    stack.enter_context(patch(f"{PKG}.report_completion", return_value=[]))
    stack.enter_context(patch(f"{PKG}._resolve_game_name", return_value="New"))
    stack.enter_context(patch.object(State, "save"))
    stack.enter_context(patch(f"{PKG}.is_game_fully_installed", return_value=True))
    stack.enter_context(
        patch(
            "steam_backlog_enforcer.library_hider.get_all_owned_app_ids",
            return_value=[],
        )
    )
    return mocks


def _output(mock_echo: MagicMock) -> str:
    return " ".join(str(c) for c in mock_echo.call_args_list)


class TestCmdPickManualKeeps:
    def test_kept_games_are_not_uninstalled(self) -> None:
        state = _state((2, "KeptA"))
        with ExitStack() as stack:
            mocks = _cli_effects(stack)
            cmd_pick_manual(Config(max_manual_picks=2), state, ["5"])
        mocks["uninstall"].assert_called_once_with({1, 2, 5})
        output = _output(mocks["echo"])
        assert "Replace" not in output
        assert "stay installed" in output
        assert "KeptA" in output

    def test_over_cap_is_refused_before_the_confirmation(self) -> None:
        state = _state((2, "KeptA"), (3, "KeptB"))
        with ExitStack() as stack:
            mocks = _cli_effects(stack)
            with pytest.raises(SystemExit) as exc:
                cmd_pick_manual(Config(max_manual_picks=2), state, ["5"])
        assert exc.value.code == 1
        mocks["confirm"].assert_not_called()
        mocks["uninstall"].assert_not_called()
        output = _output(mocks["echo"])
        for name in ("Current (AppID=1)", "KeptA (AppID=2)", "KeptB (AppID=3)"):
            assert name in output
        assert "abandon-pick 3" in output


class TestMcpPickManualKeeps:
    def _run(self, state: State) -> dict[str, object]:
        with (
            patch(
                "steam_backlog_enforcer._snapshot.load_snapshot",
                return_value=[{"app_id": 5, "name": "New"}],
            ),
            patch.object(Config, "load", return_value=Config()),
            patch.object(State, "load", return_value=state),
            patch.object(State, "save"),
            patch.object(mcp_actions, "retire_completed_manual_picks", return_value=[]),
            patch(f"{PKG}.uninstall_other_games") as uninstall,
        ):
            out = mcp_actions.pick_manual(5, confirm=True)
        uninstall.assert_not_called()
        return out

    def test_kept_game_survives(self) -> None:
        state = _state((2, "KeptA"))
        assert self._run(state)["ok"] is True
        assert allowed_app_ids(state) == {1, 2, 5}

    def test_over_cap_is_refused(self) -> None:
        state = _state((2, "KeptA"), (3, "KeptB"))
        out = self._run(state)
        assert out["ok"] is False
        assert "KeptB (AppID=3)" in str(out["reason"])
        assert allowed_app_ids(state) == {1, 2, 3}
