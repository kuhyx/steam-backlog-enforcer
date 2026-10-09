"""Tests for _file_wake: the inotify wait that wakes the enforce loop early.

The real-kernel tests watch a fresh ``tmp_path`` directory, never the real
screen-locker tree. The parsing branches the kernel will not produce on demand
(queue overflow, a watch torn down) are fed through a pipe carrying hand-packed
``inotify_event`` records, which is byte-for-byte what ``os.read`` returns.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _file_wake
from steam_backlog_enforcer._file_wake import FileWake, open_file_wake

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._file_wake"
# Far above real latency so CI cannot flake; elapsed asserts pin "early".
_LONG = 5.0
_SHORT = 0.05


@pytest.fixture
def log(tmp_path: Path) -> Path:
    """A ``log.json`` path inside a directory of its own."""
    directory = tmp_path / "screen_locker"
    directory.mkdir()
    return directory / "log.json"


@pytest.fixture
def wake(log: Path) -> Iterator[FileWake]:
    """A live watcher on ``log``, closed afterwards."""
    watcher = open_file_wake([log])
    yield watcher
    watcher.close()


def _timed_wait(watcher: FileWake, timeout: float) -> tuple[bool, float]:
    """Run ``watcher.wait`` and measure how long it took."""
    start = time.monotonic()
    woke = watcher.wait(timeout)
    return woke, time.monotonic() - start


def _event(wd: int, mask: int, name: bytes = b"") -> bytes:
    """Pack one ``struct inotify_event`` with a NUL-padded name."""
    padded = name + b"\0" * (16 - len(name) % 16) if name else b""
    return _file_wake._EVENT_HEADER.pack(wd, mask, 0, len(padded)) + padded


type Piped = Callable[[dict[int, frozenset[str]]], tuple[FileWake, int]]


@pytest.fixture
def piped() -> Iterator[Piped]:
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


class TestRealInotify:
    """Against the kernel, in a tmp directory."""

    def test_atomic_rename_wakes(self, log: Path, wake: FileWake) -> None:
        tmp = log.with_name("log.json.tmp")
        tmp.write_text("{}")
        # Drain the temp file's own events: they must not count as a wake.
        assert wake.wait(_SHORT) is False
        tmp.replace(log)
        woke, elapsed = _timed_wait(wake, _LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_in_place_write_wakes(self, log: Path, wake: FileWake) -> None:
        log.write_text("{}")
        woke, elapsed = _timed_wait(wake, _LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_other_file_does_not_wake(self, log: Path, wake: FileWake) -> None:
        log.with_name("other.json").write_text("{}")
        woke, elapsed = _timed_wait(wake, _SHORT)
        assert woke is False
        assert elapsed >= _SHORT

    def test_times_out_without_events(self, wake: FileWake) -> None:
        woke, elapsed = _timed_wait(wake, _SHORT)
        assert woke is False
        assert elapsed >= _SHORT

    def test_two_files_in_one_directory_share_a_watch(self, log: Path) -> None:
        other = log.with_name("ledger.json")
        watcher = open_file_wake([log, other])
        try:
            other.write_text("{}")
            assert watcher.wait(_LONG) is True
        finally:
            watcher.close()

    def test_one_missing_directory_keeps_the_other_watch(
        self, log: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        missing = tmp_path / "gone" / "log.json"
        with caplog.at_level(logging.WARNING, logger=_PKG):
            watcher = open_file_wake([missing, log])
        try:
            assert "Cannot watch" in caplog.text
            log.write_text("{}")
            assert watcher.wait(_LONG) is True
        finally:
            watcher.close()

    def test_close_twice_is_harmless(self, wake: FileWake) -> None:
        wake.close()
        wake.close()
        # conftest no-ops time.sleep process-wide, so assert the call instead.
        with patch(f"{_PKG}.time.sleep") as sleep:
            assert wake.wait(_SHORT) is False
        sleep.assert_called_once()


class TestSetupFallback:
    """Every setup failure warns and degrades to a plain sleep."""

    def _assert_plain_sleep(self, watcher: FileWake) -> None:
        with patch(f"{_PKG}.time.sleep") as sleep:
            assert watcher.wait(_LONG) is False
        sleep.assert_called_once()
        assert sleep.call_args.args[0] == pytest.approx(_LONG, abs=0.5)

    def test_unwatchable_directory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_PKG):
            watcher = open_file_wake([tmp_path / "missing" / "log.json"])
        assert "Cannot watch" in caplog.text
        assert "log.json" in caplog.text
        self._assert_plain_sleep(watcher)

    def test_no_libc(self, log: Path, caplog: pytest.LogCaptureFixture) -> None:
        with (
            caplog.at_level(logging.WARNING, logger=_PKG),
            patch(f"{_PKG}.ctypes.CDLL", side_effect=OSError("no libc")),
        ):
            watcher = open_file_wake([log])
        assert "inotify unavailable (no libc)" in caplog.text
        self._assert_plain_sleep(watcher)

    def test_init_fails(self, log: Path, caplog: pytest.LogCaptureFixture) -> None:
        libc = MagicMock()
        libc.inotify_init1.return_value = -1
        with (
            caplog.at_level(logging.WARNING, logger=_PKG),
            patch(f"{_PKG}.ctypes.CDLL", return_value=libc),
        ):
            watcher = open_file_wake([log])
        assert "inotify_init1 failed" in caplog.text
        libc.inotify_add_watch.assert_not_called()
        self._assert_plain_sleep(watcher)


class TestEventParsing:
    """Branches fed through a pipe of hand-packed events."""

    def test_queue_overflow_wakes(self, piped: Piped) -> None:
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        # wd -1 with no name: an overflow says nothing about *which* file, so
        # it must count as "maybe changed" rather than be dropped.
        os.write(write_fd, _event(-1, _file_wake._IN_Q_OVERFLOW))
        woke, elapsed = _timed_wait(watcher, _LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_unrelated_event_on_unknown_wd_is_ignored(self, piped: Piped) -> None:
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, _event(7, _file_wake._IN_CLOSE_WRITE, b"log.json"))
        assert watcher.wait(_SHORT) is False

    def test_removed_watch_degrades_with_warning(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, _event(1, _file_wake._IN_IGNORED))
        with (
            caplog.at_level(logging.WARNING, logger=_PKG),
            patch(f"{_PKG}.time.sleep") as sleep,
        ):
            assert watcher.wait(_LONG) is False
        assert "the watched directory was removed" in caplog.text
        sleep.assert_called_once()

    def test_one_removed_watch_of_two_keeps_watching(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        names = {1: frozenset({"a.json"}), 2: frozenset({"b.json"})}
        watcher, write_fd = piped(names)
        os.write(write_fd, _event(1, _file_wake._IN_IGNORED))
        with caplog.at_level(logging.WARNING, logger=_PKG):
            assert watcher.wait(_SHORT) is False
        assert caplog.text == ""
        os.write(write_fd, _event(2, _file_wake._IN_MOVED_TO, b"b.json"))
        assert watcher.wait(_LONG) is True

    def test_spurious_readiness_keeps_waiting(self, piped: Piped) -> None:
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, b"x")
        with patch(f"{_PKG}.os.read", side_effect=BlockingIOError):
            woke, elapsed = _timed_wait(watcher, _SHORT)
        assert woke is False
        assert elapsed >= _SHORT

    def test_read_error_degrades_with_warning(
        self, piped: Piped, caplog: pytest.LogCaptureFixture
    ) -> None:
        watcher, write_fd = piped({1: frozenset({"log.json"})})
        os.write(write_fd, b"x")
        with (
            caplog.at_level(logging.WARNING, logger=_PKG),
            patch(f"{_PKG}.os.read", side_effect=OSError("EIO")),
            patch(f"{_PKG}.time.sleep") as sleep,
        ):
            assert watcher.wait(_LONG) is False
        assert "reading inotify events failed: EIO" in caplog.text
        sleep.assert_called_once()
