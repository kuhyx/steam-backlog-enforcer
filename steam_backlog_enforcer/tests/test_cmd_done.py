"""Tests for _cmd_done module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from python_pkg.steam_backlog_enforcer._cmd_done import _try_reassign_shorter_game
from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "python_pkg.steam_backlog_enforcer._cmd_done"


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


class TestTryReassignShorterGame:
    """Tests for _try_reassign_shorter_game."""

    def test_no_snapshot(self) -> None:
        with patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=None):
            assert not _try_reassign_shorter_game({}, 1, 10.0, State(), Config())

    def test_no_shorter_candidate(self) -> None:
        snap = [_snap(1, "G", 10, 5, 10.0), _snap(2, "H", 10, 5, -1)]
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 10.0},
                1,
                10.0,
                State(),
                Config(),
            )
            assert not result

    def test_reassigns(self) -> None:
        snap = [
            _snap(1, "Long", 10, 5, 100.0),
            _snap(2, "Short", 10, 5, 5.0),
        ]
        state = State(current_app_id=1, current_game_name="Long")
        short_game = GameInfo(
            app_id=2,
            name="Short",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=5.0,
        )
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(
                f"{CMD_DONE_PKG}._pick_playable_candidate",
                return_value=short_game,
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                state,
                Config(),
            )
            assert result

    def test_playable_none(self) -> None:
        snap = [
            _snap(1, "Long", 10, 5, 100.0),
            _snap(2, "Short", 10, 5, 5.0),
        ]
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}._pick_playable_candidate", return_value=None),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                State(),
                Config(),
            )
            assert not result

    def test_playable_longer(self) -> None:
        """Playable candidate is longer than current — no reassign."""
        snap = [
            _snap(1, "Short", 10, 5, 10.0),
            _snap(2, "Long", 10, 5, 200.0),
        ]
        long_game = GameInfo(
            app_id=2,
            name="Long",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=200.0,
        )
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}._pick_playable_candidate", return_value=long_game),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 10.0, 2: 200.0},
                1,
                10.0,
                State(),
                Config(),
            )
            assert not result

    def test_refreshes_stale_shorter_snapshot_entry(self) -> None:
        """Uncached shorter snapshot candidates are refreshed before reassigning."""
        snap = [
            _snap(1, "Current", 10, 5, 20.1),
            _snap(2, "Lacuna", 10, 0, 0.9),
        ]
        state = State(current_app_id=1, current_game_name="Current")
        refreshed_short = GameInfo(
            app_id=2,
            name="Lacuna",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=60,
            completionist_hours=18.8,
        )
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}.fetch_hltb_times_cached",
                return_value={2: 18.8},
            ) as mock_fetch_hltb,
            patch(
                f"{CMD_DONE_PKG}._pick_playable_candidate",
                return_value=refreshed_short,
            ) as mock_pick_playable,
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 20.1},
                1,
                20.1,
                state,
                Config(),
            )

        assert result
        mock_fetch_hltb.assert_called_once_with([(2, "Lacuna")])
        mock_pick_playable.assert_called_once()
