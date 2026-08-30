"""Whether today has a counted workout, asked over loopback HTTP.

The screen locker owns the question "did I work out today"; this module asks it
and caches the answer. Turning it into seconds is
:mod:`steam_backlog_enforcer._budget_resolve`'s job -- this file publishes only
the fact, mirroring the split screen-locker itself documents, so the two repos
cannot disagree about what a workout day is.

**Fail closed.** Any failure to get an answer -- status server down, timeout,
malformed body, non-200 -- yields ``None``, logged at warning with the concrete
reason, and the caller grants no workout bonus. Failing open would let the
whole coupling be defeated by stopping one user service, and a silent bonus
would be indistinguishable from an earned one.

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
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

# Loopback, so a short timeout is generous. The daemon ticks frequently and
# must never block on this.
_TIMEOUT_SECONDS: Final = 2.0

# A successful answer is reused for this long. The daemon would otherwise make
# one HTTP call per tick, and the answer changes at most a few times a day. The
# cost is that a workout logged now raises the budget within a minute rather
# than instantly -- invisible next to a two-hour swing.
_CACHE_TTL_SECONDS: Final = 60.0

# Only *successes* are cached. A failure is retried on the very next tick, so a
# restarted status server takes effect immediately instead of serving the floor
# for another minute. A dict rather than a module global so no function here
# needs a `global` statement to write it.
_cache: dict[str, tuple[float, bool]] = {}


def reset_cache() -> None:
    """Drop the cached answer, forcing the next call to re-ask."""
    _cache.clear()


def _fetch_workout_today(url: str) -> bool:
    """Read ``gaming.workout_today`` from the screen-locker status API.

    Args:
        url: The status endpoint, e.g. ``http://127.0.0.1:8770/api/status``.

    Returns:
        Whether a counted workout is logged for today.

    Raises:
        OSError: The endpoint could not be reached.
        ValueError: The response was not usable JSON, or not a 200.
        KeyError: The payload lacked the expected fields.
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
    return bool(json.loads(body)["gaming"]["workout_today"])


def workout_logged_today(config: Config) -> bool | None:
    """Ask the screen locker whether today has a counted workout.

    Args:
        config: Loaded user configuration, for the status URL.

    Returns:
        True or False when the locker answered, ``None`` when it could not be
        reached or its answer could not be understood. ``None`` is deliberately
        distinct from ``False`` so the caller can log which one happened.
    """
    url = config.workout_status_url
    now = time.monotonic()
    cached = _cache.get(url)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        answer = _fetch_workout_today(url)
    except OSError as exc:
        logger.warning(
            "Could not reach the screen-locker status API at %s (%s) — "
            "granting no workout bonus. Check "
            "`systemctl --user status screen-locker-web`.",
            url,
            exc,
        )
        return None
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "Screen-locker status API at %s returned something unusable (%s) — "
            "granting no workout bonus.",
            url,
            exc,
        )
        return None

    _cache[url] = (now, answer)
    return answer
