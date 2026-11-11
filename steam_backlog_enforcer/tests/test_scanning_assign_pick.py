"""Tests for _prompt_user_pick: the ranked list plus "pick my own"."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer._scanning_assign import _prompt_user_pick
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter
from steam_backlog_enforcer.tests._half_done_game import half_done_game

_PKG = "steam_backlog_enforcer._scanning_assign"


_game = half_done_game
_RANKED = [_game(1, "Short", hours=2.5), _game(2, "Unknown")]


class TestPromptUserPick:
    """Asking the user to pick the next game from the ranked list."""

    def test_choosing_a_ranked_entry_returns_that_game(self) -> None:
        """Choosing a ranked entry returns that game."""
        prompter = FakePrompter(choices=["1"])
        with use_prompter(prompter):
            assert _prompt_user_pick(_RANKED, _RANKED, State()) is _RANKED[1]

    def test_options_carry_hours_when_known_and_end_with_own_pick(self) -> None:
        """Options show known hours and end with the own-pick entry."""
        prompter = FakePrompter(choices=["0"])
        with (
            use_prompter(prompter),
            patch.object(prompter, "choice", wraps=prompter.choice) as choice,
        ):
            _prompt_user_pick(_RANKED, _RANKED, State())
        message, options = choice.call_args.args
        assert message == "Select game number"
        assert [o.label for o in options[:2]] == [
            "Short (AppID=1) (~2.5h)",
            "Unknown (AppID=2)",
        ]
        assert options[-1].value == "own"

    def test_own_pick_returns_the_game_the_user_searched_for(self) -> None:
        """The own-pick option returns the game the user searched for."""
        mine = _game(9, "Mine")
        with (
            use_prompter(FakePrompter(choices=["own"])),
            patch(f"{_PKG}.prompt_own_pick", return_value=mine) as own,
        ):
            state = State()
            assert _prompt_user_pick(_RANKED, [*_RANKED, mine], state) is mine
        own.assert_called_once_with([*_RANKED, mine], state)

    def test_backing_out_of_own_pick_shows_the_list_again(self) -> None:
        """Backing out of the own-pick search shows the list again."""
        prompter = FakePrompter(choices=["own", "0"])
        with (
            use_prompter(prompter),
            patch(f"{_PKG}.prompt_own_pick", return_value=None),
        ):
            assert _prompt_user_pick(_RANKED, _RANKED, State()) is _RANKED[0]
        assert len(prompter.asked) == 2
