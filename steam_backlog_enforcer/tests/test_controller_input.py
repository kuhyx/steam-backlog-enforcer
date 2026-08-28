"""Tests for noticing real gamepad input.

The distinction that matters: this machine exposes an *ASRock LED Controller*
as ``/dev/input/js0``, so mere presence of a js device must not register as
play — only actual, non-synthetic events do.
"""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._controller_input import ControllerActivity

if TYPE_CHECKING:
    from pathlib import Path

CI = "steam_backlog_enforcer._controller_input"


def _event(*, init: bool) -> bytes:
    """Build one 8-byte ``struct js_event``; byte 6 is the type field."""
    return bytes([0, 0, 0, 0, 0, 0, 0x81 if init else 0x01, 0])


class TestSyncDevices:
    def test_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        activity = ControllerActivity(device_dir=tmp_path / "absent")
        activity.poll(now=1.0)
        assert activity.seconds_since_activity(now=1.0) is None

    def test_non_js_entries_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "event0").write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=1.0)
        assert activity.seconds_since_activity(now=1.0) is None

    def test_a_vanished_device_is_forgotten(self, tmp_path: Path) -> None:
        node = tmp_path / "js0"
        node.write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=1.0)
        node.unlink()
        activity.poll(now=2.0)
        activity.close()

    def test_an_unopenable_device_is_skipped(self, tmp_path: Path) -> None:
        node = tmp_path / "js0"
        node.write_bytes(_event(init=False))
        with patch(f"{CI}.os.open", side_effect=OSError("denied")):
            activity = ControllerActivity(device_dir=tmp_path)
            activity.poll(now=1.0)
        assert activity.seconds_since_activity(now=1.0) is None


class TestDrain:
    def test_a_real_event_is_activity(self, tmp_path: Path) -> None:
        (tmp_path / "js0").write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=12.5) == 2.5
        activity.close()

    def test_the_synthetic_open_burst_is_not_activity(self, tmp_path: Path) -> None:
        # joydev replays current state on open; treating that as a button press
        # would make simply having an LED device look like a gaming session.
        (tmp_path / "js0").write_bytes(_event(init=True) * 3)
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=10.0) is None
        activity.close()

    def test_a_truncated_record_stops_the_drain(self, tmp_path: Path) -> None:
        (tmp_path / "js0").write_bytes(b"\x00\x00\x00")
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=10.0) is None
        activity.close()

    def test_the_per_tick_cap_bounds_the_drain(self, tmp_path: Path) -> None:
        (tmp_path / "js0").write_bytes(_event(init=False) * 200)
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=10.0) == 0.0
        activity.close()

    def test_eagain_leaves_the_device_open(self, tmp_path: Path) -> None:
        # "No events pending" is the normal case on a quiet controller; it must
        # not be mistaken for the device going away.
        (tmp_path / "js0").write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        with patch(f"{CI}.os.read", side_effect=OSError(errno.EAGAIN, "again")):
            activity.poll(now=10.0)
        assert list(activity._fds) == [tmp_path / "js0"]
        assert activity.seconds_since_activity(now=10.0) is None
        activity.close()

    def test_an_empty_device_yields_nothing(self, tmp_path: Path) -> None:
        fifo = tmp_path / "js0"
        os.mkfifo(fifo)
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=10.0) is None
        activity.close()

    def test_a_device_that_stays_is_kept_open_across_ticks(
        self, tmp_path: Path
    ) -> None:
        node = tmp_path / "js0"
        node.write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        first = dict(activity._fds)
        activity.poll(now=11.0)
        assert activity._fds == first
        activity.close()

    def test_forgetting_an_unknown_device_is_a_no_op(self, tmp_path: Path) -> None:
        activity = ControllerActivity(device_dir=tmp_path)
        activity._forget(tmp_path / "js9")
        assert activity._fds == {}

    def test_a_hard_read_error_drops_the_device(self, tmp_path: Path) -> None:
        (tmp_path / "js0").write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        with patch(f"{CI}.os.read", side_effect=OSError(errno.EIO, "gone")):
            activity.poll(now=10.0)
        assert activity.seconds_since_activity(now=10.0) is None

    def test_forgetting_survives_an_already_closed_fd(self, tmp_path: Path) -> None:
        (tmp_path / "js0").write_bytes(_event(init=False))
        activity = ControllerActivity(device_dir=tmp_path)
        activity.poll(now=10.0)
        with patch(f"{CI}.os.close", side_effect=OSError("bad fd")):
            activity.close()
