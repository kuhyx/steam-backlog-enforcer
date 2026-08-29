"""Tests for the main CLI: cmdline-based process detection."""

from datetime import datetime, timedelta, timezone
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_notify import (
    _humanise,
)
from steam_backlog_enforcer._playtime_procs import (
    _match_cmdline,
    get_pids_by_cmdline_names,
    process_name,
    qualifying_pids,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    rules_for,
)
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=LOCAL)
INTERVAL = 3.0


def _state_ticked(seconds_ago: float, **kwargs: object) -> PlaytimeState:
    return PlaytimeState(last_tick_at=NOW.timestamp() - seconds_ago, **kwargs)


class TestMatchCmdline:
    def _proc(self, tmp_path: Path, pid: int, argv: list[str]) -> Path:
        entry = tmp_path / "playtime_proc" / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "cmdline").write_bytes(
            b"\x00".join(a.encode() for a in argv) + b"\x00"
        )
        return entry

    def test_direct_argv0_match(self, tmp_path: Path) -> None:
        entry = self._proc(tmp_path, 10, ["/usr/bin/lutris", "--foo"])
        assert _match_cmdline(entry, frozenset({"lutris"})) == "lutris"

    def test_interpreter_falls_through_to_argv1(self, tmp_path: Path) -> None:
        """The real case: /usr/bin/lutris is a python3 script."""
        entry = self._proc(tmp_path, 11, ["/usr/bin/python3", "/usr/bin/lutris"])
        assert _match_cmdline(entry, frozenset({"lutris"})) == "lutris"

    def test_interpreter_with_no_argv1(self, tmp_path: Path) -> None:
        entry = self._proc(tmp_path, 12, ["python3"])
        assert _match_cmdline(entry, frozenset({"lutris"})) is None

    def test_interpreter_running_something_else(self, tmp_path: Path) -> None:
        entry = self._proc(tmp_path, 13, ["python3", "/usr/bin/other"])
        assert _match_cmdline(entry, frozenset({"lutris"})) is None

    def test_non_interpreter_no_match(self, tmp_path: Path) -> None:
        entry = self._proc(tmp_path, 14, ["/usr/bin/firefox"])
        assert _match_cmdline(entry, frozenset({"lutris"})) is None

    def test_empty_cmdline(self, tmp_path: Path) -> None:
        entry = tmp_path / "playtime_proc" / "15"
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "cmdline").write_bytes(b"")
        assert _match_cmdline(entry, frozenset({"lutris"})) is None

    def test_unreadable_cmdline(self, tmp_path: Path) -> None:
        entry = tmp_path / "playtime_proc" / "16"
        entry.mkdir(parents=True, exist_ok=True)
        assert _match_cmdline(entry, frozenset({"lutris"})) is None

    def test_undecodable_bytes_do_not_raise(self, tmp_path: Path) -> None:
        entry = tmp_path / "playtime_proc" / "17"
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "cmdline").write_bytes(b"\xff\xfe\x00")
        assert _match_cmdline(entry, frozenset({"lutris"})) is None


class TestGetPidsByCmdlineNames:
    def _proc(self, tmp_path: Path, pid: int, argv: list[str]) -> None:
        entry = tmp_path / "playtime_proc" / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "cmdline").write_bytes(
            b"\x00".join(a.encode() for a in argv) + b"\x00"
        )

    def test_finds_matches(self, tmp_path: Path) -> None:
        self._proc(tmp_path, 100, ["python3", "/usr/bin/lutris"])
        self._proc(tmp_path, 101, ["/usr/bin/firefox"])
        assert get_pids_by_cmdline_names(frozenset({"lutris"})) == {100: "lutris"}

    def test_skips_non_digit_entries(self, tmp_path: Path) -> None:
        (tmp_path / "playtime_proc" / "cpuinfo").touch()
        (tmp_path / "playtime_proc" / "self").mkdir(exist_ok=True)
        self._proc(tmp_path, 102, ["python3", "/usr/bin/lutris"])
        assert get_pids_by_cmdline_names(frozenset({"lutris"})) == {102: "lutris"}

    def test_never_matches_our_own_pid(self, tmp_path: Path) -> None:
        """The daemon is itself python3 - it must not count as a launcher."""
        self._proc(tmp_path, os.getpid(), ["python3", "/usr/bin/lutris"])
        assert get_pids_by_cmdline_names(frozenset({"lutris"})) == {}

    def test_empty_proc(self) -> None:
        assert get_pids_by_cmdline_names(frozenset({"lutris"})) == {}


class TestQualifyingPids:
    def test_steam_games_only_when_launchers_are_off(self) -> None:
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={5: 440, 6: 0},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names"
            ) as mock_comm,
        ):
            assert qualifying_pids(rules) == {5}
        mock_comm.assert_not_called()

    def test_steam_client_appid_zero_does_not_count(self) -> None:
        """Browsing the store is not gaming."""
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with patch(
            "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
            return_value={9: 0},
        ):
            assert qualifying_pids(rules) == set()

    def test_unions_launchers_from_both_scanners(self) -> None:
        rules = rules_for(Config(count_launcher_processes=True), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={5: 440},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={7: "heroic"},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={8: "lutris"},
            ),
        ):
            assert qualifying_pids(rules) == {5, 7, 8}

    def test_no_processes_at_all(self) -> None:
        rules = rules_for(Config(), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={},
            ),
        ):
            assert qualifying_pids(rules) == set()


class TestHumanise:
    def test_seconds(self) -> None:
        assert _humanise(30) == "30 seconds"

    def test_exact_minute_boundary(self) -> None:
        assert _humanise(60) == "1 minutes"

    def test_minutes(self) -> None:
        assert _humanise(300) == "5 minutes"

    def test_one_hour_is_special_cased(self) -> None:
        assert _humanise(3600) == "1 hour"

    def test_thirty_minutes(self) -> None:
        assert _humanise(1800) == "30 minutes"


class TestProcessName:
    """Tests for resolving a PID to its program name."""

    def _comm(self, tmp_path: Path, pid: int, name: str) -> None:
        entry = tmp_path / "playtime_proc" / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "comm").write_text(name, encoding="utf-8")

    def test_reads_comm(self, tmp_path: Path) -> None:
        self._comm(tmp_path, 42, "hollow_knight\n")
        assert process_name(42) == "hollow_knight"

    def test_missing_pid_is_none(self) -> None:
        # A PID recorded earlier may have exited, and the number may since have
        # been recycled — "gone" is the only safe answer.
        assert process_name(999999) is None

    def test_empty_comm_is_none(self, tmp_path: Path) -> None:
        self._comm(tmp_path, 43, "\n")
        assert process_name(43) is None
