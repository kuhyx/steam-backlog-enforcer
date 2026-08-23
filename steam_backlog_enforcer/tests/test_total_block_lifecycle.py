"""Tests for start, tick and cleanup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._total_block import (
    end_total_block_cleanup,
    enforce_total_block_tick,
    start_total_block,
)
from steam_backlog_enforcer._total_block_iptables import (
    IPTABLES_CHAIN,
)

PKG = "steam_backlog_enforcer._total_block"


class TestStartTotalBlock:
    """Tests for start total block."""

    def test_success(self) -> None:
        """Test that success."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.uninstall_steam_package", return_value=True),
            patch(f"{PKG}.purge_steam_and_proton"),
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True

    def test_calls_purge_steam_and_proton(self) -> None:
        """Test that calls purge steam and proton."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.uninstall_steam_package", return_value=True),
            patch(f"{PKG}.purge_steam_and_proton") as mock_purge,
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            start_total_block(1)
        mock_purge.assert_called_once()

    def test_package_block_start_failure_aborts(self) -> None:
        """Test that package block start failure aborts."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="guardctl error"),
        ):
            assert start_total_block(1) is False

    def test_best_effort_steps_dont_block_success(self) -> None:
        """Even if kill/uninstall/hosts/iptables all fail, the lock
        registering successfully is what start_total_block reports."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.uninstall_steam_package", return_value=False),
            patch(f"{PKG}.purge_steam_and_proton"),
            patch(f"{PKG}.apply_total_block_hosts", return_value=False),
            patch(f"{PKG}.apply_total_block_iptables", return_value=False),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True

    def test_logs_when_processes_were_killed(self) -> None:
        """Test that logs when processes were killed."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[(1, "steam")]),
            patch(f"{PKG}.uninstall_steam_package", return_value=True),
            patch(f"{PKG}.purge_steam_and_proton"),
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True


class TestEnforceTotalBlockTick:
    """Tests for enforce total block tick."""

    def test_reinstalls_steam_if_reappeared(self) -> None:
        """Test that reinstalls steam if reappeared."""
        with (
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.is_steam_installed", return_value=True),
            patch(f"{PKG}.uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}.purge_steam_and_proton"),
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_called_once()

    def test_no_reinstall_when_steam_absent(self) -> None:
        """Test that no reinstall when steam absent."""
        with (
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.is_steam_installed", return_value=False),
            patch(f"{PKG}.uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}.purge_steam_and_proton"),
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_not_called()

    def test_purges_steam_and_proton_every_tick(self) -> None:
        """Test that purges steam and proton every tick."""
        with (
            patch(f"{PKG}.kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}.is_steam_installed", return_value=False),
            patch(f"{PKG}.uninstall_steam_package"),
            patch(f"{PKG}.purge_steam_and_proton") as mock_purge,
            patch(f"{PKG}.apply_total_block_hosts", return_value=True),
            patch(f"{PKG}.apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_purge.assert_called_once()


class TestEndTotalBlockCleanup:
    """Tests for end total block cleanup."""

    def test_ends_lock_and_removes_blocks(self) -> None:
        """Test that ends lock and removes blocks."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.remove_total_block_hosts", return_value=True) as mock_hosts,
            patch(f"{PKG}.remove_total_block_iptables", return_value=True) as mock_ipt,
            patch(f"{PKG}.flush_dns_cache"),
        ):
            end_total_block_cleanup()
        mock_hosts.assert_called_once()
        mock_ipt.assert_called_once()

    def test_package_block_end_failure_still_cleans_up_rest(self) -> None:
        """Test that package block end failure still cleans up rest."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=1, stderr="already ended"),
            ),
            patch(f"{PKG}.remove_total_block_hosts", return_value=True) as mock_hosts,
            patch(f"{PKG}.remove_total_block_iptables", return_value=True) as mock_ipt,
            patch(f"{PKG}.flush_dns_cache"),
        ):
            end_total_block_cleanup()
        mock_hosts.assert_called_once()
        mock_ipt.assert_called_once()

    def test_hosts_removal_failure_is_logged_not_raised(self) -> None:
        """Test that hosts removal failure is logged not raised."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.remove_total_block_hosts", return_value=False),
            patch(f"{PKG}.remove_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            end_total_block_cleanup()  # must not raise

    def test_iptables_removal_failure_is_logged_not_raised(self) -> None:
        """Test that iptables removal failure is logged not raised."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}.remove_total_block_hosts", return_value=True),
            patch(f"{PKG}.remove_total_block_iptables", return_value=False),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            end_total_block_cleanup()  # must not raise


# Sanity: the module-level chain name constant is what everything above
# assumes when constructing fake iptables -S output.
def test_iptables_chain_name_constant() -> None:
    """Test that iptables chain name constant."""
    assert IPTABLES_CHAIN == "STEAM_TOTAL_BLOCK"
