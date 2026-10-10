"""User-facing CLI output.

A leaf module so every command can print without importing the install
machinery. Split out of :mod:`steam_backlog_enforcer.game_install` to keep
that module under the 250-line cap.

Output normally goes to stdout. A web job installs a sink with
:func:`routed_echo`, and every ``_echo`` inside it becomes a ``log`` event
instead: the commands keep one way of talking, whoever is listening.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# Receives the raw text (message + end) when set; stdout otherwise.
_SINK: ContextVar[Callable[[str], None] | None] = ContextVar("echo_sink", default=None)


def _echo(msg: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write user-facing CLI output to stdout, or to the active sink.

    Args:
        msg: Text to output.
        end: String appended after the message.
        flush: Whether to flush stdout immediately.
    """
    sink = _SINK.get()
    if sink is not None:
        sink(msg + end)
        return
    sys.stdout.write(msg + end)
    if flush:
        sys.stdout.flush()


@contextmanager
def routed_echo(sink: Callable[[str], None]) -> Iterator[None]:
    """Send every ``_echo`` in this context to *sink* instead of stdout.

    Args:
        sink: Called with the raw text, ``end`` included, so it can treat
            carriage returns and newlines the way a terminal would.
    """
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)
