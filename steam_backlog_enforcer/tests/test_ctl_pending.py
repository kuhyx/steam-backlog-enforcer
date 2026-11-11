"""Tests for the two-phase reset bookkeeping in ``_ctl_pending``.

A fake monotonic clock drives every countdown; no test sleeps.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steam_backlog_enforcer import _ctl_pending
from steam_backlog_enforcer._ctl_protocol import (
    COUNTDOWN_RUNNING,
    PENDING_LAPSED,
    CtlError,
)

_WALL = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _Clock:
    """A settable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(name="clock")
def fixture_clock() -> _Clock:
    """A fake monotonic clock starting at 1000 s."""
    return _Clock()


@pytest.fixture(name="pending")
def fixture_pending(clock: _Clock) -> _ctl_pending.PendingResets:
    """PendingResets driven by the fake clock and a fixed wall time."""
    return _ctl_pending.PendingResets(clock=clock, wall=lambda: _WALL)


class TestCountdownSeconds:
    """The VM-only override can shorten the countdown, never lengthen it."""

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the override the countdown is 300 s."""
        monkeypatch.delenv(_ctl_pending.TEST_COUNTDOWN_ENV, raising=False)
        assert _ctl_pending.countdown_seconds() == 300

    def test_shortened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A shorter override shortens the countdown."""
        monkeypatch.setenv(_ctl_pending.TEST_COUNTDOWN_ENV, "7")
        assert _ctl_pending.countdown_seconds() == 7

    @pytest.mark.parametrize("raw", ["0", "300", "9999", "abc", "-5", ""])
    def test_invalid_or_longer_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """Zero, longer or unparsable overrides fall back to 300 s."""
        monkeypatch.setenv(_ctl_pending.TEST_COUNTDOWN_ENV, raw)
        assert _ctl_pending.countdown_seconds() == 300


class TestArm:
    """Arming starts one countdown and never restarts it."""

    def test_arm_sets_deadlines(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """arm records wall and monotonic deadlines 300 s out and a 32-char id."""
        armed = pending.arm()
        assert armed.armed_at == _WALL
        assert armed.ready_mono == clock.now + 300
        assert (armed.ready_at - _WALL).total_seconds() == 300
        assert len(armed.pending_id) == 32

    def test_rearm_returns_the_live_one(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """Arming again while live returns the same reset."""
        first = pending.arm()
        clock.now += 5
        assert pending.arm() is first

    def test_rearm_after_lapse_is_new(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """Arming after a lapse starts a new reset with a new id."""
        first = pending.arm()
        clock.now += _ctl_pending.LAPSE_AFTER_SECONDS + 1
        second = pending.arm()
        assert second.pending_id != first.pending_id


class TestBeat:
    """Heartbeats keep the reset alive."""

    def test_beat_extends_life(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """A heartbeat updates the last beat but not the ready deadline."""
        armed = pending.arm()
        clock.now += 10
        beat = pending.beat(armed.pending_id)
        assert beat.last_beat_mono == clock.now
        assert beat.ready_mono == armed.ready_mono
        clock.now += 10
        assert pending.beat(armed.pending_id).pending_id == armed.pending_id

    def test_beat_after_lapse_fails(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """A heartbeat after the lapse window fails as lapsed."""
        armed = pending.arm()
        clock.now += _ctl_pending.LAPSE_AFTER_SECONDS + 1
        with pytest.raises(CtlError) as caught:
            pending.beat(armed.pending_id)
        assert caught.value.code == PENDING_LAPSED

    def test_beat_unknown_id_fails(self, pending: _ctl_pending.PendingResets) -> None:
        """A heartbeat with the wrong id fails as lapsed."""
        pending.arm()
        with pytest.raises(CtlError) as caught:
            pending.beat("not-the-id")
        assert caught.value.code == PENDING_LAPSED

    def test_beat_non_ascii_id_does_not_raise_typeerror(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        """A non-ASCII id is a CtlError, not a TypeError from the compare."""
        pending.arm()
        with pytest.raises(CtlError):
            pending.beat("é")

    def test_beat_with_nothing_armed(self, pending: _ctl_pending.PendingResets) -> None:
        """A heartbeat with nothing armed fails as lapsed."""
        with pytest.raises(CtlError) as caught:
            pending.beat("x")
        assert caught.value.code == PENDING_LAPSED


class TestCheckReady:
    """Commit is allowed only once the countdown is over."""

    def test_early_reports_remaining(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """check_ready before the countdown ends reports the seconds left."""
        armed = pending.arm()
        for _ in range(10):
            clock.now += 10
            pending.beat(armed.pending_id)
        with pytest.raises(CtlError) as caught:
            pending.check_ready(armed.pending_id)
        assert caught.value.code == COUNTDOWN_RUNNING
        assert caught.value.data == {"retry_after_seconds": 200.0}

    def test_ready_after_countdown(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        """check_ready passes once the countdown has elapsed."""
        armed = pending.arm()
        for _ in range(30):
            clock.now += 10
            pending.beat(armed.pending_id)
        assert pending.check_ready(armed.pending_id).pending_id == armed.pending_id

    def test_unknown_id(self, pending: _ctl_pending.PendingResets) -> None:
        """check_ready with an unknown id fails as lapsed."""
        with pytest.raises(CtlError) as caught:
            pending.check_ready("x")
        assert caught.value.code == PENDING_LAPSED


class TestFinish:
    """Finishing drops the reset and is idempotent."""

    def test_finish_clears(self, pending: _ctl_pending.PendingResets) -> None:
        """finish drops the reset so later beats fail."""
        armed = pending.arm()
        pending.finish(armed.pending_id)
        with pytest.raises(CtlError):
            pending.beat(armed.pending_id)

    def test_finish_other_id_keeps_current(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        """finish with another id keeps the current reset."""
        armed = pending.arm()
        pending.finish("other")
        assert pending.beat(armed.pending_id).pending_id == armed.pending_id

    def test_finish_with_nothing_armed(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        """finish with nothing armed is a no-op."""
        pending.finish("x")

    def test_default_sources_are_usable(self) -> None:
        """The default clock and wall sources produce sane deadlines."""
        resets = _ctl_pending.PendingResets()
        assert resets.arm().ready_at > resets.arm().armed_at
