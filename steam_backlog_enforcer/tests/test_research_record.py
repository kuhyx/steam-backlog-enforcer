"""The research record: strict parse, fail-closed reads, window predicate."""

from __future__ import annotations

import json

import pytest

from steam_backlog_enforcer import _research_record as store
from steam_backlog_enforcer.tests._research_helpers import (
    HOUR,
    LOCK_END,
    LOCK_START,
    NOW,
    make_record,
)


def _raw(**changes: object) -> str:
    """The JSON of a valid record with *changes* applied (None drops a key)."""
    data: dict[str, object] = {
        "lock_started_at": LOCK_START,
        "lock_until": LOCK_END,
        "opened_at": NOW - 60,
        "until": NOW + HOUR,
        "closed": False,
        "store_reblocked": False,
        "extended_until": None,
    }
    for key, value in changes.items():
        if value is None:
            del data[key]
        else:
            data[key] = value
    return json.dumps(data)


class TestParse:
    """A record is either exactly valid or an error; there is no repair."""

    def test_roundtrip(self) -> None:
        """Test that to_json then parse gives the same record."""
        record = make_record(closed=True, store_reblocked=True)
        assert store.parse_record(record.to_json()) == record

    def test_flags_default_to_false(self) -> None:
        """Test that a record without the latches reads as not closed."""
        parsed = store.parse_record(_raw(closed=None, store_reblocked=None))
        assert (parsed.closed, parsed.store_reblocked) == (False, False)

    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            "[]",
            "null",
            "{}",
            _raw(until=None),
            _raw(lock_started_at=None),
            _raw(until="2026-11-13"),
            _raw(until=True),
            _raw(opened_at=float("nan")),
            _raw(until=float("inf")),
            _raw(until=10**400),
            _raw(until=NOW - 60),
            _raw(until=NOW - 3600),
            _raw(lock_until=LOCK_START),
            _raw(until=LOCK_END + 1),
            _raw(opened_at=LOCK_END - HOUR, until=LOCK_END + HOUR),
            _raw(closed="yes"),
            _raw(store_reblocked=1),
            _raw(extended_until="later"),
            _raw(extended_until=True),
            _raw(extended_until=float("nan")),
            _raw(extended_until=NOW + HOUR),
            _raw(extended_until=NOW),
            _raw(extended_until=LOCK_END + 1),
        ],
    )
    def test_invalid_is_an_error(self, raw: str) -> None:
        """Test that every malformed or out-of-policy record is refused."""
        with pytest.raises(store.ResearchStateError):
            store.parse_record(raw)

    def test_no_cap_but_the_lock_end(self) -> None:
        """Test that a window may run to the lock's end, however long."""
        parsed = store.parse_record(_raw(until=LOCK_END))
        assert parsed.until - parsed.opened_at > 48 * HOUR

    def test_extension_roundtrip_and_old_records_have_none(self) -> None:
        """Test that extended_until survives and is absent in an old record."""
        record = make_record(extended_until=LOCK_END)
        assert store.parse_record(record.to_json()) == record
        assert store.parse_record(_raw(extended_until=None)).extended_until is None
        old = json.loads(_raw())
        del old["extended_until"]
        assert store.parse_record(json.dumps(old)).extended_until is None


class TestReadWrite:
    """Reading distinguishes never-used from unreadable."""

    def test_absent_is_none(self) -> None:
        """Test that no file means the window was never used."""
        assert store.read_record() is None

    def test_write_then_read(self) -> None:
        """Test that a written record comes back, root-only on disk."""
        record = make_record()
        store.write_record(record)
        assert store.read_record() == record
        assert store.RESEARCH_FILE.stat().st_mode & 0o777 == 0o600
        assert store.RESEARCH_FILE.parent.stat().st_mode & 0o777 == 0o700

    def test_corrupt_raises(self) -> None:
        """Test that a corrupt file is an error, not 'never used'."""
        store.RESEARCH_FILE.parent.mkdir(parents=True)
        store.RESEARCH_FILE.write_text("{oops", encoding="utf-8")
        with pytest.raises(store.ResearchStateError):
            store.read_record()

    def test_unreadable_raises(self) -> None:
        """Test that an unreadable path (a directory) is an error."""
        store.RESEARCH_FILE.mkdir(parents=True)
        with pytest.raises(store.ResearchStateError):
            store.read_record()


class TestIsOpen:
    """Open means opened_at <= now < until and not latched closed."""

    def test_inside(self) -> None:
        """Test that a time inside the window is open."""
        assert make_record().is_open(NOW)

    def test_opened_at_is_inclusive(self) -> None:
        """Test that the first instant is open."""
        assert make_record().is_open(NOW - 60)

    def test_before_opening_is_closed(self) -> None:
        """Test that a clock set back before opening does not open it."""
        assert not make_record().is_open(NOW - 61)

    def test_until_is_exclusive(self) -> None:
        """Test that the deadline instant is already closed."""
        assert not make_record().is_open(NOW + HOUR)

    def test_after_deadline_is_closed(self) -> None:
        """Test that a late clock is closed."""
        assert not make_record().is_open(NOW + 5 * HOUR)

    def test_extension_moves_the_deadline(self) -> None:
        """Test that an extended window is open past its first deadline."""
        record = make_record(extended_until=NOW + 5 * HOUR)
        assert record.ends_at == NOW + 5 * HOUR
        assert record.is_open(NOW + 2 * HOUR)
        assert not record.is_open(NOW + 5 * HOUR)

    def test_without_extension_ends_at_until(self) -> None:
        """Test that ends_at is the plain deadline by default."""
        assert make_record().ends_at == NOW + HOUR

    def test_latch_wins_over_the_clock(self) -> None:
        """Test that a closed record stays closed even for an in-range clock."""
        assert not make_record(closed=True).is_open(NOW)
