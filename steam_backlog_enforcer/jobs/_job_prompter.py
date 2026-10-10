"""The prompter a job uses: a ``prompt`` event out, an answer line back.

The job writes a ``prompt`` event and blocks, polling ``answers.jsonl``
(appended by the server on ``POST /api/jobs/{id}/answer``) for a line with
its ``prompt_id``. Nothing the UI sends is trusted: a choice must be one of
the offered values and a phrase is re-checked with
:func:`steam_backlog_enforcer._friction.phrase_matches` right here, in the
process that carries the action out.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._friction import phrase_matches
from steam_backlog_enforcer._prompter import PromptAbortedError
from steam_backlog_enforcer.jobs._errors import JobCancelledError
from steam_backlog_enforcer.jobs._events import ANSWERS_NAME, CANCEL_NAME, read_jsonl

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from steam_backlog_enforcer._prompter import PromptOption
    from steam_backlog_enforcer.jobs._events import EventWriter

# An unanswered prompt holds the mutating-job lock; give up eventually.
PROMPT_TIMEOUT_SECONDS: Final = 3600
MAX_PHRASE_ATTEMPTS: Final = 3
_POLL_SECONDS = 0.2
_YES = frozenset({"y", "yes", "true", "1"})
_NO = frozenset({"n", "no", "false", "0"})


class JobPrompter:
    """A :class:`~steam_backlog_enforcer._prompter.Prompter` over job files."""

    def __init__(
        self,
        writer: EventWriter,
        job_dir: Path,
        *,
        preset_phrase: str | None = None,
        timeout: float = PROMPT_TIMEOUT_SECONDS,
    ) -> None:
        """Bind to a job.

        Args:
            writer: The job's event writer.
            job_dir: Where ``answers.jsonl`` appears.
            preset_phrase: ``JobRequest.confirm_phrase``, typed up front. The
                first phrase prompt consumes it if it matches, and asks
                normally if it does not.
            timeout: Seconds to wait for any one answer.
        """
        self._writer = writer
        self._answers = job_dir / ANSWERS_NAME
        self._cancel = job_dir / CANCEL_NAME
        self._preset = preset_phrase
        self._timeout = timeout

    @property
    def interactive(self) -> bool:
        """A job always has the UI to ask."""
        return True

    def _wait(self, prompt_id: str) -> str:
        """Block until the answer for *prompt_id* arrives.

        Raises:
            JobCancelledError: The user cancelled while the job was waiting.
                Safe for every command, cancellable or not: a job blocked on
                a question is where the CLI's Ctrl-C would land.
        """
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self._cancel.exists():
                raise JobCancelledError
            for answer in read_jsonl(self._answers):
                if answer.get("prompt_id") == prompt_id:
                    return str(answer.get("value", ""))
            time.sleep(_POLL_SECONDS)
        msg = f"No answer within {self._timeout / 60:.0f} minute(s)."
        raise PromptAbortedError(msg)

    def _ask(self, kind: str, message: str, **extra: object) -> str:
        """Emit one prompt, wait for its answer, and return it."""
        prompt_id = secrets.token_hex(8)
        self._writer.emit("state", state="waiting_input")
        self._writer.emit(
            "prompt", prompt_id=prompt_id, kind=kind, message=message.strip(), **extra
        )
        value = self._wait(prompt_id)
        self._writer.emit("state", state="running")
        return value

    def _warn(self, message: str) -> None:
        """Tell the user why their answer was not accepted."""
        self._writer.emit("log", level="warning", message=message)

    def choice(self, message: str, options: Sequence[PromptOption]) -> str:
        """Ask until the answer is one of the offered values."""
        payload = [
            {"value": o.value, "label": o.label}
            | ({"detail": o.detail} if o.detail else {})
            for o in options
        ]
        valid = {o.value for o in options}
        while True:
            value = self._ask("choice", message, options=payload)
            if value in valid:
                return value
            self._warn(f"Not one of the options: {value!r}")

    def confirm(self, message: str, *, default: bool) -> bool:
        """Ask yes/no; an empty answer means *default*."""
        while True:
            value = self._ask(
                "confirm", message, default="yes" if default else "no"
            ).strip()
            if not value:
                return default
            if value.lower() in _YES:
                return True
            if value.lower() in _NO:
                return False
            self._warn(f"Answer yes or no, not {value!r}")

    def phrase(self, message: str, expected: str) -> bool:
        """Return True once *expected* is typed exactly.

        Raises:
            PromptAbortedError: On an empty answer (declined) or after
                :data:`MAX_PHRASE_ATTEMPTS` wrong ones. A job never treats a
                wrong phrase as a quiet "no": it fails, visibly.
        """
        preset, self._preset = self._preset, None
        if preset is not None:
            if phrase_matches(expected, preset):
                return True
            self._warn("The phrase sent with the request did not match.")
        for _ in range(MAX_PHRASE_ATTEMPTS):
            value = self._ask("phrase", message, phrase=expected)
            if not value.strip():
                msg = "Declined."
                raise PromptAbortedError(msg)
            if phrase_matches(expected, value):
                return True
            self._warn(f'That is not the phrase. Type exactly: "{expected}"')
        msg = f"Wrong phrase {MAX_PHRASE_ATTEMPTS} times; nothing was changed."
        raise PromptAbortedError(msg)

    def text(self, message: str) -> str:
        """Ask for one line of free text."""
        return self._ask("text", message).strip()

    def game(self, message: str, app_ids: Sequence[int]) -> int | None:
        """Ask for a game from the library browser; empty means go back.

        The event carries only the ids (the UI already has the library); the
        answer must be one of them, whatever the browser let the user click.
        """
        valid = frozenset(app_ids)
        while True:
            value = self._ask("game", message, app_ids=sorted(valid)).strip()
            if not value:
                return None
            if value.isdigit() and int(value) in valid:
                return int(value)
            self._warn(f"Not a game you can pick here: {value!r}")
