"""Tests for ``jobs._job_prompter``: prompt events out, answers back."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._prompter import PromptAbortedError, PromptOption
from steam_backlog_enforcer.jobs import _job_prompter
from steam_backlog_enforcer.jobs._errors import JobCancelledError
from steam_backlog_enforcer.jobs._events import (
    ANSWERS_NAME,
    CANCEL_NAME,
    EventWriter,
    append_jsonl,
    read_events,
)
from steam_backlog_enforcer.jobs._job_prompter import JobPrompter

if TYPE_CHECKING:
    from pathlib import Path

_HEX = "steam_backlog_enforcer.jobs._job_prompter.secrets.token_hex"
_TIME = "steam_backlog_enforcer.jobs._job_prompter.time"


def _prompter(
    tmp_path: Path,
    *answers: str,
    preset_phrase: str | None = None,
    timeout: float = 3600,
) -> JobPrompter:
    """A prompter whose prompts ``p1``, ``p2``... are already answered."""
    for number, value in enumerate(answers, 1):
        append_jsonl(
            tmp_path / ANSWERS_NAME, {"prompt_id": f"p{number}", "value": value}
        )
    return JobPrompter(
        EventWriter(tmp_path), tmp_path, preset_phrase=preset_phrase, timeout=timeout
    )


def _ids(count: int = 6) -> object:
    return patch(_HEX, side_effect=[f"p{i}" for i in range(1, count + 1)])


def _warnings(tmp_path: Path) -> list[str]:
    return [e["message"] for e in read_events(tmp_path) if e.get("level") == "warning"]


class TestWait:
    """Blocking for an answer."""

    def test_interactive(self, tmp_path: Path) -> None:
        """A job can always ask."""
        assert _prompter(tmp_path).interactive is True

    def test_cancel_marker_raises(self, tmp_path: Path) -> None:
        """A cancel request while blocked cancels the job."""
        (tmp_path / CANCEL_NAME).touch()
        with pytest.raises(JobCancelledError):
            _prompter(tmp_path)._wait("p1")

    def test_zero_timeout_aborts(self, tmp_path: Path) -> None:
        """No answer in time aborts the prompt."""
        with pytest.raises(PromptAbortedError, match="No answer within"):
            _prompter(tmp_path, timeout=0)._wait("p1")

    def test_polls_until_answer_arrives(self, tmp_path: Path) -> None:
        """An answer written during the wait is picked up."""
        prompter = _prompter(tmp_path, timeout=10)
        clock = MagicMock()
        clock.monotonic.return_value = 0.0

        def answer_arrives(_seconds: float) -> None:
            append_jsonl(tmp_path / ANSWERS_NAME, {"prompt_id": "p1", "value": "later"})

        clock.sleep.side_effect = answer_arrives
        with patch(_TIME, clock):
            assert prompter._wait("p1") == "later"

    def test_other_prompts_answers_are_ignored(self, tmp_path: Path) -> None:
        """Only the line for this prompt id counts."""
        prompter = _prompter(tmp_path, "x", timeout=10)
        clock = MagicMock()
        clock.monotonic.side_effect = [0.0, 1.0, 100.0]
        with patch(_TIME, clock), pytest.raises(PromptAbortedError):
            prompter._wait("p2")


class TestAsk:
    """The state/prompt event pair around a question."""

    def test_events_around_a_question(self, tmp_path: Path) -> None:
        """waiting_input, the prompt, then running again."""
        with _ids():
            assert _prompter(tmp_path, "hello").text("  Name?  ") == "hello"
        events = read_events(tmp_path)
        assert [e["type"] for e in events] == ["state", "prompt", "state"]
        assert events[0]["state"] == "waiting_input"
        assert events[1]["message"] == "Name?"
        assert events[1]["kind"] == "text"
        assert events[2]["state"] == "running"


class TestChoice:
    """Only offered values are accepted."""

    OPTIONS = (PromptOption("a", "Alpha", "first"), PromptOption("b", "Beta"))

    def test_valid_answer_and_payload(self, tmp_path: Path) -> None:
        """The payload carries labels, with detail only when present."""
        with _ids():
            assert _prompter(tmp_path, "b").choice("Pick", self.OPTIONS) == "b"
        prompt = next(e for e in read_events(tmp_path) if e["type"] == "prompt")
        assert prompt["options"] == [
            {"value": "a", "label": "Alpha", "detail": "first"},
            {"value": "b", "label": "Beta"},
        ]

    def test_invalid_answer_asks_again(self, tmp_path: Path) -> None:
        """A value outside the options is warned about and re-asked."""
        with _ids():
            assert _prompter(tmp_path, "zzz", "a").choice("Pick", self.OPTIONS) == "a"
        assert _warnings(tmp_path) == ["Not one of the options: 'zzz'"]


class TestConfirm:
    """Yes/no with a default."""

    @pytest.mark.parametrize(
        ("answer", "default", "expected"),
        [
            ("", True, True),
            ("  ", False, False),
            ("YES", False, True),
            ("n", True, False),
        ],
    )
    def test_answers(
        self, tmp_path: Path, answer: str, *, default: bool, expected: bool
    ) -> None:
        """Empty means default; yes/no spellings are case-insensitive."""
        with _ids():
            prompter = _prompter(tmp_path, answer)
            assert prompter.confirm("Sure?", default=default) is expected

    def test_garbage_asks_again(self, tmp_path: Path) -> None:
        """An unclear answer is warned about and re-asked."""
        with _ids():
            assert _prompter(tmp_path, "maybe", "1").confirm("Sure?", default=False)
        assert _warnings(tmp_path) == ["Answer yes or no, not 'maybe'"]


class TestPhrase:
    """The typed-phrase friction."""

    def test_matching_preset_is_consumed(self, tmp_path: Path) -> None:
        """A phrase sent with the request satisfies the first prompt only."""
        prompter = _prompter(tmp_path, "", preset_phrase="abandon X")
        assert prompter.phrase("Sure?", "abandon X") is True
        assert read_events(tmp_path) == []
        with _ids(), pytest.raises(PromptAbortedError, match="Declined"):  # Asks now.
            prompter.phrase("Sure?", "abandon X")

    def test_mismatching_preset_warns_then_asks(self, tmp_path: Path) -> None:
        """A wrong preset is not trusted; the user is asked normally."""
        prompter = _prompter(tmp_path, "abandon X", preset_phrase="nope")
        with _ids():
            assert prompter.phrase("Sure?", "abandon X") is True
        assert _warnings(tmp_path) == [
            "The phrase sent with the request did not match."
        ]

    def test_typed_phrase(self, tmp_path: Path) -> None:
        """Typing it at the prompt works."""
        with _ids():
            assert _prompter(tmp_path, "abandon X").phrase("Sure?", "abandon X")
        prompt = next(e for e in read_events(tmp_path) if e["type"] == "prompt")
        assert prompt["phrase"] == "abandon X"

    def test_empty_answer_declines(self, tmp_path: Path) -> None:
        """An empty answer aborts rather than saying no."""
        with _ids(), pytest.raises(PromptAbortedError, match="Declined"):
            _prompter(tmp_path, "  ").phrase("Sure?", "abandon X")

    def test_wrong_three_times_aborts(self, tmp_path: Path) -> None:
        """Three misses abort the job, visibly."""
        prompter = _prompter(tmp_path, "a", "b", "c")
        with _ids(), pytest.raises(PromptAbortedError, match="Wrong phrase 3 times"):
            prompter.phrase("Sure?", "abandon X")
        assert len(_warnings(tmp_path)) == _job_prompter.MAX_PHRASE_ATTEMPTS


class TestGame:
    """Picking from the library browser."""

    def test_valid_id(self, tmp_path: Path) -> None:
        """An offered app id is returned as an int."""
        with _ids():
            assert _prompter(tmp_path, " 620 ").game("Pick", [730, 620]) == 620
        prompt = next(e for e in read_events(tmp_path) if e["type"] == "prompt")
        assert prompt["app_ids"] == [620, 730]

    def test_empty_goes_back(self, tmp_path: Path) -> None:
        """An empty answer means back to the choice prompt."""
        with _ids():
            assert _prompter(tmp_path, "").game("Pick", [620]) is None

    @pytest.mark.parametrize("bad", ["abc", "999"])
    def test_invalid_answer_asks_again(self, tmp_path: Path, bad: str) -> None:
        """Non-digits and ids outside the offer are refused."""
        with _ids():
            assert _prompter(tmp_path, bad, "620").game("Pick", [620]) == 620
        assert _warnings(tmp_path) == [f"Not a game you can pick here: {bad!r}"]
