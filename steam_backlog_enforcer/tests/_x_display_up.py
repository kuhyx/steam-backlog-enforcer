"""Autouse: the host's X display never decides a Steam-launch test.

``ensure_steam_debug_port`` refuses to launch when the X socket for ``DISPLAY``
(default ``:0``) is missing. That is a fact about the machine - a headless CI
box has none - so every test that reaches a launch would pass or fail by host.
Pinned "up" here; ``test_desktop_display`` tests the check itself and
``test_steam_launch_failfast`` patches it down for the refusal cases.

Split out of ``conftest.py`` like ``_no_systemd_run``; ``conftest`` imports the
fixture by name to register it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _x_display_up() -> Iterator[None]:
    """Report the X display as up to ``_steam_launch`` for one test."""
    with patch(
        "steam_backlog_enforcer._steam_launch.x_display_error", return_value=None
    ):
        yield
