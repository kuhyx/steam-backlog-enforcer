"""Whether a LeetCode problem was solved today, worth an hour of budget.

Deliberately shaped like :mod:`steam_backlog_enforcer._workout_budget`, because
the two earners must behave identically where it matters:

**Fail closed.** Any failure to get an answer -- missing ledger, unparsable
JSON, unreadable integrity key, dead fallback endpoint -- yields *no bonus*,
logged at warning and reported through :mod:`_bonus_incident`. Failing open
would let the coupling be defeated by deleting a file.

**Independent of the workout term.** Nothing here can raise or lower the
workout bonus. The two answers are read separately and summed by
``resolve_budget``, which is what "must not interfere with the workout" means
in code.

**Two transports, one fact.** The ledger is read directly first: it answers
even when leetcode-guard is not running, which is most of the day. The loopback
endpoint is the fallback, and covers a renamed or misconfigured ledger path
rather than a permission problem -- this daemon runs as root, so it already has
strictly more access than the endpoint does. Both carry the same staleness (see
below); the fallback is not a fresher source.

**Staleness.** leetcode-guard's one-minute harvester credits a solve within
about a minute, even with no lock window up.

**What earns (``earned_time`` >= 0.18.0, kuhy 2026-10-24).** Only today's
signed ``leetcode`` charge -- the day paid in full -- earns the hour; one solve
of a multi-credit day does not. The exception is a day the gate stands down
(free or sick): there one verified solve earns. ``gate_off`` is read live from
leetcode-guard's endpoint, and an unreadable answer means the gate is on.

Reading and verifying the ledger itself lives in
:mod:`steam_backlog_enforcer._leetcode_ledger`; this module owns the two
transports, the memo, and the incident on total failure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from steam_backlog_enforcer._bonus_incident import report_leetcode_incident
from steam_backlog_enforcer._leetcode_ledger import read_ledger_solved_today
from steam_backlog_enforcer._status_api import AnswerCache, file_stamp, get_status

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_cache = AnswerCache()


def reset_cache() -> None:
    """Drop the cached answer, forcing the next call to re-ask."""
    _cache.clear()


def _fetch_leetcode_today(url: str) -> bool:
    """Read ``leetcode.solved_today`` from leetcode-guard's status API.

    Args:
        url: The status endpoint, e.g. ``http://127.0.0.1:8771/api/status``.

    Returns:
        Whether today was paid in full from verified credits, or -- on a day
        the gate stands down -- whether a submission was accepted.

    Raises:
        OSError: The endpoint could not be reached.
        ValueError: The response was not usable JSON, not a 200, or said it
            could not check.
        KeyError: The payload lacked the expected fields.
    """
    block = get_status(url)["leetcode"]
    if not block["checked"]:
        # The server answered, but said it could not look. That is not a "no".
        msg = f"leetcode-guard could not check: {block.get('reason', 'no reason')}"
        raise ValueError(msg)
    # One solve of a five-credit day is not a done day (kuhy, 2026-10-24):
    # only the charge that pays the price earns, unless the gate stands down
    # today. An older server has neither field, which reads as "no hour".
    if block.get("gate_off") is True:
        return bool(block["solved_today"])
    return bool(block.get("settled_by_credit"))


def gate_off_now(url: str) -> bool:
    """Whether leetcode-guard says its gate stands down today (free or sick).

    This root daemon has neither the free-day nor the sick-day pool, so it
    asks the endpoint, live, every time the memo misses. Anything but an
    explicit ``true`` -- an unreachable server, an older one without the
    field -- means the gate is on: one solve then earns nothing.

    Args:
        url: The status endpoint.

    Returns:
        The published ``leetcode.gate_off``, or False when it cannot be read.
    """
    try:
        return get_status(url)["leetcode"].get("gate_off") is True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning(
            "Could not ask %s whether the LeetCode gate is off (%s); "
            "treating it as on, so only a fully paid day earns",
            url,
            exc,
        )
        return False


def leetcode_solved_today(config: Config) -> bool | None:
    """Whether an accepted LeetCode submission is recorded for today.

    Args:
        config: Loaded user configuration, for the ledger path and the URL.

    Returns:
        True or False when either transport answered, ``None`` when neither
        could. ``None`` is deliberately distinct from ``False`` so the caller
        can log which one happened -- and so an unreadable ledger raises an
        incident while an honest "not solved yet" does not.
    """
    url = config.leetcode_status_url
    path = Path(config.leetcode_ledger_path).expanduser()
    # A new credit row rewrites the ledger; its stamp drops the memo at once.
    stamp = file_stamp(path)
    cached = _cache.fresh(url, stamp=stamp)
    if cached is not None:
        return cached

    answer = read_ledger_solved_today(path, gate_off=gate_off_now(url))
    if answer is None:
        answer = _fallback_to_endpoint(url, path)
        if answer is None:
            return None

    return _cache.store(url, answer=answer, stamp=stamp)


def _fallback_to_endpoint(url: str, path: Path) -> bool | None:
    """Ask leetcode-guard's status API after the ledger read failed.

    Args:
        url: The status endpoint.
        path: The ledger that could not be read, for the incident message.

    Returns:
        The answer, or ``None`` when this transport failed too.
    """
    try:
        answer = _fetch_leetcode_today(url)
    except OSError as exc:
        report_leetcode_incident(
            f"could not read the ledger at {path}, and could not reach "
            f"leetcode-guard's status API at {url} ({exc})",
            fix="systemctl --user status leetcode-guard-web",
        )
        return None
    except (ValueError, KeyError, TypeError) as exc:
        report_leetcode_incident(
            f"could not read the ledger at {path}, and leetcode-guard's status "
            f"API at {url} returned something unusable ({exc})",
            fix="journalctl --user -u leetcode-guard-web -n 50",
        )
        return None
    logger.warning(
        "LeetCode ledger at %s was unreadable; used the status API instead", path
    )
    return answer
