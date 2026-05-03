"""Tests for _cmd_done module."""

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


class TestTryReassignShorterGame:
    """Tests for _try_reassign_shorter_game."""

    def test_no_snapshot(self) -> None:
        with patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=None):
            assert not _try_reassign_shorter_game({}, 1, 10.0, State(), Config())

    def test_no_shorter_candidate(self) -> None:
        snap = [
            _snap(
                app_id=1, name="G", unlocked_achievements=5, completionist_hours=10.0
            ),
            _snap(app_id=2, name="H", unlocked_achievements=5),
        ]
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
            _snap(
                app_id=1,
                name="Long",
                unlocked_achievements=5,
                completionist_hours=100.0,
            ),
            _snap(
                app_id=2, name="Short", unlocked_achievements=5, completionist_hours=5.0
            ),
        ]
        state = State(current_app_id=2, current_game_name="Short")
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
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(short_game, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(
                f"{CMD_DONE_PKG}.get_all_owned_app_ids",
                return_value=[1, 2, 3],
            ),
            patch(f"{CMD_DONE_PKG}.hide_other_games", return_value=5) as mock_hide,
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                state,
                Config(),
            )
            assert result
            mock_hide.assert_called_once_with([1, 2, 3], 2)

    def test_reassigns_no_hide_when_no_owned_ids(self) -> None:
        snap = [
            _snap(
                app_id=1,
                name="Long",
                unlocked_achievements=5,
                completionist_hours=100.0,
            ),
            _snap(
                app_id=2, name="Short", unlocked_achievements=5, completionist_hours=5.0
            ),
        ]
        state = State(current_app_id=2, current_game_name="Short")
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
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(short_game, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{CMD_DONE_PKG}.hide_other_games", return_value=0),
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                state,
                Config(),
            )
            assert result
            # hidden == 0, so "hid N games" should NOT be echoed
            for call in mock_echo.call_args_list:
                assert "hid" not in str(call)

    def test_reassigns_skip_hide_when_no_app_assigned(self) -> None:
        snap = [
            _snap(
                app_id=1,
                name="Long",
                unlocked_achievements=5,
                completionist_hours=100.0,
            ),
            _snap(
                app_id=2, name="Short", unlocked_achievements=5, completionist_hours=5.0
            ),
        ]
        state = State(current_app_id=None, current_game_name="")
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
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(short_game, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids") as mock_owned,
            patch(f"{CMD_DONE_PKG}.hide_other_games") as mock_hide,
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                state,
                Config(),
            )
            assert result
            mock_owned.assert_not_called()
            mock_hide.assert_not_called()

    def test_playable_none(self) -> None:
        snap = [
            _snap(
                app_id=1,
                name="Long",
                unlocked_achievements=5,
                completionist_hours=100.0,
            ),
            _snap(
                app_id=2, name="Short", unlocked_achievements=5, completionist_hours=5.0
            ),
        ]
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(None, 0, 0),
            ),
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
            _snap(
                app_id=1,
                name="Short",
                unlocked_achievements=5,
                completionist_hours=10.0,
            ),
            _snap(
                app_id=2,
                name="Long",
                unlocked_achievements=5,
                completionist_hours=200.0,
            ),
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
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(long_game, 0, 0),
            ),
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
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=20.1,
            ),
            _snap(app_id=2, name="Lacuna", completionist_hours=0.9),
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
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(refreshed_short, 0, 0),
            ) as mock_pick_candidate,
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.hide_other_games"),
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
        mock_pick_candidate.assert_called_once()

    def test_reassigns_when_current_confidence_too_low(self) -> None:
        """If current game fails confidence thresholds, reassign anyway."""
        snap = [
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=20.0,
                comp_100_count=0,
                count_comp=0,
            ),
            _snap(
                app_id=2,
                name="Confident",
                unlocked_achievements=5,
                completionist_hours=25.0,
            ),
        ]
        state = State(current_app_id=2, current_game_name="Confident")
        confident_game = GameInfo(
            app_id=2,
            name="Confident",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=25.0,
            comp_100_count=3,
            count_comp=15,
        )
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(confident_game, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}.pick_next_game"),
            patch(f"{CMD_DONE_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{CMD_DONE_PKG}.hide_other_games"),
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
        ):
            result = _try_reassign_shorter_game(
                {1: 20.0, 2: 25.0},
                1,
                20.0,
                state,
                Config(),
            )

        assert result
        assert any(
            "confidence too low" in str(call).lower()
            for call in mock_echo.call_args_list
        )

    def test_does_not_force_refresh_current_when_cached_confidence_is_good(
        self,
    ) -> None:
        """Current-game confidence check should use cache-backed values first."""
        snap = [
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=20.0,
                comp_100_count=0,
                count_comp=0,
            ),
            _snap(
                app_id=2,
                name="Shorter",
                unlocked_achievements=5,
                completionist_hours=5.0,
                comp_100_count=3,
                count_comp=15,
            ),
        ]
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.load_hltb_polls_cache", return_value={1: 36, 2: 20}),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_count_comp_cache",
                return_value={1: 200, 2: 50},
            ),
            patch(f"{CMD_DONE_PKG}._refresh_candidate_confidence") as mock_refresh,
            patch(
                f"{CMD_DONE_PKG}._pick_next_shortest_candidate",
                return_value=(None, 0, 0),
            ),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 20.0, 2: 5.0},
                1,
                20.0,
                State(),
                Config(),
            )

        assert not result
        mock_refresh.assert_not_called()

    def test_only_checks_strictly_shorter_candidates_when_not_forced(self) -> None:
        """No confidence checks should run for non-shorter games."""
        snap = [
            _snap(
                app_id=1,
                name="Current",
                unlocked_achievements=5,
                completionist_hours=4.0,
                comp_100_count=10,
                count_comp=40,
            ),
            _snap(
                app_id=2,
                name="TooLong",
                unlocked_achievements=5,
                completionist_hours=8.0,
                comp_100_count=1,
                count_comp=8,
            ),
        ]
        with (
            patch(f"{CMD_DONE_PKG}.load_snapshot", return_value=snap),
            patch(f"{CMD_DONE_PKG}.load_hltb_polls_cache", return_value={1: 10, 2: 1}),
            patch(
                f"{CMD_DONE_PKG}.load_hltb_count_comp_cache", return_value={1: 40, 2: 8}
            ),
            patch(f"{CMD_DONE_PKG}._pick_next_shortest_candidate") as mock_pick,
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 4.0, 2: 8.0},
                1,
                4.0,
                State(),
                Config(),
            )

        assert not result
        mock_pick.assert_not_called()

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
