"""Today's gaming budget, decided by whether a workout was logged.

The screen locker owns the question "did I work out today"; this module asks it
and turns the answer into seconds. Two values: the *earned* budget
(``daily_gaming_seconds``) when today has a counted workout, and the *unearned*
floor (``unearned_gaming_seconds``) when it does not.

Three properties this is built around:

**Fail closed.** Any failure to get an answer -- status server down, timeout,
malformed body, non-200 -- yields the *unearned* floor, logged at warning with
the concrete reason. Failing open would let the whole coupling be defeated by
stopping one user service, and a silent 8h would be indistinguishable from an
earned one.

**Rising, in normal use -- but not guaranteed.** ``workout_today`` only ever
goes false->true within a day, so in the ordinary case the budget starts at the
floor and rises when a workout lands. That is a property of the *input*, not
something enforced here: nothing persists a per-day high-water mark, so
anything that changes the resolved answer mid-day -- editing the config, or
deploying this coupling onto a day already in progress -- lowers the budget
immediately and re-prices time already spent. Seconds already accrued are then
measured against the new, smaller budget, and the cutoff fires on the next tick
with no warning first, because ``warned_seconds`` records thresholds by
seconds *remaining* and remaining has already gone negative.

That was a deliberate call (2026-08-29): the alternative is a persisted
``granted_budget_seconds`` on ``PlaytimeState`` taking ``max(resolved,
granted)``. If a mid-day drop ever bites, that is the fix -- not a nudge to
these numbers.

**One seam.** :func:`resolve_budget_seconds` is called from ``rules_for``, so
the enforcing daemon and the read-only HTTP/MCP views resolve the same number.
The daemon holds its ``Config`` for the process lifetime while ``_budget_view``
reloads it per request, so anything resolved at only one of those two sites
would let the UI report a budget the daemon was not enforcing.

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

_SECONDS_PER_HOUR: Final = 3600.0

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
            "applying the unearned gaming budget. Check "
            "`systemctl --user status screen-locker-web`.",
            url,
            exc,
        )
        return None
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "Screen-locker status API at %s returned something unusable (%s) — "
            "applying the unearned gaming budget.",
            url,
            exc,
        )
        return None

    _cache[url] = (now, answer)
    return answer


def resolve_budget_seconds(config: Config) -> float:
    """Return today's gaming budget in seconds.

    Args:
        config: Loaded user configuration.

    Returns:
        ``daily_gaming_seconds`` when a counted workout is logged today, and
        ``unearned_gaming_seconds`` otherwise -- including whenever the answer
        could not be obtained at all.
    """
    earned = float(config.daily_gaming_seconds)
    unearned = float(config.unearned_gaming_seconds)
    if unearned > earned:
        # A floor above the ceiling would silently *reward* skipping. Refuse
        # the config rather than enforce it backwards.
        logger.error(
            "unearned_gaming_seconds (%.0f) exceeds daily_gaming_seconds "
            "(%.0f); clamping to the earned budget so skipping a workout can "
            "never buy more time than doing one.",
            unearned,
            earned,
        )
        unearned = earned

    answer = workout_logged_today(config)
    if answer is None:
        return unearned
    if answer:
        return earned
    logger.info(
        "No counted workout logged today — gaming budget is %.1fh not %.1fh.",
        unearned / _SECONDS_PER_HOUR,
        earned / _SECONDS_PER_HOUR,
    )
    return unearned
