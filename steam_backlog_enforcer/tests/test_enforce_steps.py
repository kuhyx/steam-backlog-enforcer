"""Tests for the individual steps one enforce pass performs.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._enforce_loop import _guard_installed_games
from steam_backlog_enforcer._enforce_steps import (
    _enforce_auto_install,
    _enforce_hide_games,
    _enforce_setup,
)
from steam_backlog_enforcer.config import Config, State

PKG = "steam_backlog_enforcer._enforce_loop"
ENFORCE_STEPS_PKG = "steam_backlog_enforcer._enforce_steps"
OWNED_APPS_CACHE_PKG = "steam_backlog_enforcer._owned_apps_cache"


class TestGuardInstalledGames:
    """Tests for _guard_installed_games."""

    def test_removes_unauthorized(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(999, "Bad Game")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=True),
            patch(f"{ENFORCE_STEPS_PKG}.send_notification"),
        ):
            assert _guard_installed_games({440}) == 1

    def test_skips_allowed(self) -> None:
        with patch(
            f"{PKG}.get_installed_games",
            return_value=[(440, "TF2")],
        ):
            assert _guard_installed_games({440}) == 0

    def test_skips_protected(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(228980, "Runtime")],
            ),
            patch(f"{PKG}.is_protected_app", side_effect=lambda aid: aid == 228980),
        ):
            assert _guard_installed_games({440}) == 0

    def test_uninstall_fails(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(999, "Bad")],
            ),
            patch(f"{PKG}.uninstall_game", return_value=False),
        ):
            assert _guard_installed_games({440}) == 0

    def test_allowed_none_skips(self) -> None:
        assert _guard_installed_games(set()) == 0


class TestEnforceSetup:
    """Tests for _enforce_setup."""

    def test_block_store_success(self) -> None:
        config = Config(block_store=True, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{ENFORCE_STEPS_PKG}.block_store", return_value=True),
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_auto_install"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)

    def test_block_store_fail(self) -> None:
        config = Config(block_store=True, uninstall_other_games=False)
        state = State()
        with (
            patch(f"{ENFORCE_STEPS_PKG}.block_store", return_value=False),
            patch(f"{ENFORCE_STEPS_PKG}._echo") as mock_echo,
            patch(f"{ENFORCE_STEPS_PKG}._enforce_auto_install"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)
            assert any("FAILED" in str(c) for c in mock_echo.call_args_list)

    def test_no_block_store(self) -> None:
        config = Config(block_store=False, uninstall_other_games=False)
        state = State()
        with (
            patch(f"{ENFORCE_STEPS_PKG}.block_store") as mock_block,
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_auto_install"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)
            mock_block.assert_not_called()

    def test_uninstall_other_games(self) -> None:
        config = Config(uninstall_other_games=True, block_store=False)
        state = State(current_app_id=1)
        with (
            patch(f"{ENFORCE_STEPS_PKG}.uninstall_other_games", return_value=3),
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_auto_install"),
            patch(f"{ENFORCE_STEPS_PKG}._enforce_hide_games"),
        ):
            _enforce_setup(config, state)


class TestEnforceAutoInstall:
    """Tests for _enforce_auto_install."""

    def test_no_app_id(self) -> None:
        _enforce_auto_install(Config(), State())

    def test_already_installed(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=True),
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
        ):
            _enforce_auto_install(Config(), state)

    def test_installs_successfully(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=False),
            patch(f"{ENFORCE_STEPS_PKG}.install_game", return_value=True),
            patch(f"{ENFORCE_STEPS_PKG}.send_notification"),
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
        ):
            _enforce_auto_install(Config(steam_id="i"), state)

    def test_install_fails(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{ENFORCE_STEPS_PKG}.is_game_installed", return_value=False),
            patch(f"{ENFORCE_STEPS_PKG}.install_game", return_value=False),
            patch(f"{ENFORCE_STEPS_PKG}._echo") as mock_echo,
        ):
            _enforce_auto_install(Config(steam_id="i"), state)
            assert any("manually" in str(c) for c in mock_echo.call_args_list)


class TestEnforceHideGames:
    """Tests for _enforce_hide_games."""

    def test_hides_some(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{ENFORCE_STEPS_PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{ENFORCE_STEPS_PKG}.try_hide_other_games", return_value=(2, None)),
            patch(f"{ENFORCE_STEPS_PKG}._echo"),
        ):
            _enforce_hide_games(Config(), state)

    def test_already_hidden(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{ENFORCE_STEPS_PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{ENFORCE_STEPS_PKG}.try_hide_other_games", return_value=(0, None)),
            patch(f"{ENFORCE_STEPS_PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)
            assert any("already" in str(c) for c in mock_echo.call_args_list)

    def test_no_owned_ids(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{ENFORCE_STEPS_PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{ENFORCE_STEPS_PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)
            assert any("skipped" in str(c) for c in mock_echo.call_args_list)

    def test_unreachable_steam_is_not_fatal(self) -> None:
        """An unreachable Steam must degrade, never propagate.

        Regression guard: this exception used to escape all the way out of
        do_enforce, exiting the process into Restart=always - which spun the
        service through ~1000 restarts against an uninstalled Steam.
        """
        state = State(current_app_id=1)
        with (
            patch(f"{ENFORCE_STEPS_PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(
                f"{ENFORCE_STEPS_PKG}.try_hide_other_games",
                return_value=(0, "Steam is not installed"),
            ),
            patch(f"{ENFORCE_STEPS_PKG}._echo") as mock_echo,
        ):
            _enforce_hide_games(Config(), state)

        assert any("skipped" in str(c) for c in mock_echo.call_args_list)
