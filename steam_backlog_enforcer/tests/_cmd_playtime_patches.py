"""Shared patches for the ``_cmd_playtime`` CLI handler tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._cmd_playtime"


@dataclass(frozen=True)
class CliMocks:
    """The echo and mount-release mocks a handler test asserts on."""

    echo: MagicMock
    release: MagicMock


def echoed(mock_echo: MagicMock) -> str:
    """Join everything the handler echoed into one searchable string."""
    return " ".join(str(c) for c in mock_echo.call_args_list)


@contextmanager
def cli_as(euid: int | None) -> Iterator[CliMocks]:
    """Run a handler with echo and release_block mocked, as ``euid`` if given."""
    with ExitStack() as stack:
        if euid is not None:
            stack.enter_context(patch(f"{PKG}.os.geteuid", return_value=euid))
        echo = stack.enter_context(patch(f"{PKG}._echo"))
        release = stack.enter_context(patch(f"{PKG}.release_block"))
        yield CliMocks(echo=echo, release=release)
