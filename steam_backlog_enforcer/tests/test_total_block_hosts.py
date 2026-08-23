"""Tests for the /etc/hosts half of the network block."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._total_block_hosts import (
    _HOSTS_BLOCK_BEGIN,
    _HOSTS_BLOCK_END,
    apply_total_block_hosts,
    remove_total_block_hosts,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import (
        Paths,
    )

PKG = "steam_backlog_enforcer._total_block_hosts"


class TestApplyTotalBlockHosts:
    """Tests for apply total block hosts."""

    def test_appends_block_when_absent(self, total_block_paths: Paths) -> None:
        """Test that appends block when absent."""
        total_block_paths.hosts_file.write_text(
            "127.0.0.1 localhost\n", encoding="utf-8"
        )
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            assert apply_total_block_hosts() is True
        written = mock_write.call_args.args[0]
        assert _HOSTS_BLOCK_BEGIN in written
        assert _HOSTS_BLOCK_END in written
        assert "steamcommunity.com" in written

    def test_already_present_is_noop(self, total_block_paths: Paths) -> None:
        """Test that already present is noop."""
        total_block_paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}",
            encoding="utf-8",
        )
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert apply_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        """Test that missing hosts file returns false."""
        assert apply_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(
        self, total_block_paths: Paths
    ) -> None:
        """Test that write failure still reenables protection."""
        total_block_paths.hosts_file.write_text(
            "127.0.0.1 localhost\n", encoding="utf-8"
        )
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as mock_enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert apply_total_block_hosts() is False
        mock_enable.assert_called_once()


class TestRemoveTotalBlockHosts:
    """Tests for remove total block hosts."""

    def test_removes_block_when_present(self, total_block_paths: Paths) -> None:
        """Test that removes block when present."""
        total_block_paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}"
            "192.168.1.1 router\n",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            assert remove_total_block_hosts() is True
        written = mock_write.call_args.args[0]
        assert _HOSTS_BLOCK_BEGIN not in written
        assert "router" in written
        assert "localhost" in written

    def test_absent_is_noop(self, total_block_paths: Paths) -> None:
        """Test that absent is noop."""
        total_block_paths.hosts_file.write_text(
            "127.0.0.1 localhost\n", encoding="utf-8"
        )
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert remove_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        """Test that missing hosts file returns false."""
        assert remove_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(
        self, total_block_paths: Paths
    ) -> None:
        """Test that write failure still reenables protection."""
        total_block_paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as mock_enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert remove_total_block_hosts() is False
        mock_enable.assert_called_once()


# ──────────────────────────────────────────────────────────────
# IP cache
# ──────────────────────────────────────────────────────────────
