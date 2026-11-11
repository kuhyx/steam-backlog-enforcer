"""Shared reset: no approved uninstall exceptions for the zero-achievement tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Iterator


def no_approved_exceptions() -> Iterator[None]:
    """Report no approved exceptions, so only the zero-achievement rule protects.

    A generator for ``yield from`` inside a module's autouse fixture.
    """
    with patch(
        "steam_backlog_enforcer.game_uninstall.get_approved_exception_ids",
        return_value=frozenset(),
    ):
        yield
