"""Tests for _whitelist.py: time-locked exceptions, reason validation, chattr."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._whitelist import (
    _append_audit_log,
)

if TYPE_CHECKING:
    from pathlib import Path

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_VALID_REASON = "I need this game installed for a work presentation this week."


# ──────────────────────────────────────────────────────────────
# Shannon entropy
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# validate_reason
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# chattr helpers
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# Persistence helpers (_load_approved, _save_approved)
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# add_pending_exception
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# get_approved_exception_ids
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# Extra coverage for validate_reason branches 94 & 106
# ──────────────────────────────────────────────────────────────


class TestAppendAuditLog:
    """Tests for Append Audit Log."""

    def test_audit_log_written(self, tmp_path: Path) -> None:
        """Test audit log written."""
        log_file = tmp_path / "audit.log"
        with patch(
            "steam_backlog_enforcer._whitelist.EXCEPTION_AUDIT_LOG",
            log_file,
        ):
            _append_audit_log(440, "some reason", "REQUESTED")
            content = log_file.read_text(encoding="utf-8")
        assert "REQUESTED" in content
        assert "app_id=440" in content
        assert "some reason" in content

    def test_audit_log_appends(self, tmp_path: Path) -> None:
        """Test audit log appends."""
        log_file = tmp_path / "audit.log"
        with patch(
            "steam_backlog_enforcer._whitelist.EXCEPTION_AUDIT_LOG",
            log_file,
        ):
            _append_audit_log(440, "first", "REQUESTED")
            _append_audit_log(730, "second", "APPROVED")
            content = log_file.read_text(encoding="utf-8")
        assert "app_id=440" in content
        assert "app_id=730" in content
