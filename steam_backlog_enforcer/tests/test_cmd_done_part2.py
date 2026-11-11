"""Tests for _cmd_done module (part 2): _prompt_keep_or_skip."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._cmd_done import _prompt_keep_or_skip
from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter
from steam_backlog_enforcer.tests._half_done_game import half_done_game

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"


def _game(hours: float = 5.0, app_id: int = 42, name: str = "Test") -> GameInfo:
    return half_done_game(app_id, name, hours)


def _ask(prompter: FakePrompter, game: GameInfo | None = None) -> bool | GameInfo:
    """Run the prompt under *prompter*, collecting nothing from the terminal."""
    with use_prompter(prompter), patch(f"{CMD_DONE_PKG}._echo"):
        return _prompt_keep_or_skip(game or _game(), [], State())


class TestPromptKeepOrSkip:
    """Tests for _prompt_keep_or_skip."""

    def test_non_interactive_accepts_silently(self) -> None:
        """Without a terminal the pick is accepted and nothing is asked."""
        prompter = FakePrompter(interactive=False)
        assert _ask(prompter) is True
        assert prompter.asked == []

    def test_keep_accepts(self) -> None:
        """Answering keep accepts the pick."""
        assert _ask(FakePrompter(choices=["keep"])) is True

    def test_skip_rejects(self) -> None:
        """Answering skip rejects the pick."""
        assert _ask(FakePrompter(choices=["skip"])) is False

    def test_offers_keep_skip_and_own_pick(self) -> None:
        """The prompt offers keep, skip and own-pick."""
        prompter = FakePrompter(choices=["keep"])
        _ask(prompter)
        assert prompter.asked == [("  Keep this game?", ["keep", "skip", "own"])]

    def test_own_pick_returns_the_chosen_game(self) -> None:
        """Own-pick returns the game the user chose."""
        mine = _game(app_id=7, name="Mine")
        with patch(f"{CMD_DONE_PKG}.prompt_own_pick", return_value=mine):
            assert _ask(FakePrompter(choices=["own"])) is mine

    def test_going_back_from_own_pick_asks_again(self) -> None:
        """Backing out of own-pick asks the question again."""
        prompter = FakePrompter(choices=["own", "skip"])
        with patch(f"{CMD_DONE_PKG}.prompt_own_pick", return_value=None):
            assert _ask(prompter) is False
        assert len(prompter.asked) == 2

    def test_hours_are_shown_when_known(self) -> None:
        """Known completion hours appear in the prompt."""
        with (
            use_prompter(FakePrompter(choices=["keep"])),
            patch(f"{CMD_DONE_PKG}._echo") as echo,
        ):
            _prompt_keep_or_skip(_game(), [], State())
        assert "(~5.0h leisure+dlc)" in echo.call_args_list[0].args[0]

    def test_zero_hours_omits_hours_string(self) -> None:
        """Unknown (zero) hours are left out of the prompt."""
        with (
            use_prompter(FakePrompter(choices=["keep"])),
            patch(f"{CMD_DONE_PKG}._echo") as echo,
        ):
            _prompt_keep_or_skip(_game(hours=0.0), [], State())
        assert "~" not in echo.call_args_list[0].args[0]
