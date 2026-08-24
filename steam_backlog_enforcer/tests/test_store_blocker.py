"""Tests for store_blocker module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.store_blocker import (
    block_store,
    is_store_blocked,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestIsStoreBlocked:
    """Tests for is_store_blocked."""

    def test_blocked_in_hosts(self, tmp_path: Path) -> None:
        """Test blocked in hosts."""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("0.0.0.0 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
        ):
            assert is_store_blocked() is True

    def test_commented_in_hosts(self, tmp_path: Path) -> None:
        """Test commented in hosts."""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("# 0.0.0.0 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False

    def test_not_in_hosts_iptables_blocked(self, tmp_path: Path) -> None:
        """Test not in hosts iptables blocked."""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=True,
            ),
        ):
            assert is_store_blocked() is True

    def test_hosts_read_error(self, tmp_path: Path) -> None:
        """Test hosts read error."""
        hosts_file = tmp_path / "nonexistent"
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False

    def test_wrong_redirect_ip(self, tmp_path: Path) -> None:
        """Test wrong redirect ip."""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False


class TestBlockStore:
    """Tests for block_store."""

    def test_already_blocked(self) -> None:
        """Test already blocked."""
        with patch(
            "steam_backlog_enforcer.store_blocker.is_store_blocked",
            return_value=True,
        ):
            assert block_store() is True

    def test_reblock_succeeds(self) -> None:
        """Test reblock succeeds."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, True],
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_store_iptables",
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True

    def test_fallback_to_install_script(self) -> None:
        """Test fallback to install script."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True

    def test_all_fail(self) -> None:
        """Test all fail."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=False,
            ),
        ):
            assert block_store() is False

    def test_iptables_only_succeeds(self) -> None:
        """Test iptables only succeeds."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True
