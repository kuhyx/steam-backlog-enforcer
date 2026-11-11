"""Tests for _file_wake's event parsing, fed through a pipe.

The branches the kernel will not produce on demand (queue overflow, a watch
torn down) are fed through a pipe carrying hand-packed ``inotify_event``
records, which is byte-for-byte what ``os.read`` returns.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._file_wake import (
    _EVENT_HEADER,
    _IN_CLOSE_WRITE,
    _IN_IGNORED,
    _IN_MOVED_TO,
    _IN_Q_OVERFLOW,
    FileWake,
)
from steam_backlog_enforcer.tests._file_wake_timing import (
    LONG,
    PKG,
    SHORT,
    timed_wait,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _event(wd: int, mask: int, name: bytes = b"") -> bytes:
    """Pack one ``struct inotify_event`` with a NUL-padded name."""
    padded = name + b"\0" * (16 - len(name) % 16) if name else b""
    return _EVENT_HEADER.pack(wd, mask, 0, len(padded)) + padded


type Piped = Callable[[dict[int, frozenset[str]]], tuple[FileWake, int]]


@pytest.fixture(name="piped")
def fixture_piped() -> Iterator[Piped]:
    """Build FileWakes reading a non-blocking pipe instead of inotify.

    Teardown goes through ``FileWake.close`` (idempotent), never a raw
    ``os.close`` of the read end: a watcher that degraded already closed it,
    and the number may since belong to some unrelated descriptor.
    """
    made: list[tuple[FileWake, int]] = []

    def make(names: dict[int, frozenset[str]]) -> tuple[FileWake, int]:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        made.append((FileWake(read_fd, names), write_fd))
        return made[-1]

    yield make
    for watcher, write_fd in made:
        watcher.close()
        os.close(write_fd)


class TestEventParsing:
    """Branches fed through a pipe of hand-packed events."""

    def test_queue_overflow_wakes(self, piped: Piped) -> None:
        """A queue overflow counts as a possible change and wakes."""
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        # wd -1 with no name: an overflow says nothing about *which* file, so
        # it must count as "maybe changed" rather than be dropped.
        os.write(write_fd, _event(-1, _IN_Q_OVERFLOW))
        woke, elapsed = timed_wait(watcher, LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_unrelated_event_on_unknown_wd_is_ignored(self, piped: Piped) -> None:
        """An event on an unknown watch descriptor does not wake."""
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, _event(7, _IN_CLOSE_WRITE, b"log.json"))
        assert watcher.wait(SHORT) is False

    def test_removed_watch_degrades_with_warning(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Losing the only watch warns and degrades to a sleep."""
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, _event(1, _IN_IGNORED))
        with (
            caplog.at_level(logging.WARNING, logger=PKG),
            patch(f"{PKG}.time.sleep") as sleep,
        ):
            assert watcher.wait(LONG) is False
        assert "the watched directory was removed" in caplog.text
        sleep.assert_called_once()

    def test_one_removed_watch_of_two_keeps_watching(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Losing one of two watches stays silent and keeps waking."""
        names = {1: frozenset({"a.json"}), 2: frozenset({"b.json"})}
        watcher, write_fd = piped(names)
        os.write(write_fd, _event(1, _IN_IGNORED))
        with caplog.at_level(logging.WARNING, logger=PKG):
            assert watcher.wait(SHORT) is False
        assert caplog.text == ""
        os.write(write_fd, _event(2, _IN_MOVED_TO, b"b.json"))
        assert watcher.wait(LONG) is True

    def test_spurious_readiness_keeps_waiting(self, piped: Piped) -> None:
        """A readable fd with nothing to read keeps waiting."""
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, b"x")
        with patch(f"{PKG}.os.read", side_effect=BlockingIOError):
            woke, elapsed = timed_wait(watcher, SHORT)
        assert woke is False
        assert elapsed >= SHORT

    def test_read_error_degrades_with_warning(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A read error warns and degrades to a sleep."""
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, b"x")
        with (
            caplog.at_level(logging.WARNING, logger=PKG),
            patch(f"{PKG}.os.read", side_effect=OSError("EIO")),
            patch(f"{PKG}.time.sleep") as sleep,
        ):
            assert watcher.wait(LONG) is False
        assert "reading inotify events failed: EIO" in caplog.text
        sleep.assert_called_once()
