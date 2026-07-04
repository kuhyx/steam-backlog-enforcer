"""Tests for enforcer module — part 2 (comm-name process matching)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.enforcer import (
    _kill_pid_by_name,
    get_pids_by_process_names,
    kill_processes_by_name,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestGetPidsByProcessNames:
    """Tests for get_pids_by_process_names."""

    def test_finds_matching_comm(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir(parents=True)
        (pid_dir / "comm").write_text("lutris\n", encoding="utf-8")

        with patch(
            "steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_pids_by_process_names(frozenset({"lutris"}))
        assert result == {12345: "lutris"}

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "12345"
        pid_dir.mkdir(parents=True)
        (pid_dir / "comm").write_text("bash\n", encoding="utf-8")

        with patch(
            "steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_pids_by_process_names(frozenset({"lutris"}))
        assert result == {}

    def test_skips_non_digit_entries(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir(parents=True)
        (proc_dir / "self").mkdir()

        with patch(
            "steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_pids_by_process_names(frozenset({"lutris"}))
        assert result == {}

    def test_handles_missing_comm_file(self, tmp_path: Path) -> None:
        proc_dir = tmp_path / "proc"
        (proc_dir / "42").mkdir(parents=True)
        # No comm file -> OSError when reading.

        with patch(
            "steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_pids_by_process_names(frozenset({"lutris"}))
        assert result == {}

    def test_truncates_long_names_to_15_chars(self, tmp_path: Path) -> None:
        """The kernel truncates /proc/[pid]/comm to 15 chars - matching
        must compare against the truncated form, not the full name."""
        proc_dir = tmp_path / "proc"
        pid_dir = proc_dir / "777"
        pid_dir.mkdir(parents=True)
        # "EpicGamesLauncher" truncated to 15 chars is "EpicGamesLaunch".
        (pid_dir / "comm").write_text("EpicGamesLaunch\n", encoding="utf-8")

        with patch(
            "steam_backlog_enforcer.enforcer.Path",
            return_value=proc_dir,
        ):
            result = get_pids_by_process_names(frozenset({"EpicGamesLauncher"}))
        assert result == {777: "EpicGamesLauncher"}


class TestKillProcessesByName:
    """Tests for kill_processes_by_name."""

    def test_kills_matching_pids(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.enforcer.get_pids_by_process_names",
                return_value={100: "lutris", 200: "prismlauncher"},
            ),
            patch("steam_backlog_enforcer.enforcer.os.kill") as mock_kill,
        ):
            result = kill_processes_by_name(frozenset({"lutris", "prismlauncher"}))
        assert sorted(result) == [(100, "lutris"), (200, "prismlauncher")]
        assert mock_kill.call_count == 2

    def test_no_matches_returns_empty(self) -> None:
        with patch(
            "steam_backlog_enforcer.enforcer.get_pids_by_process_names",
            return_value={},
        ):
            result = kill_processes_by_name(frozenset({"lutris"}))
        assert result == []

    def test_process_already_gone_not_included(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.enforcer.get_pids_by_process_names",
                return_value={100: "lutris"},
            ),
            patch(
                "steam_backlog_enforcer.enforcer.os.kill",
                side_effect=ProcessLookupError,
            ),
        ):
            result = kill_processes_by_name(frozenset({"lutris"}))
        assert result == []

    def test_permission_error_not_included(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.enforcer.get_pids_by_process_names",
                return_value={100: "lutris"},
            ),
            patch(
                "steam_backlog_enforcer.enforcer.os.kill",
                side_effect=PermissionError,
            ),
        ):
            result = kill_processes_by_name(frozenset({"lutris"}))
        assert result == []


class TestKillPidByName:
    """Tests for _kill_pid_by_name."""

    def test_success_returns_true(self) -> None:
        with patch("steam_backlog_enforcer.enforcer.os.kill") as mock_kill:
            result = _kill_pid_by_name(123, "lutris")
        assert result is True
        mock_kill.assert_called_once()

    def test_process_already_gone_returns_false(self) -> None:
        with patch(
            "steam_backlog_enforcer.enforcer.os.kill",
            side_effect=ProcessLookupError,
        ):
            result = _kill_pid_by_name(123, "lutris")
        assert result is False

    def test_permission_error_returns_false(self) -> None:
        with patch(
            "steam_backlog_enforcer.enforcer.os.kill",
            side_effect=PermissionError,
        ):
            result = _kill_pid_by_name(123, "lutris")
        assert result is False
