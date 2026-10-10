"""A scripted prompter for tests that drive the questions a command asks.

Answers are consumed in order; asking more questions than were scripted is a
test bug and raises ``IndexError``. :class:`FakePicker` adds the optional
``game`` question a browser front end can answer (``GamePicker``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from steam_backlog_enforcer._prompter import PromptOption


class FakePrompter:
    """Answers ``choice`` / ``confirm`` / ``phrase`` / ``text`` from scripts."""

    def __init__(
        self,
        *,
        interactive: bool = True,
        choices: Sequence[str] = (),
        confirms: Sequence[bool] = (),
        phrases: Sequence[bool] = (),
        texts: Sequence[str] = (),
    ) -> None:
        """Store the scripted answers and an empty question log."""
        self.interactive = interactive
        self._choices = list(choices)
        self._confirms = list(confirms)
        self._phrases = list(phrases)
        self._texts = list(texts)
        self.asked: list[tuple[str, object]] = []

    def choice(self, message: str, options: Sequence[PromptOption]) -> str:
        """Log the offered values and return the next scripted choice."""
        self.asked.append((message, [option.value for option in options]))
        return self._choices.pop(0)

    def confirm(self, message: str, *, default: bool) -> bool:
        """Log the question and return the next scripted yes/no."""
        self.asked.append((message, default))
        return self._confirms.pop(0)

    def phrase(self, message: str, expected: str) -> bool:
        """Log the expected phrase and return the next scripted verdict."""
        self.asked.append((message, expected))
        return self._phrases.pop(0)

    def text(self, message: str) -> str:
        """Log the question and return the next scripted line."""
        self.asked.append((message, None))
        return self._texts.pop(0)


class FakePicker(FakePrompter):
    """A prompter that can also show the library (a ``GamePicker``)."""

    def __init__(
        self,
        *,
        picks: Sequence[int | None] = (),
        choices: Sequence[str] = (),
        texts: Sequence[str] = (),
    ) -> None:
        """Store the scripted library picks next to the other answers."""
        super().__init__(choices=choices, texts=texts)
        self._picks = list(picks)
        self.offered: list[list[int]] = []

    def game(self, message: str, app_ids: Sequence[int]) -> int | None:
        """Log the offered app ids and return the next scripted pick."""
        self.asked.append((message, None))
        self.offered.append(list(app_ids))
        return self._picks.pop(0)
