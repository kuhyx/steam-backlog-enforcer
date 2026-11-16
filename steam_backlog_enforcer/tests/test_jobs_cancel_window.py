"""Tests for the cancel window: hiding jobs stop only while hiding games.

A ``done`` job once sat 90+ s in the Steam launch wait holding the one
mutating-job lock, and could not be cancelled. Cancelling is now accepted
only inside the library-hiding phase: the job announces the phase with
``cancel_window`` events, the server signals it only while open, and the
runner turns the SIGTERM into a skipped hide so the job ends normally.
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
import signal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._cancel_window import cancel_window, use_cancel_window
from steam_backlog_enforcer._steam_errors import (
    HidingCancelledError,
    SteamUnavailableError,
)
from steam_backlog_enforcer.jobs import _control, _runner
from steam_backlog_enforcer.jobs._cancel_window import JobCancelWindow
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import EventWriter, read_events
from steam_backlog_enforcer.jobs._job_io import JobLogSink
from steam_backlog_enforcer.jobs._registry import HANDLERS
from steam_backlog_enforcer.jobs._runner import _run_command
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS
from steam_backlog_enforcer.library_hider import try_hide_other_games
from steam_backlog_enforcer.tests._jobs_helpers import JOB_ID, make_job

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

_PID_ALIVE = "steam_backlog_enforcer.jobs._view._pid_alive"
_ALIVE = "steam_backlog_enforcer.jobs._control.pid_of"
_KILL = "steam_backlog_enforcer.jobs._control.os.kill"
_WINDOW_SIGNAL = "steam_backlog_enforcer.jobs._cancel_window.signal"
_GATE = "steam_backlog_enforcer.jobs._runner.enforce_gate"
_HIDE = "steam_backlog_enforcer.library_hider.hide_other_games"


def _window_events(path: Path) -> list[bool]:
    """The ``open`` flag of every cancel_window event, in order."""
    return [bool(e["open"]) for e in read_events(path) if e["type"] == "cancel_window"]


# Every command whose job reaches try_hide_other_games, which opens the window.
_WINDOWED = ("done", "check", "pick", "pick-manual", "hide")


class TestFlags:
    """Which commands have a cancel window."""

    @pytest.mark.parametrize("command", _WINDOWED)
    def test_hiding_commands_have_a_window(self, command: str) -> None:
        """Each is mutating, not generally cancellable, but has the window."""
        flags = JOB_FLAGS[command]
        assert flags.mutating
        assert not flags.cancellable
        assert flags.cancel_window

    def test_nothing_else_has_one(self) -> None:
        """Every other command keeps its old cancel rules."""
        others = {k for k, f in JOB_FLAGS.items() if f.cancel_window}
        assert others == set(_WINDOWED)


class TestControlCancel:
    """_control.cancel honours the window for the commands that have one."""

    @pytest.fixture(autouse=True)
    def _alive(self) -> Iterator[None]:
        with patch(_PID_ALIVE, return_value=True):
            yield

    def test_accepted_while_the_window_is_open(self) -> None:
        """Inside the window, ``done`` gets SIGTERM on its own pid."""
        path = make_job("done", pid="5\n")
        EventWriter(path).emit("cancel_window", open=True)
        with patch(_ALIVE, return_value=5), patch(_KILL) as kill:
            _control.cancel(JOB_ID)
        kill.assert_called_once_with(5, signal.SIGTERM)

    def test_refused_before_the_window_opens(self) -> None:
        """A windowed job stays uncancellable until its window opens."""
        make_job("done", pid="5\n")
        with patch(_KILL) as kill, pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "not_cancellable"
        kill.assert_not_called()

    def test_refused_after_the_window_closes(self) -> None:
        """Once hiding is over the job can no longer be stopped."""
        path = make_job("check", pid="5\n")
        writer = EventWriter(path)
        writer.emit("cancel_window", open=True)
        writer.emit("cancel_window", open=False)
        with patch(_KILL) as kill, pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "not_cancellable"
        kill.assert_not_called()

    def test_window_event_does_not_open_other_commands(self) -> None:
        """A command without the flag ignores any window event."""
        path = make_job("abandon-pick", pid="5\n")
        EventWriter(path).emit("cancel_window", open=True)
        with patch(_KILL) as kill, pytest.raises(JobError) as info:
            _control.cancel(JOB_ID)
        assert info.value.code == "not_cancellable"
        kill.assert_not_called()


class TestJobCancelWindow:
    """JobCancelWindow: the SIGTERM handler and the events, in order."""

    @staticmethod
    def _body(*, fail: bool) -> None:
        """The hide inside the window: fine, or aborted by a cancel."""
        if fail:
            raise HidingCancelledError

    def _enter(self, *, fail: bool = False) -> MagicMock:
        """Run one window against mocks; return the recorded calls."""
        path = make_job("done")
        writer = MagicMock(wraps=EventWriter(path))
        calls = MagicMock()
        calls.attach_mock(writer.emit, "emit")
        fake_signal = MagicMock()
        fake_signal.SIGTERM = signal.SIGTERM
        fake_signal.signal.return_value = "previous"
        calls.attach_mock(fake_signal.signal, "signal")
        with (
            patch(_WINDOW_SIGNAL, fake_signal),
            suppress(HidingCancelledError),
            JobCancelWindow(writer)(),
        ):
            self._body(fail=fail)
        return calls

    def test_handler_is_installed_before_open_and_restored_before_close(
        self,
    ) -> None:
        """The marker is only visible while a handler can act on it."""
        calls = self._enter()
        names = [c[0] for c in calls.mock_calls]
        assert names == ["signal", "emit", "signal", "emit"]
        assert calls.mock_calls[1].kwargs == {"open": True}
        assert calls.mock_calls[2].args == (signal.SIGTERM, "previous")
        assert calls.mock_calls[3].kwargs == {"open": False}

    def test_window_closes_when_the_body_raises(self) -> None:
        """An aborted hide still restores the handler and closes the window."""
        names = [c[0] for c in self._enter(fail=True).mock_calls]
        assert names == ["signal", "emit", "signal", "emit"]

    def test_sigterm_handler_raises_a_hide_skip_once(self) -> None:
        """SIGTERM inside the window raises an error ``try_hide`` turns to a skip.

        The handler also ignores any later SIGTERM, so a second cancel cannot
        interrupt the cleanup. Called under a mocked ``signal``: a real call
        would change the test process's own SIGTERM disposition.
        """
        handler = self._enter().mock_calls[0].args[1]
        fake_signal = MagicMock()
        with patch(_WINDOW_SIGNAL, fake_signal), pytest.raises(HidingCancelledError):
            handler(signal.SIGTERM, None)
        fake_signal.signal.assert_called_once_with(
            fake_signal.SIGTERM, fake_signal.SIG_IGN
        )
        assert issubclass(HidingCancelledError, SteamUnavailableError)


class TestHideUsesTheWindow:
    """try_hide_other_games runs the hide inside whatever window is installed."""

    @staticmethod
    def _recorder(seen: list[str]) -> Callable[[], AbstractContextManager[None]]:
        @contextmanager
        def window() -> Iterator[None]:
            seen.append("open")
            try:
                yield
            finally:
                seen.append("close")

        return window

    def test_no_window_installed_is_a_noop(self) -> None:
        """The CLI and the daemon have no window; hiding is unchanged."""
        with cancel_window():
            pass
        with patch(_HIDE, return_value=2):
            assert try_hide_other_games([1], {2}) == (2, None)

    def test_hide_runs_between_open_and_close(self) -> None:
        """The window brackets exactly the hide."""
        seen: list[str] = []

        def hide(*_args: object) -> int:
            seen.append("hide")
            return 3

        with use_cancel_window(self._recorder(seen)), patch(_HIDE, side_effect=hide):
            assert try_hide_other_games([1], {2}) == (3, None)
        assert seen == ["open", "hide", "close"]

    def test_cancel_during_hide_is_a_skip_not_a_failure(self) -> None:
        """A cancel mid-hide is reported as a skipped hide; the window closes."""
        seen: list[str] = []
        with (
            use_cancel_window(self._recorder(seen)),
            patch(_HIDE, side_effect=HidingCancelledError("Cancelled")),
        ):
            assert try_hide_other_games([1], {2}) == (0, "Cancelled")
        assert seen == ["open", "close"]


class TestRunnerWiring:
    """The runner installs the window only for commands that have one."""

    def _run(self, command: str) -> list[bool]:
        path = make_job(command)
        writer = EventWriter(path)

        def handler(*_args: object) -> None:
            with cancel_window():
                pass

        with (
            patch.object(signal, "signal"),
            patch.object(_runner, "_hold_lock", return_value=None),
            patch.dict(HANDLERS, {command: handler}),
            patch(_GATE),
        ):
            _run_command(path, writer, JobLogSink(writer), {"command": command})
        return _window_events(path)

    def test_done_opens_and_closes_a_window(self) -> None:
        """A ``done`` job reports the window open, then closed."""
        assert self._run("done") == [True, False]

    def test_abandon_pick_has_no_window(self) -> None:
        """A command without the flag never reports one."""
        assert self._run("abandon-pick") == []
