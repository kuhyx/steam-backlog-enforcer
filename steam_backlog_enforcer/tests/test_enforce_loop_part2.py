"""Tests for _enforce_loop module (part 2)."""

from __future__ import annotations

from unittest.mock import patch

from python_pkg.steam_backlog_enforcer._enforce_loop import (
    _enforce_loop_iteration,
    do_enforce,
)
from python_pkg.steam_backlog_enforcer.config import Config, State

PKG = "python_pkg.steam_backlog_enforcer._enforce_loop"


class TestEnforceLoopIteration:
    """Tests for _enforce_loop_iteration."""

    def test_kills_unauthorized(self) -> None:
        config = Config(
            kill_unauthorized_games=True,
            uninstall_other_games=False,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(
                f"{PKG}.enforce_allowed_game",
                return_value=[(1234, 999)],
            ),
            patch(f"{PKG}.send_notification"),
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)

    def test_no_kill(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.enforce_allowed_game") as mock_enforce,
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)
            mock_enforce.assert_not_called()

    def test_guards_installed(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=True,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}._guard_installed_games", return_value=1),
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)

    def test_guard_removes_zero(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=True,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}._guard_installed_games", return_value=0),
            patch(f"{PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)

    def test_reinstalls_missing(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game") as mock_install,
        ):
            _enforce_loop_iteration(config, state)
            mock_install.assert_called_once()

    def test_no_app_id_skip_reinstall(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
        )
        state = State(current_app_id=None)
        with (
            patch(f"{PKG}.enforce_allowed_game") as mock_enforce,
            patch(f"{PKG}._guard_installed_games") as mock_guard,
            patch(f"{PKG}.is_game_installed") as mock_installed,
        ):
            _enforce_loop_iteration(config, state)
            mock_enforce.assert_not_called()
            mock_guard.assert_not_called()
            mock_installed.assert_not_called()

    def test_promotes_newly_approved_exceptions(self) -> None:
        """Loop body at line 286 executes when promote returns non-empty list."""
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(
                f"{PKG}.promote_pending_exceptions",
                return_value=[440],
            ),
        ):
            _enforce_loop_iteration(config, state)


class TestDoEnforce:
    """Tests for do_enforce."""

    def test_no_game(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            do_enforce(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_keyboard_interrupt(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        fresh = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=fresh),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=KeyboardInterrupt,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)

    def test_runs_iterations(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        fresh = State(current_app_id=1, current_game_name="G")
        call_count = 0

        def side_effect(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", return_value=fresh),
            patch(
                f"{PKG}._enforce_loop_iteration",
                side_effect=side_effect,
            ),
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
            assert call_count == 2

    def test_state_load_failure_continues(self) -> None:
        """Corrupt state file should not crash the daemon."""
        import json as json_mod

        state = State(current_app_id=1, current_game_name="G")
        config = Config()
        call_count = 0

        def load_side_effect() -> State:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "bad"
                raise json_mod.JSONDecodeError(msg, "", 0)
            if call_count == 2:
                raise KeyboardInterrupt
            return State(current_app_id=1)  # pragma: no cover

        with (
            patch(f"{PKG}._enforce_setup"),
            patch(f"{PKG}._echo"),
            patch.object(State, "load", side_effect=load_side_effect),
            patch(f"{PKG}._enforce_loop_iteration") as mock_iter,
            patch(f"{PKG}.time.sleep"),
        ):
            do_enforce(config, state)
            mock_iter.assert_not_called()
