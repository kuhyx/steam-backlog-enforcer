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
import time
from typing import Any, Final
from urllib.parse import urlsplit

# Loopback, so a short timeout is generous. The daemon ticks frequently and
# must never block on this.
_TIMEOUT_SECONDS: Final = 2.0

# A successful answer is reused for this long. The daemon would otherwise make
# one HTTP call per tick, and the answer changes at most a few times a day. The
# cost is that a workout logged now raises the budget within a minute rather
# than instantly -- invisible next to a two-hour swing.
_CACHE_TTL_SECONDS: Final = 60.0


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
    floor for another minute.
    """

    def __init__(self) -> None:
        """Start empty."""
        self._entries: dict[str, tuple[float, bool]] = {}

    def clear(self) -> None:
        """Drop every cached answer, forcing the next call to re-ask."""
        self._entries.clear()

    def fresh(self, url: str) -> bool | None:
        """The cached answer for ``url`` if it is still within its TTL."""
        cached = self._entries.get(url)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        return None

    def store(self, url: str, *, answer: bool) -> bool:
        """Remember ``answer`` for ``url`` as of now, and hand it back."""
        self._entries[url] = (time.monotonic(), answer)
        return answer
