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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._status_api import AnswerCache, get_status

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_cache = AnswerCache()


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
    return bool(get_status(url)["gaming"]["workout_today"])


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
    cached = _cache.fresh(url)
    if cached is not None:
        return cached

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

    return _cache.store(url, answer=answer)
