"""Tests for store_blocker module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.store_blocker import (
    _block_store_iptables,
    _block_via_hosts_install,
    _is_iptables_blocked,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestBlockViaHostsInstall:
    """Tests for _block_via_hosts_install."""

    def test_already_blocked(self) -> None:
        """Test already blocked."""
        with patch(
            "steam_backlog_enforcer.store_blocker.is_store_blocked",
            return_value=True,
        ):
            assert _block_via_hosts_install() is True

    def test_script_missing(self, tmp_path: Path) -> None:
        """Test script missing."""
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                tmp_path / "nonexistent.sh",
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_succeeds(self, tmp_path: Path) -> None:
        """Test script succeeds."""
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is True

    def test_script_fails(self, tmp_path: Path) -> None:
        """Test script fails."""
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=1, stderr="error", stdout="")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_fails_no_stderr(self, tmp_path: Path) -> None:
        """Test script fails no stderr."""
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=1, stderr="", stdout="out")
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_os_error(self, tmp_path: Path) -> None:
        """Test script os error."""
        script = tmp_path / "install.sh"
        script.touch()
        with (
            patch(
                "steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "steam_backlog_enforcer.store_blocker.subprocess.run",
                side_effect=OSError,
            ),
        ):
            assert _block_via_hosts_install() is False


class TestIsIptablesBlocked:
    """Tests for _is_iptables_blocked."""

    def test_blocked(self) -> None:
        """Test blocked."""
        mock_result = MagicMock(returncode=0, stdout="DROP blah")
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is True

    def test_not_blocked_no_drop(self) -> None:
        """Test not blocked no drop."""
        mock_result = MagicMock(returncode=0, stdout="ACCEPT")
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is False

    def test_not_blocked_error(self) -> None:
        """Test not blocked error."""
        mock_result = MagicMock(returncode=1, stdout="")
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is False

    def test_os_error(self) -> None:
        """Test os error."""
        with patch(
            "steam_backlog_enforcer.store_blocker.subprocess.run",
            side_effect=OSError,
        ):
            assert _is_iptables_blocked() is False


class TestBlockStoreIptables:
    """Tests for _block_store_iptables."""

    def test_success(self) -> None:
        """Test success."""
        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "steam_backlog_enforcer._store_iptables.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._store_iptables.socket.getaddrinfo",
                return_value=[
                    (None, None, None, None, ("1.2.3.4", 443)),
                ],
            ),
        ):
            assert _block_store_iptables() is True

    def test_os_error(self) -> None:
        """Test os error."""
        with patch(
            "steam_backlog_enforcer._store_iptables.subprocess.run",
            side_effect=OSError,
        ):
            assert _block_store_iptables() is False

    def test_dns_resolution_fails(self) -> None:
        """Test dns resolution fails."""
        import socket

        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "steam_backlog_enforcer._store_iptables.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._store_iptables.socket.getaddrinfo",
                side_effect=socket.gaierror,
            ),
        ):
            # Should succeed even if DNS fails (just no IPs to block)
            assert _block_store_iptables() is True

    def test_chain_hook_needed(self) -> None:
        """Test chain hook needed."""
        results = [
            MagicMock(returncode=0),  # -N
            MagicMock(returncode=0),  # -F
            MagicMock(returncode=1),  # -C OUTPUT (not hooked)
            MagicMock(returncode=0),  # -I OUTPUT
        ]
        call_count = 0

        def side_effect(*_args: object, **_kwargs: object) -> MagicMock:
            """Test side effect."""
            nonlocal call_count
            idx = min(call_count, len(results) - 1)
            call_count += 1
            return results[idx]

        with (
            patch(
                "steam_backlog_enforcer._store_iptables.subprocess.run",
                side_effect=side_effect,
            ),
            patch(
                "steam_backlog_enforcer._store_iptables.socket.getaddrinfo",
                side_effect=__import__("socket").gaierror,
            ),
        ):
            assert _block_store_iptables() is True
