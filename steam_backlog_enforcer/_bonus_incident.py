"""Telling the user, immediately, that a budget bonus could not be checked.

An honest "you have not solved anything yet today" is not an incident -- it is
the gate working. This module fires only when the answer could not be obtained
at all, which silently costs an hour and looks identical to not having earned
it.

Three channels, because each covers the others' blind spot:

1. A desktop notification, which reaches the user in seconds.
2. A warning in the journal, which survives a missed notification.
3. A line in ``leetcode_bonus_incidents.log`` at the repo root, which survives
   a journal rotation and sits where the user does their work.

The log file is deliberately a ``.log``: ``.gitignore`` already covers that
extension, so an incident never becomes an uncommitted change, and the
``md-naming`` pre-commit hook (which matches markdown only) never sees it. It
is written by a root daemon into a user-owned checkout, so removing it needs
``sudo``.

Rate-limited to one report per distinct reason per day. The enforcer ticks
frequently, and without that a single stopped service would produce a
notification storm and an unbounded file.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Final

from steam_backlog_enforcer._playtime_notify import notify_desktop_user

logger = logging.getLogger(__name__)

# Resolved from __file__, never the working directory: the shipped unit template
# still names /opt/steam-backlog-enforcer, and only the copy install.sh rewrites
# points at the checkout.
INCIDENT_LOG: Final = (
    Path(__file__).resolve().parents[1] / "leetcode_bonus_incidents.log"
)

_TITLE: Final = "Gaming budget: LeetCode bonus not applied"

# reason -> the local day it was last reported on.
_reported: dict[str, str] = {}


def reset_reported() -> None:
    """Forget which incidents have been reported, so the next one fires."""
    _reported.clear()


def report_leetcode_incident(reason: str, *, fix: str) -> None:
    """Report that the LeetCode bonus could not be checked.

    Args:
        reason: What went wrong, in the user's terms.
        fix: The command that would diagnose or repair it.
    """
    today = datetime.now().astimezone().date().isoformat()
    if _reported.get(reason) == today:
        # Already told them today. Still worth a debug line so the journal
        # shows the condition persisting rather than appearing to clear.
        logger.debug("LeetCode bonus still unavailable: %s", reason)
        return
    _reported[reason] = today

    body = f"{reason}. Budget is 1h lower until this is fixed. Try: {fix}"
    logger.warning("LeetCode bonus not applied - %s. Try: %s", reason, fix)
    notify_desktop_user(_TITLE, body)
    _append_incident(f"{datetime.now().astimezone().isoformat()} {body}")


def _append_incident(line: str) -> None:
    """Append one line to the incident log, or explain why it could not.

    Args:
        line: The already-formatted incident line.
    """
    try:
        with INCIDENT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
    except OSError as exc:
        # The notification and the journal line have already gone out, so this
        # is a degraded report rather than a lost one -- but say so.
        logger.warning("Could not append to %s (%s)", INCIDENT_LOG, exc)
