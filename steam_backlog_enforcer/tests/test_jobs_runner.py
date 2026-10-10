"""Tests for ``jobs._runner``: gating, running and ending one job."""

from __future__ import annotations

import json
import logging
import os
import signal
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._progress import current_progress
from steam_backlog_enforcer._prompter import PromptAbortedError
from steam_backlog_enforcer.jobs import _runner
from steam_backlog_enforcer.jobs._errors import (
    JobCancelledError,
    JobError,
    PrivilegedViaDaemonError,
)
from steam_backlog_enforcer.jobs._events import (
    PID_NAME,
    RESULT_NAME,
    EventWriter,
    read_events,
)
from steam_backlog_enforcer.jobs._job_io import JobLogSink
from steam_backlog_enforcer.tests._jobs_helpers import make_job

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from steam_backlog_enforcer._progress import Progress
    from steam_backlog_enforcer._prompter import Prompter

_GATE = "steam_backlog_enforcer.jobs._runner.enforce_gate"
_REASON = "steam_backlog_enforcer.jobs._runner.lock_reason"
_RUN = "steam_backlog_enforcer.jobs._runner._run_command"


@pytest.fixture(autouse=True)
def _no_side_effects() -> Iterator[None]:
    """No real signal handlers and no real lock for the fake commands."""
    with (
        patch.object(signal, "signal"),
        patch.object(_runner, "_hold_lock", return_value=None),
    ):
        yield


def _run(
    handler: Callable[..., Any],
    *,
    command: str = "scan",
    request: dict[str, Any] | None = None,
) -> tuple[_runner._Outcome, Path]:
    """Run *handler* as the job for *command* and return the outcome."""
    path = make_job(command)
    writer = EventWriter(path)
    sink = JobLogSink(writer)
    body = request or {"command": command, "params": {"x": 1}}
    with patch.dict(_runner.HANDLERS, {command: handler}), patch(_GATE):
        return _runner._run_command(path, writer, sink, body), path


class TestRunCommand:
    """The gate, the handler and the verdict."""

    def test_unknown_command_is_refused(self) -> None:
        """Commands outside the tables never run."""
        path = make_job()
        writer = EventWriter(path)
        outcome = _runner._run_command(
            path, writer, JobLogSink(writer), {"command": "frobnicate"}
        )
        assert outcome.exit_code == _runner.EXIT_REFUSED
        assert "does not run as a job" in outcome.summary

    def test_success_with_data_and_adapters(self) -> None:
        """Echo, progress and params reach the handler; running is announced."""
        seen: dict[str, Any] = {}

        def handler(
            params: Mapping[str, object], progress: Progress, prompter: Prompter
        ) -> dict[str, int]:
            seen["params"] = dict(params)
            seen["prompter"] = prompter
            progress.phase("Working", 2)
            current_progress().advance("a")
            _echo("Scanned 2 games")
            return {"games": 2}

        outcome, path = _run(handler)
        assert (outcome.state, outcome.summary, outcome.data) == (
            "succeeded",
            "Scanned 2 games",
            {"games": 2},
        )
        assert seen["params"] == {"x": 1}
        assert seen["prompter"].interactive is True
        types = [e["type"] for e in read_events(path)]
        assert "progress" in types
        assert {"type": "state", "state": "running"}.items() <= next(
            e for e in read_events(path)[2:] if e["type"] == "state"
        ).items()

    def test_logging_handler_is_removed_afterwards(self) -> None:
        """WARNING records reach the job while it runs, not after."""
        root = logging.getLogger()
        before = list(root.handlers)

        def handler(*_args: object) -> None:
            logging.getLogger("job.test").warning("careful")

        outcome, path = _run(handler)
        assert outcome.state == "succeeded"
        assert root.handlers == before
        assert any(e.get("message") == "careful" for e in read_events(path))

    def test_missing_params_default_to_empty(self) -> None:
        """A request without params still runs."""
        seen: list[dict[str, Any]] = []
        _run(lambda params, *_: seen.append(dict(params)), request={"command": "scan"})
        assert seen == [{}]

    @pytest.mark.parametrize(
        ("reason", "summary"),
        [("Total block", "Total block"), (None, "Refused by the lock gate.")],
    )
    def test_gate_refusal(self, reason: str | None, summary: str) -> None:
        """The gate's banner becomes logs; the summary is the one-line reason."""
        path = make_job()
        writer = EventWriter(path)
        sink = JobLogSink(writer)
        handler = MagicMock()
        with (
            patch.dict(_runner.HANDLERS, {"scan": handler}),
            patch(_GATE, side_effect=SystemExit(1)),
            patch(_REASON, return_value=reason),
        ):
            outcome = _runner._run_command(path, writer, sink, {"command": "scan"})
        handler.assert_not_called()
        assert (outcome.summary, outcome.exit_code) == (summary, _runner.EXIT_REFUSED)

    @pytest.mark.parametrize("code", [0, None])
    def test_clean_system_exit_is_success(self, code: int | None) -> None:
        """``sys.exit(0)`` ends the command normally."""

        def handler(*_args: object) -> None:
            _echo("Nothing to do")
            raise SystemExit(code)

        outcome, _ = _run(handler)
        assert (outcome.state, outcome.summary) == ("succeeded", "Nothing to do")

    def test_failing_system_exit_uses_last_line(self) -> None:
        """A non-zero exit fails with the last printed line."""

        def handler(*_args: object) -> None:
            _echo("Could not reach Steam")
            raise SystemExit(2)

        outcome, _ = _run(handler)
        assert (outcome.state, outcome.summary) == ("failed", "Could not reach Steam")

    def test_failing_system_exit_without_output(self) -> None:
        """Silent non-zero exits name the status."""

        def handler(*_args: object) -> None:
            raise SystemExit(3)

        assert _run(handler)[0].summary == "Exited with status 3."


class TestRunJob:
    """Start to finish, including every way a job can end."""

    def test_end_to_end_success(self) -> None:
        """Pid file, running, result and final state are all written."""
        path = make_job()
        (path / "request.json").write_text(
            json.dumps({"command": "scan", "params": {}}), encoding="utf-8"
        )

        def handler(*_args: object) -> dict[str, str]:
            _echo("Scan complete")
            return {"ok": "yes"}

        with patch.dict(_runner.HANDLERS, {"scan": handler}), patch(_GATE):
            code = _runner.run_job(path)
        assert code == 0
        assert (path / PID_NAME).read_text(encoding="utf-8") == f"{os.getpid()}\n"
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        assert result["summary"] == "Scan complete"
        assert result["data"] == {"ok": "yes"}
        assert read_events(path)[-1]["state"] == "succeeded"

    @pytest.mark.parametrize(
        ("raised", "state", "code", "summary"),
        [
            (JobCancelledError(), "cancelled", 130, "Cancelled."),
            (KeyboardInterrupt(), "cancelled", 130, "Cancelled."),
            (PromptAbortedError("Declined."), "failed", 1, "Declined."),
            (PromptAbortedError(), "failed", 1, "Aborted."),
            (JobError("Another job", code="busy"), "failed", 2, "Another job"),
            (
                PrivilegedViaDaemonError("unblock"),
                "failed",
                2,
                "unblock runs in the root daemon, not as a web job.",
            ),
            (RuntimeError("kaput"), "failed", 1, "RuntimeError: kaput"),
            (SystemExit(4), "failed", 1, "SystemExit: 4"),
        ],
    )
    def test_endings(
        self, raised: BaseException, state: str, code: int, summary: str
    ) -> None:
        """Whatever the command raises, one result and a final state follow."""
        path = make_job()
        with patch(_RUN, side_effect=raised):
            assert _runner.run_job(path) == code
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        assert (result["state"], result["summary"]) == (state, summary)
        events = read_events(path)
        assert [e["type"] for e in events[-2:]] == ["result", "state"]
        assert events[-1]["state"] == state
