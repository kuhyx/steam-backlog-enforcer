"""Any registered earner without a dedicated reader: its gate's signed ledger.

The workout, LeetCode and reading earners have their own modules (transports,
fallbacks, incidents). An earner registered in ``earned_time`` after them only
publishes HMAC-signed ``credit`` rows, so the shared reader is all it needs:
it joins the budget with no code here.

Paths resolve under :data:`LEDGER_HOME` -- the unit sets ``HOME`` to the
desktop user's, and the test suite redirects this constant.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import earned_time

from steam_backlog_enforcer._leetcode_ledger import HMAC_KEY_FILE
from steam_backlog_enforcer._status_api import AnswerCache

logger = logging.getLogger(__name__)

LEDGER_HOME: Final = Path.home()

_cache = AnswerCache()


def reset_cache() -> None:
    """Drop the cached answers, forcing the next call to re-read."""
    _cache.clear()


def ledger_answer(earner: earned_time.Earner) -> bool | None:
    """Today's answer from ``earner``'s ledger, memoised like the other earners.

    Returns:
        True or False when the ledger could be read, ``None`` when it could
        not or the earner has no ledger -- which is never "not done".
    """
    if earner.ledger is None:
        logger.warning(
            "Earner %s has no ledger and no reader here; it earns nothing",
            earner.label,
        )
        return None
    cached = _cache.fresh(earner.name)
    if cached is not None:
        return cached
    answer = earned_time.done_today(earner, LEDGER_HOME / earner.ledger, HMAC_KEY_FILE)
    if answer is None:
        return None
    return _cache.store(earner.name, answer=answer)
