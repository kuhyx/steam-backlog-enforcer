"""Tests for observing a gatelock screen hold through ``/proc/locks``.

The probe must never take the lock itself, so every case here is driven by
synthetic ``/proc/locks`` text rather than by acquiring anything.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._screen_hold import (
    ScreenHoldError,
    holder_lock_path,
    screen_hold,
)

SH = "steam_backlog_enforcer._screen_hold"


def _device_field(path: Path) -> str:
    stat = path.stat()
    return f"{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}"


class TestHolderLockPath:
    def test_uses_the_runtime_dir_of_the_session_owner(self) -> None:
        assert holder_lock_path(1000) == Path("/run/user/1000/gatelock/holder.lock")

    def test_differs_per_uid(self) -> None:
        assert holder_lock_path(1000) != holder_lock_path(1001)


class TestScreenHold:
    def test_missing_file_is_not_held_and_not_an_error(self, tmp_path: Path) -> None:
        result = screen_hold(tmp_path / "never-created.lock")
        assert result.held is False
        assert result.holder_pid is None

    def test_reports_held_with_the_holding_pid(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text(
            f"1: FLOCK  ADVISORY  WRITE 4242 {_device_field(lock)} 0 EOF\n"
        )
        with patch(f"{SH}._PROC_LOCKS", locks):
            result = screen_hold(lock)
        assert result.held is True
        assert result.holder_pid == 4242

    def test_reports_free_when_another_file_is_locked(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text("1: FLOCK  ADVISORY  WRITE 4242 00:19:999999 0 EOF\n")
        with patch(f"{SH}._PROC_LOCKS", locks):
            assert screen_hold(lock).held is False

    def test_a_waiter_row_is_not_a_holder(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text(
            f"1: -> FLOCK  ADVISORY  WRITE 4242 {_device_field(lock)} 0 EOF\n"
        )
        with patch(f"{SH}._PROC_LOCKS", locks):
            assert screen_hold(lock).held is False

    def test_rows_without_a_device_field_are_skipped(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text(
            "garbage row with no device\n"
            f"2: FLOCK  ADVISORY  READ 7 {_device_field(lock)} 0 EOF\n"
        )
        with patch(f"{SH}._PROC_LOCKS", locks):
            assert screen_hold(lock).held is True

    def test_short_row_yields_no_pid(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text(f"1: FLOCK {_device_field(lock)}\n")
        with patch(f"{SH}._PROC_LOCKS", locks):
            result = screen_hold(lock)
        assert result.held is True
        assert result.holder_pid is None

    def test_non_numeric_pid_yields_no_pid(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        locks = tmp_path / "locks"
        locks.write_text(
            f"1: FLOCK  ADVISORY  WRITE nope {_device_field(lock)} 0 EOF\n"
        )
        with patch(f"{SH}._PROC_LOCKS", locks):
            assert screen_hold(lock).holder_pid is None

    def test_unreadable_proc_locks_raises(self, tmp_path: Path) -> None:
        lock = tmp_path / "holder.lock"
        lock.touch()
        with (
            patch(f"{SH}._PROC_LOCKS", tmp_path / "absent"),
            pytest.raises(ScreenHoldError),
        ):
            screen_hold(lock)
