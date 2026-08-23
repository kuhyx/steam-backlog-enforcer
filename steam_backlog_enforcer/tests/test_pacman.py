"""Tests for the generic pacman wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._pacman import (
    is_package_installed,
    pacman_owner,
    uninstall_package,
)

PKG = "steam_backlog_enforcer._pacman"


class TestPacmanOwner:
    """Tests for pacman owner."""

    def test_owned_path_returns_package_name(self) -> None:
        """Test that owned path returns package name."""
        result = MagicMock(
            returncode=0,
            stdout="/usr/bin/prismlauncher is owned by prismlauncher-git 11.0.0-1\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert pacman_owner("/usr/bin/prismlauncher") == "prismlauncher-git"

    def test_unowned_path_returns_none(self) -> None:
        """Test that unowned path returns none."""
        result = MagicMock(returncode=1, stdout="")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert pacman_owner("/opt/foo/bar") is None

    def test_unexpected_output_format_returns_none(self) -> None:
        """Test that unexpected output format returns none."""
        result = MagicMock(returncode=0, stdout="something unexpected\n")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert pacman_owner("/usr/bin/x") is None


class TestUninstallPackage:
    """Tests for uninstall package."""

    def test_success(self) -> None:
        """Test that success."""
        with patch(
            f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")
        ):
            assert uninstall_package("foo") is True

    def test_already_absent_treated_as_success(self) -> None:
        """Test that already absent treated as success."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="error: target not found: foo"),
        ):
            assert uninstall_package("foo") is True

    def test_real_failure_returns_false(self) -> None:
        """Test that real failure returns false."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert uninstall_package("foo") is False

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert uninstall_package("foo") is False


class TestIsPackageInstalled:
    """Tests for is package installed."""

    def test_installed(self) -> None:
        """Test that installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert is_package_installed("protonup-qt") is True

    def test_not_installed(self) -> None:
        """Test that not installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert is_package_installed("protonup-qt") is False
