"""Tests for _prompt_user_pick: the ranked list plus "pick my own"."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer._scanning_assign import _prompt_user_pick
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter

_PKG = "steam_backlog_enforcer._scanning_assign"


def _game(app_id: int, name: str, hours: float = -1) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=10,
        unlocked_achievements=5,
        playtime_minutes=60,
        completionist_hours=hours,
    )


_RANKED = [_game(1, "Short", hours=2.5), _game(2, "Unknown")]


class TestPromptUserPick:
    def test_choosing_a_ranked_entry_returns_that_game(self) -> None:
        prompter = FakePrompter(choices=["1"])
        with use_prompter(prompter):
            assert _prompt_user_pick(_RANKED, _RANKED, State()) is _RANKED[1]

    def test_options_carry_hours_when_known_and_end_with_own_pick(self) -> None:
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
        mine = _game(9, "Mine")
        with (
            use_prompter(FakePrompter(choices=["own"])),
            patch(f"{_PKG}.prompt_own_pick", return_value=mine) as own,
        ):
            state = State()
            assert _prompt_user_pick(_RANKED, [*_RANKED, mine], state) is mine
        own.assert_called_once_with([*_RANKED, mine], state)

    def test_backing_out_of_own_pick_shows_the_list_again(self) -> None:
        prompter = FakePrompter(choices=["own", "0"])
        with (
            use_prompter(prompter),
            patch(f"{_PKG}.prompt_own_pick", return_value=None),
        ):
            assert _prompt_user_pick(_RANKED, _RANKED, State()) is _RANKED[0]
        assert len(prompter.asked) == 2
