"""Tests for the main CLI: the warn/cutoff/kill escalation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._playtime_cutoff import (
    _begin_cutoff,
    _kill_set,
    _sustain_block,
    reconcile_for,
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


def _rules(*, demo: bool = False, **cfg: object) -> object:
    return rules_for(Config(**cfg), demo=demo)


class TestBeginCutoff:
    """Starting the cutoff: shutdown order, kill, notify and stamp."""

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

    def test_demo_says_out_loud_that_it_will_not_mask(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only a demo cutoff logs that it will not mask."""
        state = PlaytimeState(day_key=TODAY, seconds=60.0)
        with (
            patch("steam_backlog_enforcer._playtime_cutoff.request_steam_shutdown"),
            patch("steam_backlog_enforcer._playtime_cutoff.kill_gaming_processes"),
            patch("steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"),
            patch(
                "steam_backlog_enforcer._playtime_cutoff._kill_set", return_value=set()
            ),
        ):
            _begin_cutoff(state, _rules(demo=True), now=NOW)
            assert "only the daemon does that" in caplog.text
            caplog.clear()
            _begin_cutoff(state, _rules(), now=NOW)
            assert "only the daemon" not in caplog.text


class TestReconcileFor:
    """Only production cutoffs drive the store mounts."""

    def test_production_drives_the_mounts(self) -> None:
        """Production passes should_block straight to reconcile."""
        with patch("steam_backlog_enforcer._playtime_cutoff.reconcile") as rec:
            reconcile_for(_rules(), should_block=True)
        rec.assert_called_once_with(should_block=True)

    @pytest.mark.parametrize("should_block", [True, False])
    def test_demo_never_touches_them(self, *, should_block: bool) -> None:
        """Demo never reconciles the mounts."""
        with patch("steam_backlog_enforcer._playtime_cutoff.reconcile") as rec:
            reconcile_for(_rules(demo=True), should_block=should_block)
        rec.assert_not_called()


class TestSustainBlock:
    """While blocked: grace before mounting, then SIGTERM, then SIGKILL."""

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
        """Inside the grace period games are terminated but nothing is mounted."""
        mock_rec, mock_kill = self._run(1.0)
        mock_rec.assert_not_called()
        mock_kill.assert_called_once_with({7}, force=False)

    def test_mounts_once_the_grace_has_passed(self) -> None:
        """After the grace period the block mounts."""
        mock_rec, _ = self._run(3.0)
        mock_rec.assert_called_once_with(should_block=True)

    def test_escalates_to_sigkill(self) -> None:
        """Past 30 s the kill escalates to SIGKILL."""
        _, mock_kill = self._run(31.0)
        mock_kill.assert_called_once_with({7}, force=True)

    def test_no_escalation_just_before_the_threshold(self) -> None:
        """At 29 s the kill is still SIGTERM."""
        _, mock_kill = self._run(29.0)
        mock_kill.assert_called_once_with({7}, force=False)

    def test_demo_never_mounts_but_keeps_killing(self) -> None:
        """Demo keeps killing but never mounts."""
        mock_rec, mock_kill = self._run(5.0, demo=True)
        mock_rec.assert_not_called()
        mock_kill.assert_called_once()

    def test_demo_escalates_sooner(self) -> None:
        """Demo escalates to SIGKILL after 10 s."""
        _, mock_kill = self._run(11.0, demo=True)
        mock_kill.assert_called_once_with({7}, force=True)

    def test_state_is_unchanged(self) -> None:
        """Sustaining a block returns the same state object."""
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
    """The kill set covers more than the budget's qualifying pids."""

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
