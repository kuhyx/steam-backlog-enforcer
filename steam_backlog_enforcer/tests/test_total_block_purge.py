"""Tests for killing Steam and launchers, and removing their packages."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._total_block_launchers import LAUNCHER_PROCESS_NAMES
from steam_backlog_enforcer._total_block_purge import (
    is_steam_installed,
    kill_and_uninstall_launchers,
    kill_steam_and_launchers,
    uninstall_steam_package,
)

PKG = "steam_backlog_enforcer._total_block_purge"


class TestKillSteamAndLaunchers:
    """Tests for kill steam and launchers."""

    def test_combines_steam_and_launcher_kills(self) -> None:
        """Test that combines steam and launcher kills."""
        with (
            patch(f"{PKG}.kill_processes_by_name", return_value=[(1, "steam")]),
            patch(
                f"{PKG}.kill_and_uninstall_launchers",
                return_value=[(2, "prismlauncher")],
            ) as mock_launchers,
        ):
            result = kill_steam_and_launchers(LAUNCHER_PROCESS_NAMES)
        assert result == [(1, "steam"), (2, "prismlauncher")]
        mock_launchers.assert_called_once()


class TestKillAndUninstallLaunchers:
    """Tests for kill and uninstall launchers."""

    def test_no_launchers_running(self) -> None:
        """Test that no launchers running."""
        with (
            patch(f"{PKG}.get_pids_by_process_names", return_value={}),
            patch(f"{PKG}.kill_processes_by_name", return_value=[]),
        ):
            assert kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES) == []

    def test_kills_and_uninstalls_owned_package(self) -> None:
        """Test that kills and uninstalls owned package."""
        with (
            patch(
                f"{PKG}.get_pids_by_process_names",
                return_value={123: "prismlauncher"},
            ),
            patch(f"{PKG}.Path") as mock_path_cls,
            patch(
                f"{PKG}.kill_processes_by_name",
                return_value=[(123, "prismlauncher")],
            ),
            patch(f"{PKG}.pacman_owner", return_value="prismlauncher-git"),
            patch(f"{PKG}.uninstall_package", return_value=True) as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.return_value = "/usr/bin/prismlauncher"
            result = kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES)
        assert result == [(123, "prismlauncher")]
        mock_uninstall.assert_called_once_with("prismlauncher-git")

    def test_exe_path_unreadable_skips_uninstall(self) -> None:
        """Test that exe path unreadable skips uninstall."""
        with (
            patch(
                f"{PKG}.get_pids_by_process_names",
                return_value={123: "prismlauncher"},
            ),
            patch(f"{PKG}.Path") as mock_path_cls,
            patch(
                f"{PKG}.kill_processes_by_name",
                return_value=[(123, "prismlauncher")],
            ),
            patch(f"{PKG}.pacman_owner") as mock_owner,
            patch(f"{PKG}.uninstall_package") as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.side_effect = OSError
            result = kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES)
        assert result == [(123, "prismlauncher")]
        mock_owner.assert_not_called()
        mock_uninstall.assert_not_called()

    def test_unowned_package_not_uninstalled(self) -> None:
        """Test that unowned package not uninstalled."""
        with (
            patch(f"{PKG}.get_pids_by_process_names", return_value={123: "custom"}),
            patch(f"{PKG}.Path") as mock_path_cls,
            patch(f"{PKG}.kill_processes_by_name", return_value=[(123, "custom")]),
            patch(f"{PKG}.pacman_owner", return_value=None),
            patch(f"{PKG}.uninstall_package") as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.return_value = "/opt/custom/launcher"
            kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES)
        mock_uninstall.assert_not_called()

    def test_uninstall_failure_is_logged_not_raised(self) -> None:
        """Test that uninstall failure is logged not raised."""
        with (
            patch(
                f"{PKG}.get_pids_by_process_names",
                return_value={123: "prismlauncher"},
            ),
            patch(f"{PKG}.Path") as mock_path_cls,
            patch(
                f"{PKG}.kill_processes_by_name",
                return_value=[(123, "prismlauncher")],
            ),
            patch(f"{PKG}.pacman_owner", return_value="prismlauncher-git"),
            patch(f"{PKG}.uninstall_package", return_value=False),
        ):
            mock_path_cls.return_value.resolve.return_value = "/usr/bin/prismlauncher"
            kill_and_uninstall_launchers(LAUNCHER_PROCESS_NAMES)  # must not raise


# ──────────────────────────────────────────────────────────────
# Steam package removal
# ──────────────────────────────────────────────────────────────


class TestIsSteamInstalled:
    """Tests for is steam installed."""

    def test_installed(self) -> None:
        """Test that installed."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            return_value=MagicMock(returncode=0),
        ):
            assert is_steam_installed() is True

    def test_not_installed(self) -> None:
        """Test that not installed."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            return_value=MagicMock(returncode=1),
        ):
            assert is_steam_installed() is False


class TestUninstallSteamPackage:
    """Tests for uninstall steam package."""

    def test_success(self) -> None:
        """Test that success."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            return_value=MagicMock(returncode=0, stderr=""),
        ):
            assert uninstall_steam_package() is True

    def test_already_absent_treated_as_success(self) -> None:
        """Test that already absent treated as success."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            return_value=MagicMock(
                returncode=1, stderr="error: target not found: steam"
            ),
        ):
            assert uninstall_steam_package() is True

    def test_real_failure_returns_false(self) -> None:
        """Test that real failure returns false."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert uninstall_steam_package() is False

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(
            "steam_backlog_enforcer._pacman.subprocess.run", side_effect=OSError
        ):
            assert uninstall_steam_package() is False
