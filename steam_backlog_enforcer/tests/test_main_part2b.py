"""Tests for the main CLI: enforce-on-done behaviour."""

from unittest.mock import patch

from steam_backlog_enforcer._cmd_done_finalize import (
    _enforce_on_done,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.tests._main_patches import HIDER_ECHO, library_hider

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"
PKG = "steam_backlog_enforcer.main"


class TestEnforceOnDone:
    """Tests for _enforce_on_done."""

    def test_no_current_game(self) -> None:
        """With no game assigned there is nothing to enforce."""
        _enforce_on_done(Config(), State())

    def test_kills_and_uninstalls(self) -> None:
        """Violations are killed and other games uninstalled."""
        config = Config(kill_unauthorized_games=True, uninstall_other_games=True)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(
                f"{CMD_DONE_PKG}.enforce_allowed_game",
                return_value=[(1234, 999)],
            ),
            patch(f"{CMD_DONE_PKG}.uninstall_other_games", return_value=2),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=True),
            library_hider([1, 2], (1, None)),
        ):
            _enforce_on_done(config, state)

    def test_no_violations_no_uninstalls(self) -> None:
        """No violations and nothing to uninstall still completes."""
        config = Config(kill_unauthorized_games=True, uninstall_other_games=True)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.enforce_allowed_game", return_value=[]),
            patch(f"{CMD_DONE_PKG}.uninstall_other_games", return_value=0),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=True),
            library_hider([], (0, None)),
        ):
            _enforce_on_done(config, state)

    def test_hide_skipped_when_steam_unreachable(self) -> None:
        """Hiding is skipped with the reason when Steam is unreachable."""
        config = Config(kill_unauthorized_games=False, uninstall_other_games=False)
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo") as mock_echo,
            patch(HIDER_ECHO, mock_echo),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=True),
            library_hider([1, 2], (0, "Steam is not installed")),
        ):
            _enforce_on_done(config, state)
        assert "skipped (Steam is not installed)" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )

    def test_reinstall_when_not_installed(self) -> None:
        """A missing assigned game is reinstalled through the Steam protocol."""
        config = Config(
            kill_unauthorized_games=False,
            uninstall_other_games=False,
            steam_id="s1",
        )
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.is_game_fully_installed", return_value=False),
            patch(f"{CMD_DONE_PKG}.install_game") as mock_install,
            library_hider([1, 2], (0, None)),
        ):
            _enforce_on_done(config, state)
        mock_install.assert_called_once_with(1, "G", "s1", use_steam_protocol=True)
