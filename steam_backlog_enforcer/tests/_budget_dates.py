"""Pin the day ``resolve_budget`` believes it is, around the 5h -> 4h base cut.

``earned_time`` takes the reading hour off the floor from its penalty start
on: ``READING.penalty_from``, delayed by maturity (0.6.0) to the day after
``confirmed_on`` when no credit is on record. A budget test that reads the
real clock would change its answer on that day, so every such test pins the
date on one side of the cut.
The module asks ``datetime.now().astimezone().date()``, so that chain is what
the pin answers.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import earned_time

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from datetime import date

# With no ledger on record (the suite's empty LEDGER_HOME) the cut waits for
# the day after READING.confirmed_on: fail closed, never before penalty_from.
_CUT = earned_time.penalty_start(earned_time.READING, None)
assert _CUT is not None, "earned_time.READING lost its penalty_from date"

AFTER_CUT = _CUT
BEFORE_CUT = _CUT - timedelta(days=1)


def pin_today(day: date) -> AbstractContextManager[object]:
    """Make ``_budget_resolve`` see ``day`` as today.

    Args:
        day: The local date the module's clock should report.

    Returns:
        A patch context manager replacing the module's ``datetime`` binding.
    """
    clock = MagicMock()
    clock.now.return_value.astimezone.return_value.date.return_value = day
    return patch("steam_backlog_enforcer._budget_resolve.datetime", clock)
