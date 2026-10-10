"""What every control-socket op shares: the daemon's state and the guards.

The ops run on connection threads, the enforce loop on the main thread. The
``tick_lock`` is how they stay out of each other's way: the loop holds it for
one whole iteration and a mutating op holds it for its whole body, so an op
never sees (or clobbers) a half-finished tick. The loop only holds it while
working, never while sleeping between ticks, so an op waits at most one tick.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._actions import is_manual_pick_locked
from steam_backlog_enforcer._command_locks import (
    _MANUAL_LOCK_EXEMPT_COMMANDS,
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
)
from steam_backlog_enforcer._ctl_pending import PendingResets
from steam_backlog_enforcer._ctl_protocol import (
    BUSY,
    INVALID_PARAMS,
    LOCKED,
    WRONG_PHRASE,
    CtlError,
)
from steam_backlog_enforcer._friction import expected_phrase, phrase_matches
from steam_backlog_enforcer._total_block import is_total_block_active
from steam_backlog_enforcer.config import State

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    import threading

    from steam_backlog_enforcer.config import Config

# Longer than any single enforce iteration should take; an op that cannot get
# the lock by then reports ``busy`` instead of hanging its connection.
LOCK_WAIT_SECONDS: Final = 60.0


@dataclass
class CtlContext:
    """Shared state for the control socket's ops.

    Attributes:
        config: The daemon's loaded configuration.
        tick_lock: Held by the enforce loop for each iteration.
        restart_event: Set by the ``restart`` op; the loop exits once it sees it.
        started_at: When the daemon process started (UTC).
        supervised: Whether systemd will bring the daemon back after an exit.
        pending: Armed two-phase gaming resets.
    """

    config: Config
    tick_lock: threading.Lock
    restart_event: threading.Event
    started_at: datetime
    supervised: bool
    pending: PendingResets = field(default_factory=PendingResets)


@contextmanager
def hold_tick(ctx: CtlContext) -> Iterator[None]:
    """Hold the loop's lock for the body of a mutating op.

    Raises:
        CtlError: ``busy`` if the loop does not release the lock in time.
    """
    if not ctx.tick_lock.acquire(timeout=LOCK_WAIT_SECONDS):
        raise CtlError(BUSY, "the enforcer is mid-pass; try again in a moment")
    try:
        yield
    finally:
        ctx.tick_lock.release()


def require_phrase(command: str, typed: object, **fields: object) -> None:
    """Check the typed confirmation phrase for *command*.

    Raises:
        CtlError: ``invalid_params`` if *typed* is not text, ``wrong_phrase``
            if it differs from the one ``_friction`` demands.
    """
    if not isinstance(typed, str):
        raise CtlError(INVALID_PARAMS, "phrase must be a string")
    expected = expected_phrase(command, **fields)
    if expected is None or not phrase_matches(expected, typed):
        raise CtlError(WRONG_PHRASE, "the typed phrase does not match")


def int_arg(args: dict[str, object], name: str, low: int, high: int) -> int:
    """Read an integer argument within ``[low, high]``.

    ``bool`` is rejected explicitly: ``True`` is an ``int`` in Python and would
    otherwise pass as ``1``.

    Raises:
        CtlError: ``invalid_params`` if absent, not an integer, or out of range.
    """
    value = args.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CtlError(INVALID_PARAMS, f"{name} must be an integer")
    if not low <= value <= high:
        raise CtlError(INVALID_PARAMS, f"{name} must be between {low} and {high}")
    return value


def str_arg(args: dict[str, object], name: str) -> str:
    """Read a non-empty string argument.

    Raises:
        CtlError: ``invalid_params`` if absent or not a non-empty string.
    """
    value = args.get(name)
    if not isinstance(value, str) or not value:
        raise CtlError(INVALID_PARAMS, f"{name} must be a non-empty string")
    return value


def check_locks(command: str) -> None:
    """Refuse *command* while a lock the CLI would honour is in force.

    Mirrors ``main._shared._enforce_total_block_lock`` and
    ``_enforce_manual_pick_lock`` using the same tables, because the socket
    would otherwise be the one door those locks do not cover.

    Args:
        command: The CLI command name the op corresponds to.

    Raises:
        CtlError: ``locked`` if a total block or the manual-pick lock forbids it.
    """
    if is_total_block_active() and command not in _TOTAL_BLOCK_EXEMPT_COMMANDS:
        raise CtlError(LOCKED, "a total gaming block is active")
    if command not in _MANUAL_LOCK_EXEMPT_COMMANDS and is_manual_pick_locked(
        State.load()
    ):
        raise CtlError(LOCKED, "a manual pick lock is active")
