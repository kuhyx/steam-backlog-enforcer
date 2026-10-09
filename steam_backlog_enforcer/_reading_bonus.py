"""Whether a paper-book reading session was credited today, worth an hour.

book-guard (``~/src/book-guard``) publishes reading through its signed ledger,
the same shape as leetcode-guard's, and screen-locker reads the same fact for a
shutdown hour. Shaped like :mod:`steam_backlog_enforcer._leetcode_bonus` where
it matters:

**Fail closed.** Bad JSON, a missing entries array or an unreadable key yields
``None`` -- no bonus, logged at warning. Failing open would let the coupling be
defeated by deleting a file.

**Independent.** Read separately and summed by ``resolve_budget``; nothing here
can move the workout or LeetCode terms.

**One transport.** book-guard has no status server, so there is no fallback;
and no incident either -- until the first book is registered the ledger simply
does not exist, and that is not worth waking anyone about.

The contract (book-guard's ``_quiz.record_verdict``): only ``credit`` rows with
``detail["bonus"] == "1"`` count -- a passed quiz on a 20+ page, 20+ minute
session -- dated by ``detail["ended_at"]``, when the reading happened.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

import earned_time

from steam_backlog_enforcer._leetcode_ledger import HMAC_KEY_FILE
from steam_backlog_enforcer._status_api import AnswerCache, file_stamp

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_cache = AnswerCache()
_CACHE_KEY: Final = "book-guard-ledger"


def reset_cache() -> None:
    """Drop the cached answer, forcing the next call to re-read."""
    _cache.clear()


def read_ledger_read_today(path: Path) -> bool | None:
    """Whether a verified, bonus-eligible reading session ended today.

    Returns:
        True or False when the ledger could be read, ``None`` when it could
        not -- which is never "did not read". A ledger that does not exist
        yet (no book registered) is an honest, silent "no".
    """
    return earned_time.done_today(earned_time.READING, path, HMAC_KEY_FILE)


def read_today(config: Config) -> bool | None:
    """Today's reading answer, memoised like the other earners."""
    path = Path(config.book_ledger_path).expanduser()
    # Stat before reading, so a credit landing mid-read is re-read next tick.
    stamp = file_stamp(path)
    cached = _cache.fresh(_CACHE_KEY, stamp=stamp)
    if cached is not None:
        return cached
    answer = read_ledger_read_today(path)
    if answer is None:
        return None
    return _cache.store(_CACHE_KEY, answer=answer, stamp=stamp)
