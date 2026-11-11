"""Shared patch block that runs do_enforce for exactly one loop iteration.

Several do_enforce tests need the same scaffolding: a fixed reloaded state,
an iteration that raises KeyboardInterrupt to end the loop, and no real file
wake. Keeping it here means each test only spells out what it is about.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import State

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._enforce_loop"


@dataclass(frozen=True)
class LoopMocks:
    """Mocks a single-iteration do_enforce run exposes to assertions."""

    echo: MagicMock
    iteration: MagicMock


@contextmanager
def one_iteration(state: State) -> Iterator[LoopMocks]:
    """Patch do_enforce so it reloads ``state`` and stops after one iteration."""
    with (
        patch(f"{PKG}._echo") as echo,
        patch.object(State, "load", return_value=state),
        patch(
            f"{PKG}._enforce_loop_iteration",
            side_effect=KeyboardInterrupt,
        ) as iteration,
        patch(f"{PKG}.open_file_wake"),
    ):
        yield LoopMocks(echo=echo, iteration=iteration)
