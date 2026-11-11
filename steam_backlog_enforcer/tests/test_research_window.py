"""The research window: lock binding, fail-closed live record, the clock."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _research_record as store
from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer.tests._research_helpers import (
    HOUR,
    LOCK_END,
    LOCK_START,
    NOW,
    lock,
    make_record,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import Paths

NOW_PATCH = "steam_backlog_enforcer._research_window.now"


class TestLiveRecord:
    """live_record is the daemon's fail-closed view of the file."""

    def test_no_lock_means_no_window(self) -> None:
        """Test that a record without an active total block is ignored."""
        window.write_record(make_record())
        assert window.live_record() is None

    def test_no_record(self, total_block_paths: Paths) -> None:
        """Test that a lock without a record has no window."""
        lock(total_block_paths)
        with patch(NOW_PATCH, return_value=NOW):
            assert window.live_record() is None

    def test_matching_record(self, total_block_paths: Paths) -> None:
        """Test that a record for the live lock is returned."""
        lock(total_block_paths)
        window.write_record(make_record())
        with patch(NOW_PATCH, return_value=NOW):
            assert window.live_record() == make_record()

    def test_other_locks_record_is_ignored(self, total_block_paths: Paths) -> None:
        """Test that last month's record does not open this lock."""
        lock(total_block_paths)
        window.write_record(make_record(lock_started_at=LOCK_START - 99.0))
        with patch(NOW_PATCH, return_value=NOW):
            assert window.live_record() is None

    def test_corrupt_record_is_no_window_and_logged_once(
        self, total_block_paths: Paths, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that corruption fails closed and does not spam every tick."""
        lock(total_block_paths)
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        with patch(NOW_PATCH, return_value=NOW), caplog.at_level(logging.ERROR):
            assert window.live_record() is None
            assert window.live_record() is None
        assert len([r for r in caplog.records if "research" in r.message]) == 1

    def test_corruption_is_logged_again_after_recovery(
        self, total_block_paths: Paths, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that a record that heals and breaks again is reported again."""
        lock(total_block_paths)
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        with patch(NOW_PATCH, return_value=NOW), caplog.at_level(logging.ERROR):
            window.live_record()
            window.write_record(make_record())
            assert window.live_record() is not None
            store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
            window.live_record()
        assert len([r for r in caplog.records if "research" in r.message]) == 2


class TestOpenNow:
    """live_record plus is_open is the daemon's whole decision."""

    @staticmethod
    def _open_at(at: float) -> bool:
        with patch(NOW_PATCH, return_value=at):
            record = window.live_record()
        return record is not None and record.is_open(at)

    def test_open_window(self, total_block_paths: Paths) -> None:
        """Test that an open window on the live lock is open."""
        lock(total_block_paths)
        window.write_record(make_record())
        assert self._open_at(NOW) is True

    def test_expired_window(self, total_block_paths: Paths) -> None:
        """Test that a passed deadline is not open."""
        lock(total_block_paths)
        window.write_record(make_record())
        assert self._open_at(NOW + 2 * HOUR) is False

    def test_clock_in_the_past_is_not_open(self, total_block_paths: Paths) -> None:
        """Test that a clock before opening is fully blocked."""
        lock(total_block_paths)
        window.write_record(make_record())
        assert self._open_at(NOW - 3 * HOUR) is False

    def test_closed_latch_is_not_open(self, total_block_paths: Paths) -> None:
        """Test that a latched window never reopens."""
        lock(total_block_paths)
        window.write_record(make_record(closed=True))
        assert self._open_at(NOW) is False

    def test_missing_state_is_fully_blocked(self, total_block_paths: Paths) -> None:
        """Test that no record at all is the blocked default."""
        lock(total_block_paths)
        assert self._open_at(NOW) is False

    def test_lock_identity_tolerates_float_rounding(
        self, total_block_paths: Paths
    ) -> None:
        """Test that sub-second noise still matches, whole seconds do not."""
        lock(total_block_paths)
        window.write_record(make_record(lock_started_at=LOCK_START + 0.4))
        assert self._open_at(NOW) is True
        window.write_record(make_record(lock_started_at=LOCK_START + 2.0))
        assert self._open_at(NOW) is False

    def test_lock_without_start_is_no_lock(self, total_block_paths: Paths) -> None:
        """Test that a lock file lacking started_at cannot host a window."""
        total_block_paths.lock_file.write_text(
            json.dumps({"until": LOCK_END}), encoding="utf-8"
        )
        window.write_record(make_record())
        assert self._open_at(NOW) is False

    def test_now_is_the_wall_clock(self) -> None:
        """Test that now() reads time.time()."""
        with patch("steam_backlog_enforcer._research_window.time.time") as clock:
            clock.return_value = 42.5
            assert window.now() == 42.5


class TestResearchUsed:
    """research_used decides whether the Steam folder may be purged."""

    @staticmethod
    def _used() -> bool:
        with patch(NOW_PATCH, return_value=NOW):
            return window.research_used()

    def test_never_used(self, total_block_paths: Paths) -> None:
        """Test that a lock without a record purges as before."""
        lock(total_block_paths)
        assert self._used() is False

    def test_no_lock(self) -> None:
        """Test that without a total block nothing is kept on its account."""
        window.write_record(make_record())
        assert self._used() is False

    @pytest.mark.parametrize("closed", [False, True])
    def test_used_for_this_lock(
        self, total_block_paths: Paths, *, closed: bool
    ) -> None:
        """Test that an open or ended window both protect the Steam folder."""
        lock(total_block_paths)
        window.write_record(make_record(closed=closed))
        assert self._used() is True

    def test_other_locks_record_does_not_protect(
        self, total_block_paths: Paths
    ) -> None:
        """Test that last lock's window gives this lock no exemption."""
        lock(total_block_paths)
        window.write_record(make_record(lock_started_at=LOCK_START - 99.0))
        assert self._used() is False

    def test_unreadable_record_keeps_the_data(self, total_block_paths: Paths) -> None:
        """Test that when the record cannot say, nothing irreversible happens."""
        lock(total_block_paths)
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        assert self._used() is True
