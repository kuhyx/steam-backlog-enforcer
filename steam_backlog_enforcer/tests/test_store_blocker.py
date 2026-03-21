"""Tests for store_blocker module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.store_blocker import (
    _block_store_iptables,
    _block_via_hosts_install,
    _is_iptables_blocked,
    _unblock_store_iptables,
    block_store,
    is_store_blocked,
    unblock_store,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestIsStoreBlocked:
    """Tests for is_store_blocked."""

    def test_blocked_in_hosts(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("0.0.0.0 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
        ):
            assert is_store_blocked() is True

    def test_commented_in_hosts(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("# 0.0.0.0 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False

    def test_not_in_hosts_iptables_blocked(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=True,
            ),
        ):
            assert is_store_blocked() is True

    def test_hosts_read_error(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "nonexistent"
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False

    def test_wrong_redirect_ip(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1 store.steampowered.com\n", encoding="utf-8")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_FILE",
                hosts_file,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._is_iptables_blocked",
                return_value=False,
            ),
        ):
            assert is_store_blocked() is False


class TestBlockStore:
    """Tests for block_store."""

    def test_already_blocked(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
            return_value=True,
        ):
            assert block_store() is True

    def test_reblock_succeeds(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, True],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_store_iptables",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True

    def test_fallback_to_install_script(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True

    def test_all_fail(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=False,
            ),
        ):
            assert block_store() is False

    def test_iptables_only_succeeds(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                side_effect=[False, False],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._reblock_hosts",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_via_hosts_install",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._block_store_iptables",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert block_store() is True


class TestBlockViaHostsInstall:
    """Tests for _block_via_hosts_install."""

    def test_already_blocked(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
            return_value=True,
        ):
            assert _block_via_hosts_install() is True

    def test_script_missing(self, tmp_path: Path) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                tmp_path / "nonexistent.sh",
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_succeeds(self, tmp_path: Path) -> None:
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is True

    def test_script_fails(self, tmp_path: Path) -> None:
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=1, stderr="error", stdout="")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_fails_no_stderr(self, tmp_path: Path) -> None:
        script = tmp_path / "install.sh"
        script.touch()
        mock_result = MagicMock(returncode=1, stderr="", stdout="out")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
        ):
            assert _block_via_hosts_install() is False

    def test_script_os_error(self, tmp_path: Path) -> None:
        script = tmp_path / "install.sh"
        script.touch()
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.is_store_blocked",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.HOSTS_INSTALL_SCRIPT",
                script,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                side_effect=OSError,
            ),
        ):
            assert _block_via_hosts_install() is False


class TestIsIptablesBlocked:
    """Tests for _is_iptables_blocked."""

    def test_blocked(self) -> None:
        mock_result = MagicMock(returncode=0, stdout="DROP blah")
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is True

    def test_not_blocked_no_drop(self) -> None:
        mock_result = MagicMock(returncode=0, stdout="ACCEPT")
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is False

    def test_not_blocked_error(self) -> None:
        mock_result = MagicMock(returncode=1, stdout="")
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_iptables_blocked() is False

    def test_os_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            side_effect=OSError,
        ):
            assert _is_iptables_blocked() is False


class TestBlockStoreIptables:
    """Tests for _block_store_iptables."""

    def test_success(self) -> None:
        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.socket.getaddrinfo",
                return_value=[
                    (None, None, None, None, ("1.2.3.4", 443)),
                ],
            ),
        ):
            assert _block_store_iptables() is True

    def test_os_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            side_effect=OSError,
        ):
            assert _block_store_iptables() is False

    def test_dns_resolution_fails(self) -> None:
        import socket

        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.socket.getaddrinfo",
                side_effect=socket.gaierror,
            ),
        ):
            # Should succeed even if DNS fails (just no IPs to block)
            assert _block_store_iptables() is True

    def test_chain_hook_needed(self) -> None:
        results = [
            MagicMock(returncode=0),  # -N
            MagicMock(returncode=0),  # -F
            MagicMock(returncode=1),  # -C OUTPUT (not hooked)
            MagicMock(returncode=0),  # -I OUTPUT
        ]
        call_count = 0

        def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            idx = min(call_count, len(results) - 1)
            call_count += 1
            return results[idx]

        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
                side_effect=side_effect,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.socket.getaddrinfo",
                side_effect=__import__("socket").gaierror,
            ),
        ):
            assert _block_store_iptables() is True


class TestUnblockStore:
    """Tests for unblock_store."""

    def test_both_succeed(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is True

    def test_iptables_fails(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is True

    def test_both_fail(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_store_iptables",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker._unblock_hosts",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.store_blocker.flush_dns_cache",
            ),
        ):
            assert unblock_store() is False


class TestUnblockStoreIptables:
    """Tests for _unblock_store_iptables."""

    def test_success(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
        ):
            assert _unblock_store_iptables() is True

    def test_os_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.store_blocker.subprocess.run",
            side_effect=OSError,
        ):
            assert _unblock_store_iptables() is False
