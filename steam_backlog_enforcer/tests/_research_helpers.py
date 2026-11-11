"""Shared fixtures-as-functions for the research-window tests.

One total block (6 days, as the live one) and one record inside it, so each
test only spells out the field it is about.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from steam_backlog_enforcer._research_record import ResearchRecord
from steam_backlog_enforcer.tests._total_block_paths import write_lock

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import Paths

LOCK_START = 1_794_233_872.0
LOCK_END = LOCK_START + 6 * 86400
NOW = LOCK_START + 2 * 86400
HOUR = 3600.0


def lock(paths: Paths) -> None:
    """Write the 6-day total-block lock the records below belong to."""
    write_lock(paths, LOCK_START, LOCK_END, days=6)


def make_record(**changes: float | bool) -> ResearchRecord:
    """A valid record opened a minute before NOW and open for one more hour."""
    base = ResearchRecord(
        lock_started_at=LOCK_START,
        lock_until=LOCK_END,
        opened_at=NOW - 60,
        until=NOW + HOUR,
    )
    return replace(base, **changes)
