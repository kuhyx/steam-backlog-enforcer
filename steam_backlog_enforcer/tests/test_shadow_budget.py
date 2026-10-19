"""Tests for the shadow leisure budget: resolution, the held day, the tick, views."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _budget_view as budget_view
from steam_backlog_enforcer import _leetcode_bonus, _shadow, _workout_budget
from steam_backlog_enforcer import _mcp_gaming_time as mcp_gaming_time
from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer._gaming_days import held_shadow_today
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    rules_for,
    save_state,
)
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._budget_dates import AFTER_CUT, pin_today
from steam_backlog_enforcer.tests._fake_session import fake_session

if TYPE_CHECKING:
    from collections.abc import Iterator

_WORKOUT = "steam_backlog_enforcer._workout_budget._fetch_workout_today"
_LEETCODE = "steam_backlog_enforcer._leetcode_bonus.read_ledger_solved_today"
_READING = "steam_backlog_enforcer._budget_resolve.read_today"
_HOUR = 3600.0
_LOCAL = timezone(timedelta(hours=2))
_NOW = datetime(2026, 7, 27, 20, 0, tzinfo=_LOCAL)
_TODAY = "2026-07-27"
_PKG = "steam_backlog_enforcer._playtime"


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    _workout_budget.reset_cache()
    _leetcode_bonus.reset_cache()
    with pin_today(AFTER_CUT):
        yield
    _workout_budget.reset_cache()
    _leetcode_bonus.reset_cache()


def _resolve(*, done: bool) -> object:
    with (
        patch(_WORKOUT, return_value=done),
        patch(_LEETCODE, return_value=done),
        patch(_READING, return_value=done),
    ):
        return resolve_budget(Config())


class TestShadowResolution:
    def test_a_fully_done_day_prices_ten_hours_and_enforces_eight(self) -> None:
        resolved = _resolve(done=True)
        assert resolved.shadow_seconds == 10 * _HOUR
        assert resolved.seconds == 8 * _HOUR

    def test_the_leisure_base_is_two_hours_above_the_enforced_one(self) -> None:
        resolved = _resolve(done=False)
        assert resolved.shadow_seconds == resolved.seconds + 2 * _HOUR

    def test_a_missing_answer_warns_once_not_once_per_pricing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Enforced + shadow pricing is one resolution: one warning per earner."""
        with (
            caplog.at_level(logging.WARNING, logger="earned_time"),
            patch("steam_backlog_enforcer._budget_resolve._answers", return_value={}),
        ):
            resolve_budget(Config())
        warned = [r.getMessage() for r in caplog.records if "No answer" in r.message]
        assert warned
        assert len(warned) == len(set(warned))


class TestHeldShadow:
    def test_same_day_holds_the_high_water(self) -> None:
        stored = PlaytimeState(day_key=_TODAY, shadow_budget_seconds=9 * _HOUR)
        assert held_shadow_today(stored, _NOW) == 9 * _HOUR

    def test_another_day_or_no_state_holds_nothing(self) -> None:
        stored = PlaytimeState(day_key="2026-07-26", shadow_budget_seconds=_HOUR)
        assert held_shadow_today(stored, _NOW) == 0.0
        assert held_shadow_today(None, _NOW) == 0.0

    def test_rules_take_the_higher_of_live_and_held(self) -> None:
        held = "steam_backlog_enforcer._playtime_state.held_shadow_today"
        with patch(held, return_value=20 * _HOUR):
            assert rules_for(Config(), demo=False).shadow_budget_seconds == 20 * (_HOUR)
        with patch(held, return_value=0.0):
            live = rules_for(Config(), demo=False).shadow_budget_seconds
        assert 0.0 < live < 20 * _HOUR

    def test_demo_has_no_shadow_budget(self) -> None:
        assert rules_for(Config(), demo=True).shadow_budget_seconds == 0.0


class TestShadowTick:
    def _tick(self, owners: dict[int, str], *, total_block: bool = False) -> None:
        save_state(
            PlaytimeState(day_key=_TODAY, last_tick_at=_NOW.timestamp() - 3.0),
            demo=False,
        )
        cutoff = "steam_backlog_enforcer._playtime_cutoff"
        with (
            patch(f"{cutoff}.reconcile"),
            patch(f"{cutoff}.notify_desktop_user"),
            patch(f"{_PKG}.mounted_targets", return_value=set()),
            patch(f"{_PKG}.is_total_block_active", return_value=total_block),
            patch(f"{_PKG}.qualifying_pids", return_value=owners),
            patch.object(_shadow, "read_now", return_value=None),
            patch.object(_shadow, "paused_by", return_value=None),
            patch(f"{_PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _NOW
            playtime_tick(Config(), interval=3.0, session=fake_session())

    def test_bills_shadow_beside_the_enforced_count(self) -> None:
        self._tick({7: "app:440"})
        state = load_state(demo=False)
        assert state is not None
        assert (state.seconds, state.per_game) == (3.0, {"app:440": 3.0})
        assert state.shadow_seconds == 3.0
        assert state.shadow_per_source == {"app:440": 3.0}
        assert state.shadow_budget_seconds > 0.0

    def test_no_game_and_no_watcher_fails_closed(self) -> None:
        self._tick({})
        state = load_state(demo=False)
        assert state is not None
        assert state.seconds == 0.0
        assert state.shadow_per_source == {_shadow.FAILCLOSED_KEY: 3.0}

    def test_no_shadow_under_a_total_block(self) -> None:
        self._tick({}, total_block=True)
        state = load_state(demo=False)
        assert state is not None
        assert state.shadow_seconds == 0.0
        assert state.shadow_budget_seconds > 0.0

    def test_the_session_journals_the_shadow_verdict(self) -> None:
        session = fake_session()
        save_state(
            PlaytimeState(day_key=_TODAY, last_tick_at=_NOW.timestamp() - 3.0),
            demo=False,
        )
        with (
            patch("steam_backlog_enforcer._playtime_cutoff.reconcile"),
            patch(f"{_PKG}.mounted_targets", return_value=set()),
            patch(f"{_PKG}.is_total_block_active", return_value=False),
            patch(f"{_PKG}.qualifying_pids", return_value={}),
            patch(f"{_PKG}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _NOW
            playtime_tick(Config(), interval=3.0, session=session)
        assert [v.state for v in session.shadow.observed] == ["leisure"]


class TestShadowViews:
    def test_mcp_reports_the_shadow_block(self) -> None:
        stored = PlaytimeState(
            day_key=_TODAY,
            seconds=10.0,
            shadow_seconds=40.0,
            shadow_budget_seconds=100.0,
            shadow_per_source={"app:440": 40.0},
            shadow_paused_seconds=5.0,
        )
        with (
            patch.object(budget_view, "load_state", return_value=stored),
            patch.object(budget_view, "mounted_targets", return_value=set()),
        ):
            out = mcp_gaming_time.get_gaming_time()
        assert out["shadow"] == {
            "seconds_used": 40.0,
            "budget_seconds": 100.0,
            "seconds_remaining": 60.0,
            "would_block": False,
            "paused_seconds": 5.0,
            "per_source": {"app:440": 40.0},
        }

    def test_would_block_at_zero(self) -> None:
        stored = PlaytimeState(shadow_seconds=100.0, shadow_budget_seconds=100.0)
        shadow = budget_view.build_today(stored, rules_for(Config(), demo=True))
        assert shadow["shadow"]["would_block"] is True
        assert shadow["shadow"]["seconds_remaining"] == 0.0
