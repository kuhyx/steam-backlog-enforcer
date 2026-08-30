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

**Known staleness, accepted.** leetcode-guard only writes credits from its lock
window's poll loop, so a *voluntary extra* solve made after the day is settled
never reaches the ledger and earns nothing. The bonus tracks what the day's
gate run recorded.

Reading and verifying the ledger itself lives in
:mod:`steam_backlog_enforcer._leetcode_ledger`; this module owns the two
transports, the memo, and the incident on total failure.
"""

from __future__ import annotations

import http.client
import json
import logging
from pathlib import Path
import time as time_module
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from steam_backlog_enforcer._bonus_incident import report_leetcode_incident
from steam_backlog_enforcer._leetcode_ledger import read_ledger_solved_today

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS: Final = 2.0
_CACHE_TTL_SECONDS: Final = 60.0

# Only successes are cached, matching _workout_budget: a failure is retried on
# the very next tick, so a restarted service takes effect immediately instead
# of costing an hour for another minute.
_cache: dict[str, tuple[float, bool]] = {}


def reset_cache() -> None:
    """Drop the cached answer, forcing the next call to re-ask."""
    _cache.clear()


def _fetch_leetcode_today(url: str) -> bool:
    """Read ``leetcode.solved_today`` from leetcode-guard's status API.

    Args:
        url: The status endpoint, e.g. ``http://127.0.0.1:8771/api/status``.

    Returns:
        Whether an accepted submission is recorded for today.

    Raises:
        OSError: The endpoint could not be reached.
        ValueError: The response was not usable JSON, not a 200, or said it
            could not check.
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
    block = json.loads(body)["leetcode"]
    if not block["checked"]:
        # The server answered, but said it could not look. That is not a "no".
        msg = f"leetcode-guard could not check: {block.get('reason', 'no reason')}"
        raise ValueError(msg)
    return bool(block["solved_today"])


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
    now = time_module.monotonic()
    cached = _cache.get(url)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    path = Path(config.leetcode_ledger_path).expanduser()
    answer = read_ledger_solved_today(path)
    if answer is None:
        answer = _fallback_to_endpoint(url, path)
        if answer is None:
            return None

    _cache[url] = (now, answer)
    return answer


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
