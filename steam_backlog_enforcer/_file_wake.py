"""Wake the enforce loop early when a watched file is rewritten.

The loop ticks every few seconds. A workout credited on the PC should move the
gaming budget well inside one tick, so the wait between ticks returns the
moment screen-locker rewrites its ``log.json``; without an event it waits the
full interval, exactly like the plain sleep it replaces.

Watches the *directory*, filtered to the file's name, never the file itself:
writers replace these files atomically (temp file + rename), which swaps the
inode, and a watch on the file dies after the first write.

inotify through ctypes rather than a dependency -- it is three libc calls. Any
failure logs a warning and degrades to a plain sleep: the answer cache's stat
stamp still picks the change up on the next tick, so degraded means "within a
tick", never "missed".
"""

from __future__ import annotations

import ctypes
import logging
import os
import select
import struct
import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

logger = logging.getLogger(__name__)

# <sys/inotify.h>
_IN_CLOSE_WRITE: Final = 0x00000008
_IN_MOVED_TO: Final = 0x00000080
_IN_CREATE: Final = 0x00000100
_IN_Q_OVERFLOW: Final = 0x00004000
_IN_IGNORED: Final = 0x00008000
_IN_ONLYDIR: Final = 0x01000000
_WATCH_MASK: Final = _IN_CLOSE_WRITE | _IN_MOVED_TO | _IN_CREATE | _IN_ONLYDIR

# struct inotify_event { int wd; uint32_t mask, cookie, len; char name[]; }
_EVENT_HEADER: Final = struct.Struct("iIII")
_READ_SIZE: Final = 64 * 1024


class FileWake:
    """An interruptible inter-tick wait. Build once; never per tick.

    A per-tick watcher would leak descriptors and miss every write landing
    between two ticks, which is the whole window this exists to close.
    """

    def __init__(self, fd: int | None, names: dict[int, frozenset[str]]) -> None:
        """Wrap an inotify ``fd`` whose watch descriptors map to file names.

        Args:
            fd: Non-blocking inotify descriptor, or ``None`` for plain sleep.
            names: Watch descriptor -> the file names that count in that dir.
        """
        self._fd = fd
        self._names = names
        self._poll = select.poll()
        if fd is not None:
            self._poll.register(fd, select.POLLIN)

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds, returning early on a watched write.

        Returns:
            True when a watched file changed, False when the time ran out.
        """
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            if self._fd is None:
                time.sleep(remaining)
                return False
            if self._poll.poll(remaining * 1000) and self._drain():
                return True
        return False

    def close(self) -> None:
        """Release the inotify descriptor; later waits are plain sleeps."""
        if self._fd is not None:
            self._poll.unregister(self._fd)
            os.close(self._fd)
            self._fd = None

    def _degrade(self, reason: str) -> None:
        """Drop to plain sleep, saying why, once."""
        logger.warning(
            "Workout wake-up disabled (%s) -- the budget now updates on the "
            "next enforce tick instead of instantly.",
            reason,
        )
        self.close()

    def _drain(self) -> bool:
        """Read every queued event; whether any of them is a watched file."""
        try:
            buf = os.read(self._fd, _READ_SIZE) if self._fd is not None else b""
        except BlockingIOError:
            return False
        except OSError as exc:
            self._degrade(f"reading inotify events failed: {exc}")
            return False
        changed = False
        offset = 0
        while offset + _EVENT_HEADER.size <= len(buf):
            wd, mask, _cookie, length = _EVENT_HEADER.unpack_from(buf, offset)
            start = offset + _EVENT_HEADER.size
            name = os.fsdecode(buf[start : start + length].split(b"\0", 1)[0])
            offset = start + length
            if mask & _IN_Q_OVERFLOW or name in self._names.get(wd, ()):
                changed = True
            elif mask & _IN_IGNORED:
                self._names.pop(wd, None)
                if not self._names:
                    self._degrade("the watched directory was removed")
                    return changed
        return changed


def open_file_wake(paths: Iterable[Path]) -> FileWake:
    """Watch the parent directory of each path for writes to that path.

    Args:
        paths: Files to wake on; their directories must exist.

    Returns:
        A :class:`FileWake`; a plain-sleep one, warned about, when inotify or
        every watch could not be set up.
    """
    by_dir: dict[Path, set[str]] = {}
    for path in paths:
        by_dir.setdefault(path.parent, set()).add(path.name)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_add_watch.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    except (OSError, AttributeError) as exc:
        logger.warning("inotify unavailable (%s) -- waking on the tick only.", exc)
        return FileWake(None, {})
    if fd < 0:
        reason = os.strerror(ctypes.get_errno())
        logger.warning("inotify_init1 failed (%s) -- waking on the tick only.", reason)
        return FileWake(None, {})
    names: dict[int, frozenset[str]] = {}
    for directory, files in by_dir.items():
        wd = libc.inotify_add_watch(fd, os.fsencode(directory), _WATCH_MASK)
        if wd < 0:
            logger.warning(
                "Cannot watch %s (%s) -- %s changes wake only on the tick.",
                directory,
                os.strerror(ctypes.get_errno()),
                ", ".join(sorted(files)),
            )
            continue
        names[wd] = frozenset(files)
    if not names:
        os.close(fd)
        return FileWake(None, {})
    return FileWake(fd, names)
