"""One loopback status-API read, shared by the workout and LeetCode bonuses.

Both bonuses ask a sibling daemon's ``/api/status`` endpoint over loopback and
reuse a successful answer for a minute. The transport and the cache policy
are identical, so they live here once; each bonus keeps only the field it
reads out of the payload.

Uses ``http.client`` rather than ``urllib.request`` deliberately, matching
``screen_locker._http_workout_fetch``: it takes a host and a path rather than a
URL, so there is no scheme for a bad config value to turn into a ``file://``
read, and no lint waiver is needed to say so.
"""

from __future__ import annotations

import http.client
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Loopback, so a short timeout is generous. The daemon ticks frequently and
# must never block on this.
_TIMEOUT_SECONDS: Final = 2.0

# A successful answer is reused for this long. The daemon would otherwise make
# one HTTP call per tick, and the answer changes at most a few times a day. The
# cost is that a workout logged now raises the budget within a minute rather
# than instantly -- invisible next to a two-hour swing. A caller that knows
# which file the answer is derived from also passes its stat stamp, and a
# changed stamp drops the answer at once (see :func:`file_stamp`).
_CACHE_TTL_SECONDS: Final = 60.0

# ``(st_ino, st_mtime_ns, st_size)`` of a source file; ``None`` when absent.
type Stamp = tuple[int, int, int] | None

# Last stat error per path, so an unreadable file warns once, not every tick.
_stat_errors: dict[Path, str] = {}


def file_stamp(path: Path) -> Stamp:
    """Cheap identity of ``path``'s current contents, for cache invalidation.

    The inode is part of it because writers replace these files atomically:
    a rename within the same mtime tick still changes the inode.

    Returns:
        The stamp, or ``None`` when the file does not exist -- an ordinary
        state (no workout log yet, no book registered), compared like any
        other stamp. Any other stat failure also yields ``None``, warned once
        per distinct error so a 3 s loop cannot flood the journal.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        _stat_errors.pop(path, None)
        return None
    except OSError as exc:
        if _stat_errors.get(path) != str(exc):
            _stat_errors[path] = str(exc)
            logger.warning(
                "Cannot stat %s (%s) -- its cached answer now expires only "
                "on the %ds TTL instead of on change.",
                path,
                exc,
                int(_CACHE_TTL_SECONDS),
            )
        return None
    _stat_errors.pop(path, None)
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def get_status(url: str) -> dict[str, Any]:
    """GET a status endpoint and return its JSON body.

    Args:
        url: The status endpoint, e.g. ``http://127.0.0.1:8770/api/status``.

    Raises:
        OSError: The endpoint could not be reached.
        ValueError: The response was not usable JSON, or not a 200.
    """
    split = urlsplit(url)
    conn = http.client.HTTPConnection(
        split.hostname or "127.0.0.1",
        split.port or 80,
        timeout=_TIMEOUT_SECONDS,
    )
    try:
        conn.request("GET", split.path or "/api/status")
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != http.HTTPStatus.OK:
            msg = f"status {resp.status} {resp.reason}"
            raise ValueError(msg)
    finally:
        conn.close()
    payload: dict[str, Any] = json.loads(body)
    return payload


class AnswerCache:
    """Successful answers by URL, each good for :data:`_CACHE_TTL_SECONDS`.

    Only *successes* are stored. A failure is retried on the very next tick, so
    a restarted status server takes effect immediately instead of serving the
    floor for another minute. An answer stored with a :data:`Stamp` is also
    dropped as soon as the caller presents a different one.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._entries: dict[str, tuple[float, bool, Stamp]] = {}

    def clear(self) -> None:
        """Drop every cached answer, forcing the next call to re-ask."""
        self._entries.clear()

    def fresh(self, url: str, *, stamp: Stamp = None) -> bool | None:
        """The cached answer for ``url`` if within its TTL and ``stamp``."""
        cached = self._entries.get(url)
        if cached is None or cached[2] != stamp:
            return None
        if time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        return None

    def store(self, url: str, *, answer: bool, stamp: Stamp = None) -> bool:
        """Remember ``answer`` for ``url`` as of now, and hand it back.

        ``stamp`` must be taken *before* the answer was fetched: a write that
        lands mid-fetch then leaves the stored stamp stale, so the next call
        re-asks instead of trusting a pre-write answer for a whole TTL.
        """
        self._entries[url] = (time.monotonic(), answer, stamp)
        return answer
