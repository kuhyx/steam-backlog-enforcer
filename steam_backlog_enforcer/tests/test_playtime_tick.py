"""Tests for the playtime tick state machine and cutoff sequence."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._playtime import (
    PlaytimeState,
    _begin_cutoff,
    _kill_set,
    _policy,
    _state_or_recover,
    _sustain_block,
    _warn,
    load_state,
    notify_desktop_user,
    playtime_tick,
    rules_for,
    save_state,
)
from steam_backlog_enforcer.config import Config

PKG = "steam_backlog_enforcer._playtime"
LOCAL = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=LOCAL)
TODAY = "2026-07-27"


@pytest.fixture
def quiet_tick() -> object:
    """Neutralise every side effect the tick can produce."""
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch(f"{PKG}.{name}"))
            for name in (
                "reconcile",
                "request_steam_shutdown",
                "kill_gaming_processes",
                "notify_desktop_user",
                "mounted_targets",
            )
        }
        mocks["mounted_targets"].return_value = set()
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        yield mocks


def _rules(*, demo: bool = False, **cfg: object) -> object:
    return rules_for(Config(**cfg), demo=demo)


class TestStateOrRecover:
    def test_loads_existing_state(self) -> None:
        save_state(PlaytimeState(day_key=TODAY, seconds=42.0), demo=False)
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 42.0

    def test_fresh_state_when_nothing_stored_and_nothing_mounted(self) -> None:
        with patch(f"{PKG}.mounted_targets", return_value=set()):
            out = _state_or_recover(_rules(), now=NOW)
        assert out.seconds == 0.0
        assert out.is_blocked() is False
        assert out.day_key == TODAY

    def test_fails_closed_when_state_is_gone_but_mounts_remain(self) -> None:
        """Deleting the state file must not be a way to lift the block."""
        rules = _rules(daily_gaming_seconds=100)
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(rules, now=NOW)
        assert out.seconds == 100.0
        assert out.is_blocked() is True

    def test_fails_closed_on_corrupt_state(self) -> None:
        from steam_backlog_enforcer._playtime import state_path

        state_path(demo=False).write_text("{bad", encoding="utf-8")
        with patch(f"{PKG}.mounted_targets", return_value={"/usr/bin/steam"}):
            out = _state_or_recover(_rules(daily_gaming_seconds=50), now=NOW)
        assert out.is_blocked() is True


class TestPolicyBelowBudget:
    def test_releases_and_warns(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=8 * 3600 - 3600)
        with (
            patch(f"{PKG}.reconcile") as mock_rec,
            patch(f"{PKG}.notify_desktop_user") as mock_notify,
        ):
            out = _policy(state, _rules(), now=NOW)
        mock_rec.assert_called_once_with(should_block=False)
        mock_notify.assert_called_once()
        assert out.warned_seconds == [3600]

    def test_no_warning_when_far_from_budget(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=0.0)
        with (
            patch(f"{PKG}.reconcile"),
            patch(f"{PKG}.notify_desktop_user") as mock_notify,
        ):
            out = _policy(state, _rules(), now=NOW)
        mock_notify.assert_not_called()
        assert out.warned_seconds == []


class TestPolicyAtOrOverBudget:
    def test_engages_the_cutoff_when_not_yet_blocked(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=10**6)
        with (
            patch(f"{PKG}._begin_cutoff") as mock_begin,
            patch(f"{PKG}._sustain_block") as mock_sustain,
        ):
            _policy(state, _rules(), now=NOW)
        mock_begin.assert_called_once()
        mock_sustain.assert_not_called()

    def test_sustains_the_block_once_engaged(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=10**6, blocked_at=1.0)
        with (
            patch(f"{PKG}._begin_cutoff") as mock_begin,
            patch(f"{PKG}._sustain_block") as mock_sustain,
        ):
            _policy(state, _rules(), now=NOW)
        mock_begin.assert_not_called()
        mock_sustain.assert_called_once()


class TestPolicyEnforcementDisabled:
    def test_releases_but_does_not_block(self) -> None:
        """Disabling must never come to mean 'blocked forever'."""
        state = PlaytimeState(day_key=TODAY, seconds=10**6)
        with (
            patch(f"{PKG}.reconcile") as mock_rec,
            patch(f"{PKG}.request_steam_shutdown") as mock_shutdown,
        ):
            out = _policy(state, _rules(playtime_enforcement=False), now=NOW)
        mock_rec.assert_called_once_with(should_block=False)
        mock_shutdown.assert_not_called()
        assert out.is_blocked() is False


class TestBeginCutoff:
    def test_asks_steam_to_close_before_masking_anything(self) -> None:
        """Masking makes `steam -shutdown` a no-op, so order is load-bearing."""
        state = PlaytimeState(day_key=TODAY, seconds=60.0)
        with (
            patch(f"{PKG}.reconcile") as mock_rec,
            patch(f"{PKG}.request_steam_shutdown") as mock_shutdown,
            patch(f"{PKG}.kill_gaming_processes") as mock_kill,
            patch(f"{PKG}.notify_desktop_user") as mock_notify,
            patch(f"{PKG}._kill_set", return_value={7}),
        ):
            out = _begin_cutoff(state, _rules(demo=True), now=NOW)
        mock_shutdown.assert_called_once()
        mock_rec.assert_not_called()
        mock_kill.assert_called_once_with({7}, force=False)
        mock_notify.assert_called_once()
        assert out.blocked_at == NOW.timestamp()


class TestSustainBlock:
    def _run(
        self, elapsed: float, *, demo: bool = False
    ) -> tuple[MagicMock, MagicMock]:
        state = PlaytimeState(
            day_key=TODAY, seconds=10**6, blocked_at=NOW.timestamp() - elapsed
        )
        with (
            patch(f"{PKG}.reconcile") as mock_rec,
            patch(f"{PKG}.kill_gaming_processes") as mock_kill,
            patch(f"{PKG}._kill_set", return_value={7}),
        ):
            _sustain_block(state, _rules(demo=demo), now=NOW)
        return mock_rec, mock_kill

    def test_grace_period_defers_the_mount(self) -> None:
        mock_rec, mock_kill = self._run(1.0)
        mock_rec.assert_not_called()
        mock_kill.assert_called_once_with({7}, force=False)

    def test_mounts_once_the_grace_has_passed(self) -> None:
        mock_rec, _ = self._run(3.0)
        mock_rec.assert_called_once_with(should_block=True)

    def test_escalates_to_sigkill(self) -> None:
        _, mock_kill = self._run(31.0)
        mock_kill.assert_called_once_with({7}, force=True)

    def test_no_escalation_just_before_the_threshold(self) -> None:
        _, mock_kill = self._run(29.0)
        mock_kill.assert_called_once_with({7}, force=False)

    def test_demo_escalates_sooner(self) -> None:
        _, mock_kill = self._run(11.0, demo=True)
        mock_kill.assert_called_once_with({7}, force=True)

    def test_state_is_unchanged(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=99.0, blocked_at=1.0)
        with (
            patch(f"{PKG}.reconcile"),
            patch(f"{PKG}.kill_gaming_processes"),
            patch(f"{PKG}._kill_set", return_value=set()),
        ):
            out = _sustain_block(state, _rules(), now=NOW)
        assert out is state


class TestKillSet:
    def test_is_wider_than_the_budget_predicate(self) -> None:
        """A Lutris Wine game is invisible to both budget matchers."""
        with (
            patch(f"{PKG}.qualifying_pids", return_value={1}),
            patch(f"{PKG}.steam_and_launcher_pids", return_value={2}),
        ):
            assert _kill_set(_rules()) == {1, 2}


class TestWarn:
    def test_records_the_threshold(self) -> None:
        state = PlaytimeState(seconds=8 * 3600 - 300, warned_seconds=[3600, 1800, 600])
        with patch(f"{PKG}.notify_desktop_user") as mock_notify:
            out = _warn(state, _rules())
        assert out.warned_seconds == [3600, 1800, 600, 300]
        assert "5 minutes" in mock_notify.call_args.args[1]

    def test_no_op_when_nothing_is_due(self) -> None:
        state = PlaytimeState(seconds=0.0)
        with patch(f"{PKG}.notify_desktop_user") as mock_notify:
            out = _warn(state, _rules())
        mock_notify.assert_not_called()
        assert out is state


class TestNotifyDesktopUser:
    def test_routes_through_the_desktop_session(self) -> None:
        """notify-send as root with no DBUS address never reaches the user."""
        with (
            patch(f"{PKG}._resolve_desktop_user", return_value="kuhy"),
            patch(f"{PKG}._run_as_user") as mock_run,
        ):
            notify_desktop_user("T", "B")
        cmd, user = mock_run.call_args.args
        assert cmd[0] == "notify-send"
        assert user == "kuhy"

    def test_swallows_errors(self) -> None:
        with (
            patch(f"{PKG}._resolve_desktop_user", return_value="kuhy"),
            patch(f"{PKG}._run_as_user", side_effect=OSError("no session")),
        ):
            notify_desktop_user("T", "B")


class TestPlaytimeTick:
    def test_accumulates_while_a_game_runs(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(day_key=TODAY, last_tick_at=NOW.timestamp() - 3.0),
            demo=False,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0)
        assert load_state(demo=False).seconds == 3.0

    def test_total_block_releases_and_stops_accruing(self, quiet_tick: dict) -> None:
        """Our mounts would make the total block's `pacman -R steam` fail."""
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=5.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=False,
        )
        with (
            patch(f"{PKG}.is_total_block_active", return_value=True),
            patch(f"{PKG}.qualifying_pids", return_value={7}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0)
        quiet_tick["reconcile"].assert_called_once_with(should_block=False)
        assert load_state(demo=False).seconds == 5.0

    def test_rollover_clears_a_stale_block(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(
                day_key="2026-07-26",
                seconds=10**6,
                blocked_at=1.0,
                last_tick_at=NOW.timestamp() - 3.0,
            ),
            demo=False,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value=set()),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0)
        stored = load_state(demo=False)
        assert stored.day_key == TODAY
        assert stored.seconds == 0.0
        assert stored.is_blocked() is False
        quiet_tick["reconcile"].assert_called_with(should_block=False)

    def test_cutoff_engages_at_the_budget(self, quiet_tick: dict) -> None:
        save_state(
            PlaytimeState(
                day_key=TODAY, seconds=59.0, last_tick_at=NOW.timestamp() - 3.0
            ),
            demo=True,
        )
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7}),
            patch(f"{PKG}._kill_set", return_value={7}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, demo=True)
        stored = load_state(demo=True)
        assert stored.is_blocked() is True
        quiet_tick["request_steam_shutdown"].assert_called_once()

    def test_demo_uses_a_separate_state_file(self, quiet_tick: dict) -> None:
        """A demo run must never consume the real day's budget."""
        with (
            patch(f"{PKG}.qualifying_pids", return_value={7}),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0, demo=True)
        assert load_state(demo=True) is not None
        assert load_state(demo=False) is None

    def test_first_tick_writes_state(self, quiet_tick: dict) -> None:
        with (
            patch(f"{PKG}.qualifying_pids", return_value=set()),
            patch(f"{PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            playtime_tick(Config(), interval=3.0)
        stored = load_state(demo=False)
        assert stored is not None
        assert stored.day_key == TODAY
