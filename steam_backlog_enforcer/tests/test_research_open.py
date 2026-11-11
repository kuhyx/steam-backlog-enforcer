"""Opening a research window: the 48 h cap, once per lock, fail closed."""

from __future__ import annotations

from datetime import UTC, datetime
import os
import time
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
    from collections.abc import Iterator

    from steam_backlog_enforcer._research_record import ResearchRecord
    from steam_backlog_enforcer.tests._total_block_paths import Paths

NOW_PATCH = "steam_backlog_enforcer._research_window.now"


def _at(offset: float) -> datetime:
    """The instant NOW + *offset* seconds, timezone-aware."""
    return datetime.fromtimestamp(NOW + offset, tz=UTC)


def _open(offset: float) -> ResearchRecord:
    with patch(NOW_PATCH, return_value=NOW):
        return window.open_research_window(_at(offset))


@pytest.fixture(name="live")
def _live(total_block_paths: Paths) -> None:
    """An active 6-day lock, two days in."""
    lock(total_block_paths)


@pytest.mark.usefixtures("live")
class TestOpen:
    """The happy path and the bounds around it."""

    def test_records_the_window_for_this_lock(self) -> None:
        """Test that a valid expiry is stored with the lock's identity."""
        record = _open(10 * HOUR)
        assert record == window.read_record()
        assert (record.lock_started_at, record.lock_until) == (LOCK_START, LOCK_END)
        assert (record.opened_at, record.until) == (NOW, NOW + 10 * HOUR)
        assert (record.closed, record.store_reblocked) == (False, False)

    def test_exactly_48_hours_is_allowed(self) -> None:
        """Test that the cap is inclusive."""
        assert _open(48 * HOUR).until == NOW + 48 * HOUR

    def test_more_than_48_hours_is_refused(self) -> None:
        """Test that one second over the cap is refused and nothing written."""
        with pytest.raises(window.ResearchRefusedError, match="48"):
            _open(48 * HOUR + 1)
        assert window.read_record() is None

    @pytest.mark.parametrize("offset", [0.0, -1.0, -3 * HOUR])
    def test_not_in_the_future_is_refused(self, offset: float) -> None:
        """Test that now and the past are refused."""
        with pytest.raises(window.ResearchRefusedError, match="future"):
            _open(offset)
        assert window.read_record() is None

    def test_window_may_not_outlive_the_lock(self) -> None:
        """Test that an expiry after the lock end is refused."""
        with (
            patch(NOW_PATCH, return_value=LOCK_END - HOUR),
            pytest.raises(window.ResearchRefusedError, match="lock"),
        ):
            window.open_research_window(datetime.fromtimestamp(LOCK_END + 1, tz=UTC))
        assert window.read_record() is None

    def test_write_failure_is_a_refusal(self) -> None:
        """Test that an unwritable state dir is reported, not a traceback."""
        with (
            patch.object(window, "write_record", side_effect=OSError("ro")),
            pytest.raises(window.ResearchRefusedError, match="write"),
        ):
            _open(HOUR)


class TestNoLock:
    """Without an active total block there is nothing to research."""

    def test_no_lock_file(self) -> None:
        """Test that the command has no meaning without a block."""
        with pytest.raises(window.ResearchRefusedError, match="total block"):
            _open(HOUR)

    def test_expired_lock(self, total_block_paths: Paths) -> None:
        """Test that a lock that already ended cannot host a window."""
        lock(total_block_paths)
        with (
            patch(NOW_PATCH, return_value=LOCK_END + 1),
            pytest.raises(window.ResearchRefusedError, match="total block"),
        ):
            window.open_research_window(datetime.fromtimestamp(LOCK_END + 2, UTC))


@pytest.mark.usefixtures("live")
class TestOncePerLock:
    """One window per lock, however it ended; reruns never extend."""

    def test_second_open_is_refused_and_changes_nothing(self) -> None:
        """Test that a rerun with a later expiry never extends the window."""
        _open(2 * HOUR)
        before = store.RESEARCH_FILE.read_bytes()
        with pytest.raises(window.ResearchRefusedError, match="already"):
            _open(40 * HOUR)
        assert store.RESEARCH_FILE.read_bytes() == before

    def test_used_window_stays_used_after_it_closed(self) -> None:
        """Test that an expired, latched window is not a free second window."""
        window.write_record(make_record(closed=True, store_reblocked=True))
        with pytest.raises(window.ResearchRefusedError, match="already"):
            _open(HOUR)

    def test_a_new_lock_gets_its_own_window(self, total_block_paths: Paths) -> None:
        """Test that last lock's record does not burn the next lock's window."""
        window.write_record(make_record(lock_started_at=LOCK_START - 7 * 86400))
        lock(total_block_paths)
        assert _open(HOUR).lock_started_at == LOCK_START

    def test_corrupt_state_refuses_instead_of_resetting(self) -> None:
        """Test that corruption cannot be used to get a second window."""
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        with pytest.raises(window.ResearchRefusedError, match="unreadable"):
            _open(HOUR)
        assert store.RESEARCH_FILE.read_text(encoding="utf-8") == "{oops"


@pytest.fixture(name="warsaw")
def _warsaw(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the test in Europe/Warsaw local time, restoring the zone after."""
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestParseUntil:
    """--until is local time unless it carries an offset."""

    @pytest.mark.usefixtures("warsaw")
    def test_naive_means_local_time(self) -> None:
        """Test that 2026-11-13T00:00 is midnight in the local zone."""
        parsed = window.parse_until("2026-11-13T00:00")
        assert parsed == datetime(2026, 11, 12, 23, 0, tzinfo=UTC)
        assert os.environ["TZ"] == "Europe/Warsaw"

    def test_offset_is_honoured(self) -> None:
        """Test that an explicit offset is not reinterpreted."""
        parsed = window.parse_until("2026-11-13T00:00:00+02:00")
        assert parsed == datetime(2026, 11, 12, 22, 0, tzinfo=UTC)

    def test_z_suffix(self) -> None:
        """Test that Z means UTC."""
        assert window.parse_until("2026-11-13T00:00:00Z") == datetime(
            2026, 11, 13, tzinfo=UTC
        )

    @pytest.mark.parametrize("raw", ["", "tomorrow", "2026-13-40", "13:00"])
    def test_garbage_is_a_value_error(self, raw: str) -> None:
        """Test that an unparsable expiry is rejected."""
        with pytest.raises(ValueError, match="until"):
            window.parse_until(raw)
