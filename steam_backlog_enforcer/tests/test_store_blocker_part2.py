"""Tests for store_blocker module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.store_blocker import (
    _disable_hosts_protection,
    _enable_hosts_protection,
    _reblock_hosts,
    _sudo_write_hosts,
    _unblock_hosts,
    flush_dns_cache,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "python_pkg.steam_backlog_enforcer.store_blocker"


class TestSudoWriteHosts:
    """Tests for _sudo_write_hosts."""

    def test_writes_content(self) -> None:
        with patch(f"{PKG}.subprocess.run") as mock_run:
            _sudo_write_hosts("127.0.0.1 localhost\n")
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["input"] == b"127.0.0.1 localhost\n"


class TestDisableHostsProtection:
    """Tests for _disable_hosts_protection."""

    def test_stops_services_unmounts_chattr(self) -> None:
        findmnt_found = MagicMock(returncode=0)

        def run_side_effect(
            cmd: list[str],
            **kwargs: object,
        ) -> MagicMock:
            if any("findmnt" in str(c) for c in cmd):
                return findmnt_found
            return MagicMock(returncode=0)

        with patch(f"{PKG}.subprocess.run", side_effect=run_side_effect):
            _disable_hosts_protection()

    def test_no_bind_mount(self) -> None:
        findmnt_missing = MagicMock(returncode=1)

        def run_side_effect(
            cmd: list[str],
            **kwargs: object,
        ) -> MagicMock:
            if any("findmnt" in str(c) for c in cmd):
                return findmnt_missing
            return MagicMock(returncode=0)

        with patch(f"{PKG}.subprocess.run", side_effect=run_side_effect):
            _disable_hosts_protection()


class TestEnableHostsProtection:
    """Tests for _enable_hosts_protection."""

    def test_with_locked_copy(self, tmp_path: Path) -> None:
        locked_copy = tmp_path / "locked-hosts"
        locked_copy.touch()
        with (
            patch(f"{PKG}.subprocess.run"),
            patch(f"{PKG}._LOCKED_HOSTS_COPY", locked_copy),
        ):
            _enable_hosts_protection()

    def test_without_locked_copy(self, tmp_path: Path) -> None:
        locked_copy = tmp_path / "nonexistent"
        with (
            patch(f"{PKG}.subprocess.run"),
            patch(f"{PKG}._LOCKED_HOSTS_COPY", locked_copy),
        ):
            _enable_hosts_protection()


class TestUnblockHosts:
    """Tests for _unblock_hosts."""

    def test_not_blocked(self) -> None:
        with patch(f"{PKG}.is_store_blocked", return_value=False):
            result = _unblock_hosts()
        assert result is True

    def test_comments_out_entries(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text(
            "127.0.0.1 localhost\n"
            "0.0.0.0 store.steampowered.com\n"
            "0.0.0.0 checkout.steampowered.com\n",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}.is_store_blocked", return_value=True),
            patch(f"{PKG}.HOSTS_FILE", hosts_file),
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            result = _unblock_hosts()
        assert result is True
        written = mock_write.call_args[0][0]
        assert "# 0.0.0.0 store.steampowered.com" in written

    def test_no_change_needed(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text(
            "# 0.0.0.0 store.steampowered.com\n",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}.is_store_blocked", return_value=True),
            patch(f"{PKG}.HOSTS_FILE", hosts_file),
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            result = _unblock_hosts()
        assert result is True
        mock_write.assert_not_called()

    def test_os_error(self) -> None:
        with (
            patch(f"{PKG}.is_store_blocked", return_value=True),
            patch(f"{PKG}._disable_hosts_protection", side_effect=OSError),
        ):
            result = _unblock_hosts()
        assert result is False


class TestReblockHosts:
    """Tests for _reblock_hosts."""

    def test_uncomments_entries(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text(
            "127.0.0.1 localhost\n"
            "# 0.0.0.0 store.steampowered.com\n"
            "# 0.0.0.0 checkout.steampowered.com\n",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}.HOSTS_FILE", hosts_file),
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            result = _reblock_hosts()
        assert result is True
        written = mock_write.call_args[0][0]
        # Should have uncommented lines
        assert "0.0.0.0 store.steampowered.com" in written
        assert "# 0.0.0.0 store.steampowered.com" not in written

    def test_no_change(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(f"{PKG}.HOSTS_FILE", hosts_file),
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            result = _reblock_hosts()
        assert result is True
        mock_write.assert_not_called()

    def test_os_error(self) -> None:
        with patch(f"{PKG}._disable_hosts_protection", side_effect=OSError):
            result = _reblock_hosts()
        assert result is False


class TestFlushDnsCache:
    """Tests for flush_dns_cache."""

    def test_runs_commands(self) -> None:
        with patch(f"{PKG}.subprocess.run") as mock_run:
            flush_dns_cache()
        assert mock_run.call_count == 3

    def test_file_not_found_suppressed(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            flush_dns_cache()

    def test_os_error_suppressed(self) -> None:
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            flush_dns_cache()
