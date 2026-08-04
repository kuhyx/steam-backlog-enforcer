"""Tests for playtime accumulation, rollover, warnings and /proc scanning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime import (
    PlaytimeState,
    _humanise,
    _match_cmdline,
    accumulate,
    get_pids_by_cmdline_names,
    pending_warning,
    qualifying_pids,
    roll_over,
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


class TestAccumulate:
    def test_first_ever_tick_credits_nothing(self) -> None:
        out = accumulate(
            PlaytimeState(last_tick_at=0.0),
            now=NOW,
            qualifying={1},
            interval=INTERVAL,
        )
        assert out.seconds == 0.0
        assert out.last_tick_at == NOW.timestamp()

    def test_normal_tick_credits_the_delta(self) -> None:
        out = accumulate(_state_ticked(3.0), now=NOW, qualifying={1}, interval=INTERVAL)
        assert out.seconds == 3.0

    def test_idle_tick_credits_nothing_but_advances_the_clock(self) -> None:
        out = accumulate(
            _state_ticked(3.0), now=NOW, qualifying=set(), interval=INTERVAL
        )
        assert out.seconds == 0.0
        assert out.last_tick_at == NOW.timestamp()

    def test_long_gap_is_clamped(self) -> None:
        """A suspend must not credit hours of gaming that never happened."""
        out = accumulate(
            _state_ticked(3600.0), now=NOW, qualifying={1}, interval=INTERVAL
        )
        assert out.seconds == 6.0

    def test_gap_exactly_at_the_clamp(self) -> None:
        out = accumulate(_state_ticked(6.0), now=NOW, qualifying={1}, interval=INTERVAL)
        assert out.seconds == 6.0

    def test_backward_clock_step_credits_nothing(self) -> None:
        """An NTP step backwards must never refund time already spent."""
        out = accumulate(
            _state_ticked(-10.0),
            now=NOW,
            qualifying={1},
            interval=INTERVAL,
        )
        assert out.seconds == 0.0
        assert out.last_tick_at == NOW.timestamp()

    def test_zero_delta(self) -> None:
        out = accumulate(_state_ticked(0.0), now=NOW, qualifying={1}, interval=INTERVAL)
        assert out.seconds == 0.0

    def test_accrues_across_ticks(self) -> None:
        state = PlaytimeState(seconds=100.0, last_tick_at=NOW.timestamp() - 3.0)
        out = accumulate(state, now=NOW, qualifying={1}, interval=INTERVAL)
        assert out.seconds == 103.0

    def test_is_pure(self) -> None:
        state = _state_ticked(3.0)
        accumulate(state, now=NOW, qualifying={1}, interval=INTERVAL)
        assert state.seconds == 0.0


class TestRollOver:
    def test_same_day_is_unchanged(self) -> None:
        state = PlaytimeState(day_key="2026-07-27", seconds=50.0, blocked_at=9.0)
        assert roll_over(state, day_key="2026-07-27") is state

    def test_new_day_resets_counter_and_block(self) -> None:
        state = PlaytimeState(
            day_key="2026-07-27",
            seconds=50.0,
            blocked_at=9.0,
            warned_seconds=[600],
        )
        out = roll_over(state, day_key="2026-07-28")
        assert out.day_key == "2026-07-28"
        assert out.seconds == 0.0
        assert out.is_blocked() is False
        assert out.warned_seconds == []

    def test_last_tick_carries_across_the_boundary(self) -> None:
        """Otherwise the first tick of the new day measures a bogus delta."""
        state = PlaytimeState(day_key="2026-07-27", last_tick_at=1234.0)
        assert roll_over(state, day_key="2026-07-28").last_tick_at == 1234.0

    def test_empty_day_key_rolls_over(self) -> None:
        assert roll_over(PlaytimeState(), day_key="2026-07-28").day_key == "2026-07-28"


class TestPendingWarning:
    def _rules(self, *, demo: bool = False) -> object:
        return rules_for(Config(daily_gaming_seconds=8 * 3600), demo=demo)

    def test_none_when_far_from_the_budget(self) -> None:
        state = PlaytimeState(seconds=0.0)
        assert pending_warning(state, self._rules()) is None

    def test_fires_at_the_first_threshold(self) -> None:
        state = PlaytimeState(seconds=8 * 3600 - 3600)
        assert pending_warning(state, self._rules()) == 3600

    def test_skips_already_fired_thresholds(self) -> None:
        state = PlaytimeState(seconds=8 * 3600 - 1800, warned_seconds=[3600])
        assert pending_warning(state, self._rules()) == 1800

    def test_returns_largest_uncrossed_when_two_are_skipped(self) -> None:
        """A missed tick crossing two thresholds must warn once, not twice."""
        state = PlaytimeState(seconds=8 * 3600 - 400)
        assert pending_warning(state, self._rules()) == 3600

    def test_none_when_all_fired(self) -> None:
        state = PlaytimeState(
            seconds=8 * 3600 - 100, warned_seconds=[3600, 1800, 600, 300]
        )
        assert pending_warning(state, self._rules()) is None

    def test_demo_thresholds(self) -> None:
        state = PlaytimeState(seconds=35.0)
        assert pending_warning(state, self._rules(demo=True)) == 30

    def test_over_budget_still_reports(self) -> None:
        state = PlaytimeState(seconds=8 * 3600 + 500, warned_seconds=[3600, 1800, 600])
        assert pending_warning(state, self._rules()) == 300


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
            patch(f"{PKG}.get_running_steam_game_pids", return_value={5: 440, 6: 0}),
            patch(f"{PKG}.get_pids_by_process_names") as mock_comm,
        ):
            assert qualifying_pids(rules) == {5}
        mock_comm.assert_not_called()

    def test_steam_client_appid_zero_does_not_count(self) -> None:
        """Browsing the store is not gaming."""
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with patch(f"{PKG}.get_running_steam_game_pids", return_value={9: 0}):
            assert qualifying_pids(rules) == set()

    def test_unions_launchers_from_both_scanners(self) -> None:
        rules = rules_for(Config(count_launcher_processes=True), demo=False)
        with (
            patch(f"{PKG}.get_running_steam_game_pids", return_value={5: 440}),
            patch(f"{PKG}.get_pids_by_process_names", return_value={7: "heroic"}),
            patch(f"{PKG}.get_pids_by_cmdline_names", return_value={8: "lutris"}),
        ):
            assert qualifying_pids(rules) == {5, 7, 8}

    def test_no_processes_at_all(self) -> None:
        rules = rules_for(Config(), demo=False)
        with (
            patch(f"{PKG}.get_running_steam_game_pids", return_value={}),
            patch(f"{PKG}.get_pids_by_process_names", return_value={}),
            patch(f"{PKG}.get_pids_by_cmdline_names", return_value={}),
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
