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
    _is_steam_installed,
    _kill_and_uninstall_launchers,
    _kill_steam_and_launchers,
    _load_cached_ips,
    _pacman_owner,
    _remove_total_block_hosts,
    _remove_total_block_iptables,
    _save_cached_ips,
    _uninstall_package,
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
    lock_file: Path
    ip_cache_file: Path
    hosts_file: Path


@pytest.fixture(autouse=True)
def paths(tmp_path: Path) -> Iterator[_Paths]:
    """Redirect the module's path constants to tmp_path for every test."""
    paths = _Paths(
        lock_file=tmp_path / "total_block_lock.json",
        ip_cache_file=tmp_path / "total_block_ip_cache.json",
        hosts_file=tmp_path / "hosts",
    )
    with (
        patch(f"{PKG}.TOTAL_BLOCK_LOCK_FILE", paths.lock_file),
        patch(f"{PKG}._IPTABLES_IP_CACHE_FILE", paths.ip_cache_file),
        patch(f"{PKG}.HOSTS_FILE", paths.hosts_file),
    ):
        yield paths


def _write_lock(paths: _Paths, started_at: float, until: float, days: int = 1) -> None:
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
    def test_no_lock_file(self) -> None:
        assert is_total_block_active() is False

    def test_active_lock(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW, _NOW + 3600)
        assert is_total_block_active() is True

    def test_expired_lock(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW - 3600, _NOW - 1)
        assert is_total_block_active() is False

    def test_malformed_json(self, paths: _Paths) -> None:
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("not json", encoding="utf-8")
        assert is_total_block_active() is False

    def test_non_dict_json(self, paths: _Paths) -> None:
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert is_total_block_active() is False

    def test_missing_until_key(self, paths: _Paths) -> None:
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text(json.dumps({"days": 1}), encoding="utf-8")
        assert is_total_block_active() is False

    def test_non_numeric_until(self, paths: _Paths) -> None:
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text(
            json.dumps({"until": "not-a-number"}), encoding="utf-8"
        )
        assert is_total_block_active() is False


class TestTotalBlockNeedsCleanup:
    def test_no_lock_file(self) -> None:
        assert total_block_needs_cleanup() is False

    def test_active_lock_no_cleanup_needed(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW, _NOW + 3600)
        assert total_block_needs_cleanup() is False

    def test_expired_lock_needs_cleanup(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW - 3600, _NOW - 1)
        assert total_block_needs_cleanup() is True


class TestGetTotalBlockStatus:
    def test_no_lock(self) -> None:
        status = get_total_block_status()
        assert status.active is False
        assert status.started_at is None
        assert status.until is None
        assert status.days == 0
        assert status.days_remaining == 0.0

    def test_active_lock(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW, _NOW + 86400, days=1)
        status = get_total_block_status()
        assert status.active is True
        assert status.days == 1
        assert 0.0 < status.days_remaining <= 1.0
        assert status.started_at is not None
        assert status.until is not None

    def test_expired_lock(self, paths: _Paths) -> None:
        _write_lock(paths, _NOW - 7200, _NOW - 3600, days=1)
        status = get_total_block_status()
        assert status.active is False
        assert status.days_remaining == 0.0

    def test_malformed_json_returns_inactive(self, paths: _Paths) -> None:
        paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
        paths.lock_file.write_text("garbage", encoding="utf-8")
        status = get_total_block_status()
        assert status.active is False

    def test_non_int_days_defaults_to_zero(self, paths: _Paths) -> None:
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
    def test_combines_steam_and_launcher_kills(self) -> None:
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
    def test_owned_path_returns_package_name(self) -> None:
        result = MagicMock(
            returncode=0,
            stdout="/usr/bin/prismlauncher is owned by prismlauncher-git 11.0.0-1\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/usr/bin/prismlauncher") == "prismlauncher-git"

    def test_unowned_path_returns_none(self) -> None:
        result = MagicMock(returncode=1, stdout="")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/opt/foo/bar") is None

    def test_unexpected_output_format_returns_none(self) -> None:
        result = MagicMock(returncode=0, stdout="something unexpected\n")
        with patch(f"{PKG}.subprocess.run", return_value=result):
            assert _pacman_owner("/usr/bin/x") is None


class TestUninstallPackage:
    def test_success(self) -> None:
        with patch(
            f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")
        ):
            assert _uninstall_package("foo") is True

    def test_already_absent_treated_as_success(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="error: target not found: foo"),
        ):
            assert _uninstall_package("foo") is True

    def test_real_failure_returns_false(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert _uninstall_package("foo") is False

    def test_subprocess_error_returns_false(self) -> None:
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _uninstall_package("foo") is False


class TestKillAndUninstallLaunchers:
    def test_no_launchers_running(self) -> None:
        with (
            patch(f"{PKG}.get_pids_by_process_names", return_value={}),
            patch(f"{PKG}.kill_processes_by_name", return_value=[]),
        ):
            assert _kill_and_uninstall_launchers() == []

    def test_kills_and_uninstalls_owned_package(self) -> None:
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
    def test_installed(self) -> None:
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _is_steam_installed() is True

    def test_not_installed(self) -> None:
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _is_steam_installed() is False


class TestUninstallSteamPackage:
    def test_success(self) -> None:
        with patch(
            f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")
        ):
            assert _uninstall_steam_package() is True

    def test_already_absent_treated_as_success(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(
                returncode=1, stderr="error: target not found: steam"
            ),
        ):
            assert _uninstall_steam_package() is True

    def test_real_failure_returns_false(self) -> None:
        with patch(
            f"{PKG}.subprocess.run",
            return_value=MagicMock(returncode=1, stderr="some other error"),
        ):
            assert _uninstall_steam_package() is False

    def test_subprocess_error_returns_false(self) -> None:
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _uninstall_steam_package() is False


# ──────────────────────────────────────────────────────────────
# Hosts domain blocking
# ──────────────────────────────────────────────────────────────


class TestApplyTotalBlockHosts:
    def test_appends_block_when_absent(self, paths: _Paths) -> None:
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
        paths.hosts_file.write_text(
            f"127.0.0.1 localhost\n{_HOSTS_BLOCK_BEGIN}"
            f"0.0.0.0 x.com\n{_HOSTS_BLOCK_END}",
            encoding="utf-8",
        )
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert _apply_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        assert _apply_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(self, paths: _Paths) -> None:
        paths.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as mock_enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert _apply_total_block_hosts() is False
        mock_enable.assert_called_once()


class TestRemoveTotalBlockHosts:
    def test_removes_block_when_present(self, paths: _Paths) -> None:
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
        paths.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        with patch(f"{PKG}._sudo_write_hosts") as mock_write:
            assert _remove_total_block_hosts() is True
        mock_write.assert_not_called()

    def test_missing_hosts_file_returns_false(self) -> None:
        assert _remove_total_block_hosts() is False

    def test_write_failure_still_reenables_protection(self, paths: _Paths) -> None:
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
    def test_load_no_file_returns_empty(self) -> None:
        assert _load_cached_ips() == set()

    def test_save_then_load_round_trips(self) -> None:
        _save_cached_ips({"1.2.3.4", "5.6.7.8"})
        assert _load_cached_ips() == {"1.2.3.4", "5.6.7.8"}

    def test_load_malformed_json_returns_empty(self, paths: _Paths) -> None:
        paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        paths.ip_cache_file.write_text("not json", encoding="utf-8")
        assert _load_cached_ips() == set()

    def test_load_non_list_json_returns_empty(self, paths: _Paths) -> None:
        paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        paths.ip_cache_file.write_text(json.dumps({"a": 1}), encoding="utf-8")
        assert _load_cached_ips() == set()


# ──────────────────────────────────────────────────────────────
# iptables
# ──────────────────────────────────────────────────────────────


class TestIptablesChainIntact:
    def test_missing_chain_returns_false(self) -> None:
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_missing_ip_returns_false(self) -> None:
        listing = MagicMock(
            returncode=0,
            stdout="-N STEAM_TOTAL_BLOCK\n-A STEAM_TOTAL_BLOCK -d 9.9.9.9/32 -j DROP\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=listing):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_all_ips_present_and_hooked_returns_true(self) -> None:
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
    def test_intact_chain_short_circuits(self) -> None:
        _save_cached_ips({"1.2.3.4"})
        with (
            patch(f"{PKG}._iptables_chain_intact", return_value=True),
            patch(f"{PKG}.subprocess.run") as mock_run,
        ):
            assert _apply_total_block_iptables() is True
        mock_run.assert_not_called()

    def test_rebuilds_when_not_intact(self) -> None:
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
        import socket as real_socket

        with (
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=real_socket.gaierror),
        ):
            assert _apply_total_block_iptables() is True
        assert _load_cached_ips() == set()

    def test_subprocess_error_returns_false(self) -> None:
        with (
            patch(
                f"{PKG}.subprocess.run",
                side_effect=[MagicMock(returncode=0), OSError],
            ),
            patch(f"{PKG}.socket.getaddrinfo", return_value=[]),
        ):
            assert _apply_total_block_iptables() is False

    def test_inserts_output_hook_when_missing(self) -> None:
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
    def test_removes_chain_and_cache(self, paths: _Paths) -> None:
        _save_cached_ips({"1.2.3.4"})
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _remove_total_block_iptables() is True
        assert not paths.ip_cache_file.exists()

    def test_no_cache_file_is_fine(self) -> None:
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert _remove_total_block_iptables() is True

    def test_subprocess_error_returns_false(self) -> None:
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert _remove_total_block_iptables() is False


# ──────────────────────────────────────────────────────────────
# Public lifecycle API
# ──────────────────────────────────────────────────────────────


class TestStartTotalBlock:
    def test_success(self) -> None:
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._uninstall_steam_package", return_value=True),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True

    def test_package_block_start_failure_aborts(self) -> None:
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
            patch(f"{PKG}._apply_total_block_hosts", return_value=False),
            patch(f"{PKG}._apply_total_block_iptables", return_value=False),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True

    def test_logs_when_processes_were_killed(self) -> None:
        with (
            patch(
                f"{PKG}.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=""),
            ),
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[(1, "steam")]),
            patch(f"{PKG}._uninstall_steam_package", return_value=True),
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
            patch(f"{PKG}.flush_dns_cache"),
        ):
            assert start_total_block(1) is True


class TestEnforceTotalBlockTick:
    def test_reinstalls_steam_if_reappeared(self) -> None:
        with (
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._is_steam_installed", return_value=True),
            patch(f"{PKG}._uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_called_once()

    def test_no_reinstall_when_steam_absent(self) -> None:
        with (
            patch(f"{PKG}._kill_steam_and_launchers", return_value=[]),
            patch(f"{PKG}._is_steam_installed", return_value=False),
            patch(f"{PKG}._uninstall_steam_package") as mock_uninstall,
            patch(f"{PKG}._apply_total_block_hosts", return_value=True),
            patch(f"{PKG}._apply_total_block_iptables", return_value=True),
        ):
            enforce_total_block_tick()
        mock_uninstall.assert_not_called()


class TestEndTotalBlockCleanup:
    def test_ends_lock_and_removes_blocks(self) -> None:
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
    assert IPTABLES_CHAIN == "STEAM_TOTAL_BLOCK"
