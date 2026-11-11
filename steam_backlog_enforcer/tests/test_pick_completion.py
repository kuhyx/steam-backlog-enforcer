"""Tests for achievement-based release of manual picks."""

from unittest.mock import patch

from steam_backlog_enforcer._pick_completion import (
    PickProgress,
    retire_completed_manual_picks,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_helpers import locked_state, two_pick_state
from steam_backlog_enforcer.tests._pick_completion_helpers import (
    client_returning,
    game,
)

PKG = "steam_backlog_enforcer._pick_completion"


class TestPickProgressDescribe:
    """describe() renders each pick state as one status line."""

    def test_undeterminable(self) -> None:
        """A pick with unreadable achievements says progress is unavailable."""
        line = PickProgress(1, "G", 0, 0, retired=False, determinable=False).describe()
        assert "progress unavailable" in line

    def test_retired_at_100(self) -> None:
        """A pick retired at 100% says complete and still playable."""
        line = PickProgress(1, "G", 5, 5, retired=True, determinable=True).describe()
        assert "COMPLETE, slot freed, stays playable" in line

    def test_released_by_new_achievement(self) -> None:
        """A pick released by a new unlock names that achievement."""
        line = PickProgress(
            1, "G", 2, 5, retired=True, determinable=True, new_achievement="Win"
        ).describe()
        assert "2/5 (40%) - earned 'Win', slot freed, stays playable" in line

    def test_in_progress(self) -> None:
        """An unreleased pick shows its ratio and waits for an unlock."""
        line = PickProgress(1, "G", 1, 4, retired=False, determinable=True).describe()
        assert "1/4 (25%) - no new achievement since it was picked yet" in line

    def test_in_progress_with_zero_total(self) -> None:
        """A determinable pick with zero achievements shows 0% safely."""
        # Defensive: determinable but no achievements must not divide by zero.
        line = PickProgress(1, "G", 0, 0, retired=False, determinable=True).describe()
        assert "(0%)" in line


class TestRetireCompletedManualPicks:
    """Manual picks are released on completion or a new unlock only."""

    def test_no_picks_makes_no_api_call(self) -> None:
        """No manual picks means no Steam query."""
        fake = client_returning()
        assert retire_completed_manual_picks(Config(), State(), client=fake) == []
        fake.refresh_single_game.assert_not_called()

    def test_complete_pick_is_retired_and_saved(self) -> None:
        """A 100% pick is finished, retired and saved."""
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(game(100, 5, 5))
            )
        assert [r.retired for r in results] == [True]
        assert state.finished_app_ids == [100]
        mock_save.assert_called_once()

    def test_new_achievement_releases_without_finishing(self) -> None:
        """A new unlock releases the slot but does not finish the game."""
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(game(100, 1, 5, new=True))
            )
        assert [(r.retired, r.new_achievement) for r in results] == [(True, "Ach0")]
        assert state.finished_app_ids == []
        assert state.manual_picks[0]["released_at"]
        assert 100 in state.active_skipped_ids()
        mock_save.assert_called_once()

    def test_incomplete_pick_is_left_alone(self) -> None:
        """A pick without a new unlock stays locked and unsaved."""
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(game(100, 1, 5))
            )
        assert [r.retired for r in results] == [False]
        assert state.finished_app_ids == []
        mock_save.assert_not_called()

    def test_unreadable_pick_stays_locked(self) -> None:
        """A pick whose progress cannot be read stays locked."""
        # No achievements at all, or Steam unreachable: both surface as None.
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(None)
            )
        assert results == [
            PickProgress(100, "TestGame", 0, 0, retired=False, determinable=False)
        ]
        assert state.finished_app_ids == []
        mock_save.assert_not_called()

    def test_reports_every_pick_not_only_retirements(self) -> None:
        """Every pick gets a result, retired or not."""
        state = two_pick_state()
        with patch.object(State, "save"):
            results = retire_completed_manual_picks(
                Config(),
                state,
                client=client_returning(game(100, 1, 5), game(200, 5, 5)),
            )
        assert [(r.app_id, r.retired) for r in results] == [(100, False), (200, True)]

    def test_pick_without_app_id_is_skipped(self) -> None:
        """A malformed pick with no app id is skipped without a query."""
        state = State(manual_picks=[{"game_name": "Broken", "started_at": ""}])
        fake = client_returning()
        assert retire_completed_manual_picks(Config(), state, client=fake) == []
        fake.refresh_single_game.assert_not_called()

    def test_unnamed_pick_falls_back_to_app_id(self) -> None:
        """A pick with no name is labelled by its app id."""
        state = State(manual_picks=[{"app_id": 100, "game_name": "", "started_at": ""}])
        results = retire_completed_manual_picks(
            Config(), state, client=client_returning(game(100, 1, 5))
        )
        assert results[0].game_name == "AppID=100"

    def test_builds_its_own_client_when_none_given(self) -> None:
        """Without a client one is built from the config credentials."""
        state = locked_state(app_id=100)
        fake = client_returning(game(100, 1, 5))
        with patch(f"{PKG}.SteamAPIClient", return_value=fake) as mock_cls:
            retire_completed_manual_picks(
                Config(steam_api_key="k", steam_id="i"), state
            )
        mock_cls.assert_called_once_with("k", "i")
