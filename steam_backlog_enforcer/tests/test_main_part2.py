"""Tests for main CLI module — part 2 (missing coverage)."""

from typing import Any
from unittest.mock import (
    patch,
)

from steam_backlog_enforcer._cmd_done import (
    _finalize_completion,
)
from steam_backlog_enforcer.config import Config, State

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"
PKG = "steam_backlog_enforcer.main"


def _snap(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": 60,
        "completionist_hours": hours,
    }


class TestFinalizeCompletion:
    def test_with_snapshot_and_hiding(self) -> None:
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(2, None)),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_next(
                _games: object,
                s: State,
                _c: object,
                **_kwargs: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "NewGame"

            mock_pick.side_effect = set_next
            _finalize_completion(config, state, "G", 1)
        assert 1 in state.finished_app_ids

    def test_hide_skipped_when_steam_unreachable(self) -> None:
        # Reconciliation is best-effort: an undrivable Steam must not abort
        # the completion flow.
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(
                f"{CMD_DONE_PKG}.try_hide_other_games",
                return_value=(0, "update in progress"),
            ),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=True),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_next(
                _games: object,
                s: State,
                _c: object,
                **_kwargs: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "NewGame"

            mock_pick.side_effect = set_next
            _finalize_completion(config, state, "G", 1)
        assert "skipped (update in progress)" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

    def test_no_snapshot(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=None),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "G", 1)
        assert state.current_app_id is None

    def test_no_next_game(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(1, "G", 10, 10)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch.object(State, "save"),
        ):

            def set_none(
                _games: object,
                s: State,
                _c: object,
                **_kwargs: object,
            ) -> None:
                s.current_app_id = None

            mock_pick.side_effect = set_none
            _finalize_completion(config, state, "G", 1)

    def test_no_owned_ids(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_2(
                _games: object,
                s: State,
                _c: object,
                **_kwargs: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "Next"

            mock_pick.side_effect = set_2
            _finalize_completion(config, state, "G", 1)

    def test_hide_returns_zero(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [_snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(0, None)),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):

            def set_2(
                _games: object,
                s: State,
                _c: object,
                **_kwargs: object,
            ) -> None:
                s.current_app_id = 2
                s.current_game_name = "Next"

            mock_pick.side_effect = set_2
            _finalize_completion(config, state, "G", 1)
