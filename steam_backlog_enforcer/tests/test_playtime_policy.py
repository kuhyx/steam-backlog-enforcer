"""Tests for the budget policy decision — warn, cut off, sustain.

Split out of ``test_playtime_tick.py`` to hold both files inside the
250-line cap. ``_policy`` is a pure decision over state and rules; the tick
tests exercise the loop that feeds it.
"""

from contextlib import ExitStack
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._playtime import (
    _policy,
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


class TestPolicyBelowBudget:
    def test_releases_and_warns(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=8 * 3600 - 3600)
        with (
            patch("steam_backlog_enforcer._playtime.reconcile") as mock_rec,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
            ) as mock_notify,
        ):
            out = _policy(state, _rules(), now=NOW)
        mock_rec.assert_called_once_with(should_block=False)
        mock_notify.assert_called_once()
        assert out.warned_seconds == [3600]

    def test_no_warning_when_far_from_budget(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=0.0)
        with (
            patch("steam_backlog_enforcer._playtime.reconcile"),
            patch(
                "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
            ) as mock_notify,
        ):
            out = _policy(state, _rules(), now=NOW)
        mock_notify.assert_not_called()
        assert out.warned_seconds == []


class TestPolicyAtOrOverBudget:
    def test_engages_the_cutoff_when_not_yet_blocked(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=10**6)
        with (
            patch("steam_backlog_enforcer._playtime._begin_cutoff") as mock_begin,
            patch("steam_backlog_enforcer._playtime._sustain_block") as mock_sustain,
        ):
            _policy(state, _rules(), now=NOW)
        mock_begin.assert_called_once()
        mock_sustain.assert_not_called()

    def test_sustains_the_block_once_engaged(self) -> None:
        state = PlaytimeState(day_key=TODAY, seconds=10**6, blocked_at=1.0)
        with (
            patch("steam_backlog_enforcer._playtime._begin_cutoff") as mock_begin,
            patch("steam_backlog_enforcer._playtime._sustain_block") as mock_sustain,
        ):
            _policy(state, _rules(), now=NOW)
        mock_begin.assert_not_called()
        mock_sustain.assert_called_once()


class TestPolicyEnforcementDisabled:
    def test_releases_but_does_not_block(self) -> None:
        """Disabling must never come to mean 'blocked forever'."""
        state = PlaytimeState(day_key=TODAY, seconds=10**6)
        with (
            patch("steam_backlog_enforcer._playtime.reconcile") as mock_rec,
            patch(
                "steam_backlog_enforcer._playtime_cutoff.request_steam_shutdown"
            ) as mock_shutdown,
        ):
            out = _policy(state, _rules(playtime_enforcement=False), now=NOW)
        mock_rec.assert_called_once_with(should_block=False)
        mock_shutdown.assert_not_called()
        assert out.is_blocked() is False
