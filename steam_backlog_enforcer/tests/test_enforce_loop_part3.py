"""Tests for _enforce_loop module (part 3 - total-block short-circuit)."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._enforce_loop import _enforce_loop_iteration, do_enforce
from steam_backlog_enforcer.config import Config, State

PKG = "steam_backlog_enforcer._enforce_loop"


class TestEnforceLoopIterationTotalBlock:
    """Total-block short-circuit at the top of _enforce_loop_iteration."""

    def test_active_short_circuits_before_assigned_game_logic(self) -> None:
        config = Config(kill_unauthorized_games=True, uninstall_other_games=True)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.enforce_total_block_tick") as mock_tick,
            patch(f"{PKG}.enforce_allowed_game") as mock_enforce,
            patch(f"{PKG}._guard_installed_games") as mock_guard,
            patch(f"{PKG}.is_game_installed") as mock_installed,
        ):
            _enforce_loop_iteration(config, state)
        mock_tick.assert_called_once()
        mock_enforce.assert_not_called()
        mock_guard.assert_not_called()
        mock_installed.assert_not_called()

    def test_not_active_runs_normal_logic(self) -> None:
        config = Config(kill_unauthorized_games=False, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.total_block_needs_cleanup", return_value=False),
            patch(f"{PKG}.enforce_total_block_tick") as mock_tick,
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)
        mock_tick.assert_not_called()

    def test_expired_lock_triggers_cleanup_once(self) -> None:
        config = Config(kill_unauthorized_games=False, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.total_block_needs_cleanup", return_value=True),
            patch(f"{PKG}.end_total_block_cleanup") as mock_cleanup,
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)
        mock_cleanup.assert_called_once()

    def test_no_lock_no_cleanup_call(self) -> None:
        config = Config(kill_unauthorized_games=False, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.total_block_needs_cleanup", return_value=False),
            patch(f"{PKG}.end_total_block_cleanup") as mock_cleanup,
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)
        mock_cleanup.assert_not_called()


class TestDoEnforceTotalBlock:
    """Total-block awareness in do_enforce's one-time setup."""

    def test_active_skips_enforce_setup_but_still_loops(self) -> None:
        state = State()  # no assigned game
        config = Config()
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}._enforce_setup") as mock_setup,
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
        mock_setup.assert_not_called()

    def test_active_with_no_game_does_not_early_return(self) -> None:
        """A total block with no assigned game must still run the loop."""
        state = State()
        config = Config()
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ) as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
        mock_iter.assert_called_once()

    def test_inactive_with_no_game_still_enters_the_loop(self) -> None:
        """No assigned game must NOT exit the process.

        It used to return here, which silently stopped enforcing the daily
        gaming budget for as long as a game was finished but not yet
        rescanned - the budget is accounted for from inside this loop.
        """
        state = State()
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}._echo") as mock_echo,
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ) as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(Config(), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "No game" in output
        assert "budget is still enforced" in output
        mock_iter.assert_called_once()


class TestPlaytimeIsEnforcedFirst:
    """The gaming budget must run before every other guard in the tick."""

    def test_runs_even_when_total_block_short_circuits(self) -> None:
        """Time is still spent, and a 06:00 release still has to happen."""
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.playtime_tick") as mock_playtime,
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.enforce_total_block_tick"),
        ):
            _enforce_loop_iteration(config, state)
        mock_playtime.assert_called_once()

    def test_receives_the_loop_interval(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.playtime_tick") as mock_playtime,
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.enforce_total_block_tick"),
        ):
            _enforce_loop_iteration(config, state)
        assert mock_playtime.call_args.kwargs["interval"] == 3
        assert mock_playtime.call_args.kwargs["demo"] is False

    def test_demo_flag_is_plumbed_through(self) -> None:
        config = Config()
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.playtime_tick") as mock_playtime,
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.enforce_total_block_tick"),
        ):
            _enforce_loop_iteration(config, state, demo=True)
        assert mock_playtime.call_args.kwargs["demo"] is True

    def test_do_enforce_plumbs_demo_into_the_iteration(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_total_block_active", return_value=False),
            patch(f"{PKG}.steam_is_installed", return_value=True),
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=state),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ) as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(Config(), state, demo=True)
        assert mock_iter.call_args.kwargs["demo"] is True
