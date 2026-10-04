"""Autouse isolation of the reading earner from the host's book-guard ledger.

``resolve_budget`` asks :mod:`steam_backlog_enforcer._reading_bonus` whether a
reading session was credited today, which reads the real integrity key and the
real ``~/.local/share/book_guard/ledger.json``. Unstubbed, every test that
resolves a budget would answer differently depending on whether the machine's
owner has read a book today -- the same morning/evening flake the workout stub
exists to prevent.

Two layers: the consumer binding answers a plain "no reading" unless a test
overrides it, and the module's key path points at a file that does not exist,
so even a direct call without the test's own key fixture can never reach the
real ledger. The module memo is cleared around every test.

Any other registered earner (:mod:`steam_backlog_enforcer._ledger_earners`)
gets the same two layers: its memo is cleared and its key binding is hidden,
while ``conftest`` redirects its ``LEDGER_HOME``.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ledger_earners, _reading_bonus

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_reading(tmp_path: Path) -> Iterator[None]:
    """Answer "no reading" and hide the real signing key for one test.

    Args:
        tmp_path: pytest's temporary directory.

    Yields:
        None, with the reading earner isolated for the whole test.
    """
    _reading_bonus.reset_cache()
    _ledger_earners.reset_cache()
    with (
        patch(
            "steam_backlog_enforcer._budget_resolve.read_today",
            return_value=False,
        ),
        patch.object(_reading_bonus, "HMAC_KEY_FILE", tmp_path / "no-reading-hmac.key"),
        patch.object(_ledger_earners, "HMAC_KEY_FILE", tmp_path / "no-ledger-hmac.key"),
    ):
        yield
    _reading_bonus.reset_cache()
    _ledger_earners.reset_cache()
