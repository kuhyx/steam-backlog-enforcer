"""Autouse redirect for the bonus-incident log.

``report_leetcode_incident`` appends to ``leetcode_bonus_incidents.log`` at the
repo root, which is a real artifact the user reads to find out why an hour went
missing. Left unpatched, any test that drives the fail-closed path writes into
it -- and because the file is gitignored, nothing would ever fail to warn you.
That happened: the first run of ``test_budget_resolve.py`` put two fabricated
incidents into the live file.

Redirected here rather than in each test for the same reason
``_isolate_filesystem`` exists: enumerating the tests that need it is the
version of this that goes wrong the next time someone adds one.

Split into its own module to keep ``conftest.py`` inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_incidents(tmp_path: Path) -> Iterator[None]:
    """Point the incident log at a per-test file.

    Args:
        tmp_path: pytest's temporary directory.

    Yields:
        None, with the log redirected and the reported-incident memo cleared so
        one test's rate limit cannot mute the next.
    """
    from steam_backlog_enforcer import _bonus_incident

    _bonus_incident.reset_reported()
    with patch.object(
        _bonus_incident, "INCIDENT_LOG", tmp_path / "leetcode_bonus_incidents.log"
    ):
        yield
    _bonus_incident.reset_reported()
