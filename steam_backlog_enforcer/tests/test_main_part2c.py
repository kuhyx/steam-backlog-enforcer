"""Tests for finalize_completion: snapshot refresh and install retry."""

from typing import Any
from unittest.mock import (
    patch,
)

from steam_backlog_enforcer._cmd_done import (
    _finalize_completion,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"
# _refresh_uncached_shortlist_hours stayed in _cmd_done, so its
# fetch_hltb_times_cached resolves there, not in the finalize module.
_CMD_DONE = "steam_backlog_enforcer._cmd_done"
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


class TestFinalizeCompletionRetries:
    def test_refreshes_snapshot_hours_before_pick(self) -> None:
        """Ensure stale snapshot hours are replaced before picking next game."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        snap = [
            _snap(2, "A Space for the Unbound", 10, 0, 0.56),
            _snap(3, "Lacuna", 10, 0, 1.2),
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
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={2: 20.05}),
            patch(
                f"{_CMD_DONE}.fetch_hltb_times_cached",
                return_value={3: 18.81},
            ) as mock_fetch_hltb,
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=capture_pick),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "G", 1)

        assert seen[2] == 20.05
        assert seen[3] == 18.81
        mock_fetch_hltb.assert_called_once_with([(3, "Lacuna")])

    def test_retriggers_install_after_library_hide_if_still_missing(self) -> None:
        """Re-trigger install after hide step in case Steam restart drops it."""
        config = Config(steam_id="sid")
        state = State(current_app_id=1, current_game_name="DoneGame")
        snap = [_snap(2, "Next", 10, 0, 5.0)]

        def set_next(
            _games: object,
            s: State,
            _c: object,
            **_kwargs: object,
        ) -> None:
            s.current_app_id = 2
            s.current_game_name = "Next"

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=set_next),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(1, None)),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=False),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "DoneGame", 1)

        mock_install.assert_called_once_with(2, "Next", "sid", use_steam_protocol=True)

    def test_skips_install_retry_when_assigned_game_already_installed(self) -> None:
        """Do not re-trigger install when assigned game is already present."""
        config = Config(steam_id="sid")
        state = State(current_app_id=1, current_game_name="DoneGame")
        snap = [_snap(2, "Next", 10, 0, 5.0)]

        def set_next(
            _games: object,
            s: State,
            _c: object,
            **_kwargs: object,
        ) -> None:
            s.current_app_id = 2
            s.current_game_name = "Next"

        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.pick_next_game", side_effect=set_next),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.try_hide_other_games", return_value=(1, None)),
            patch(f"{CMD_DONE_PKG}.is_game_installed", return_value=True),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
            patch(f"{CMD_DONE_PKG}.send_notification"),
            patch.object(State, "save"),
        ):
            _finalize_completion(config, state, "DoneGame", 1)

        mock_install.assert_not_called()
