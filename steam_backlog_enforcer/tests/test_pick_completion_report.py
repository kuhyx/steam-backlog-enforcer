"""Tests for reporting, stale-assignment warnings and the daemon pick sweep.

Split out of test_pick_completion.py to keep both files under the 250-line cap.
"""

from unittest.mock import patch

from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._pick_completion import (
    MANUAL_PICK_RECHECK_TTL_SECONDS,
    PickProgress,
    _DaemonSweep,
    daemon_sweep,
    report_completion,
    retire_completed_manual_picks_throttled,
    warn_stale_assignment,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_helpers import locked_state, two_pick_state
from steam_backlog_enforcer.tests._pick_completion_helpers import (
    client_returning,
    game,
)

PKG = "steam_backlog_enforcer._pick_completion"


class TestReportCompletion:
    """report_completion prints every pick and returns retirements."""

    def test_prints_nothing_without_picks(self) -> None:
        """No picks means no output."""
        with patch(f"{PKG}._echo") as mock_echo:
            assert report_completion(Config(), State()) == []
        mock_echo.assert_not_called()

    def test_prints_each_pick_and_returns_only_retirements(self) -> None:
        """Each pick is printed; only retired ones are returned."""
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
        assert "no new achievement" in output
        assert "COMPLETE, slot freed" in output


class TestWarnStaleAssignment:
    """A retired pick still set as the current game is flagged."""

    def test_warns_when_retired_pick_is_current(self) -> None:
        """Retiring the current game prints a warning."""
        state = State(current_app_id=200, current_game_name="SecondGame")
        retired = [
            PickProgress(200, "SecondGame", 5, 5, retired=True, determinable=True)
        ]
        with patch(f"{PKG}._echo") as mock_echo:
            warn_stale_assignment(state, retired)
        assert "still" in " ".join(str(c) for c in mock_echo.call_args_list)

    def test_silent_when_current_is_something_else(self) -> None:
        """Retiring another game prints nothing."""
        state = State(current_app_id=999)
        retired = [PickProgress(200, "G", 5, 5, retired=True, determinable=True)]
        with patch(f"{PKG}._echo") as mock_echo:
            warn_stale_assignment(state, retired)
        mock_echo.assert_not_called()


class TestDaemonSweep:
    """The daemon's pick sweep runs at most once per TTL."""

    def test_due_then_throttled(self) -> None:
        """The sweep is due, then throttled, then due again after the TTL."""
        sweep = _DaemonSweep()
        assert sweep.due(1000.0, 900.0) is True
        assert sweep.due(1100.0, 900.0) is False
        assert sweep.due(2000.0, 900.0) is True

    def test_throttled_call_releases_without_evicting(self) -> None:
        """A throttled sweep releases once and skips Steam within the TTL."""
        state = locked_state(app_id=100)
        daemon_sweep.last = None
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
                assert 100 in allowed_app_ids(state)
                # Second call inside the TTL must not re-query Steam.
                assert retire_completed_manual_picks_throttled(Config(), state) == []
        finally:
            daemon_sweep.last = None

    def test_ttl_is_well_clear_of_the_three_second_loop(self) -> None:
        """The recheck TTL is at least five minutes."""
        assert MANUAL_PICK_RECHECK_TTL_SECONDS >= 300
