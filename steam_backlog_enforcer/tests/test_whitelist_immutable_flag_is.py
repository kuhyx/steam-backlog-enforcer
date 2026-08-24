"""Tests for _whitelist.py: time-locked exceptions, reason validation, chattr."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._whitelist import (
    _immutable_flag_is,
    _load_approved,
    _save_approved,
    _try_set_immutable,
    lock_enforcement_files,
    unlock_for_write,
)

if TYPE_CHECKING:
    import array
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


class TestImmutableFlagIs:
    """Tests for Immutable Flag Is."""

    def test_reads_clear_flag_on_real_file(self, tmp_path: Path) -> None:
        """Test reads clear flag on real file."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        assert _immutable_flag_is(target, immutable=False) is True
        assert _immutable_flag_is(target, immutable=True) is False

    def test_fails_closed_when_ioctl_refuses(self, tmp_path: Path) -> None:
        # Filesystems without flag support raise OSError; we must report False
        # so the caller still shells out rather than silently skipping.
        """Test fails closed when ioctl refuses."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch("fcntl.ioctl", side_effect=OSError("unsupported")):
            assert _immutable_flag_is(target, immutable=False) is False
            assert _immutable_flag_is(target, immutable=True) is False

    def test_fails_closed_on_value_error(self, tmp_path: Path) -> None:
        """Test fails closed on value error."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch("fcntl.ioctl", side_effect=ValueError("bad buffer")):
            assert _immutable_flag_is(target, immutable=True) is False

    def test_fails_closed_when_file_cannot_be_opened(self, tmp_path: Path) -> None:
        """Test fails closed when file cannot be opened."""
        assert _immutable_flag_is(tmp_path / "missing.txt", immutable=True) is False

    def test_reports_set_flag(self, tmp_path: Path) -> None:
        """Test reports set flag."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")

        def _fake_ioctl(_fd: int, _req: int, buf: array.array[int]) -> int:
            """Test fake ioctl."""
            buf[0] = 0x00000010  # FS_IMMUTABLE_FL
            return 0

        with patch("fcntl.ioctl", side_effect=_fake_ioctl):
            assert _immutable_flag_is(target, immutable=True) is True
            assert _immutable_flag_is(target, immutable=False) is False

    def test_oserror_swallowed(self, tmp_path: Path) -> None:
        """Test oserror swallowed."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch("shutil.which", return_value="/usr/bin/chattr"),
            patch("subprocess.run", side_effect=OSError("no permission")),
        ):
            _try_set_immutable(target, immutable=True)  # must not raise

    def test_timeout_swallowed(self, tmp_path: Path) -> None:
        """Test timeout swallowed."""
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
    """Tests for Lock And Unlock."""

    def test_lock_enforcement_files(self, tmp_path: Path) -> None:
        """Test lock enforcement files."""
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
        """Test unlock for write."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with (
            patch("shutil.which", return_value="/usr/bin/chattr"),
            # Pretend the file really is immutable; a fresh tmp file is not,
            # and unlocking an already-mutable file is now a no-op.
            patch(
                "steam_backlog_enforcer._whitelist._immutable_flag_is",
                return_value=False,
            ),
            patch("subprocess.run") as mock_run,
        ):
            unlock_for_write(target)
            args = mock_run.call_args[0][0]
            assert "-i" in args

    def test_unlock_for_write_skips_already_mutable_file(self, tmp_path: Path) -> None:
        """Test unlock for write skips already mutable file."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            unlock_for_write(target)
            mock_run.assert_not_called()


class TestPersistence:
    """Tests for Persistence."""

    def test_load_approved_missing_file(self) -> None:
        """Test load approved missing file."""
        assert _load_approved() == []

    def test_load_approved_corrupt_file(self, tmp_path: Path) -> None:
        """Test load approved corrupt file."""
        bad = tmp_path / "approved.json"
        bad.write_text("{{broken", encoding="utf-8")
        with patch(
            "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
            bad,
        ):
            assert _load_approved() == []

    def test_load_approved_non_list(self, tmp_path: Path) -> None:
        """Test load approved non list."""
        bad = tmp_path / "approved.json"
        bad.write_text('"just a string"', encoding="utf-8")
        with patch(
            "steam_backlog_enforcer._whitelist.APPROVED_EXCEPTIONS_FILE",
            bad,
        ):
            assert _load_approved() == []

    def test_save_approved_roundtrip(self) -> None:
        """Test save approved roundtrip."""
        entries: list[dict[str, object]] = [
            {"app_id": 730, "reason": "cs2", "approved_at": 99999.0}
        ]
        with (
            patch("shutil.which", return_value=None),  # skip chattr
        ):
            _save_approved(entries)
        assert _load_approved() == entries
