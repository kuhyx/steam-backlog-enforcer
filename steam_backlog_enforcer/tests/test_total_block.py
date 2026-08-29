"""Tests for the lock file and the status derived from it."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from steam_backlog_enforcer._total_block import (
    get_total_block_status,
    is_total_block_active,
    total_block_needs_cleanup,
)
from steam_backlog_enforcer.tests._total_block_paths import (
    Paths,
    write_lock,
)

PKG = "steam_backlog_enforcer._total_block"

_NOW = datetime.now(UTC).timestamp()


class TestIsTotalBlockActive:
    """Tests for is total block active."""

    def test_no_lock_file(self) -> None:
        """Test that no lock file."""
        assert is_total_block_active() is False

    def test_active_lock(self, total_block_paths: Paths) -> None:
        """Test that active lock."""
        write_lock(total_block_paths, _NOW, _NOW + 3600)
        assert is_total_block_active() is True

    def test_expired_lock(self, total_block_paths: Paths) -> None:
        """Test that expired lock."""
        write_lock(total_block_paths, _NOW - 3600, _NOW - 1)
        assert is_total_block_active() is False

    def test_malformed_json(self, total_block_paths: Paths) -> None:
        """Test that malformed json."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text("not json", encoding="utf-8")
        assert is_total_block_active() is False

    def test_non_dict_json(self, total_block_paths: Paths) -> None:
        """Test that non dict json."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert is_total_block_active() is False

    def test_missing_until_key(self, total_block_paths: Paths) -> None:
        """Test that missing until key."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text(
            json.dumps({"days": 1}), encoding="utf-8"
        )
        assert is_total_block_active() is False

    def test_non_numeric_until(self, total_block_paths: Paths) -> None:
        """Test that non numeric until."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text(
            json.dumps({"until": "not-a-number"}), encoding="utf-8"
        )
        assert is_total_block_active() is False


class TestTotalBlockNeedsCleanup:
    """Tests for total block needs cleanup."""

    def test_no_lock_file(self) -> None:
        """Test that no lock file."""
        assert total_block_needs_cleanup() is False

    def test_active_lock_no_cleanup_needed(self, total_block_paths: Paths) -> None:
        """Test that active lock no cleanup needed."""
        write_lock(total_block_paths, _NOW, _NOW + 3600)
        assert total_block_needs_cleanup() is False

    def test_expired_lock_needs_cleanup(self, total_block_paths: Paths) -> None:
        """Test that expired lock needs cleanup."""
        write_lock(total_block_paths, _NOW - 3600, _NOW - 1)
        assert total_block_needs_cleanup() is True


class TestGetTotalBlockStatus:
    """Tests for get total block status."""

    def test_no_lock(self) -> None:
        """Test that no lock."""
        status = get_total_block_status()
        assert status.active is False
        assert status.started_at is None
        assert status.until is None
        assert status.days == 0
        assert status.days_remaining == 0.0

    def test_active_lock(self, total_block_paths: Paths) -> None:
        """Test that active lock."""
        write_lock(total_block_paths, _NOW, _NOW + 86400, days=1)
        status = get_total_block_status()
        assert status.active is True
        assert status.days == 1
        assert 0.0 < status.days_remaining <= 1.0
        assert status.started_at is not None
        assert status.until is not None

    def test_expired_lock(self, total_block_paths: Paths) -> None:
        """Test that expired lock."""
        write_lock(total_block_paths, _NOW - 7200, _NOW - 3600, days=1)
        status = get_total_block_status()
        assert status.active is False
        assert status.days_remaining == 0.0

    def test_malformed_json_returns_inactive(self, total_block_paths: Paths) -> None:
        """Test that malformed json returns inactive."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text("garbage", encoding="utf-8")
        status = get_total_block_status()
        assert status.active is False

    def test_non_int_days_defaults_to_zero(self, total_block_paths: Paths) -> None:
        """Test that non int days defaults to zero."""
        total_block_paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.lock_file.write_text(
            json.dumps({"started_at": _NOW, "until": _NOW + 3600, "days": "one"}),
            encoding="utf-8",
        )
        status = get_total_block_status()
        assert status.days == 0


# ──────────────────────────────────────────────────────────────
# Process killing
# ──────────────────────────────────────────────────────────────
