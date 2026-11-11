"""Tests for stopping the processes a playtime cutoff must end."""

from __future__ import annotations

import signal
from unittest.mock import patch

from steam_backlog_enforcer._playtime_kill import (
    kill_gaming_processes,
    request_steam_shutdown,
    steam_and_launcher_pids,
)

PKG = "steam_backlog_enforcer._playtime_kill"


class TestRequestSteamShutdown:
    """request_steam_shutdown asks a present Steam to exit."""

    def test_skips_when_steam_is_absent(self) -> None:
        """Without a steam binary nothing is run."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.shutil.which", return_value=None
            ),
            patch("steam_backlog_enforcer._playtime_kill._run") as mock_run,
        ):
            request_steam_shutdown()
        mock_run.assert_not_called()

    def test_sends_shutdown(self) -> None:
        """With steam on PATH the shutdown command is sent."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.shutil.which",
                return_value="/usr/bin/steam",
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._run", return_value=True
            ) as mock_run,
        ):
            request_steam_shutdown()
        mock_run.assert_called_once_with(["/usr/bin/steam", "-shutdown"])


class TestSteamAndLauncherPids:
    """steam_and_launcher_pids finds Steam and other launchers."""

    def test_unions_both_name_sets(self) -> None:
        """Steam and launcher pids are merged into one set."""
        with patch(
            "steam_backlog_enforcer._playtime_kill.get_pids_by_process_names",
            return_value={11: "steam", 22: "lutris"},
        ) as mock_get:
            assert steam_and_launcher_pids() == {11, 22}
        names = mock_get.call_args.args[0]
        assert "steam" in names
        assert "lutris" in names


class TestKillGamingProcesses:
    """kill_gaming_processes signals the game tree but never us."""

    def test_sigterm_by_default(self) -> None:
        """Without force the pids get SIGTERM."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch("steam_backlog_enforcer._playtime_kill.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes({7}, force=False) == [7]
        mock_kill.assert_called_once_with(7, signal.SIGTERM)

    def test_sigkill_when_forced(self) -> None:
        """With force the pids get SIGKILL."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch("steam_backlog_enforcer._playtime_kill.os.kill") as mock_kill,
        ):
            kill_gaming_processes({7}, force=True)
        mock_kill.assert_called_once_with(7, signal.SIGKILL)

    def test_includes_descendants(self) -> None:
        """Descendants of the targets are signalled too."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value={8, 9},
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch("steam_backlog_enforcer._playtime_kill.os.kill"),
        ):
            assert kill_gaming_processes({7}, force=False) == [7, 8, 9]

    def test_never_signals_our_own_chain(self) -> None:
        """Pids in our own ancestor chain are skipped."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value={7},
            ),
            patch("steam_backlog_enforcer._playtime_kill.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes({7, 8}, force=False) == [8]
        mock_kill.assert_called_once_with(8, signal.SIGTERM)

    def test_process_already_gone(self) -> None:
        """A pid that is already gone is not reported as killed."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill.os.kill",
                side_effect=ProcessLookupError,
            ),
        ):
            assert kill_gaming_processes({7}, force=False) == []

    def test_permission_denied(self) -> None:
        """A pid we may not signal is not reported as killed."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill.os.kill",
                side_effect=PermissionError,
            ),
        ):
            assert kill_gaming_processes({7}, force=False) == []

    def test_empty_set(self) -> None:
        """No targets means no signal."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_kill.descendant_pids",
                return_value=set(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_kill._own_process_chain",
                return_value=set(),
            ),
            patch("steam_backlog_enforcer._playtime_kill.os.kill") as mock_kill,
        ):
            assert kill_gaming_processes(set(), force=False) == []
        mock_kill.assert_not_called()
