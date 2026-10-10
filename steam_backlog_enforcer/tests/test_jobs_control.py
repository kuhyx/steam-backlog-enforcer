"""Tests for ``jobs._control``: answering prompts and cancelling jobs."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.jobs import _control
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    ANSWERS_NAME,
    CANCEL_NAME,
    EventWriter,
    append_jsonl,
    read_jsonl,
)
from steam_backlog_enforcer.tests._jobs_helpers import JOB_ID, make_job

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_ALIVE = "steam_backlog_enforcer.jobs._control.pid_of"
_PID_ALIVE = "steam_backlog_enforcer.jobs._view._pid_alive"
_KILL = "steam_backlog_enforcer.jobs._control.os.kill"


@pytest.fixture(autouse=True)
def _job_process_is_alive() -> Iterator[None]:
    """Make every fake job's pid look alive, so reading it never fails it."""
    with patch(_PID_ALIVE, return_value=True):
        yield


def _waiting_job() -> Path:
    """A job blocked on prompt ``p1``."""
    path = make_job(states=("queued", "running", "waiting_input"), pid="5\n")
    EventWriter(path).emit("prompt", prompt_id="p1", kind="text", message="?")
    return path


class TestOpenPromptId:
    """Which prompt is waiting."""

    def test_no_prompt(self) -> None:
        """A job that never asked has no open prompt."""
        make_job()
        assert _control._open_prompt_id(JOB_ID) is None

    def test_unanswered_prompt_is_open(self) -> None:
        """The latest prompt without an answer."""
        _waiting_job()
        assert _control._open_prompt_id(JOB_ID) == "p1"

    def test_answered_prompt_is_closed(self) -> None:
        """An answer closes it."""
        path = _waiting_job()
        append_jsonl(path / ANSWERS_NAME, {"prompt_id": "p1", "value": "x"})
        assert _control._open_prompt_id(JOB_ID) is None


class TestWriteAnswer:
    """Delivering an answer."""

    def test_writes_answer_line(self) -> None:
        """The answer lands in answers.jsonl."""
        path = _waiting_job()
        with patch(_ALIVE, return_value=5):
            _control.write_answer(JOB_ID, "p1", "yes")
        assert read_jsonl(path / ANSWERS_NAME) == [{"prompt_id": "p1", "value": "yes"}]

    def test_unknown_job(self) -> None:
        """Unknown ids are ``not_found``."""
        with pytest.raises(JobError) as info:
            _control.write_answer(JOB_ID, "p1", "yes")
        assert info.value.code == "not_found"

    def test_finished_job(self) -> None:
        """A finished job takes no answers."""
        make_job(states=("running", "succeeded"))
        with pytest.raises(JobError) as info:
            _control.write_answer(JOB_ID, "p1", "yes")
        assert info.value.code == "invalid_params"
        assert "already finished" in info.value.message

    def test_stale_prompt_id(self) -> None:
        """Only the open prompt can be answered."""
        _waiting_job()
        with patch(_ALIVE, return_value=5), pytest.raises(JobError) as info:
            _control.write_answer(JOB_ID, "old", "yes")
        assert info.value.code == "invalid_params"
        assert "not waiting" in info.value.message

    def test_replayed_answer(self) -> None:
        """A second answer to the same prompt is refused."""
        _waiting_job()
        with patch(_ALIVE, return_value=5):
            _control.write_answer(JOB_ID, "p1", "yes")
            with pytest.raises(JobError):
                _control.write_answer(JOB_ID, "p1", "no")


class TestCancel:
    """Stopping a job."""

    def test_waiting_job_gets_marker(self) -> None:
        """Any command can be cancelled while it waits on a prompt."""
        path = make_job("reset", states=("running", "waiting_input"), pid="5\n")
        with patch(_KILL) as kill:
            _control.cancel(JOB_ID)
        assert (path / CANCEL_NAME).exists()
        kill.assert_not_called()

    def test_not_cancellable_command(self) -> None:
        """A running ``done`` cannot be stopped midway."""
        make_job("done")
        with pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "not_cancellable"

    def test_unknown_command_is_not_cancellable(self) -> None:
        """No flags at all means not cancellable."""
        make_job("mystery")
        with pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "not_cancellable"

    def test_finished_job(self) -> None:
        """A cancellable but finished job is ``invalid_params``."""
        make_job("scan", states=("running", "succeeded"))
        with pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "invalid_params"

    def test_no_process(self) -> None:
        """A running job without a live pid cannot be signalled."""
        make_job("scan", pid="5\n")
        with patch(_ALIVE, return_value=None), pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert "no running process" in info.value.message

    def test_signals_only_the_job_pid(self) -> None:
        """SIGTERM goes to the pid, never a process group."""
        make_job("scan", pid="5\n")
        with patch(_ALIVE, return_value=5), patch(_KILL) as kill:
            _control.cancel(JOB_ID)
        kill.assert_called_once_with(5, signal.SIGTERM)
