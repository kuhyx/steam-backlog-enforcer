"""Tests for achievement-based retirement of finished manual picks."""

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._pick_completion import (
    MANUAL_PICK_RECHECK_TTL_SECONDS,
    PickProgress,
    _DaemonSweep,
    daemon_sweep,
    mark_finished,
    report_completion,
    retire_completed_manual_picks,
    retire_completed_manual_picks_throttled,
    warn_stale_assignment,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._main_helpers import locked_state, two_pick_state

PKG = "steam_backlog_enforcer._pick_completion"


def game(app_id: int, unlocked: int, total: int) -> GameInfo:
    """Build a GameInfo with the given achievement progress.

    Args:
        app_id: Steam application id.
        unlocked: Unlocked achievement count.
        total: Total achievement count.

    Returns:
        A GameInfo carrying that progress.
    """
    return GameInfo(
        app_id=app_id,
        name="G",
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=0,
    )


def client_returning(*games: GameInfo | None) -> MagicMock:
    """Build a fake SteamAPIClient yielding *games* in order.

    Args:
        games: What each ``refresh_single_game`` call should return.

    Returns:
        A MagicMock standing in for SteamAPIClient.
    """
    fake = MagicMock()
    fake.refresh_single_game.side_effect = list(games)
    return fake


class TestMarkFinished:
    def test_records_once(self) -> None:
        state = State()
        assert mark_finished(state, 7) is True
        assert state.finished_app_ids == [7]

    def test_does_not_duplicate(self) -> None:
        state = State(finished_app_ids=[7])
        assert mark_finished(state, 7) is False
        assert state.finished_app_ids == [7]


class TestPickProgressDescribe:
    def test_undeterminable(self) -> None:
        line = PickProgress(1, "G", 0, 0, retired=False, determinable=False).describe()
        assert "progress unavailable" in line

    def test_retired(self) -> None:
        line = PickProgress(1, "G", 5, 5, retired=True, determinable=True).describe()
        assert "COMPLETE, freeing its slot" in line

    def test_in_progress(self) -> None:
        line = PickProgress(1, "G", 1, 4, retired=False, determinable=True).describe()
        assert "1/4 (25%) - still in progress" in line

    def test_in_progress_with_zero_total(self) -> None:
        # Defensive: determinable but no achievements must not divide by zero.
        line = PickProgress(1, "G", 0, 0, retired=False, determinable=True).describe()
        assert "(0%)" in line


class TestRetireCompletedManualPicks:
    def test_no_picks_makes_no_api_call(self) -> None:
        fake = client_returning()
        assert retire_completed_manual_picks(Config(), State(), client=fake) == []
        fake.refresh_single_game.assert_not_called()

    def test_complete_pick_is_retired_and_saved(self) -> None:
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(game(100, 5, 5))
            )
        assert [r.retired for r in results] == [True]
        assert state.finished_app_ids == [100]
        mock_save.assert_called_once()

    def test_incomplete_pick_is_left_alone(self) -> None:
        state = locked_state(app_id=100)
        with patch.object(State, "save") as mock_save:
            results = retire_completed_manual_picks(
                Config(), state, client=client_returning(game(100, 1, 5))
            )
        assert [r.retired for r in results] == [False]
        assert state.finished_app_ids == []
        mock_save.assert_not_called()

    def test_unreadable_pick_stays_locked(self) -> None:
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
        state = two_pick_state()
        with patch.object(State, "save"):
            results = retire_completed_manual_picks(
                Config(),
                state,
                client=client_returning(game(100, 1, 5), game(200, 5, 5)),
            )
        assert [(r.app_id, r.retired) for r in results] == [(100, False), (200, True)]

    def test_pick_without_app_id_is_skipped(self) -> None:
        state = State(manual_picks=[{"game_name": "Broken", "started_at": ""}])
        fake = client_returning()
        assert retire_completed_manual_picks(Config(), state, client=fake) == []
        fake.refresh_single_game.assert_not_called()

    def test_unnamed_pick_falls_back_to_app_id(self) -> None:
        state = State(manual_picks=[{"app_id": 100, "game_name": "", "started_at": ""}])
        results = retire_completed_manual_picks(
            Config(), state, client=client_returning(game(100, 1, 5))
        )
        assert results[0].game_name == "AppID=100"

    def test_builds_its_own_client_when_none_given(self) -> None:
        state = locked_state(app_id=100)
        fake = client_returning(game(100, 1, 5))
        with patch(f"{PKG}.SteamAPIClient", return_value=fake) as mock_cls:
            retire_completed_manual_picks(
                Config(steam_api_key="k", steam_id="i"), state
            )
        mock_cls.assert_called_once_with("k", "i")


class TestReportCompletion:
    def test_prints_nothing_without_picks(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            assert report_completion(Config(), State()) == []
        mock_echo.assert_not_called()

    def test_prints_each_pick_and_returns_only_retirements(self) -> None:
        state = two_pick_state()
        with (
            patch.object(State, "save"),
            patch(
                f"{PKG}.SteamAPIClient",
                return_value=client_returning(game(100, 1, 5), game(200, 5, 5)),
            ),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            retired = report_completion(Config(), state)
        assert [r.app_id for r in retired] == [200]
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "still in progress" in output
        assert "COMPLETE, freeing its slot" in output


class TestWarnStaleAssignment:
    def test_warns_when_retired_pick_is_current(self) -> None:
        state = State(current_app_id=200, current_game_name="SecondGame")
        retired = [
            PickProgress(200, "SecondGame", 5, 5, retired=True, determinable=True)
        ]
        with patch(f"{PKG}._echo") as mock_echo:
            warn_stale_assignment(state, retired)
        assert "still" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_silent_when_current_is_something_else(self) -> None:
        state = State(current_app_id=999)
        retired = [PickProgress(200, "G", 5, 5, retired=True, determinable=True)]
        with patch(f"{PKG}._echo") as mock_echo:
            warn_stale_assignment(state, retired)
        mock_echo.assert_not_called()


class TestDaemonSweep:
    def test_due_then_throttled(self) -> None:
        sweep = _DaemonSweep()
        assert sweep.due(1000.0, 900.0) is True
        assert sweep.due(1100.0, 900.0) is False
        assert sweep.due(2000.0, 900.0) is True

    def test_throttled_call_records_retirements_without_evicting(self) -> None:
        state = locked_state(app_id=100)
        daemon_sweep.last = None
        daemon_sweep.retired.clear()
        try:
            with (
                patch.object(State, "save"),
                patch(
                    f"{PKG}.SteamAPIClient",
                    return_value=client_returning(game(100, 5, 5)),
                ),
            ):
                results = retire_completed_manual_picks_throttled(Config(), state)
                assert [r.retired for r in results] == [True]
                assert daemon_sweep.retired == {100}
                # Second call inside the TTL must not re-query Steam.
                assert retire_completed_manual_picks_throttled(Config(), state) == []
        finally:
            daemon_sweep.last = None
            daemon_sweep.retired.clear()

    def test_ttl_is_well_clear_of_the_three_second_loop(self) -> None:
        assert MANUAL_PICK_RECHECK_TTL_SECONDS >= 300
