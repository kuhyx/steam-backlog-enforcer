"""Tests for enforcer module — part 2 (comm-name process matching)."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.enforcer import (
    _kill_pid_by_name,
    kill_processes_by_name,
)


class TestKillProcessesByName:
    """Tests for kill_processes_by_name."""

    def test_kills_matching_pids(self) -> None:
        """Every matching process is killed and reported with its name."""
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
        """No matching process means nothing killed."""
        with patch(
            "steam_backlog_enforcer.enforcer.get_pids_by_process_names",
            return_value={},
        ):
            result = kill_processes_by_name(frozenset({"lutris"}))
        assert result == []

    def test_process_already_gone_not_included(self) -> None:
        """A process that exited before the kill is not reported."""
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
        """A process we may not kill is not reported."""
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
        """A delivered kill reports True."""
        with patch("steam_backlog_enforcer.enforcer.os.kill") as mock_kill:
            result = _kill_pid_by_name(123, "lutris")
        assert result is True
        mock_kill.assert_called_once()

    def test_process_already_gone_returns_false(self) -> None:
        """A process that already exited reports False."""
        with patch(
            "steam_backlog_enforcer.enforcer.os.kill",
            side_effect=ProcessLookupError,
        ):
            result = _kill_pid_by_name(123, "lutris")
        assert result is False

    def test_permission_error_returns_false(self) -> None:
        """A process we may not kill reports False."""
        with patch(
            "steam_backlog_enforcer.enforcer.os.kill",
            side_effect=PermissionError,
        ):
            result = _kill_pid_by_name(123, "lutris")
        assert result is False
