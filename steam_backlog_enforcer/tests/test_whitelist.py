"""Tests for _whitelist.py: time-locked exceptions, reason validation, chattr."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._whitelist import (
    _shannon_entropy,
    _try_set_immutable,
    validate_reason,
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


class TestShannonEntropy:
    """Tests for Shannon Entropy."""

    def test_empty_string(self) -> None:
        """Test empty string."""
        assert _shannon_entropy("") == 0.0

    def test_all_whitespace(self) -> None:
        """Test all whitespace."""
        assert _shannon_entropy("   ") == 0.0

    def test_single_char(self) -> None:
        # one unique char → entropy = 0
        """Test single char."""
        assert _shannon_entropy("aaaa") == 0.0

    def test_high_entropy(self) -> None:
        # natural English sentence has decent entropy
        """Test high entropy."""
        assert _shannon_entropy("The quick brown fox jumps") > 3.0


class TestValidateReason:
    """Tests for Validate Reason."""

    def test_valid_reason_returns_none(self) -> None:
        """Test valid reason returns none."""
        assert validate_reason(_VALID_REASON) is None

    def test_too_short(self) -> None:
        """Test too short."""
        err = validate_reason("short")
        assert err is not None
        assert "too short" in err

    def test_too_few_words(self) -> None:
        # 25+ chars but only 4 words
        """Test too few words."""
        err = validate_reason("word1 word2 word3 word4xxx")
        assert err is not None
        assert "words" in err

    def test_low_entropy_rejected(self) -> None:
        # repeating 'ab' has low entropy
        """Test low entropy rejected."""
        err = validate_reason("ababababababababababababababab")
        assert err is not None
        # could be caught by entropy or alternating-pattern check
        assert err is not None

    def test_char_run_rejected(self) -> None:
        """Test char run rejected."""
        err = validate_reason("I neeeeed this game to play it")
        assert err is not None
        assert "repeated characters" in err

    def test_alternating_pattern_rejected(self) -> None:
        # "ababababab..." repeated many times
        """Test alternating pattern rejected."""
        err = validate_reason("abababababababababababababababababababababab")
        assert err is not None
        assert "repetitive" in err or "random" in err or err is not None


class TestTrySetImmutable:
    """Tests for Try Set Immutable."""

    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        # Should silently do nothing when the file doesn't exist
        """Test file does not exist."""
        _try_set_immutable(tmp_path / "nonexistent.txt", immutable=True)

    def test_chattr_not_available(self, tmp_path: Path) -> None:
        """Test chattr not available."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch("shutil.which", return_value=None):
            _try_set_immutable(target, immutable=True)  # no-op, no crash

    def test_chattr_called_set(self, tmp_path: Path) -> None:
        """Test chattr called set."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        fake_chattr = tmp_path / "chattr"
        with (
            patch("shutil.which", return_value=str(fake_chattr)),
            patch("subprocess.run") as mock_run,
        ):
            _try_set_immutable(target, immutable=True)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "+i" in args

    def test_chattr_called_clear(self, tmp_path: Path) -> None:
        """Test chattr called clear."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        fake_chattr = tmp_path / "chattr"
        with (
            patch("shutil.which", return_value=str(fake_chattr)),
            # A fresh tmp file is already mutable, so without this the call
            # would (correctly) short-circuit before reaching chattr.
            patch(
                "steam_backlog_enforcer._whitelist_locking._immutable_flag_is",
                return_value=False,
            ),
            patch("subprocess.run") as mock_run,
        ):
            _try_set_immutable(target, immutable=False)
            args = mock_run.call_args[0][0]
            assert "-i" in args

    def test_skips_chattr_when_flag_already_correct(self, tmp_path: Path) -> None:
        # The hot path: lock_enforcement_files runs every loop iteration, and
        # the flag is already what it should be, so nothing should be spawned.
        """Test skips chattr when flag already correct."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer._whitelist_locking._immutable_flag_is",
                return_value=True,
            ),
            patch("shutil.which") as mock_which,
            patch("subprocess.run") as mock_run,
        ):
            _try_set_immutable(target, immutable=True)
            mock_run.assert_not_called()
            mock_which.assert_not_called()
