"""What happens around a write to the ``chattr +i`` exceptions file.

Split out of :mod:`steam_backlog_enforcer._whitelist_locking` to keep it under
the 250-line cap. Imports nothing from it, so either side can be loaded alone.

* A direct write that cannot set the flag again raises
  :class:`ExceptionNotLockedError`: the entry is kept, but the caller must not
  report success for a file anyone can now edit.
* A file root creates is handed back to the config dir's owner, or the
  unprivileged CLI and web server could no longer read their own list.
* The enforce loop's per-tick lock stays best-effort, so it can never crash
  the daemon; :func:`note_lock_state` logs only when a file's lock state
  changes, so a flag that will not stick warns once, not every ~3 s tick.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

NOT_LOCKED_MESSAGE = "exception saved but file not locked"

# Files whose flag did not stick at the last tick (warned about already).
_unlocked: set[Path] = set()


class ExceptionNotLockedError(RuntimeError):
    """The exception was saved, but the file could not be made immutable."""


def hand_back_to_dir_owner(path: Path) -> None:
    """Give *path* to the owner of its directory if root just created it.

    Must run while the file is still mutable: ``chown`` on a ``+i`` file is
    refused. A missing file or a refused ``chown`` (non-root) is left alone.
    """
    with contextlib.suppress(OSError):
        owner = path.parent.stat()
        if path.stat().st_uid != owner.st_uid:
            os.chown(path, owner.st_uid, owner.st_gid)


def note_lock_state(path: Path, *, locked: bool) -> None:
    """Log *path*'s lock state, but only when it changed since the last tick."""
    if not locked and path not in _unlocked:
        _unlocked.add(path)
        logger.warning("%s: immutable flag did not stick (chattr +i failed)", path)
    elif locked and path in _unlocked:
        _unlocked.discard(path)
        logger.info("%s: immutable flag holds again", path)


def reset_lock_warnings() -> None:
    """Forget which files were warned about (tests)."""
    _unlocked.clear()
