"""Tests for finalize_completion: snapshot refresh and install retry."""

from typing import TYPE_CHECKING
from unittest.mock import (
    patch,
)

from steam_backlog_enforcer._cmd_done_finalize import _finalize_completion
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_helpers import done_game, snap
from steam_backlog_enforcer.tests._main_patches import assign_next, library_hider

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"
# _refresh_uncached_shortlist_hours stayed in _cmd_done, so its
# fetch_hltb_times_cached resolves there, not in the finalize module.
_CMD_DONE = "steam_backlog_enforcer._cmd_done"
PKG = "steam_backlog_enforcer.main"


class TestFinalizeCompletionRetries:
    """Finalizing a completion refreshes hours and retries a dropped install."""

    def test_refreshes_snapshot_hours_before_pick(self) -> None:
        """Ensure stale snapshot hours are replaced before picking next game."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snapshot = [
            snap(2, "A Space for the Unbound", 10, 0, 0.56),
            snap(3, "Lacuna", 10, 0, 1.2),
        ]
        seen: dict[int, float] = {}

        def capture_pick(
            games: list[GameInfo],
            s: State,
            _c: object,
            **_kwargs: object,
        ) -> None:
            for game in games:
                seen[game.app_id] = game.completionist_hours
            # Force early return path after pick_next_game.
            s.current_app_id = None

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={2: 20.05}),
            patch(
                f"{_CMD_DONE}.fetch_hltb_times_cached",
                return_value={3: 18.81},
            ) as mock_fetch_hltb,
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=capture_pick),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, done_game(1, "G"))

        assert seen[2] == 20.05
        assert seen[3] == 18.81
        mock_fetch_hltb.assert_called_once_with([(3, "Lacuna")])

    def test_retriggers_install_after_library_hide_if_still_missing(self) -> None:
        """Re-trigger install after hide step in case Steam restart drops it."""
        config = Config(steam_id="sid")
        state = State(current_app_id=1, current_game_name="DoneGame")
        snapshot = [snap(2, "Next", 10, 0, 5.0)]

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=assign_next(2, "Next")),
            library_hider([1, 2], (1, None)),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=False),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, done_game(1, "DoneGame"))

        mock_install.assert_called_once_with(2, "Next", "sid", use_steam_protocol=True)

    def test_skips_install_retry_when_assigned_game_already_installed(self) -> None:
        """Do not re-trigger install when assigned game is already present."""
        config = Config(steam_id="sid")
        state = State(current_app_id=1, current_game_name="DoneGame")
        snapshot = [snap(2, "Next", 10, 0, 5.0)]

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=assign_next(2, "Next")),
            library_hider([1, 2], (1, None)),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=True),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, done_game(1, "DoneGame"))

        mock_install.assert_not_called()
