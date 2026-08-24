"""Tests for _enforce_loop module (part 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._enforce_loop import (
    _enforce_loop_iteration,
)
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._enforce_loop"
ENFORCE_STEPS_PKG = "steam_backlog_enforcer._enforce_steps"


class TestEnforceLoopIteration:
    """Tests for _enforce_loop_iteration."""

    @pytest.fixture(autouse=True)
    def _steam_present(self) -> Iterator[None]:
        """Pretend Steam is installed for every test in this class.

        The iteration short-circuits when it is not, which on a test machine
        without Steam would silently make every assertion below vacuous. The
        absent case is covered explicitly by test_skips_when_steam_absent.
        """
        with patch(f"{PKG}.steam_is_installed", return_value=True):
            yield

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
            patch(f"{ENFORCE_STEPS_PKG}.send_notification"),
            patch(f"{PKG}._echo"),
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=True),
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
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=True),
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
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=True),
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
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=True),
        ):
            _enforce_loop_iteration(config, state)

    def test_skips_when_steam_absent(self) -> None:
        """With Steam uninstalled the iteration must do nothing.

        Regression guard: this path used to try to write an appmanifest into
        a steamapps directory a total block had deleted, erroring every 3s.
        """
        config = Config(
            kill_unauthorized_games=True,
            uninstall_other_games=True,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.steam_is_installed", return_value=False),
            patch(f"{PKG}.enforce_allowed_game") as mock_enforce,
            patch(f"{PKG}._guard_installed_games") as mock_guard,
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed") as mock_installed,
            patch(f"{ENFORCE_STEPS_PKG}.install_game") as mock_install,
        ):
            _enforce_loop_iteration(config, state)

        mock_enforce.assert_not_called()
        mock_guard.assert_not_called()
        mock_installed.assert_not_called()
        mock_install.assert_not_called()

    def test_reinstalls_missing(self) -> None:
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=False),
            patch(f"{ENFORCE_STEPS_PKG}.install_game") as mock_install,
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
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed") as mock_installed,
        ):
            _enforce_loop_iteration(config, state)
            mock_enforce.assert_not_called()
            mock_guard.assert_not_called()
            mock_installed.assert_not_called()
