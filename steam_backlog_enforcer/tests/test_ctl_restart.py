"""Tests for the restart op, its persisted rate limit and the billed-gap marker.

``RESTART_STATE_FILE`` / ``RESTART_EXIT_FILE`` are redirected to tmp_path by
the conftest's control-plane fixture; they are reached through the module
attribute so the redirect applies.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_gap, _ctl_restart
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

if TYPE_CHECKING:
    from pathlib import Path


def _write_last(value: object) -> None:
    path = _ctl_restart.RESTART_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_restart_at": value}))


class TestRateLimitState:
    """Reading the persisted last-restart time."""

    def test_absent_means_allowed(self) -> None:
        assert _ctl_restart.seconds_until_available() == 0.0
        assert _ctl_restart.restart_available_at() is None

    @pytest.mark.parametrize(
        "text", ["not json", "{}", "[1]", '{"last_restart_at":"x"}']
    )
    def test_unusable_file_means_allowed(self, text: str) -> None:
        path = _ctl_restart.RESTART_STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        assert _ctl_restart.seconds_until_available() == 0.0

    def test_recent_restart_waits(self) -> None:
        _write_last(time.time() - 100)
        wait = _ctl_restart.seconds_until_available()
        assert 495 < wait <= 500
        assert _ctl_restart.restart_available_at() is not None

    def test_future_timestamp_is_capped_at_interval(self) -> None:
        _write_last(time.time() + 99999)
        wait = _ctl_restart.seconds_until_available()
        assert wait == pytest.approx(_ctl_restart.RESTART_INTERVAL_SECONDS, abs=1)

    def test_old_restart_allowed(self) -> None:
        _write_last(time.time() - 10_000)
        assert _ctl_restart.seconds_until_available() == 0.0


class TestOpRestart:
    """The restart op."""

    def test_unsupervised_is_refused(self) -> None:
        ctx = make_ctx(supervised=False)
        with pytest.raises(CtlError) as caught:
            _ctl_restart.op_restart(ctx, {})
        assert caught.value.code == "unsupported"
        assert not ctx.restart_event.is_set()

    def test_accepts_and_persists(self) -> None:
        ctx = make_ctx()
        data = _ctl_restart.op_restart(ctx, {})
        assert ctx.restart_event.is_set()
        assert data["restarting"] is True
        assert data["restart_available_at"] is not None
        saved = json.loads(_ctl_restart.RESTART_STATE_FILE.read_text())
        assert saved["last_restart_at"] == pytest.approx(time.time(), abs=5)
        assert _ctl_restart.RESTART_STATE_FILE.stat().st_mode & 0o777 == 0o600

    def test_second_restart_is_rate_limited(self) -> None:
        _ctl_restart.op_restart(make_ctx(), {})
        ctx = make_ctx()
        with pytest.raises(CtlError) as caught:
            _ctl_restart.op_restart(ctx, {})
        assert caught.value.code == "rate_limited"
        assert caught.value.data["retry_after_seconds"] > 0
        assert not ctx.restart_event.is_set()

    def test_unwritable_limit_fails_closed(self) -> None:
        ctx = make_ctx()
        with (
            patch.object(_ctl_restart, "_atomic_write", side_effect=OSError("ro")),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_restart.op_restart(ctx, {})
        assert caught.value.code == "op_failed"
        assert not ctx.restart_event.is_set()


class TestRestartGap:
    """The exit marker and its settlement by the next daemon."""

    def test_record_exit_writes_marker(self) -> None:
        _ctl_gap.record_exit()
        saved = json.loads(_ctl_gap.RESTART_EXIT_FILE.read_text())
        assert saved["exited_at"] == pytest.approx(time.time(), abs=5)

    def test_record_exit_never_raises(self) -> None:
        with patch.object(_ctl_gap, "_atomic_write", side_effect=OSError("ro")):
            _ctl_gap.record_exit()

    def _marker(self, text: str) -> Path:
        path = _ctl_gap.RESTART_EXIT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    @pytest.mark.parametrize("text", ["junk", "{}", '{"exited_at":"x"}'])
    def test_unusable_marker_is_dropped(self, text: str) -> None:
        path = self._marker(text)
        assert _ctl_gap._take_exit_time() is None
        assert not path.exists()

    def test_missing_marker(self) -> None:
        assert _ctl_gap._take_exit_time() is None

    def _settle(self, *, demo: bool = False) -> MagicMock:
        with patch.object(_ctl_gap, "playtime_tick") as tick:
            _ctl_gap.settle_restart_gap(
                MagicMock(), MagicMock(), base_interval=3.0, demo=demo
            )
        return tick

    def test_bills_the_gap_once(self) -> None:
        path = self._marker(json.dumps({"exited_at": time.time() - 20}))
        tick = self._settle()
        interval = tick.call_args.kwargs["interval"]
        assert interval == pytest.approx(11, abs=0.5)
        assert not path.exists()

    def test_short_gap_keeps_base_interval(self) -> None:
        self._marker(json.dumps({"exited_at": time.time() - 0.5}))
        assert self._settle().call_args.kwargs["interval"] == 3.0

    @pytest.mark.parametrize("age", [-50, 301])
    def test_out_of_window_is_not_billed(self, age: float) -> None:
        self._marker(json.dumps({"exited_at": time.time() - age}))
        self._settle().assert_not_called()

    def test_no_marker_bills_nothing(self) -> None:
        self._settle().assert_not_called()

    def test_demo_never_bills_but_spends_marker(self) -> None:
        path = self._marker(json.dumps({"exited_at": time.time() - 20}))
        self._settle(demo=True).assert_not_called()
        assert not path.exists()
