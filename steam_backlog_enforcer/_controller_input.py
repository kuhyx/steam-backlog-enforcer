"""Noticing that a game controller is being used.

The X screensaver idle counter only tracks keyboards and pointers. A gamepad
session that goes five minutes without touching either would look idle, and
pausing the budget there would hand out free gaming — the single worst failure
mode of the engagement gate, because it rewards the behaviour it fails to see.

Presence is not a usable proxy for use. Measured on this machine, ``/dev/input/js0``
is an *ASRock LED Controller*: the kernel exposes the motherboard's RGB device as
a joystick. Treating "a js device exists" as "a controller is in play" would
disable the idle criterion permanently, on a machine with no gamepad attached.

So this watches for actual events instead. Each joystick device is opened
non-blocking and drained every tick; joydev gives every reader its own event
queue, so draining ours cannot steal input from the game. The synthetic burst
joydev replays on open is flagged ``JS_EVENT_INIT`` and is skipped — without that
filter, merely opening the device would look like a button press.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_DEVICE_DIR: Final = Path("/dev/input")
_DEVICE_PREFIX: Final = "js"

# struct js_event { __u32 time; __s16 value; __u8 type; __u8 number; }
_EVENT_SIZE: Final = 8
_TYPE_OFFSET: Final = 6
_JS_EVENT_INIT: Final = 0x80

# Cap per device per tick so a flood cannot stall the enforce loop.
_MAX_EVENTS_PER_POLL: Final = 64


class ControllerActivity:
    """Tracks when a joystick device last produced a real event."""

    def __init__(self, *, device_dir: Path = _DEVICE_DIR) -> None:
        """Start with no devices open and no activity seen.

        Args:
            device_dir: Directory holding ``js*`` nodes.
        """
        self._device_dir = device_dir
        self._fds: dict[Path, int] = {}
        self._last_event_at: float | None = None

    def poll(self, *, now: float) -> None:
        """Drain pending controller events, recording any real activity.

        Args:
            now: Monotonic timestamp for this tick.
        """
        self._sync_devices()
        for path in list(self._fds):
            if self._drain(path):
                self._last_event_at = now

    def seconds_since_activity(self, *, now: float) -> float | None:
        """Return seconds since the last real controller event.

        Args:
            now: Monotonic timestamp for this tick.

        Returns:
            The elapsed seconds, or ``None`` if no event has been seen at all —
            which the caller must not read as "idle", only as "no evidence".
        """
        if self._last_event_at is None:
            return None
        return now - self._last_event_at

    def close(self) -> None:
        """Close every open device."""
        for path in list(self._fds):
            self._forget(path)

    def _sync_devices(self) -> None:
        """Open newly appeared ``js*`` devices and forget vanished ones."""
        try:
            present = {
                entry
                for entry in self._device_dir.iterdir()
                if entry.name.startswith(_DEVICE_PREFIX)
            }
        except OSError:
            present = set()

        for path in list(self._fds):
            if path not in present:
                self._forget(path)

        for path in present - set(self._fds):
            self._open(path)

    def _open(self, path: Path) -> None:
        """Open *path* for reading, ignoring devices we may not read.

        Args:
            path: Device to open.
        """
        try:
            self._fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            # A js node we cannot open tells us nothing either way; the idle
            # criterion simply falls back to keyboard and pointer input.
            logger.debug("Cannot open controller device %s", path)

    def _drain(self, path: Path) -> bool:
        """Read pending events from *path*.

        Args:
            path: Device to drain.

        Returns:
            Whether at least one non-synthetic event was read.
        """
        fd = self._fds[path]
        seen = False
        for _ in range(_MAX_EVENTS_PER_POLL):
            try:
                chunk = os.read(fd, _EVENT_SIZE)
            except OSError as exc:
                if exc.errno != errno.EAGAIN:
                    self._forget(path)
                break
            if len(chunk) < _EVENT_SIZE:
                break
            if not chunk[_TYPE_OFFSET] & _JS_EVENT_INIT:
                seen = True
        return seen

    def _forget(self, path: Path) -> None:
        """Close and drop *path*.

        Args:
            path: Device to close.
        """
        fd = self._fds.pop(path, None)
        if fd is not None:
            # The usual reason to forget a device is that reading it just
            # failed, which often means the fd is already unusable; closing it
            # again must not take the enforce loop down with it.
            with contextlib.suppress(OSError):
                os.close(fd)
