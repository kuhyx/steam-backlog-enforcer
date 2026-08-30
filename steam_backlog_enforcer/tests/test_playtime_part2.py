"""Tests for playtime accumulation, rollover, warnings and /proc scanning."""

from datetime import datetime, timedelta, timezone

from steam_backlog_enforcer._playtime_budget import (
    accumulate,
    pending_warning,
    roll_over,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    rules_for,
)
from steam_backlog_enforcer.config import Config

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
        return rules_for(Config(), demo=demo)

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
