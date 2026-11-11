"""Tests for _file_wake: the inotify wait that wakes the enforce loop early.

The real-kernel tests watch a fresh ``tmp_path`` directory, never the real
screen-locker tree. The parsing branches the kernel will not produce on demand
live in ``test_file_wake_events``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._file_wake import FileWake, open_file_wake
from steam_backlog_enforcer.tests._file_wake_timing import (
    LONG,
    PKG,
    SHORT,
    timed_wait,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="log")
def fixture_log(tmp_path: Path) -> Path:
    """A ``log.json`` path inside a directory of its own."""
    directory = tmp_path / "screen_locker"
    directory.mkdir()
    return directory / "log.json"


@pytest.fixture(name="wake")
def fixture_wake(log: Path) -> Iterator[FileWake]:
    """A live watcher on ``log``, closed afterwards."""
    watcher = open_file_wake([log])
    yield watcher
    watcher.close()


class TestRealInotify:
    """Against the kernel, in a tmp directory."""

    def test_atomic_rename_wakes(self, log: Path, wake: FileWake) -> None:
        """An atomic rename onto the watched file wakes the wait early."""
        tmp = log.with_name("log.json.tmp")
        tmp.write_text("{}")
        # Drain the temp file's own events: they must not count as a wake.
        assert wake.wait(SHORT) is False
        tmp.replace(log)
        woke, elapsed = timed_wait(wake, LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_in_place_write_wakes(self, log: Path, wake: FileWake) -> None:
        """Writing the watched file in place wakes the wait early."""
        log.write_text("{}")
        woke, elapsed = timed_wait(wake, LONG)
        assert woke is True
        assert elapsed < 1.0

    def test_other_file_does_not_wake(self, log: Path, wake: FileWake) -> None:
        """A write to a sibling file leaves the wait to time out."""
        log.with_name("other.json").write_text("{}")
        woke, elapsed = timed_wait(wake, SHORT)
        assert woke is False
        assert elapsed >= SHORT

    def test_times_out_without_events(self, wake: FileWake) -> None:
        """With no events the wait runs its full timeout."""
        woke, elapsed = timed_wait(wake, SHORT)
        assert woke is False
        assert elapsed >= SHORT

    def test_two_files_in_one_directory_share_a_watch(self, log: Path) -> None:
        """Two files in one directory both wake through a shared watch."""
        other = log.with_name("ledger.json")
        watcher = open_file_wake([log, other])
        try:
            other.write_text("{}")
            assert watcher.wait(LONG) is True
        finally:
            watcher.close()

    def test_one_missing_directory_keeps_the_other_watch(
        self, log: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A missing directory warns but the other watch still wakes."""
        missing = tmp_path / "gone" / "log.json"
        with caplog.at_level(logging.WARNING, logger=PKG):
            watcher = open_file_wake([missing, log])
        try:
            assert "Cannot watch" in caplog.text
            log.write_text("{}")
            assert watcher.wait(LONG) is True
        finally:
            watcher.close()

    def test_close_twice_is_harmless(self, wake: FileWake) -> None:
        """Closing twice is safe and later waits fall back to sleep."""
        wake.close()
        wake.close()
        # conftest no-ops time.sleep process-wide, so assert the call instead.
        with patch(f"{PKG}.time.sleep") as sleep:
            assert wake.wait(SHORT) is False
        sleep.assert_called_once()


class TestSetupFallback:
    """Every setup failure warns and degrades to a plain sleep."""

    def _assert_plain_sleep(self, watcher: FileWake) -> None:
        """Assert ``watcher.wait`` degrades to one full-length sleep."""
        with patch(f"{PKG}.time.sleep") as sleep:
            assert watcher.wait(LONG) is False
        sleep.assert_called_once()
        assert sleep.call_args.args[0] == pytest.approx(LONG, abs=0.5)

    def test_unwatchable_directory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unwatchable directory warns, names the file, and sleeps."""
        with caplog.at_level(logging.WARNING, logger=PKG):
            watcher = open_file_wake([tmp_path / "missing" / "log.json"])
        assert "Cannot watch" in caplog.text
        assert "log.json" in caplog.text
        self._assert_plain_sleep(watcher)

    def test_no_libc(self, log: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Missing libc warns and degrades to a plain sleep."""
        with (
            caplog.at_level(logging.WARNING, logger=PKG),
            patch(f"{PKG}.ctypes.CDLL", side_effect=OSError("no libc")),
        ):
            watcher = open_file_wake([log])
        assert "inotify unavailable (no libc)" in caplog.text
        self._assert_plain_sleep(watcher)

    def test_init_fails(self, log: Path, caplog: pytest.LogCaptureFixture) -> None:
        """A failed ``inotify_init1`` warns, adds no watch, and sleeps."""
        libc = MagicMock()
        libc.inotify_init1.return_value = -1
        with (
            caplog.at_level(logging.WARNING, logger=PKG),
            patch(f"{PKG}.ctypes.CDLL", return_value=libc),
        ):
            watcher = open_file_wake([log])
        assert "inotify_init1 failed" in caplog.text
        libc.inotify_add_watch.assert_not_called()
        self._assert_plain_sleep(watcher)
