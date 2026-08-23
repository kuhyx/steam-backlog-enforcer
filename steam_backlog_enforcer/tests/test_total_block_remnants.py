"""Tests for removing Proton helpers and filesystem remnants."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._total_block_purge import (
    _log_steam_purge,
    _remove_steam_remnants,
    _uninstall_proton_helpers,
    purge_steam_and_proton,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import (
        Paths,
    )

PKG = "steam_backlog_enforcer._total_block_purge"


class TestUninstallProtonHelpers:
    """Tests for uninstall proton helpers."""

    def test_none_installed_removes_nothing(self) -> None:
        """Test that none installed removes nothing."""
        with patch(f"{PKG}.is_package_installed", return_value=False):
            assert _uninstall_proton_helpers() == []

    def test_installed_packages_are_uninstalled(self) -> None:
        """Test that installed packages are uninstalled."""
        installed = {"protonup-qt", "protontricks-git"}
        with (
            patch(f"{PKG}.is_package_installed", side_effect=lambda p: p in installed),
            patch(f"{PKG}.uninstall_package", return_value=True) as mock_uninstall,
        ):
            removed = _uninstall_proton_helpers()
        assert set(removed) == installed
        assert mock_uninstall.call_count == len(installed)

    def test_failed_uninstall_is_logged_not_raised(self) -> None:
        """Test that failed uninstall is logged not raised."""
        with (
            patch(f"{PKG}.is_package_installed", return_value=True),
            patch(f"{PKG}.uninstall_package", return_value=False),
        ):
            assert _uninstall_proton_helpers() == []


class TestRemoveSteamRemnants:
    """Tests for remove steam remnants."""

    def test_no_remnants_present(self, total_block_paths: Paths) -> None:
        """Test that no remnants present."""
        assert _remove_steam_remnants() == []

    def test_removes_directory(self, total_block_paths: Paths) -> None:
        """Test that removes directory."""
        steam_dir = total_block_paths.remnant_paths[0]
        (steam_dir / "steamapps").mkdir(parents=True)
        removed = _remove_steam_remnants()
        assert str(steam_dir) in removed
        assert not steam_dir.exists()

    def test_removes_symlink_without_following_into_rmtree(
        self, total_block_paths: Paths
    ) -> None:
        """Test that removes symlink without following into rmtree."""
        # Target lives outside the curated remnant list, so this test can
        # tell "unlinked the symlink" apart from "rmtree'd its target".
        external_target = (
            total_block_paths.remnant_paths[0].parent / "external_target.pid"
        )
        external_target.parent.mkdir(parents=True, exist_ok=True)
        external_target.write_text("123", encoding="utf-8")
        symlink_path = total_block_paths.remnant_paths[4]
        symlink_path.symlink_to(external_target)

        removed = _remove_steam_remnants()

        assert str(symlink_path) in removed
        assert not symlink_path.exists()
        assert not symlink_path.is_symlink()
        assert external_target.exists()

    def test_removal_failure_is_logged_not_raised(
        self, total_block_paths: Paths
    ) -> None:
        """Test that removal failure is logged not raised."""
        steam_dir = total_block_paths.remnant_paths[0]
        steam_dir.mkdir(parents=True)
        with patch(f"{PKG}.shutil.rmtree", side_effect=OSError):
            assert _remove_steam_remnants() == []


class TestLogSteamPurge:
    """Tests for log steam purge."""

    def test_noop_when_nothing_removed(self, total_block_paths: Paths) -> None:
        """Test that noop when nothing removed."""
        _log_steam_purge([], [])
        assert not total_block_paths.purge_log_file.exists()

    def test_appends_entry(self, total_block_paths: Paths) -> None:
        """Test that appends entry."""
        _log_steam_purge(["/home/kuhy/.steam"], ["protonup-qt"])
        entries = json.loads(
            total_block_paths.purge_log_file.read_text(encoding="utf-8")
        )
        assert len(entries) == 1
        assert entries[0]["removed_paths"] == ["/home/kuhy/.steam"]
        assert entries[0]["removed_packages"] == ["protonup-qt"]

        _log_steam_purge(["/home/kuhy/steam"], [])
        entries = json.loads(
            total_block_paths.purge_log_file.read_text(encoding="utf-8")
        )
        assert len(entries) == 2

    def test_corrupt_log_file_is_reset(self, total_block_paths: Paths) -> None:
        """Test that corrupt log file is reset."""
        total_block_paths.purge_log_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.purge_log_file.write_text("not json", encoding="utf-8")
        _log_steam_purge(["/home/kuhy/.steam"], [])
        entries = json.loads(
            total_block_paths.purge_log_file.read_text(encoding="utf-8")
        )
        assert len(entries) == 1

    def test_non_list_log_file_is_reset(self, total_block_paths: Paths) -> None:
        """Test that non list log file is reset."""
        total_block_paths.purge_log_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.purge_log_file.write_text(
            json.dumps({"not": "a list"}), encoding="utf-8"
        )
        _log_steam_purge(["/home/kuhy/.steam"], [])
        entries = json.loads(
            total_block_paths.purge_log_file.read_text(encoding="utf-8")
        )
        assert len(entries) == 1


class TestPurgeSteamAndProton:
    """Tests for purge steam and proton."""

    def test_delegates_and_logs(self, total_block_paths: Paths) -> None:
        """Test that delegates and logs."""
        with (
            patch(f"{PKG}._remove_steam_remnants", return_value=["/home/kuhy/.steam"]),
            patch(f"{PKG}._uninstall_proton_helpers", return_value=["protonup-qt"]),
        ):
            purge_steam_and_proton()
        entries = json.loads(
            total_block_paths.purge_log_file.read_text(encoding="utf-8")
        )
        assert entries[0]["removed_paths"] == ["/home/kuhy/.steam"]
        assert entries[0]["removed_packages"] == ["protonup-qt"]

    def test_nothing_removed_does_not_log(self, total_block_paths: Paths) -> None:
        """Test that nothing removed does not log."""
        with (
            patch(f"{PKG}._remove_steam_remnants", return_value=[]),
            patch(f"{PKG}._uninstall_proton_helpers", return_value=[]),
        ):
            purge_steam_and_proton()
        assert not total_block_paths.purge_log_file.exists()


# ──────────────────────────────────────────────────────────────
# Hosts domain blocking
# ──────────────────────────────────────────────────────────────
