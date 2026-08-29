"""Reading the kernel's mount table to see which blocks are live.

``/proc/self/mountinfo`` is the source of truth rather than our own record of
what we mounted: a bind mount can survive a crash or be removed by hand, and
the enforcer has to reconcile against reality on every tick.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_INIT_MOUNTINFO_PATH = Path("/proc/1/mountinfo")
MOUNTINFO_PATH = Path("/proc/self/mountinfo")
_MOUNTINFO_MIN_FIELDS = 5
_MOUNTPOINT_FIELD = 4


def _unescape_mountinfo(field: str) -> str:
    """Decode the octal escapes the kernel writes into mountinfo paths.

    Args:
        field: A raw mountinfo field.

    Returns:
        The decoded field.
    """
    return (
        field.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )


def _mountpoints(path: Path) -> set[Path]:
    """Parse *path* as mountinfo and return the mount points it lists.

    Args:
        path: A mountinfo file.

    Returns:
        Every mount point named in the file.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError, ValueError:
        logger.warning("Could not read mountinfo at %s.", path)
        return set()

    points: set[Path] = set()
    for line in raw.splitlines():
        fields = line.split(" ")
        if len(fields) < _MOUNTINFO_MIN_FIELDS:
            continue
        points.add(Path(_unescape_mountinfo(fields[_MOUNTPOINT_FIELD])))
    return points
