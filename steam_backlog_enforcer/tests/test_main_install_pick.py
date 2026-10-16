"""Tests for ``install`` choosing which allowed game to (fast-)install.

A fast install that was skipped at pick time must be startable later, for the
assignment and for every manual pick alike.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import cmd_install
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter

PKG = "steam_backlog_enforcer.main.install"


def _state() -> State:
    return State(
        current_app_id=1,
        current_game_name="Assigned",
        manual_picks=[{"app_id": 2, "game_name": "Picked"}],
    )


class TestInstallPicksGame:
    """Every allowed game that is not fully installed is offered."""

    def test_only_unfinished_game_installed_without_asking(self) -> None:
        prompter = FakePrompter()
        with (
            use_prompter(prompter),
            patch(f"{PKG}.is_game_fully_installed", side_effect=lambda a: a == 1),
            patch(f"{PKG}.install_game", return_value=True) as install,
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), _state())
        assert prompter.asked == []
        assert install.call_args.args[:2] == (2, "Picked")

    def test_several_unfinished_games_prompt(self) -> None:
        prompter = FakePrompter(choices=["2"])
        with (
            use_prompter(prompter),
            patch(f"{PKG}.is_game_fully_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=True) as install,
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), _state())
        assert prompter.asked[0][1] == ["1", "2"]
        assert install.call_args.args[:2] == (2, "Picked")

    def test_all_installed(self) -> None:
        with (
            patch(f"{PKG}.is_game_fully_installed", return_value=True),
            patch(f"{PKG}.install_game") as install,
            patch(f"{PKG}._echo") as echo,
        ):
            cmd_install(Config(steam_id="i"), _state())
        install.assert_not_called()
        assert any("already installed" in str(c) for c in echo.call_args_list)
