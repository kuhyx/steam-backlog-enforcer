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


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def pending(clock: _Clock) -> _ctl_pending.PendingResets:
    return _ctl_pending.PendingResets(clock=clock, wall=lambda: _WALL)


class TestCountdownSeconds:
    """The VM-only override can shorten the countdown, never lengthen it."""

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ctl_pending.TEST_COUNTDOWN_ENV, raising=False)
        assert _ctl_pending.countdown_seconds() == 300

    def test_shortened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ctl_pending.TEST_COUNTDOWN_ENV, "7")
        assert _ctl_pending.countdown_seconds() == 7

    @pytest.mark.parametrize("raw", ["0", "300", "9999", "abc", "-5", ""])
    def test_invalid_or_longer_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv(_ctl_pending.TEST_COUNTDOWN_ENV, raw)
        assert _ctl_pending.countdown_seconds() == 300


class TestArm:
    """Arming starts one countdown and never restarts it."""

    def test_arm_sets_deadlines(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        armed = pending.arm()
        assert armed.armed_at == _WALL
        assert armed.ready_mono == clock.now + 300
        assert (armed.ready_at - _WALL).total_seconds() == 300
        assert len(armed.pending_id) == 32

    def test_rearm_returns_the_live_one(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        first = pending.arm()
        clock.now += 5
        assert pending.arm() is first

    def test_rearm_after_lapse_is_new(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
        first = pending.arm()
        clock.now += _ctl_pending.LAPSE_AFTER_SECONDS + 1
        second = pending.arm()
        assert second.pending_id != first.pending_id


class TestBeat:
    """Heartbeats keep the reset alive."""

    def test_beat_extends_life(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
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
        armed = pending.arm()
        clock.now += _ctl_pending.LAPSE_AFTER_SECONDS + 1
        with pytest.raises(CtlError) as caught:
            pending.beat(armed.pending_id)
        assert caught.value.code == PENDING_LAPSED

    def test_beat_unknown_id_fails(self, pending: _ctl_pending.PendingResets) -> None:
        pending.arm()
        with pytest.raises(CtlError) as caught:
            pending.beat("not-the-id")
        assert caught.value.code == PENDING_LAPSED

    def test_beat_non_ascii_id_does_not_raise_typeerror(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        pending.arm()
        with pytest.raises(CtlError):
            pending.beat("é")

    def test_beat_with_nothing_armed(self, pending: _ctl_pending.PendingResets) -> None:
        with pytest.raises(CtlError) as caught:
            pending.beat("x")
        assert caught.value.code == PENDING_LAPSED


class TestCheckReady:
    """Commit is allowed only once the countdown is over."""

    def test_early_reports_remaining(
        self, pending: _ctl_pending.PendingResets, clock: _Clock
    ) -> None:
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
        armed = pending.arm()
        for _ in range(30):
            clock.now += 10
            pending.beat(armed.pending_id)
        assert pending.check_ready(armed.pending_id).pending_id == armed.pending_id

    def test_unknown_id(self, pending: _ctl_pending.PendingResets) -> None:
        with pytest.raises(CtlError) as caught:
            pending.check_ready("x")
        assert caught.value.code == PENDING_LAPSED


class TestFinish:
    """Finishing drops the reset and is idempotent."""

    def test_finish_clears(self, pending: _ctl_pending.PendingResets) -> None:
        armed = pending.arm()
        pending.finish(armed.pending_id)
        with pytest.raises(CtlError):
            pending.beat(armed.pending_id)

    def test_finish_other_id_keeps_current(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        armed = pending.arm()
        pending.finish("other")
        assert pending.beat(armed.pending_id).pending_id == armed.pending_id

    def test_finish_with_nothing_armed(
        self, pending: _ctl_pending.PendingResets
    ) -> None:
        pending.finish("x")

    def test_default_sources_are_usable(self) -> None:
        resets = _ctl_pending.PendingResets()
        assert resets.arm().ready_at > resets.arm().armed_at
