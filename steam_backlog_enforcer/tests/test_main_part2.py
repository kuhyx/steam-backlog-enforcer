"""Tests for main CLI module — part 2 (missing coverage)."""

from unittest.mock import (
    patch,
)

from steam_backlog_enforcer._cmd_done_finalize import _finalize_completion
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_helpers import done_game, snap
from steam_backlog_enforcer.tests._main_patches import (
    HIDER_ECHO,
    assign_next,
    library_hider,
)

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"
PKG = "steam_backlog_enforcer.main"


class TestFinalizeCompletion:
    """_finalize_completion records the finish and moves on to the next game."""

    def test_with_snapshot_and_hiding(self) -> None:
        """With a snapshot the finished game is recorded and the next one picked."""
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            library_hider([1, 2, 3], (2, None)),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            mock_pick.side_effect = assign_next(2, "NewGame")
            _finalize_completion(config, state, done_game(1, "G"))
        assert 1 in state.finished_app_ids

    def test_hide_skipped_when_steam_unreachable(self) -> None:
        """An undrivable Steam skips hiding with a note instead of aborting."""
        # Reconciliation is best-effort: an undrivable Steam must not abort
        # the completion flow.
        config = Config(steam_api_key="k", steam_id="i")
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
            patch(HIDER_ECHO, mock_echo),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            library_hider([1, 2, 3], (0, "update in progress")),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=True),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            mock_pick.side_effect = assign_next(2, "NewGame")
            _finalize_completion(config, state, done_game(1, "G"))
        assert "skipped (update in progress)" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

    def test_no_snapshot(self) -> None:
        """Without a snapshot the current game is kept."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=None),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, done_game(1, "G"))
        # No replacement was chosen, so the released game stays assigned.
        assert state.current_app_id == 1

    def test_no_next_game(self) -> None:
        """Completion survives when no next game is picked."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [snap(1, "G", 10, 10)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            patch.object(State, "save"),
        ):
            mock_pick.side_effect = assign_next(None)
            _finalize_completion(config, state, done_game(1, "G"))

    def test_no_owned_ids(self) -> None:
        """Completion survives an empty owned-games list."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            library_hider([]),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            mock_pick.side_effect = assign_next(2, "Next")
            _finalize_completion(config, state, done_game(1, "G"))

    def test_hide_returns_zero(self) -> None:
        """Completion survives when nothing new needs hiding."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [snap(2, "Next", 10, 0)]
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick,
            library_hider([1, 2], (0, None)),
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            mock_pick.side_effect = assign_next(2, "Next")
            _finalize_completion(config, state, done_game(1, "G"))
