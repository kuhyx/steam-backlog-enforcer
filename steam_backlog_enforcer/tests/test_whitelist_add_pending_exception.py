"""Tests for _whitelist.py: time-locked exceptions, reason validation, chattr."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer._whitelist import (
    _load_approved,
    _save_approved,
    add_pending_exception,
    get_approved_exception_ids,
    validate_reason,
)

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


class TestAddPendingException:
    """Tests for Add Pending Exception."""

    def test_add_new_exception(self) -> None:
        """Test add new exception."""
        with patch("shutil.which", return_value=None):
            msg = add_pending_exception(440, _VALID_REASON)
        assert "440" in msg
        assert "immediately" in msg.lower()
        approved = _load_approved()
        assert len(approved) == 1
        assert int(approved[0]["app_id"]) == 440
        # Now active right away, no cooldown.
        assert 440 in get_approved_exception_ids()

    def test_invalid_reason_raises(self) -> None:
        """Test invalid reason raises."""
        with pytest.raises(
            ValueError, match=r"short|words|entropy|repeated|repetitive"
        ):
            add_pending_exception(440, "too short")

    def test_already_approved_raises(self) -> None:
        """Test already approved raises."""
        approved: list[dict[str, object]] = [
            {"app_id": 440, "reason": _VALID_REASON, "approved_at": 0.0}
        ]
        _save_approved(approved)
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(ValueError, match="already in the approved"),
        ):
            add_pending_exception(440, _VALID_REASON)


class TestGetApprovedExceptionIds:
    """Tests for Get Approved Exception Ids."""

    def test_empty(self) -> None:
        """Test empty."""
        result = get_approved_exception_ids()
        assert result == frozenset()

    def test_populated(self) -> None:
        """Test populated."""
        approved: list[dict[str, object]] = [
            {"app_id": 440, "reason": "r", "approved_at": 0.0},
            {"app_id": 730, "reason": "r", "approved_at": 0.0},
        ]
        _save_approved(approved)
        with patch("shutil.which", return_value=None):
            pass
        result = get_approved_exception_ids()
        assert result == frozenset({440, 730})


class TestValidateReasonExtraBranches:
    """Cover lines 94 and 106 that need multi-word, long, low-entropy inputs."""

    def test_low_entropy_multi_word(self) -> None:
        # 8 words, 31+ chars, entropy ≈ 2.0 (< 3.0), no char run, no alt pattern
        """Test low entropy multi word."""
        err = validate_reason("the the the the the the the the")
        assert err is not None
        assert "entropy" in err

    def test_alternating_pattern_multi_word(self) -> None:
        # "abababab" satisfies (..)(\1){3,}, rest provides uniqueness for entropy
        """Test alternating pattern multi word."""
        reason = "abababab xyz pqr uvw lmn"  # 5 words, 24 chars → need 25+
        reason = "abababab xyz pqr uvw lmnop"  # 5 words, 26 chars
        err = validate_reason(reason)
        assert err is not None
        assert "repetitive" in err
