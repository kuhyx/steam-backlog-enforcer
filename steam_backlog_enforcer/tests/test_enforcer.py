"""Tests for enforcer module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from python_pkg.steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    get_running_steam_game_pids,
    kill_process,
    send_notification,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestGetRunningPids:
    """Tests for get_running_steam_game_pids."""

    def test_finds_steam_pid(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir(parents=True)
        environ = b"HOME=/home/user\x00SteamAppId=440\x00PATH=/usr/bin"
        (pid_dir / "environ").write_bytes(environ)

        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_running_steam_game_pids()
            assert result == {12345: 440}

    def test_skips_non_digit_entries(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir(parents=True)
        (proc_dir / "self").mkdir()
        (proc_dir / "cpuinfo").touch()

        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_running_steam_game_pids()
            assert result == {}

    def test_handles_permission_error(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "99"
        pid_dir.mkdir(parents=True)
        # No environ file -> OSError when reading

        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_running_steam_game_pids()
            assert result == {}

    def test_skips_non_digit_steam_app_id(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "100"
        pid_dir.mkdir(parents=True)
        environ = b"SteamAppId=notanumber\x00"
        (pid_dir / "environ").write_bytes(environ)

        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_running_steam_game_pids()
            assert result == {}

    def test_no_steam_env(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "200"
        pid_dir.mkdir(parents=True)
        environ = b"HOME=/home/user\x00PATH=/usr/bin\x00"
        (pid_dir / "environ").write_bytes(environ)

        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_running_steam_game_pids()
            assert result == {}


class TestEnforceAllowedGame:
    """Tests for enforce_allowed_game."""

    def test_no_violations(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
            return_value={100: 440},
        ):
            result = enforce_allowed_game(440)
            assert result == []

    def test_kills_unauthorized(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
                return_value={100: 570, 200: 440},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.enforcer.kill_process"
            ) as mock_kill,
        ):
            result = enforce_allowed_game(440, kill_unauthorized=True)
            assert result == [(100, 570)]
            mock_kill.assert_called_once_with(100, 570)

    def test_skips_app_id_zero(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
            return_value={100: 0},
        ):
            result = enforce_allowed_game(440)
            assert result == []

    def test_detects_without_killing(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
            return_value={100: 570},
        ):
            result = enforce_allowed_game(440, kill_unauthorized=False)
            assert result == [(100, 570)]

    def test_allowed_none(self) -> None:
        result = enforce_allowed_game(None, kill_unauthorized=True)
        assert result == []


class TestKillProcess:
    """Tests for kill_process."""

    def test_kill_success(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.enforcer.os.kill") as mock_kill:
            kill_process(123, 440)
            mock_kill.assert_called_once()

    def test_process_already_gone(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.os.kill",
            side_effect=ProcessLookupError,
        ):
            kill_process(123, 440)  # Should not raise

    def test_permission_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.os.kill",
            side_effect=PermissionError,
        ):
            kill_process(123, 440)  # Should not raise


class TestSendNotification:
    """Tests for send_notification."""

    def test_sends(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.subprocess.run"
        ) as mock_run:
            send_notification("Title", "Body")
            mock_run.assert_called_once()

    def test_handles_missing_notify_send(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            send_notification("Title", "Body")  # Should not raise

    def test_handles_os_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.enforcer.subprocess.run",
            side_effect=OSError,
        ):
            send_notification("Title", "Body")  # Should not raise
