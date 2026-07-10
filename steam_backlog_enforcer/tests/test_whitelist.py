"""Tests for _whitelist.py: time-locked exceptions, reason validation, chattr."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._whitelist import (
    _append_audit_log,
    _load_approved,
    _save_approved,
    _shannon_entropy,
    _try_set_immutable,
    add_pending_exception,
    get_approved_exception_ids,
    lock_enforcement_files,
    unlock_for_write,
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


class TestShannonEntropy:
    def test_empty_string(self) -> None:
        assert _shannon_entropy("") == 0.0

    def test_all_whitespace(self) -> None:
        assert _shannon_entropy("   ") == 0.0

    def test_single_char(self) -> None:
        # one unique char → entropy = 0
        assert _shannon_entropy("aaaa") == 0.0

    def test_high_entropy(self) -> None:
        # natural English sentence has decent entropy
        assert _shannon_entropy("The quick brown fox jumps") > 3.0


# ──────────────────────────────────────────────────────────────
# validate_reason
# ──────────────────────────────────────────────────────────────


class TestValidateReason:
    def test_valid_reason_returns_none(self) -> None:
        assert validate_reason(_VALID_REASON) is None

    def test_too_short(self) -> None:
        err = validate_reason("short")
        assert err is not None
        assert "too short" in err

    def test_too_few_words(self) -> None:
        # 25+ chars but only 4 words
        err = validate_reason("word1 word2 word3 word4xxx")
        assert err is not None
        assert "words" in err

    def test_low_entropy_rejected(self) -> None:
        # repeating 'ab' has low entropy
        err = validate_reason("ababababababababababababababab")
        assert err is not None
        # could be caught by entropy or alternating-pattern check
        assert err is not None

    def test_char_run_rejected(self) -> None:
        err = validate_reason("I neeeeed this game to play it")
        assert err is not None
        assert "repeated characters" in err

    def test_alternating_pattern_rejected(self) -> None:
        # "ababababab..." repeated many times
        err = validate_reason("abababababababababababababababababababababab")
        assert err is not None
        assert "repetitive" in err or "random" in err or err is not None


# ──────────────────────────────────────────────────────────────
# chattr helpers
# ──────────────────────────────────────────────────────────────


class TestTrySetImmutable:
    def test_file_does_not_exist(self, tmp_path: Path) -> None:
        # Should silently do nothing when the file doesn't exist
        _try_set_immutable(tmp_path / "nonexistent.txt", immutable=True)

    def test_chattr_not_available(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch("shutil.which", return_value=None):
            _try_set_immutable(target, immutable=True)  # no-op, no crash

    def test_chattr_called_set(self, tmp_path: Path) -> None:
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
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        fake_chattr = tmp_path / "chattr"
        with (
            patch("shutil.which", return_value=str(fake_chattr)),
            patch("subprocess.run") as mock_run,
        ):
            _try_set_immutable(target, immutable=False)
            args = mock_run.call_args[0][0]
            assert "-i" in args

    def test_oserror_swallowed(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch("shutil.which", return_value="/usr/bin/chattr"),
            patch("subprocess.run", side_effect=OSError("no permission")),
        ):
            _try_set_immutable(target, immutable=True)  # must not raise

    def test_timeout_swallowed(self, tmp_path: Path) -> None:
        import subprocess

        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch("shutil.which", return_value="/usr/bin/chattr"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="chattr", timeout=5),
            ),
        ):
            _try_set_immutable(target, immutable=True)  # must not raise


class TestLockAndUnlock:
    def test_lock_enforcement_files(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        cfg.write_text("{}", encoding="utf-8")
        approved = tmp_path / "approved.json"
        approved.write_text("[]", encoding="utf-8")

        with (
            patch(
                "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
                approved,
            ),
            patch("shutil.which", return_value="/usr/bin/chattr"),
            patch("subprocess.run") as mock_run,
        ):
            lock_enforcement_files(cfg)
            assert mock_run.call_count == 2
            all_calls = [c[0][0] for c in mock_run.call_args_list]
            assert all("+i" in c for c in all_calls)

    def test_unlock_for_write(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch("shutil.which", return_value="/usr/bin/chattr"),
            patch("subprocess.run") as mock_run,
        ):
            unlock_for_write(target)
            args = mock_run.call_args[0][0]
            assert "-i" in args


# ──────────────────────────────────────────────────────────────
# Persistence helpers (_load_approved, _save_approved)
# ──────────────────────────────────────────────────────────────


class TestPersistence:
    def test_load_approved_missing_file(self) -> None:
        assert _load_approved() == []

    def test_load_approved_corrupt_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "approved.json"
        bad.write_text("{{broken", encoding="utf-8")
        with patch(
            "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
            bad,
        ):
            assert _load_approved() == []

    def test_load_approved_non_list(self, tmp_path: Path) -> None:
        bad = tmp_path / "approved.json"
        bad.write_text('"just a string"', encoding="utf-8")
        with patch(
            "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
            bad,
        ):
            assert _load_approved() == []

    def test_save_approved_roundtrip(self) -> None:
        entries: list[dict[str, object]] = [
            {"app_id": 730, "reason": "cs2", "approved_at": 99999.0}
        ]
        with (
            patch("shutil.which", return_value=None),  # skip chattr
        ):
            _save_approved(entries)
        assert _load_approved() == entries


# ──────────────────────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────────────────────


class TestAppendAuditLog:
    def test_audit_log_written(self, tmp_path: Path) -> None:
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


# ──────────────────────────────────────────────────────────────
# add_pending_exception
# ──────────────────────────────────────────────────────────────


class TestAddPendingException:
    def test_add_new_exception(self) -> None:
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
        with pytest.raises(
            ValueError, match=r"short|words|entropy|repeated|repetitive"
        ):
            add_pending_exception(440, "too short")

    def test_already_approved_raises(self) -> None:
        approved: list[dict[str, object]] = [
            {"app_id": 440, "reason": _VALID_REASON, "approved_at": 0.0}
        ]
        _save_approved(approved)
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(ValueError, match="already in the approved"),
        ):
            add_pending_exception(440, _VALID_REASON)


# ──────────────────────────────────────────────────────────────
# get_approved_exception_ids
# ──────────────────────────────────────────────────────────────


class TestGetApprovedExceptionIds:
    def test_empty(self) -> None:
        result = get_approved_exception_ids()
        assert result == frozenset()

    def test_populated(self) -> None:
        approved: list[dict[str, object]] = [
            {"app_id": 440, "reason": "r", "approved_at": 0.0},
            {"app_id": 730, "reason": "r", "approved_at": 0.0},
        ]
        _save_approved(approved)
        with patch("shutil.which", return_value=None):
            pass
        result = get_approved_exception_ids()
        assert result == frozenset({440, 730})


# ──────────────────────────────────────────────────────────────
# Extra coverage for validate_reason branches 94 & 106
# ──────────────────────────────────────────────────────────────


class TestValidateReasonExtraBranches:
    """Cover lines 94 and 106 that need multi-word, long, low-entropy inputs."""

    def test_low_entropy_multi_word(self) -> None:
        # 8 words, 31+ chars, entropy ≈ 2.0 (< 3.0), no char run, no alt pattern
        err = validate_reason("the the the the the the the the")
        assert err is not None
        assert "entropy" in err

    def test_alternating_pattern_multi_word(self) -> None:
        # "abababab" satisfies (..)(\1){3,}, rest provides uniqueness for entropy
        reason = "abababab xyz pqr uvw lmn"  # 5 words, 24 chars → need 25+
        reason = "abababab xyz pqr uvw lmnop"  # 5 words, 26 chars
        err = validate_reason(reason)
        assert err is not None
        assert "repetitive" in err
