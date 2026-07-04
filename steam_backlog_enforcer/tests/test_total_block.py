"""Tests for _total_block module (block-gaming total block).

`TOTAL_BLOCK_LOCK_FILE`, `_IPTABLES_IP_CACHE_FILE`, and `HOSTS_FILE` are
patched per-test by the `paths` fixture below to tmp_path locations,
overriding conftest's own autouse patch with paths the tests can read and
write directly. Tests must never do `from ... import TOTAL_BLOCK_LOCK_FILE`
- that captures the value at file-import time, before any patch is active,
and silently ignores every subsequent patch (the same binding gotcha
documented in this repo's own conftest.py for HLTB_CACHE_FILE).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._total_block import (
    _HOSTS_BLOCK_BEGIN,
    _HOSTS_BLOCK_END,
    IPTABLES_CHAIN,
    _apply_total_block_hosts,
    _apply_total_block_iptables,
    _iptables_chain_intact,
    _is_package_installed,
    _is_steam_installed,
    _kill_and_uninstall_launchers,
    _kill_steam_and_launchers,
    _load_cached_ips,
    _log_steam_purge,
    _pacman_owner,
    _purge_steam_and_proton,
    _remove_steam_remnants,
    _remove_total_block_hosts,
    _remove_total_block_iptables,
    _save_cached_ips,
    _uninstall_package,
    _uninstall_proton_helpers,
    _uninstall_steam_package,
    end_total_block_cleanup,
    enforce_total_block_tick,
    get_total_block_status,
    is_total_block_active,
    start_total_block,
    total_block_needs_cleanup,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer._total_block"


@dataclass
class _Paths:
    """Tests for paths."""

    lock_file: Path
    ip_cache_file: Path
    hosts_file: Path
    purge_log_file: Path
    remnant_paths: tuple[Path, ...]


@pytest.fixture(autouse=True)
def paths(tmp_path: Path) -> Iterator[_Paths]:
    """Redirect the module's path constants to tmp_path for every test."""
    remnant_paths = (
        tmp_path / "home" / ".steam",
        tmp_path / "home" / "steam",
        tmp_path / "home" / ".local" / "share" / "Steam",
        tmp_path / "home" / ".steampath",
        tmp_path / "home" / ".steampid",
        tmp_path / "home" / ".config" / "steamtinkerlaunch",
        tmp_path / "home" / ".config" / "CSDSteamBuild",
    )
    paths = _Paths(
        lock_file=tmp_path / "total_block_lock.json",
        ip_cache_file=tmp_path / "total_block_ip_cache.json",
        hosts_file=tmp_path / "hosts",
        purge_log_file=tmp_path / "total_block_purge_log.json",
        remnant_paths=remnant_paths,
    )
    with (
        patch(f"{PKG}.TOTAL_BLOCK_LOCK_FILE", paths.lock_file),
        patch(f"{PKG}._IPTABLES_IP_CACHE_FILE", paths.ip_cache_file),
        patch(f"{PKG}.HOSTS_FILE", paths.hosts_file),
        patch(f"{PKG}._STEAM_PURGE_LOG_FILE", paths.purge_log_file),
        patch(f"{PKG}._STEAM_REMNANT_PATHS", paths.remnant_paths),
    ):
        yield paths


def _write_lock(paths: _Paths, started_at: float, until: float, days: int = 1) -> None:
    """Test that write lock."""
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    paths.lock_file.write_text(
        json.dumps({"started_at": started_at, "until": until, "days": days}),
        encoding="utf-8",
    )


_NOW = datetime.now(timezone.utc).timestamp()


# ──────────────────────────────────────────────────────────────
# Lock reading / status
# ──────────────────────────────────────────────────────────────


class TestIsTotalBlockActive:
    """Tests for is total block active."""

    def test_no_lock_file(self) -> None:
        """Test that no lock file."""
        assert is_total_block_active() is False

    def test_active_lock(self, paths: _Paths) -> None:
        """Test that active lock."""
        _write_lock(paths, _NOW, _NOW + 3600)
        assert is_total_block_active() is True

    def test_expired_lock(self, paths: _Paths) -> None:
        """Test that expired lock."""
        _write_lock(paths, _NOW - 3600, _NOW - 1)
        assert is_total_block_active() is False

    def test_malformed_json(self, paths: _Paths) -> None:
        """Test that malformed json."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("not json", encoding="utf-8")
        assert is_total_block_active() is False

    def test_non_dict_json(self, paths: _Paths) -> None:
        """Test that non dict json."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert is_total_block_active() is False

    def test_missing_until_key(self, paths: _Paths) -> None:
        """Test that missing until key."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text(json.dumps({"days": 1}), encoding="utf-8")
        assert is_total_block_active() is False

    def test_non_numeric_until(self, paths: _Paths) -> None:
        """Test that non numeric until."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text(
            json.dumps({"until": "not-a-number"}), encoding="utf-8"
        )
        assert is_total_block_active() is False


class TestTotalBlockNeedsCleanup:
    """Tests for total block needs cleanup."""

    def test_no_lock_file(self) -> None:
        """Test that no lock file."""
        assert total_block_needs_cleanup() is False

    def test_active_lock_no_cleanup_needed(self, paths: _Paths) -> None:
        """Test that active lock no cleanup needed."""
        _write_lock(paths, _NOW, _NOW + 3600)
        assert total_block_needs_cleanup() is False

    def test_expired_lock_needs_cleanup(self, paths: _Paths) -> None:
        """Test that expired lock needs cleanup."""
        _write_lock(paths, _NOW - 3600, _NOW - 1)
        assert total_block_needs_cleanup() is True


class TestGetTotalBlockStatus:
    """Tests for get total block status."""

    def test_no_lock(self) -> None:
        """Test that no lock."""
        status = get_total_block_status()
        assert status.active is False
        assert status.started_at is None
        assert status.until is None
        assert status.days == 0
        assert status.days_remaining == 0.0

    def test_active_lock(self, paths: _Paths) -> None:
        """Test that active lock."""
        _write_lock(paths, _NOW, _NOW + 86400, days=1)
        status = get_total_block_status()
        assert status.active is True
        assert status.days == 1
        assert 0.0 < status.days_remaining <= 1.0
        assert status.started_at is not None
        assert status.until is not None

    def test_expired_lock(self, paths: _Paths) -> None:
        """Test that expired lock."""
        _write_lock(paths, _NOW - 7200, _NOW - 3600, days=1)
        status = get_total_block_status()
        assert status.active is False
        assert status.days_remaining == 0.0

    def test_malformed_json_returns_inactive(self, paths: _Paths) -> None:
        """Test that malformed json returns inactive."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("garbage", encoding="utf-8")
        status = get_total_block_status()
        assert status.active is False

    def test_non_int_days_defaults_to_zero(self, paths: _Paths) -> None:
        """Test that non int days defaults to zero."""
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text(
            json.dumps({"started_at": _NOW, "until": _NOW + 3600, "days": "one"}),
            encoding="utf-8",
        )
        status = get_total_block_status()
        assert status.days == 0


# ──────────────────────────────────────────────────────────────
# Process killing
# ──────────────────────────────────────────────────────────────


class TestKillSteamAndLaunchers:
    """Tests for kill steam and launchers."""

    def test_combines_steam_and_launcher_kills(self) -> None:
        """Test that combines steam and launcher kills."""
        with (
            patch(f"{PKG}.kill_processes_by_name", return_value=[(1, "steam")]),
            patch(
                f"{PKG}._kill_and_uninstall_launchers",
                return_value=[(2, "prismlauncher")],
            ) as mock_launchers,
        ):
            result = _kill_steam_and_launchers()
        assert result == [(1, "steam"), (2, "prismlauncher")]
        mock_launchers.assert_called_once()


class TestPacmanOwner:
    """Tests for pacman owner."""

    def test_owned_path_returns_package_name(self) -> None:
        """Test that owned path returns package name."""
        result = MagicMock(
            returncode=0,
            stdout="/usr/bin/prismlauncher is owned by prismlauncher-git 11.0.0-1\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/usr/bin/prismlauncher") == "prismlauncher-git"

    def test_unowned_path_returns_none(self) -> None:
        """Test that unowned path returns none."""
        result = MagicMock(returncode=1, stdout="")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/opt/foo/bar") is None

    def test_unexpected_output_format_returns_none(self) -> None:
        """Test that unexpected output format returns none."""
        result = MagicMock(returncode=0, stdout="something unexpected\n")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/usr/bin/x") is None


class TestUninstallPackage:
    """Tests for uninstall package."""

    def test_success(self) -> None:
        """Test that success."""
        with patch(
            f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")
        ):
            assert _uninstall_package("foo") is True

    def test_already_absent_treated_as_success(self) -> None:
        """Test that already absent treated as success."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="error: target not found: foo"),
        ):
            assert _uninstall_package("foo") is True

    def test_real_failure_returns_false(self) -> None:
        """Test that real failure returns false."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert _uninstall_package("foo") is False

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _uninstall_package("foo") is False


class TestKillAndUninstallLaunchers:
    """Tests for kill and uninstall launchers."""

    def test_no_launchers_running(self) -> None:
        """Test that no launchers running."""
        with (
            patch(f"{PKG}.get_pids_by_process_names", return_value={}),
            patch(f"{PKG}.kill_processes_by_name", return_value=[]),
        ):
            assert _kill_and_uninstall_launchers() == []

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
            patch(f"{PKG}._pacman_owner", return_value="prismlauncher-git"),
            patch(f"{PKG}._uninstall_package", return_value=True) as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.return_value = "/usr/bin/prismlauncher"
            result = _kill_and_uninstall_launchers()
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
            patch(f"{PKG}._pacman_owner") as mock_owner,
            patch(f"{PKG}._uninstall_package") as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.side_effect = OSError
            result = _kill_and_uninstall_launchers()
        assert result == [(123, "prismlauncher")]
        mock_owner.assert_not_called()
        mock_uninstall.assert_not_called()

    def test_unowned_package_not_uninstalled(self) -> None:
        """Test that unowned package not uninstalled."""
        with (
            patch(f"{PKG}.get_pids_by_process_names", return_value={123: "custom"}),
            patch(f"{PKG}.Path") as mock_path_cls,
            patch(f"{PKG}.kill_processes_by_name", return_value=[(123, "custom")]),
            patch(f"{PKG}._pacman_owner", return_value=None),
            patch(f"{PKG}._uninstall_package") as mock_uninstall,
        ):
            mock_path_cls.return_value.resolve.return_value = "/opt/custom/launcher"
            _kill_and_uninstall_launchers()
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
            patch(f"{PKG}._pacman_owner", return_value="prismlauncher-git"),
            patch(f"{PKG}._uninstall_package", return_value=False),
        ):
            mock_path_cls.return_value.resolve.return_value = "/usr/bin/prismlauncher"
            _kill_and_uninstall_launchers()  # must not raise


# ──────────────────────────────────────────────────────────────
# Steam package removal
# ──────────────────────────────────────────────────────────────


class TestIsSteamInstalled:
    """Tests for is steam installed."""

    def test_installed(self) -> None:
        """Test that installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _is_steam_installed() is True

    def test_not_installed(self) -> None:
        """Test that not installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _is_steam_installed() is False


class TestUninstallSteamPackage:
    """Tests for uninstall steam package."""

    def test_success(self) -> None:
        """Test that success."""
        with patch(
            f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")
        ):
            assert _uninstall_steam_package() is True

    def test_already_absent_treated_as_success(self) -> None:
        """Test that already absent treated as success."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(
                returncode=1, stderr="error: target not found: steam"
            ),
        ):
            assert _uninstall_steam_package() is True

    def test_real_failure_returns_false(self) -> None:
        """Test that real failure returns false."""
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert _uninstall_steam_package() is False

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _uninstall_steam_package() is False


class TestIsPackageInstalled:
    """Tests for is package installed."""

    def test_installed(self) -> None:
        """Test that installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _is_package_installed("protonup-qt") is True

    def test_not_installed(self) -> None:
        """Test that not installed."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _is_package_installed("protonup-qt") is False


class TestUninstallProtonHelpers:
    """Tests for uninstall proton helpers."""

    def test_none_installed_removes_nothing(self) -> None:
        """Test that none installed removes nothing."""
        with patch(f"{PKG}._is_package_installed", return_value=False):
            assert _uninstall_proton_helpers() == []

    def test_installed_packages_are_uninstalled(self) -> None:
        """Test that installed packages are uninstalled."""
        installed = {"protonup-qt", "protontricks-git"}
        with (
            patch(f"{PKG}._is_package_installed", side_effect=lambda p: p in installed),
            patch(f"{PKG}._uninstall_package", return_value=True) as mock_uninstall,
        ):
            removed = _uninstall_proton_helpers()
        assert set(removed) == installed
        assert mock_uninstall.call_count == len(installed)

    def test_failed_uninstall_is_logged_not_raised(self) -> None:
        """Test that failed uninstall is logged not raised."""
        with (
            patch(f"{PKG}._is_package_installed", return_value=True),
            patch(f"{PKG}._uninstall_package", return_value=False),
        ):
            assert _uninstall_proton_helpers() == []


class TestRemoveSteamRemnants:
    """Tests for remove steam remnants."""

    def test_no_remnants_present(self, paths: _Paths) -> None:
        """Test that no remnants present."""
        assert _remove_steam_remnants() == []

    def test_removes_directory(self, paths: _Paths) -> None:
        """Test that removes directory."""
        steam_dir = paths.remnant_paths[0]
        (steam_dir / "steamapps").mkdir(parents=True)
        removed = _remove_steam_remnants()
        assert str(steam_dir) in removed
        assert not steam_dir.exists()

    def test_removes_symlink_without_following_into_rmtree(self, paths: _Paths) -> None:
        """Test that removes symlink without following into rmtree."""
        # Target lives outside the curated remnant list, so this test can
        # tell "unlinked the symlink" apart from "rmtree'd its target".
        external_target = paths.remnant_paths[0].parent / "external_target.pid"
        external_target.parent.mkdir(parents=True, exist_ok=True)
        external_target.write_text("123", encoding="utf-8")
        symlink_path = paths.remnant_paths[4]
        symlink_path.symlink_to(external_target)

        removed = _remove_steam_remnants()

        assert str(symlink_path) in removed
        assert not symlink_path.exists()
        assert not symlink_path.is_symlink()
        assert external_target.exists()

    def test_removal_failure_is_logged_not_raised(self, paths: _Paths) -> None:
        """Test that removal failure is logged not raised."""
        steam_dir = paths.remnant_paths[0]
        steam_dir.mkdir(parents=True)
        with patch(f"{PKG}.shutil.rmtree", side_effect=OSError):
            assert _remove_steam_remnants() == []


class TestLogSteamPurge:
    """Tests for log steam purge."""

    def test_noop_when_nothing_removed(self, paths: _Paths) -> None:
        """Test that noop when nothing removed."""
        _log_steam_purge([], [])
        assert not paths.purge_log_file.exists()

    def test_appends_entry(self, paths: _Paths) -> None:
        """Test that appends entry."""
        _log_steam_purge(["/home/kuhy/.steam"], ["protonup-qt"])
        entries = json.loads(paths.purge_log_file.read_text(encoding="utf-8"))
        assert len(entries) == 1
        assert entries[0]["removed_paths"] == ["/home/kuhy/.steam"]
        assert entries[0]["removed_packages"] == ["protonup-qt"]

        _log_steam_purge(["/home/kuhy/steam"], [])
        entries = json.loads(paths.purge_log_file.read_text(encoding="utf-8"))
        assert len(entries) == 2

    def test_corrupt_log_file_is_reset(self, paths: _Paths) -> None:
        """Test that corrupt log file is reset."""
        paths.purge_log_file.parent.mkdir(parents=True, exist_ok=True)
        paths.purge_log_file.write_text("not json", encoding="utf-8")
        _log_steam_purge(["/home/kuhy/.steam"], [])
        entries = json.loads(paths.purge_log_file.read_text(encoding="utf-8"))
        assert len(entries) == 1

    def test_non_list_log_file_is_reset(self, paths: _Paths) -> None:
        """Test that non list log file is reset."""
        paths.purge_log_file.parent.mkdir(parents=True, exist_ok=True)
        paths.purge_log_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        _log_steam_purge(["/home/kuhy/.steam"], [])
        entries = json.loads(paths.purge_log_file.read_text(encoding="utf-8"))
        assert len(entries) == 1


class TestPurgeSteamAndProton:
    """Tests for purge steam and proton."""

    def test_delegates_and_logs(self, paths: _Paths) -> None:
        """Test that delegates and logs."""
        with (
            patch(f"{PKG}._remove_steam_remnants", return_value=["/home/kuhy/.steam"]),
            patch(f"{PKG}._uninstall_proton_helpers", return_value=["protonup-qt"]),
        ):
            _purge_steam_and_proton()
        entries = json.loads(paths.purge_log_file.read_text(encoding="utf-8"))
        assert entries[0]["removed_paths"] == ["/home/kuhy/.steam"]
        assert entries[0]["removed_packages"] == ["protonup-qt"]

    def test_nothing_removed_does_not_log(self, paths: _Paths) -> None:
        """Test that nothing removed does not log."""
        with (
            patch(f"{PKG}._remove_steam_remnants", return_value=[]),
            patch(f"{PKG}._uninstall_proton_helpers", return_value=[]),
        ):
            _purge_steam_and_proton()
        assert not paths.purge_log_file.exists()


# ──────────────────────────────────────────────────────────────
# Hosts domain blocking
# ──────────────────────────────────────────────────────────────


class TestApplyTotalBlockHosts:
    """Tests for apply total block hosts."""

    def test_appends_block_when_absent(self, paths: _Paths) -> None:
        """Test that appends block when absent."""
        paths.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as mock_write,
        ):
            assert _apply_total_block_hosts() is True
        written = mock_write.call_args.args[0]
        assert _HOSTS_BLOCK_BEGIN in written
        assert _HOSTS_BLOCK_END in written
        assert "steamcommunity.com" in written

    def test_already_present_is_noop(self, paths: _Paths) -> None:
        """Test that already present is noop."""
        paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}",
            encoding="utf-8",
        )
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert _apply_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        """Test that missing hosts file returns false."""
        assert _apply_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(self, paths: _Paths) -> None:
        """Test that write failure still reenables protection."""
        paths.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as mock_enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert _apply_total_block_hosts() is False
        mock_enable.assert_called_once()


class TestRemoveTotalBlockHosts:
    """Tests for remove total block hosts."""

    def test_removes_block_when_present(self, paths: _Paths) -> None:
        """Test that removes block when present."""
        paths.hosts_file.write_text(
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
            assert _remove_total_block_hosts() is True
        written = mock_write.call_args.args[0]
        assert _HOSTS_BLOCK_BEGIN not in written
        assert "router" in written
        assert "localhost" in written

    def test_absent_is_noop(self, paths: _Paths) -> None:
        """Test that absent is noop."""
        paths.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert _remove_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        """Test that missing hosts file returns false."""
        assert _remove_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(self, paths: _Paths) -> None:
        """Test that write failure still reenables protection."""
        paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}",
            encoding="utf-8",
        )
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as mock_enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert _remove_total_block_hosts() is False
        mock_enable.assert_called_once()


# ──────────────────────────────────────────────────────────────
# IP cache
# ──────────────────────────────────────────────────────────────


class TestIpCache:
    """Tests for ip cache."""

    def test_load_no_file_returns_empty(self) -> None:
        """Test that load no file returns empty."""
        assert _load_cached_ips() == set()

    def test_save_then_load_round_trips(self) -> None:
        """Test that save then load round trips."""
        _save_cached_ips({"1.2.3.4", "5.6.7.8"})
        assert _load_cached_ips() == {"1.2.3.4", "5.6.7.8"}

    def test_load_malformed_json_returns_empty(self, paths: _Paths) -> None:
        """Test that load malformed json returns empty."""
        paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        paths.ip_cache_file.write_text("not json", encoding="utf-8")
        assert _load_cached_ips() == set()

    def test_load_non_list_json_returns_empty(self, paths: _Paths) -> None:
        """Test that load non list json returns empty."""
        paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        paths.ip_cache_file.write_text(json.dumps({"a": 1}), encoding="utf-8")
        assert _load_cached_ips() == set()


# ──────────────────────────────────────────────────────────────
# iptables
# ──────────────────────────────────────────────────────────────


class TestIptablesChainIntact:
    """Tests for iptables chain intact."""

    def test_missing_chain_returns_false(self) -> None:
        """Test that missing chain returns false."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_missing_ip_returns_false(self) -> None:
        """Test that missing ip returns false."""
        listing = MagicMock(
            returncode=0,
            stdout="-N STEAM_TOTAL_BLOCK\n-A STEAM_TOTAL_BLOCK -d 9.9.9.9/32 -j DROP\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=listing):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_all_ips_present_and_hooked_returns_true(self) -> None:
        """Test that all ips present and hooked returns true."""
        listing = MagicMock(
            returncode=0,
            stdout=(
                "-N STEAM_TOTAL_BLOCK\n"
                "-A STEAM_TOTAL_BLOCK -d 1.2.3.4/32 -j DROP\n"
                "-A STEAM_TOTAL_BLOCK -d 5.6.7.8/32 -j DROP\n"
            ),
        )
        hook_check = MagicMock(returncode=0)
        with patch(f"{PKG}.subprocess.run", side_effect=[listing, hook_check]):
            assert _iptables_chain_intact({"1.2.3.4", "5.6.7.8"}) is True

    def test_ips_present_but_not_hooked_returns_false(self) -> None:
        """Test that ips present but not hooked returns false."""
        listing = MagicMock(
            returncode=0,
            stdout="-A STEAM_TOTAL_BLOCK -d 1.2.3.4/32 -j DROP\n",
        )
        hook_check = MagicMock(returncode=1)
        with patch(f"{PKG}.subprocess.run", side_effect=[listing, hook_check]):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_malformed_trailing_d_flag_is_ignored(self) -> None:
        """A `-d` token with nothing after it (malformed/truncated rule
        line) must not index past the end of `parts`."""
        listing = MagicMock(
            returncode=0,
            stdout="-A STEAM_TOTAL_BLOCK -j DROP -d\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=listing):
            assert _iptables_chain_intact({"1.2.3.4"}) is False


class TestApplyTotalBlockIptables:
    """Tests for apply total block iptables."""

    def test_intact_chain_short_circuits(self) -> None:
        """Test that intact chain short circuits."""
        _save_cached_ips({"1.2.3.4"})
        with (
            patch(f"{PKG}._iptables_chain_intact", return_value=True),
            patch(f"{PKG}.subprocess.run") as mock_run,
        ):
            assert _apply_total_block_iptables() is True
        mock_run.assert_not_called()

    def test_rebuilds_when_not_intact(self) -> None:
        """Test that rebuilds when not intact."""
        with (
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch(
                f"{PKG}.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("9.9.9.9", 443))],
            ),
        ):
            assert _apply_total_block_iptables() is True
        assert "9.9.9.9" in _load_cached_ips()

    def test_dns_failure_skips_that_domain(self) -> None:
        """Test that dns failure skips that domain."""
        import socket as real_socket

        with (
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=real_socket.gaierror),
        ):
            assert _apply_total_block_iptables() is True
        assert _load_cached_ips() == set()

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                side_effect=[MagicMock(returncode=0), OSError],
            ),
            patch(f"{PKG}.socket.getaddrinfo", return_value=[]),
        ):
            assert _apply_total_block_iptables() is False

    def test_inserts_output_hook_when_missing(self) -> None:
        """Test that inserts output hook when missing."""

        def run_side_effect(cmd: list[str], **_kwargs: object) -> MagicMock:
            if "-C" in cmd:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with (
            patch(f"{PKG}.subprocess.run", side_effect=run_side_effect),
            patch(f"{PKG}.socket.getaddrinfo", return_value=[]),
        ):
            assert _apply_total_block_iptables() is True


class TestRemoveTotalBlockIptables:
    """Tests for remove total block iptables."""

    def test_removes_chain_and_cache(self, paths: _Paths) -> None:
        """Test that removes chain and cache."""
        _save_cached_ips({"1.2.3.4"})
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _remove_total_block_iptables() is True
        assert not paths.ip_cache_file.exists()

    def test_no_cache_file_is_fine(self) -> None:
        """Test that no cache file is fine."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _remove_total_block_iptables() is True

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _remove_total_block_iptables() is False


# ──────────────────────────────────────────────────────────────
# Public lifecycle API
# ──────────────────────────────────────────────────────────────


class TestStartTotalBlock:
    """Tests for start total block."""

    def test_success(self) -> None:
        """Test that success."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._uninstall_steam_package", return_value=True),
            patch(f"{PKG}._purge_steam_and_proton"),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
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
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._uninstall_steam_package", return_value=True),
            patch(f"{PKG}._purge_steam_and_proton") as mock_purge,
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
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
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._uninstall_steam_package", return_value=False),
            patch(f"{PKG}._purge_steam_and_proton"),
            patch(f"{PKG}._apply_total_block_hosts", return_value=False),
            patch(f"{PKG}._apply_total_block_iptables", return_value=False),
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
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[(1, "steam")]),
            patch(f"{PKG}._uninstall_steam_package", return_value=True),
            patch(f"{PKG}._purge_steam_and_proton"),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True


class TestEnforceTotalBlockTick:
    """Tests for enforce total block tick."""

    def test_reinstalls_steam_if_reappeared(self) -> None:
        """Test that reinstalls steam if reappeared."""
        with (
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._is_steam_installed", return_value=True),
            patch(f"{PKG}._uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}._purge_steam_and_proton"),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_called_once()

    def test_no_reinstall_when_steam_absent(self) -> None:
        """Test that no reinstall when steam absent."""
        with (
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._is_steam_installed", return_value=False),
            patch(f"{PKG}._uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}._purge_steam_and_proton"),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_not_called()

    def test_purges_steam_and_proton_every_tick(self) -> None:
        """Test that purges steam and proton every tick."""
        with (
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._is_steam_installed", return_value=False),
            patch(f"{PKG}._uninstall_steam_package"),
            patch(f"{PKG}._purge_steam_and_proton") as mock_purge,
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
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
            patch(f"{PKG}._remove_total_block_hosts", return_value=True) as mock_hosts,
            patch(f"{PKG}._remove_total_block_iptables", return_value=True) as mock_ipt,
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
            patch(f"{PKG}._remove_total_block_hosts", return_value=True) as mock_hosts,
            patch(f"{PKG}._remove_total_block_iptables", return_value=True) as mock_ipt,
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
            patch(f"{PKG}._remove_total_block_hosts", return_value=False),
            patch(f"{PKG}._remove_total_block_iptables", return_value=True),
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
            patch(f"{PKG}._remove_total_block_hosts", return_value=True),
            patch(f"{PKG}._remove_total_block_iptables", return_value=False),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            end_total_block_cleanup()  # must not raise


# Sanity: the module-level chain name constant is what everything above
# assumes when constructing fake iptables -S output.
def test_iptables_chain_name_constant() -> None:
    """Test that iptables chain name constant."""
    assert IPTABLES_CHAIN == "STEAM_TOTAL_BLOCK"
