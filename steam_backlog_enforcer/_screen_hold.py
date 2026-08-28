"""Detecting that a gatelock guard currently owns the screen.

The screen lockers (``screen_locker``, ``leetcode_guard``) coordinate through a
single advisory ``flock`` on ``$XDG_RUNTIME_DIR/gatelock/holder.lock``. The file's
*contents* cannot answer "is it held right now" — a stale record left by a dead
process is byte-identical to a live one — and gatelock's own
``read_claim_if_held`` answers the question by *taking* the lock.

The enforcer must not do that. Taking the lock every three seconds, even for
microseconds, would race a guard trying to claim the screen. ``/proc/locks``
reports the same fact by observation, so this reads that instead and never
touches the file.

Line format is ``idx: FLOCK ADVISORY WRITE <pid> <maj:min:inode> <start> <end>``,
with major and minor in hex. Lines containing ``->`` describe processes *waiting*
for a lock, not holding one, and are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Final

_PROC_LOCKS: Final = Path("/proc/locks")
_HOLDER_RELATIVE: Final = Path("gatelock/holder.lock")

# `maj:min:inode`, major and minor hex, inode decimal.
_DEVICE_FIELD: Final = re.compile(r"^[0-9a-f]+:[0-9a-f]+:\d+$")

_WAITER_MARKER: Final = "->"
_PID_FIELD_INDEX: Final = 4


class ScreenHoldError(RuntimeError):
    """Whether the screen is held could not be determined."""


@dataclass(frozen=True)
class ScreenHold:
    """Whether a guard owns the screen, and which process does."""

    held: bool
    holder_pid: int | None = None


def holder_lock_path(uid: int) -> Path:
    """Return the gatelock holder-lock path for *uid*.

    Args:
        uid: Owner of the desktop session.

    Returns:
        Path to ``holder.lock``.
    """
    return Path(f"/run/user/{uid}") / _HOLDER_RELATIVE


def screen_hold(path: Path) -> ScreenHold:
    """Report whether *path*'s advisory lock is currently held.

    Args:
        path: The gatelock holder-lock file.

    Returns:
        The hold state, with the holding PID when there is one.

    Raises:
        ScreenHoldError: If ``/proc/locks`` cannot be read. A missing *path* is
            not an error — it means no guard has ever run this boot.
    """
    try:
        stat = path.stat()
    except OSError:
        return ScreenHold(held=False)

    target = f"{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}"

    try:
        raw = _PROC_LOCKS.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read {_PROC_LOCKS}: {exc}"
        raise ScreenHoldError(msg) from exc

    return _find_holder(raw, target)


def _find_holder(raw: str, target: str) -> ScreenHold:
    """Scan ``/proc/locks`` text for a live lock on *target*.

    Args:
        raw: Contents of ``/proc/locks``.
        target: ``maj:min:inode`` string to match.

    Returns:
        The hold state.
    """
    for line in raw.splitlines():
        fields = line.split()
        if _WAITER_MARKER in fields:
            continue
        if not any(field == target for field in fields if _DEVICE_FIELD.match(field)):
            continue
        return ScreenHold(held=True, holder_pid=_pid_of(fields))
    return ScreenHold(held=False)


def _pid_of(fields: list[str]) -> int | None:
    """Return the PID column of a ``/proc/locks`` row.

    Args:
        fields: Whitespace-split row.

    Returns:
        The PID, or ``None`` if the row is shaped unexpectedly.
    """
    if len(fields) <= _PID_FIELD_INDEX:
        return None
    try:
        return int(fields[_PID_FIELD_INDEX])
    except ValueError:
        return None
