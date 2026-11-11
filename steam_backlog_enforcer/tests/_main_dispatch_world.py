"""Shared patch bundles for the ``main`` dispatch and ``status`` test modules."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from collections.abc import Iterator
    from unittest.mock import MagicMock

PKG = "steam_backlog_enforcer.main"
SHARED = "steam_backlog_enforcer.main._shared"
STATUS = "steam_backlog_enforcer.main.status"


@contextmanager
def cli_run(argv: list[str], *, total_block: bool) -> Iterator[None]:
    """Run ``main`` on ``argv`` with stub config/state and a fixed total block."""
    with (
        patch.object(sys, "argv", argv),
        patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
        patch(f"{PKG}.State.load", return_value=State()),
        patch(f"{SHARED}.is_total_block_active", return_value=total_block),
    ):
        yield


@contextmanager
def status_stubs(*, stub_completion: bool) -> Iterator[MagicMock]:
    """Stub the store and install lookups ``cmd_status`` makes; yield its echo.

    ``stub_completion`` also stubs ``report_completion`` to report nothing.
    """
    with ExitStack() as stack:
        stack.enter_context(patch(f"{STATUS}.is_store_blocked", return_value=False))
        stack.enter_context(patch(f"{STATUS}.get_installed_games", return_value=[]))
        if stub_completion:
            stack.enter_context(patch(f"{STATUS}.report_completion", return_value=[]))
        # cmd_status resolves _echo from its own module, not the package.
        yield stack.enter_context(patch(f"{STATUS}._echo"))
