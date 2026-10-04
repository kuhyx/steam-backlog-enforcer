"""Autouse: the host's ``systemd-run`` never leaks into launch argv.

``spawn_detached`` wraps root launches in a transient scope when
``systemd-run`` is on PATH. That is a fact about the machine, so every test
that asserts a launch command would pass or fail by host. Pinned absent here;
``test_steam_process_scope`` patches it back in to test the wrapper itself.

Split out of ``conftest.py``, whose isolation ``with`` is already at Python's
static nesting limit; ``conftest`` imports the fixture by name to register it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _no_systemd_run() -> Iterator[None]:
    """Report ``systemd-run`` missing to ``_steam_process`` for one test."""
    with patch(
        "steam_backlog_enforcer._steam_process.shutil",
        **{"which.return_value": None},
    ):
        yield
