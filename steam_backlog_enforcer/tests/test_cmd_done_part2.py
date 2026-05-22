"""Tests for _cmd_done module (part 2)."""

from __future__ import annotations

from unittest.mock import patch

from python_pkg.steam_backlog_enforcer._cmd_done import (
    _should_reassign_candidate,
    _try_reassign_shorter_game,
)
from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "python_pkg.steam_backlog_enforcer._cmd_done"


def _snap(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "app_id": 1,
        "name": "G",
        "total_achievements": 10,
        "unlocked_achievements": 0,
        "playtime_minutes": 60,
        "completionist_hours": -1,
        "comp_100_count": 3,
        "count_comp": 15,
    }
    snapshot["app_id"] = overrides.get("app_id", 1)
    snapshot.update(overrides)
    return snapshot


class TestTryReassignShorterGame2:
    """Tests for _try_reassign_shorter_game (continued)."""

    def test_reassigns_when_current_hours_unknown(self) -> None:
        """If current game has unknown hours, allow a confident replacement."""
        snap = [
            _snap(app_id=1, name="Current", unlocked_achievements=5),
            _snap(
                app_id=2, name="Known", unlocked_achievements=5, completionist_hours=9.0
            ),
        ]
        state = State(current_app_id=2, current_game_name="Known")
        known_game = GameInfo(
            app_id=2,
            name="Known",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=9.0,
            comp_100_count=3,
            count_comp=15,
        )
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(known_game, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.hide_other_games"),
        ):
            result = _try_reassign_shorter_game(
                {2: 9.0},
                1,
                -1.0,
                state,
                Config(),
            )

        assert result

    def test_try_reassign_returns_false_when_playable_not_shorter(self) -> None:
        """_try_reassign_shorter_game should not reassign to longer candidates."""
        snap = [
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=8.0,
                comp_100_count=10,
                count_comp=40,
            ),
            _snap(
                app_id=2,
                name="Longer",
                unlocked_achievements=5,
                completionist_hours=12.0,
                comp_100_count=10,
                count_comp=40,
            ),
        ]
        longer = GameInfo(
            app_id=2,
            name="Longer",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=12.0,
            comp_100_count=10,
            count_comp=40,
        )

        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_polls_cache",
                return_value={1: 10, 2: 10},
            ),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_count_comp_cache",
                return_value={1: 40, 2: 40},
            ),
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(longer, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick_next,
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                hltb_cache={1: 8.0, 2: 12.0},
                app_id=1,
                hours=8.0,
                state=State(),
                config=Config(),
            )

        assert not result
        mock_pick_next.assert_not_called()

    def test_try_reassign_stops_when_should_reassign_is_false(self) -> None:
        """Covers early return when policy says not to reassign."""
        snap = [
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=8.0,
                comp_100_count=10,
                count_comp=40,
            ),
            _snap(
                app_id=2,
                name="Candidate",
                unlocked_achievements=5,
                completionist_hours=6.0,
                comp_100_count=10,
                count_comp=40,
            ),
        ]
        candidate = GameInfo(
            app_id=2,
            name="Candidate",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=6.0,
            comp_100_count=10,
            count_comp=40,
        )

        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_polls_cache",
                return_value={1: 10, 2: 10},
            ),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_count_comp_cache",
                return_value={1: 40, 2: 40},
            ),
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(candidate, 0, 0),
            ),
            patch(
                f"{CMD_DONE_PKG}._should_reassign_candidate",
                return_value=False,
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game") as mock_pick_next,
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                hltb_cache={1: 8.0, 2: 6.0},
                app_id=1,
                hours=8.0,
                state=State(),
                config=Config(),
            )

        assert not result
        mock_pick_next.assert_not_called()


class TestShouldReassignCandidate:
    """Tests for _should_reassign_candidate."""

    def test_returns_false_when_candidate_not_shorter(self) -> None:
        candidate = GameInfo(
            app_id=2,
            name="Candidate",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=9.0,
            comp_100_count=3,
            count_comp=15,
        )
        should = _should_reassign_candidate(
            candidate,
            8.0,
            force_reassign=False,
        )
        assert should is False
