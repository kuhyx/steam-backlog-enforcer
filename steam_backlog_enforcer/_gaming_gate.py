"""The one switch that says whether a gaming budget exists on a gaming day.

kuhy removed the daily gaming (and leisure) budget on 2026-11-16: from then on
games may run until shutdown, and shutdown time (screen-locker) is the only
carrot. ``earned_time.gaming_enforced`` owns the date; every place that
*applies* a budget (kill, block, warning, leisure kill, leisure billing) asks
this wrapper, and every place that *reports* one prints "unlimited" instead of
a number. Numbers stay resolvable for history and the shadow view.

**Fail open, loudly.** If the switch cannot be read (an old ``earned_time``
without the function, a day key that is no date) the answer is "unlimited", not
"enforce whatever the registry falls back to": from the switch the fallback is
the 5 h base, a *lower* budget than kuhy lived under, and a crash here would
take the root daemon down. The failure is logged at ERROR, once per distinct
cause, because this runs every 3 s tick.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import Final

import earned_time

logger = logging.getLogger(__name__)

# Failures already logged, so a permanent fault is one journal line, not 28k a day.
_logged: Final[set[str]] = set()


def reset_logged() -> None:
    """Forget the failures already logged (tests, and a daemon reload)."""
    _logged.clear()


def gaming_enforced_on(day_key: str) -> bool:
    """Whether a gaming budget is enforced on the gaming day *day_key*.

    Args:
        day_key: The 06:00-shifted gaming day, ``YYYY-MM-DD``.

    Returns:
        ``False`` from ``earned_time.GAMING_UNLIMITED_FROM`` (no budget), and
        ``False`` when the switch cannot be read (fail open, logged).
    """
    try:
        return bool(earned_time.gaming_enforced(date.fromisoformat(day_key)))
    except (AttributeError, TypeError, ValueError) as exc:
        cause = f"{type(exc).__name__}: {exc}"
        if cause not in _logged:
            _logged.add(cause)
            logger.exception(
                "Cannot read the gaming-budget switch for %r (%s); treating the "
                "day as unlimited so no lower budget is enforced.",
                day_key,
                cause,
            )
        return False
