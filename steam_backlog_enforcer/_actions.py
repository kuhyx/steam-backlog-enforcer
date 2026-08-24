"""Stdout-free, state-only core operations shared by the CLI and MCP server.

Every function here is safe to call from a stdio MCP server, where STDOUT
carries the JSON-RPC protocol and any stray write corrupts the stream. That
means: no ``print``/``_echo``/``sys.stdout`` writes, no ``input()``, and no
``sys.exit()``. The interactive CLI (``main.py``) reuses these same functions so
there is a single tested implementation of the underlying behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
from typing import TYPE_CHECKING, Any, TypeAlias

from steam_backlog_enforcer._allowed_games import (
    active_manual_picks,
    allowed_games,
)

# Marks these two as an intentional re-export (they're imported from
# _allowed_games above, not defined here) -- without this, mypy's
# --no-implicit-reexport flags every downstream `from _actions import
# active_manual_picks` as an error. Everything else in this file is
# accessible normally; this only needs to list names imported-then-reexported.

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

# How long an abandoned pick stays out of the auto-assignment pool, so that
# ``scan`` does not immediately hand back the game the user just rejected.
ABANDON_COOLDOWN_DAYS = 30


def find_manual_pick(state: State, app_id: int) -> dict[str, Any] | None:
    """Return the active manual pick for *app_id*, or ``None``.

    Args:
        state: The loaded enforcer state.
        app_id: The Steam app id to look for.

    Returns:
        The matching active pick entry, or ``None`` if *app_id* is not one.
    """
    return next(
        (p for p in active_manual_picks(state) if p.get("app_id") == app_id),
        None,
    )


def is_manual_pick_locked(state: State) -> bool:
    """Return ``True`` if any manual pick is currently holding the lock.

    With several picks allowed at once the lock releases only when every one
    of them is finished or expired.

    Args:
        state: The loaded enforcer state.

    Returns:
        Whether the manual-pick lock is active right now.
    """
    return bool(active_manual_picks(state))


def allowed_app_ids(state: State) -> set[int]:
    """Return every app id the enforcer must leave installed and visible.

    This is the single source of truth for "may exist" across the uninstall
    guard, the process killer, the library hider and the auto-installer. It is
    the union of the active manual picks and the current assignment, so two
    manually-picked games survive an enforcement pass while everything else is
    still removed.

    Args:
        state: The loaded enforcer state.

    Returns:
        The set of allowed app ids (empty when nothing is assigned).
    """
    return {app_id for app_id, _ in allowed_games(state)}


def manual_pick_slots_left(state: State, max_picks: int) -> int:
    """Return how many further manual picks fit under *max_picks*.

    Args:
        state: The loaded enforcer state.
        max_picks: Configured cap (``Config.max_manual_picks``).

    Returns:
        Remaining slots, never negative.
    """
    return max(0, max_picks - len(active_manual_picks(state)))


def apply_manual_pick(
    state: State,
    app_id: int,
    game_name: str,
    *,
    max_picks: int = 1,
) -> str | None:
    """Add *app_id* to the manual picks and persist ``state``.

    This is the non-interactive, side-effect-scoped core of the CLI's
    ``pick-manual`` command. It mutates and saves ``State`` only; it deliberately
    does **not** run the destructive post-assignment cascade (uninstalling other
    games, installing the pick, hiding the library) that the CLI performs after
    its interactive ``YES`` confirmation. Keeping this state-only means an
    automated caller (the MCP server) can never wipe installed games.

    Finished and expired entries are dropped on the way through so the stored
    list does not grow without bound.

    Args:
        state: The enforcer state to mutate and save.
        app_id: The Steam app id to lock in.
        game_name: Human-readable name for the picked game.
        max_picks: How many picks may be active at once.

    Returns:
        ``None`` on success, or a message explaining why the pick was refused
        (already picked, or no slots left), in which case nothing was saved.
    """
    active = active_manual_picks(state)

    if any(p.get("app_id") == app_id for p in active):
        return f"{game_name} (AppID={app_id}) is already one of your manual picks."

    if len(active) >= max_picks:
        names = ", ".join(f"{p['game_name']} (AppID={p['app_id']})" for p in active)
        return (
            f"You already have {len(active)} manual pick(s) locked in "
            f"(cap is {max_picks}): {names}."
        )

    now = datetime.now(timezone.utc).isoformat()
    # Rewriting from `active` also prunes finished/expired entries.
    state.manual_picks = [
        *active,
        {"app_id": app_id, "game_name": game_name, "started_at": now},
    ]
    state.current_app_id = app_id
    state.current_game_name = game_name
    if not state.enforcement_started_at:
        state.enforcement_started_at = now
    state.save()
    return None


_MOVED_TO_MANUAL_PICK_LIFECYCLE = frozenset(
    {
        "abandon_manual_pick",
        "manual_pick_age_days",
        "status_payload",
    }
)


# Whatever the re-exported name turns out to be -- a function, a class or
# a constant. Aliased so the annotation is a name rather than a bare Any.
_Reexport: TypeAlias = Any


def __getattr__(name: str) -> _Reexport:
    """Re-export the names that moved to :mod:`_manual_pick_lifecycle`.

    Deferred rather than imported at the top because _manual_pick_lifecycle imports
    back from this module, so a module-level import would be circular.
    """
    if name in _MOVED_TO_MANUAL_PICK_LIFECYCLE:
        module = importlib.import_module(
            "steam_backlog_enforcer._manual_pick_lifecycle",
        )
        return getattr(module, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
