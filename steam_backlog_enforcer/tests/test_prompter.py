"""Tests for _prompter: the CLI prompter and the active-prompter context."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _prompter
from steam_backlog_enforcer._prompter import (
    CliPrompter,
    GamePicker,
    PromptOption,
    confirm_phrase,
    current_prompter,
    use_prompter,
)
from steam_backlog_enforcer.tests._fake_prompter import FakePicker, FakePrompter

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

_OPTIONS = [PromptOption("a", "Alpha"), PromptOption("b", "Beta")]


def _typed(*answers: str) -> AbstractContextManager[MagicMock]:
    """Patch ``input`` to return *answers* in order."""
    return patch("builtins.input", side_effect=list(answers))


class TestCliPrompterChoice:
    def test_lists_options_and_returns_the_chosen_value(self) -> None:
        with _typed("2"), patch("steam_backlog_enforcer._prompter._echo") as echo:
            assert CliPrompter().choice("Pick", _OPTIONS) == "b"
        assert [c.args[0] for c in echo.call_args_list] == ["  1. Alpha", "  2. Beta"]

    def test_retries_on_junk_and_out_of_range(self) -> None:
        with (
            _typed("x", "0", "3", "1"),
            patch("steam_backlog_enforcer._prompter._echo") as echo,
        ):
            assert CliPrompter().choice("Pick", _OPTIONS) == "a"
        said = [c.args[0] for c in echo.call_args_list]
        assert "Invalid input: 'x'" in said
        assert "Out of range: 0" in said
        assert "Out of range: 3" in said


class TestCliPrompterConfirm:
    @pytest.mark.parametrize(
        ("answer", "default", "expected"),
        [
            ("y", False, True),
            ("YES", False, True),
            ("n", True, False),
            ("No", True, False),
            ("", True, True),
            ("", False, False),
        ],
    )
    def test_answers(self, answer: str, *, default: bool, expected: bool) -> None:
        with _typed(answer):
            assert CliPrompter().confirm("Sure?", default=default) is expected

    def test_end_of_input_means_the_default(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            assert CliPrompter().confirm("Sure?", default=True) is True

    def test_asks_again_after_an_unclear_answer(self) -> None:
        with _typed("maybe", "y"), patch("steam_backlog_enforcer._prompter._echo"):
            assert CliPrompter().confirm("Sure?", default=False) is True

    def test_hint_shows_the_default(self) -> None:
        with _typed("") as typed:
            CliPrompter().confirm("Sure?", default=True)
        assert typed.call_args.args[0] == "Sure? [Y/n]: "


class TestCliPrompterPhraseAndText:
    def test_exact_phrase_matches_ignoring_outer_whitespace(self) -> None:
        with _typed("  lock in X ") as typed:
            assert CliPrompter().phrase("ignored", "lock in X") is True
        assert typed.call_args.args[0] == 'Type "lock in X" to confirm: '

    def test_wrong_phrase_is_a_no(self) -> None:
        with _typed("LOCK IN X"):
            assert CliPrompter().phrase("ignored", "lock in X") is False

    def test_text_is_stripped(self) -> None:
        with _typed("  hello ") as typed:
            assert CliPrompter().text("Name") == "hello"
        assert typed.call_args.args[0] == "Name: "

    def test_interactive_follows_stdin(self) -> None:
        with patch("steam_backlog_enforcer._prompter.sys.stdin") as stdin:
            stdin.isatty.return_value = True
            assert CliPrompter().interactive is True
            stdin.isatty.return_value = False
            assert CliPrompter().interactive is False


class TestActivePrompter:
    def test_defaults_to_the_cli(self) -> None:
        assert current_prompter() is _prompter._CLI

    def test_use_prompter_scopes_the_override(self) -> None:
        fake = FakePrompter()
        with use_prompter(fake) as active:
            assert active is fake
            assert current_prompter() is fake
        assert current_prompter() is _prompter._CLI

    def test_the_override_is_dropped_when_the_body_raises(self) -> None:
        with pytest.raises(RuntimeError), use_prompter(FakePrompter()):
            raise RuntimeError
        assert current_prompter() is _prompter._CLI


class TestGamePickerProtocol:
    def test_only_prompters_with_a_game_method_are_pickers(self) -> None:
        assert isinstance(FakePicker(), GamePicker)
        assert not isinstance(FakePrompter(), GamePicker)
        assert not isinstance(CliPrompter(), GamePicker)


class TestConfirmPhrase:
    def test_asks_for_the_commands_phrase(self) -> None:
        fake = FakePrompter(phrases=[True])
        with use_prompter(fake):
            assert confirm_phrase("pick-manual", "Lock it?", game_name="Doom") is True
        assert fake.asked == [("Lock it?", "lock in Doom")]

    def test_a_declined_phrase_is_false(self) -> None:
        with use_prompter(FakePrompter(phrases=[False])):
            assert confirm_phrase("reset", "Wipe?") is False

    def test_a_command_without_a_phrase_is_an_error_not_a_yes(self) -> None:
        with pytest.raises(KeyError, match="no-such-command"):
            confirm_phrase("no-such-command", "?")
