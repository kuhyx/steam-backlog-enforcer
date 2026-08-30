"""Reading leetcode-guard's ledger for today's accepted submissions.

Credits are verified against the shared HMAC key, reproducing gatelock's
canonicalisation in eight lines rather than importing it: gatelock is installed
into the user's site-packages and this daemon runs as root, so the import is
not available. ``test_leetcode_ledger.py`` pins the canonicalisation to a fixed
vector so the duplication cannot drift silently.

Only ``credit`` entries count. A ``seen`` entry is first-run seeding worth
zero, and a ``charge`` proves only that the day was *settled* -- which also
happens from banked credit, from the escape hatch and from a classified
outage, so it can never stand in for a solve.

The solve time is ``detail["submitted_at"]``, LeetCode's own timestamp, not the
entry's ``day``: ``day`` is stamped by the *harvesting* run, so a problem
solved at 23:50 and harvested the next morning carries the next day's key.

Every unreadable state returns ``None``, never ``False``. "Cannot check" is not
"not solved", and only one of the two is worth waking the user about.
"""

from __future__ import annotations

from datetime import datetime, time
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# The key every locker signs its state with. Root-owned, world-readable.
HMAC_KEY_FILE: Final = Path("/etc/workout-locker/hmac.key")

_CREDIT: Final = "credit"


def _verified(entry: dict[str, Any], key: bytes) -> bool:
    """Whether a ledger entry's HMAC signature is genuine.

    Args:
        entry: The full entry, including its ``hmac`` field.
        key: The shared signing key.

    Returns:
        Whether the signature matches. An unverified credit is worth an hour of
        gaming time, so a forged one must not count.
    """
    stored = entry.get("hmac")
    if not isinstance(stored, str):
        return False
    body = {k: v for k, v in entry.items() if k != "hmac"}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(stored, expected)


def _landed_today(entry: dict[str, Any], *, window: tuple[float, float]) -> bool:
    """Whether this credit's accepted submission happened today, locally.

    Args:
        entry: One verified credit entry.
        window: Local midnight and now, as unix seconds.

    Returns:
        Whether the solve falls inside today. ``detail.submitted_at`` is
        LeetCode's own timestamp; ``day`` is the *harvest* day and runs late, so
        it is only a fallback -- it can miss a late solve, never invent one.
    """
    detail = entry.get("detail")
    raw = detail.get("submitted_at") if isinstance(detail, dict) else None
    if raw is not None:
        try:
            stamp = float(str(raw))
        except ValueError:
            logger.warning(
                "LeetCode credit %r has an unparsable submitted_at (%r); "
                "falling back to its day key",
                entry.get("entry_id"),
                raw,
            )
        else:
            start, end = window
            return start <= stamp <= end
    today = datetime.now().astimezone().date().isoformat()
    return entry.get("day") == today


def _today_window() -> tuple[float, float]:
    """Local midnight and now, as unix seconds.

    Returns:
        The inclusive window a solve must fall in to count for today.
    """
    moment = datetime.now().astimezone()
    midnight = datetime.combine(moment.date(), time.min, moment.tzinfo)
    return midnight.timestamp(), moment.timestamp()


def read_ledger_solved_today(path: Path) -> bool | None:
    """Read leetcode-guard's ledger and count today's verified credits.

    Args:
        path: The ledger file.

    Returns:
        True or False when the ledger could be read and verified, ``None`` when
        it could not -- which is never "nothing was solved".
    """
    try:
        key = HMAC_KEY_FILE.read_bytes().strip()
    except OSError as exc:
        logger.warning("Cannot read the integrity key at %s (%s)", HMAC_KEY_FILE, exc)
        return None
    if not key:
        logger.warning("Integrity key at %s is empty", HMAC_KEY_FILE)
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Cannot read the LeetCode ledger at %s (%s)", path, exc)
        return None
    except ValueError as exc:
        logger.warning("LeetCode ledger at %s is not valid JSON (%s)", path, exc)
        return None

    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        logger.warning("LeetCode ledger at %s has no entries array", path)
        return None

    window = _today_window()
    return any(
        isinstance(row, dict)
        and row.get("kind") == _CREDIT
        and _verified(row, key)
        and _landed_today(row, window=window)
        for row in rows
    )
