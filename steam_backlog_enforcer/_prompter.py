"""Questions a command asks its user, answered by a terminal or the web UI.

Every ``input()`` in the package goes through :func:`current_prompter`. The
CLI prompter reads stdin exactly as the commands used to; a web job installs
one that emits a ``prompt`` event and waits for the answer the server writes
(see :mod:`steam_backlog_enforcer.jobs._job_prompter`).

Typed-phrase confirmations take their text from
:func:`steam_backlog_enforcer._friction.expected_phrase`, so the CLI, the job
runner and the daemon all demand the same sentence.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import sys
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._friction import expected_phrase, phrase_matches

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


@dataclass(frozen=True)
class PromptOption:
    """One answer to a ``choice`` prompt.

    Attributes:
        value: What the prompter returns when this option is chosen.
        label: The text shown for it.
        detail: Optional secondary text (the UI shows it under the label).
    """

    value: str
    label: str
    detail: str | None = None


class PromptAbortedError(Exception):
    """The user declined, or never answered, a prompt the command needs."""


class Prompter(Protocol):
    """Asks the user something and returns the answer."""

    @property
    def interactive(self) -> bool:
        """Whether a human can answer at all (a piped CLI cannot)."""

    def choice(self, message: str, options: Sequence[PromptOption]) -> str:
        """Return the ``value`` of the option the user picked."""

    def confirm(self, message: str, *, default: bool) -> bool:
        """Return the user's yes/no answer."""

    def phrase(self, message: str, expected: str) -> bool:
        """Return whether the user typed *expected* exactly."""

    def text(self, message: str) -> str:
        """Return a line of free text, stripped."""


@runtime_checkable
class GamePicker(Protocol):
    """A prompter that can show the whole library to pick a game from.

    Optional on top of :class:`Prompter`: the CLI has no browser and keeps
    its text search (:func:`steam_backlog_enforcer._own_pick.prompt_own_pick`).
    """

    def game(self, message: str, app_ids: Sequence[int]) -> int | None:
        """Return the picked app id (one of *app_ids*), or ``None`` to go back."""


class CliPrompter:
    """Reads answers from stdin; the CLI's behaviour before prompters existed."""

    @property
    def interactive(self) -> bool:
        """True when stdin is a terminal."""
        return sys.stdin.isatty()

    def choice(self, message: str, options: Sequence[PromptOption]) -> str:
        """Print a numbered list and loop until a valid number is typed."""
        for i, option in enumerate(options, 1):
            _echo(f"  {i}. {option.label}")
        while True:
            raw = input(f"{message}: ")
            try:
                idx = int(raw)
            except ValueError:
                _echo(f"Invalid input: {raw!r}")
                continue
            if idx < 1 or idx > len(options):
                _echo(f"Out of range: {idx}")
                continue
            return options[idx - 1].value

    def confirm(self, message: str, *, default: bool) -> bool:
        """Ask ``[Y/n]``; an empty answer or end of input means *default*."""
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                answer = input(f"{message} {hint}: ").strip().lower()
            except EOFError:
                return default
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            _echo("  Please answer 'y' or 'n'.")

    def phrase(self, message: str, expected: str) -> bool:
        """Ask for the phrase once; a mismatch is a "no".

        The CLI has already printed what is at stake before asking, so only
        the phrase itself is shown; *message* is for front ends without that
        preamble.
        """
        del message
        return phrase_matches(expected, input(f'Type "{expected}" to confirm: '))

    def text(self, message: str) -> str:
        """Ask for one line of text."""
        return input(f"{message}: ").strip()


_ACTIVE: ContextVar[Prompter | None] = ContextVar("prompter", default=None)
_CLI = CliPrompter()


def current_prompter() -> Prompter:
    """Return the prompter the running command should ask."""
    return _ACTIVE.get() or _CLI


@contextmanager
def use_prompter(prompter: Prompter) -> Iterator[Prompter]:
    """Make *prompter* the active one for the duration of the context."""
    token = _ACTIVE.set(prompter)
    try:
        yield prompter
    finally:
        _ACTIVE.reset(token)


def confirm_phrase(command: str, message: str, **fields: object) -> bool:
    """Ask for *command*'s friction phrase and say whether it was typed.

    Args:
        command: Key into :data:`steam_backlog_enforcer._friction.FRICTION`.
        message: What is being confirmed, for front ends that show it.
        **fields: The template's slots (``game_name``, ``count``, ...).

    Raises:
        KeyError: If *command* has no phrase; a missing phrase must never
            silently mean "confirmed".
    """
    expected = expected_phrase(command, **fields)
    if expected is None:
        raise KeyError(command)
    return current_prompter().phrase(message, expected)
