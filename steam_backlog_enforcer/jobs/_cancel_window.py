"""The job side of a cancel window: announce it, and turn SIGTERM into a skip.

``done`` and ``check`` cannot be stopped midway, except while they hide games
in the Steam library (see :mod:`steam_backlog_enforcer._cancel_window`). While
a window is open the job writes ``cancel_window`` events (``open: true`` then
``open: false``), which the server reads to accept a cancel and the UI reads
to show its button, and a SIGTERM raises :class:`HidingCancelledError`. The hide
turns that into a skip, so the job finishes normally and drops the lock.
"""

from __future__ import annotations

from contextlib import contextmanager
import signal
from typing import TYPE_CHECKING

from steam_backlog_enforcer._steam_errors import HidingCancelledError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

    from steam_backlog_enforcer.jobs._events import EventWriter

CANCEL_WINDOW_EVENT = "cancel_window"


def _raise_cancelled(_signum: int, _frame: FrameType | None) -> None:
    """SIGTERM inside the window: abort the hide, once. No I/O, as in the runner.

    Ignoring further SIGTERMs first means a second cancel cannot interrupt the
    cleanup that restores the previous handler and closes the window.
    """
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    msg = "Cancelled"
    raise HidingCancelledError(msg)


class JobCancelWindow:
    """Builds the context manager that brackets one cancellable phase."""

    def __init__(self, writer: EventWriter) -> None:
        """Bind to the job's event writer."""
        self._writer = writer

    @contextmanager
    def __call__(self) -> Iterator[None]:
        """Open the window for the body, then close it, however it ends.

        The handler goes in before ``open`` is written and the previous one
        comes back before ``close``, so the server only ever sees a window
        the job can act on. The previous handler is restored rather than
        assumed to be "ignore": a cancellable command already had its own.
        """
        previous = signal.signal(signal.SIGTERM, _raise_cancelled)
        try:
            self._writer.emit(CANCEL_WINDOW_EVENT, open=True)
            yield
        finally:
            signal.signal(signal.SIGTERM, previous)
            self._writer.emit(CANCEL_WINDOW_EVENT, open=False)
