"""Pin the day ``resolve_budget`` believes it is, around the 5h -> 4h base cut.

``_budget_resolve.base_for`` adds an hour to the floor before
``READING_BASE_FROM``. A budget test that reads the real clock would change its
answer on 2026-10-01, so every such test pins the date on one side of the cut.
The module asks ``datetime.now().astimezone().date()``, so that chain is what
the pin answers.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._budget_resolve import READING_BASE_FROM

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from datetime import date

AFTER_CUT = READING_BASE_FROM
BEFORE_CUT = READING_BASE_FROM - timedelta(days=1)


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
