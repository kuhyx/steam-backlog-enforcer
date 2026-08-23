"""Tests for the main CLI: the warn/cutoff/kill escalation."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._playtime_cutoff import (
    _begin_cutoff,
    _kill_set,
    _sustain_block,
    _warn,
)
from steam_backlog_enforcer._playtime_notify import (
    notify_desktop_user,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    rules_for,
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
        # Each name is patched in the module that *resolves* it, not in the
        # package that re-exports it -- otherwise the patch never bites.
        cutoff = "steam_backlog_enforcer._playtime_cutoff"
        mocks = {
            name: stack.enter_context(patch(f"{where}.{name}"))
            for name, where in (
                ("reconcile", PKG),
                ("request_steam_shutdown", cutoff),
                ("kill_gaming_processes", cutoff),
                ("notify_desktop_user", cutoff),
                ("mounted_targets", PKG),
            )
        }
        mocks["mounted_targets"].return_value = set()
        stack.enter_context(patch(f"{PKG}.is_total_block_active", return_value=False))
        yield mocks


def _rules(*, demo: bool = False, **cfg: object) -> object:
    return rules_for(Config(**cfg), demo=demo)


class TestBeginCutoff:
    def test_asks_steam_to_close_before_masking_anything(self) -> None:
        """Masking makes `steam -shutdown` a no-op, so order is load-bearing."""
        state = PlaytimeState(day_key=TODAY, seconds=60.0)
        with (
            patch("steam_backlog_enforcer._playtime_cutoff.reconcile") as mock_rec,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.request_steam_shutdown"
            ) as mock_shutdown,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.kill_gaming_processes"
            ) as mock_kill,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
            ) as mock_notify,
            patch(
                "steam_backlog_enforcer._playtime_cutoff._kill_set", return_value={7}
            ),
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
            patch("steam_backlog_enforcer._playtime_cutoff.reconcile") as mock_rec,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.kill_gaming_processes"
            ) as mock_kill,
            patch(
                "steam_backlog_enforcer._playtime_cutoff._kill_set", return_value={7}
            ),
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
            patch("steam_backlog_enforcer._playtime_cutoff.reconcile"),
            patch("steam_backlog_enforcer._playtime_cutoff.kill_gaming_processes"),
            patch(
                "steam_backlog_enforcer._playtime_cutoff._kill_set", return_value=set()
            ),
        ):
            out = _sustain_block(state, _rules(), now=NOW)
        assert out is state


class TestKillSet:
    def test_is_wider_than_the_budget_predicate(self) -> None:
        """A Lutris Wine game is invisible to both budget matchers."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_cutoff.qualifying_pids",
                return_value={1},
            ),
            patch(
                "steam_backlog_enforcer._playtime_cutoff.steam_and_launcher_pids",
                return_value={2},
            ),
        ):
            assert _kill_set(_rules()) == {1, 2}


class TestWarn:
    def test_records_the_threshold(self) -> None:
        state = PlaytimeState(seconds=8 * 3600 - 300, warned_seconds=[3600, 1800, 600])
        with patch(
            "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
        ) as mock_notify:
            out = _warn(state, _rules())
        assert out.warned_seconds == [3600, 1800, 600, 300]
        assert "5 minutes" in mock_notify.call_args.args[1]

    def test_no_op_when_nothing_is_due(self) -> None:
        state = PlaytimeState(seconds=0.0)
        with patch(
            "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
        ) as mock_notify:
            out = _warn(state, _rules())
        mock_notify.assert_not_called()
        assert out is state


class TestNotifyDesktopUser:
    def test_routes_through_the_desktop_session(self) -> None:
        """notify-send as root with no DBUS address never reaches the user."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_notify._resolve_desktop_user",
                return_value="kuhy",
            ),
            patch("steam_backlog_enforcer._playtime_notify._run_as_user") as mock_run,
        ):
            notify_desktop_user("T", "B")
        cmd, user = mock_run.call_args.args
        assert cmd[0] == "notify-send"
        assert user == "kuhy"

    def test_swallows_errors(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._playtime_notify._resolve_desktop_user",
                return_value="kuhy",
            ),
            patch(
                "steam_backlog_enforcer._playtime_notify._run_as_user",
                side_effect=OSError("no session"),
            ),
        ):
            notify_desktop_user("T", "B")
