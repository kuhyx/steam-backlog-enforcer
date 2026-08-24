"""Tests for store_blocker module."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.store_blocker import (
    _unblock_store_iptables,
    unblock_store,
)


class TestUnblockStore:
    """Tests for unblock_store."""

    def test_both_succeed(self) -> None:
        """Test both succeed."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is True

    def test_iptables_fails(self) -> None:
        """Test iptables fails."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is True

    def test_both_fail(self) -> None:
        """Test both fail."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is False


class TestUnblockStoreIptables:
    """Tests for _unblock_store_iptables."""

    def test_success(self) -> None:
        """Test success."""
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
        ):
            assert _unblock_store_iptables() is True

    def test_os_error(self) -> None:
        """Test os error."""
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            side_effect=OSError,
        ):
            assert _unblock_store_iptables() is False
