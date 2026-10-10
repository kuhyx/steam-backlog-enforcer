"""Tests for the gaming-reset ops in ``_ctl_reset``.

The reset core and the lock gate are mocked; the countdown runs on a fake
clock, so nothing sleeps and no state file is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_reset
from steam_backlog_enforcer._ctl_pending import PendingResets
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer._gaming_reset import ResetOutcome
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

if TYPE_CHECKING:
    from steam_backlog_enforcer._ctl_context import CtlContext

_PHRASE = "reset today's gaming budget"


class _Clock:
    """A settable monotonic clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _ctx_with_clock() -> tuple[CtlContext, _Clock]:
    clock = _Clock()
    ctx = make_ctx()
    ctx.pending = PendingResets(clock=clock)
    return ctx, clock


def _outcome() -> ResetOutcome:
    return ResetOutcome("2026-01-01", 123.4567, was_blocked=True, released=[Path("/m")])


class TestArmHeartbeatCancel:
    """The cheap phases of the two-phase reset."""

    def test_arm_returns_view(self) -> None:
        ctx = make_ctx()
        with patch.object(_ctl_reset, "check_locks") as locks:
            view = _ctl_reset.op_arm(ctx, {"phrase": _PHRASE})
        locks.assert_called_once_with("gaming-reset")
        assert view["phrase"] == _PHRASE
        assert view["heartbeat_interval_seconds"] == 10
        assert view["lapse_after_seconds"] == 15
        assert set(view) >= {"pending_id", "armed_at", "ready_at"}

    def test_arm_wrong_phrase(self) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_reset.op_arm(make_ctx(), {"phrase": "no"})
        assert caught.value.code == "wrong_phrase"

    def test_heartbeat(self) -> None:
        ctx = make_ctx()
        pending_id = ctx.pending.arm().pending_id
        view = _ctl_reset.op_heartbeat(ctx, {"pending_id": pending_id})
        assert view["pending_id"] == pending_id

    def test_heartbeat_needs_id(self) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_reset.op_heartbeat(make_ctx(), {})
        assert caught.value.code == "invalid_params"

    def test_cancel_is_idempotent(self) -> None:
        ctx = make_ctx()
        pending_id = ctx.pending.arm().pending_id
        for _ in range(2):
            result = _ctl_reset.op_cancel(ctx, {"pending_id": pending_id})
            assert result == {"cancelled": True}
        with pytest.raises(CtlError):
            ctx.pending.beat(pending_id)


class TestCommit:
    """The commit phase re-checks everything under the tick lock."""

    @staticmethod
    def _ready() -> tuple[CtlContext, str]:
        ctx, clock = _ctx_with_clock()
        pending_id = ctx.pending.arm().pending_id
        for _ in range(31):
            clock.now += 10
            ctx.pending.beat(pending_id)
        return ctx, pending_id

    def test_commits_and_clears(self) -> None:
        ctx, pending_id = self._ready()
        with (
            patch.object(_ctl_reset, "check_locks"),
            patch.object(_ctl_reset, "reset_today", return_value=_outcome()) as reset,
        ):
            data = _ctl_reset.op_commit(
                ctx, {"pending_id": pending_id, "phrase": _PHRASE}
            )
        reset.assert_called_once_with(source="ctl")
        assert data == {
            "day_key": "2026-01-01",
            "seconds_before": 123.457,
            "was_blocked": True,
            "released": ["/m"],
        }
        assert not ctx.tick_lock.locked()
        with pytest.raises(CtlError):
            ctx.pending.beat(pending_id)

    def test_too_early(self) -> None:
        ctx = make_ctx()
        pending_id = ctx.pending.arm().pending_id
        with pytest.raises(CtlError) as caught:
            _ctl_reset.op_commit(ctx, {"pending_id": pending_id, "phrase": _PHRASE})
        assert caught.value.code == "countdown_running"

    def test_wrong_phrase(self) -> None:
        ctx, pending_id = self._ready()
        with pytest.raises(CtlError) as caught:
            _ctl_reset.op_commit(ctx, {"pending_id": pending_id, "phrase": "no"})
        assert caught.value.code == "wrong_phrase"

    def test_os_error_is_op_failed_and_keeps_pending(self) -> None:
        ctx, pending_id = self._ready()
        with (
            patch.object(_ctl_reset, "check_locks"),
            patch.object(_ctl_reset, "reset_today", side_effect=OSError("ro")),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_reset.op_commit(ctx, {"pending_id": pending_id, "phrase": _PHRASE})
        assert caught.value.code == "op_failed"
        assert ctx.pending.check_ready(pending_id).pending_id == pending_id

    def test_locked(self) -> None:
        ctx, pending_id = self._ready()
        lock = CtlError("locked", "total block")
        with (
            patch.object(_ctl_reset, "check_locks", side_effect=lock),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_reset.op_commit(ctx, {"pending_id": pending_id, "phrase": _PHRASE})
        assert caught.value.code == "locked"
