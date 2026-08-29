"""Self-check: is this server process running code that has since changed?

``_serve_guard`` already answers this about *other* processes, at launch time,
so ``serve`` can replace a stale server before taking the port. That guard has
two holes, both of which were open on 2026-08-29:

1. It only runs from ``cmd_serve``. A server started as
   ``python -c "from ..._web_server import serve; serve(port=8000)"`` never
   passes through it.
2. :func:`~steam_backlog_enforcer._serve_guard.is_our_server` matches argv
   holding ``steam_backlog_enforcer.main``, which such a process does not have,
   so it is not even recognised as ours to replace.

The result was a UI reporting an 8-hour budget while the daemon enforced six,
which is precisely the divergence the shared ``rules_for`` seam exists to
prevent -- defeated not by a second copy of the logic but by a second copy of
the *process*.

So the check also lives here, inside the server, where no launch path can skip
it. A server that has been outrun by its own source stops answering rather than
answering wrongly: with a supervisor it comes straight back on fresh code, and
without one it is at least honestly silent. A wrong number is worse than no
number, because only one of the two gets believed.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Final

logger = logging.getLogger(__name__)

# Package tree whose .py mtimes decide whether this process is out of date.
_PACKAGE_ROOT: Final = Path(__file__).resolve().parent

# Re-checking on every request would stat the whole package per request. The
# window this leaves is bounded and small: at worst one stale answer in this
# many seconds, versus the unbounded staleness it replaces.
_RECHECK_INTERVAL_SECONDS: Final = 5.0

_last_checked: dict[str, float] = {}
_last_result: dict[str, Path | None] = {}


def reset_cache() -> None:
    """Drop the memoised answer, forcing the next call to re-stat."""
    _last_checked.clear()
    _last_result.clear()


def newest_py_after(cutoff: float) -> Path | None:
    """Return the newest package ``.py`` modified after *cutoff*.

    Args:
        cutoff: Epoch seconds to compare mtimes against.

    Returns:
        The newest offending path, or ``None`` when the tree is older than
        *cutoff*. Returning the path rather than a bool keeps the refusal
        auditable: the log names the file that made this process obsolete.
    """
    newest: Path | None = None
    newest_mtime = cutoff
    for path in _PACKAGE_ROOT.rglob("*.py"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            # A file removed mid-scan cannot make us stale; skip it quietly.
            continue
        if mtime > newest_mtime:
            newest, newest_mtime = path, mtime
    return newest


def outdated_source(started_at: float, *, now: float | None = None) -> Path | None:
    """Return the source file that makes this process stale, if any.

    Args:
        started_at: Epoch seconds this process began. Any package file newer
            than this was not the file this process loaded.
        now: Override for the current monotonic time (for testing).

    Returns:
        The newest changed path, or ``None`` when the running code is current.
    """
    moment = now if now is not None else time.monotonic()
    checked = _last_checked.get("at")
    if checked is not None and moment - checked < _RECHECK_INTERVAL_SECONDS:
        return _last_result.get("path")

    result = newest_py_after(started_at)
    _last_checked["at"] = moment
    _last_result["path"] = result
    if result is not None:
        logger.error(
            "This server is running outdated code: %s changed after the "
            "process started. Refusing to serve rather than report numbers "
            "the daemon is not enforcing. Restart it with `./run.sh serve`.",
            result,
        )
    return result
