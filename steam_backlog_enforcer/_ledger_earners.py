"""Any registered earner without a dedicated reader: its gate's signed ledger.

The workout, LeetCode and reading earners have their own modules (transports,
fallbacks, incidents). An earner registered in ``earned_time`` after them only
publishes HMAC-signed ``credit`` rows, so the shared reader is all it needs:
it joins the budget with no code here.

A *counted* gate (the Automation tutor, from ``earned_time.TUTOR_FROM``) pays
per unit -- each verified 15-minute block -- so :func:`ledger_units` reads its
unit count for the day instead of a yes/no.

Paths resolve under :data:`LEDGER_HOME` -- the unit sets ``HOME`` to the
desktop user's, and the test suite redirects this constant.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path
import time
from typing import Final

import earned_time

from steam_backlog_enforcer._leetcode_ledger import HMAC_KEY_FILE
from steam_backlog_enforcer._status_api import AnswerCache

logger = logging.getLogger(__name__)

LEDGER_HOME: Final = Path.home()

# A unit count is reused for this long, like AnswerCache's yes/no: a block
# credited now raises the budget within a minute.
_UNITS_TTL_SECONDS: Final = 60.0

_cache = AnswerCache()
_units: dict[str, tuple[float, int]] = {}


def reset_cache() -> None:
    """Drop the cached answers, forcing the next call to re-read."""
    _cache.clear()
    _units.clear()


def registry_for(day: date) -> tuple[earned_time.Earner, ...]:
    """The earners in force on ``day``.

    ``earners_for`` (earned_time >= 0.5) switches the registry on
    ``TUTOR_FROM``; an older earned_time has one static registry.
    """
    fn = getattr(earned_time, "earners_for", None)
    return tuple(earned_time.EARNERS if fn is None else fn(day))


def _no_ledger(earner: earned_time.Earner) -> None:
    logger.warning(
        "Earner %s has no ledger and no reader here; it earns nothing",
        earner.label,
    )


def ledger_units(earner: earned_time.Earner) -> int | None:
    """Today's verified units of a counted gate earner, memoised for a minute.

    Returns:
        The count (``0`` included), or ``None`` when the ledger or key could
        not be read -- never "no units". ``max_units`` is applied by
        ``earned_time.resolve``.
    """
    if earner.ledger is None:
        _no_ledger(earner)
        return None
    now = time.monotonic()
    cached = _units.get(earner.name)
    if cached is not None and now - cached[0] < _UNITS_TTL_SECONDS:
        return cached[1]
    today = datetime.now().astimezone().date()
    path = LEDGER_HOME / earner.ledger
    units = earned_time.credit_units(earner, path, HMAC_KEY_FILE, today)
    if units is None:
        return None
    _units[earner.name] = (now, units)
    return units


def ledger_answer(earner: earned_time.Earner) -> bool | None:
    """Today's answer from ``earner``'s ledger, memoised like the other earners.

    Returns:
        True or False when the ledger could be read, ``None`` when it could
        not or the earner has no ledger -- which is never "not done".
    """
    if earner.ledger is None:
        _no_ledger(earner)
        return None
    cached = _cache.fresh(earner.name)
    if cached is not None:
        return cached
    answer = earned_time.done_today(earner, LEDGER_HOME / earner.ledger, HMAC_KEY_FILE)
    if answer is None:
        return None
    return _cache.store(earner.name, answer=answer)
