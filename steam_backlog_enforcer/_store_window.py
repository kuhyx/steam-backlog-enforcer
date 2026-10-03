"""A bounded window in which the Steam store stays unblocked.

``run.sh unblock`` used to comment the store lines out of ``/etc/hosts`` once
and walk away. Anything that reinstalls the hosts file -- the hourly
``periodic-system-maintenance`` job, any other ``hosts-blocker/install.sh`` run
-- put the block straight back, sometimes within seconds, so a purchase could
not be finished. The window moves that job into the daemon: until the
deadline it re-applies the unblock whenever the block reappears, and after it
re-blocks exactly once.

Only the CLI writes the deadline (``State.store_unblocked_until``). The daemon
runs as root and never saves state for this: a root-written ``state.json``
would lock the unprivileged CLI out of its own file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer.store_blocker import (
    block_store,
    hosts_blocks_store,
    unblock_store,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_MINUTES = 15
MAX_WINDOW_MINUTES = 30

# Deadlines this daemon process has already re-blocked for. In memory on
# purpose (see module docstring); a restarted daemon re-blocks at startup anyway.
_reblocked_for: set[str] = set()


def open_store_window(state: State, minutes: int) -> datetime:
    """Record a store window ending *minutes* from now and unblock at once.

    Args:
        state: Enforcer state; saved with the new deadline.
        minutes: Window length, 1 to ``MAX_WINDOW_MINUTES``.

    Returns:
        The UTC deadline.

    Raises:
        ValueError: If *minutes* is out of range.
        RuntimeError: If the store could not be unblocked right now.
    """
    if not 1 <= minutes <= MAX_WINDOW_MINUTES:
        msg = f"minutes must be between 1 and {MAX_WINDOW_MINUTES}, got {minutes}"
        raise ValueError(msg)
    until = datetime.now(UTC) + timedelta(minutes=minutes)
    state.store_unblocked_until = until.isoformat()
    state.save()
    if not unblock_store():
        msg = "could not unblock the store (sudo?)"
        raise RuntimeError(msg)
    return until


def _deadline(state: State) -> datetime | None:
    """The window's deadline, or ``None`` when unset or unparsable."""
    raw = state.store_unblocked_until
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Ignoring malformed store_unblocked_until %r", raw)
        return None


def store_window_tick(config: Config, state: State) -> None:
    """Keep the store open inside the window; re-block once it has passed.

    Runs every daemon iteration. Outside a window it only parses one string,
    so it costs nothing; inside one it reads ``/etc/hosts`` (no subprocess)
    and shells out only when the block has actually come back.

    Args:
        config: Enforcer configuration (``block_store`` gates the re-block).
        state: Freshly reloaded enforcer state.
    """
    until = _deadline(state)
    if until is None:
        return
    if datetime.now(UTC) < until:
        if hosts_blocks_store():
            logger.info("Store window open until %s: block came back, undoing", until)
            unblock_store()
        return
    if state.store_unblocked_until in _reblocked_for:
        return
    _reblocked_for.add(state.store_unblocked_until)
    if config.block_store:
        logger.info("Store window ended at %s: re-blocking the store", until)
        block_store()
