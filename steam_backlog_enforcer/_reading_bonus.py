"""Whether a paper-book reading session was credited today, worth an hour.

book-guard (``~/src/book-guard``) publishes reading through its signed ledger,
the same shape as leetcode-guard's, and screen-locker reads the same fact for a
shutdown hour. Shaped like :mod:`steam_backlog_enforcer._leetcode_bonus` where
it matters:

**Fail closed.** A missing ledger, bad JSON or an unreadable key yields
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

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._leetcode_ledger import (
    HMAC_KEY_FILE,
    _today_window,
    _verified,
)
from steam_backlog_enforcer._status_api import AnswerCache

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_cache = AnswerCache()
_CACHE_KEY: Final = "book-guard-ledger"


def reset_cache() -> None:
    """Drop the cached answer, forcing the next call to re-read."""
    _cache.clear()


def _read_today(entry: dict[str, Any], *, window: tuple[float, float]) -> bool:
    """Whether this verified credit earns the hour and was read today."""
    detail = entry.get("detail")
    if not isinstance(detail, dict) or detail.get("bonus") != "1":
        return False
    try:
        ended = float(str(detail.get("ended_at")))
    except ValueError:
        logger.warning(
            "reading credit %r has no usable ended_at", entry.get("entry_id")
        )
        return False
    start, end = window
    return start <= ended <= end


def _rows(path: Path) -> list[Any] | None:
    """The ledger's entry array, or ``None`` when it cannot be read."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # No ledger = book-guard has never registered a book: an honest "no
        # reading", not a fault -- and not worth a warning every 3 seconds.
        return []
    except OSError as exc:
        logger.warning("Cannot read the book-guard ledger at %s (%s)", path, exc)
        return None
    except ValueError as exc:
        logger.warning("book-guard ledger at %s is not valid JSON (%s)", path, exc)
        return None
    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        logger.warning("book-guard ledger at %s has no entries array", path)
        return None
    return rows


def read_ledger_read_today(path: Path) -> bool | None:
    """Whether a verified, bonus-eligible reading session ended today.

    Returns:
        True or False when the ledger could be read, ``None`` when it could
        not -- which is never "did not read".
    """
    try:
        key = HMAC_KEY_FILE.read_bytes().strip()
    except OSError as exc:
        logger.warning("Cannot read the integrity key at %s (%s)", HMAC_KEY_FILE, exc)
        return None
    if not key:
        logger.warning("Integrity key at %s is empty", HMAC_KEY_FILE)
        return None
    rows = _rows(path)
    if rows is None:
        return None
    window = _today_window()
    return any(
        isinstance(row, dict)
        and row.get("kind") == "credit"
        and _verified(row, key)
        and _read_today(row, window=window)
        for row in rows
    )


def read_today(config: Config) -> bool | None:
    """Today's reading answer, memoised like the other earners."""
    cached = _cache.fresh(_CACHE_KEY)
    if cached is not None:
        return cached
    answer = read_ledger_read_today(Path(config.book_ledger_path).expanduser())
    if answer is None:
        return None
    return _cache.store(_CACHE_KEY, answer=answer)
