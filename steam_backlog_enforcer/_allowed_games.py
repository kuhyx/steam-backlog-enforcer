"""Which games the enforcer currently must leave installed and visible.

Pure functions over ``State`` with no dependency on ``game_install.py``.
Kept as its own leaf module (rather than living in ``_actions.py``, which
already imports from ``game_install.py`` for unrelated functions) so that
``game_install.py`` can import ``allowed_games`` at the top level for its
deletion safety net without creating a circular import.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

# Days before the manual-pick lock automatically expires. Single source of
# truth: both ``main.py`` and the MCP server import it via ``_actions``.
MANUAL_LOCK_DAYS = 14


def _pick_is_active(state: State, pick: dict[str, Any]) -> bool:
    """Return ``True`` if *pick* still holds the lock and a pick slot.

    An inactive pick is *not* evicted: it stays in ``state.manual_picks``, and
    so installed and playable, until the user explicitly chooses another game
    (:func:`drop_inactive_picks`).

    A pick stops being active once it earned a new achievement since it was
    picked (``released_at``), once its game is 100% finished, or once
    ``MANUAL_LOCK_DAYS`` have elapsed. A missing or malformed timestamp
    keeps it active: with no deadline to evaluate, the safe answer for an
    enforcement tool is "still locked".

    Args:
        state: The loaded enforcer state (for ``finished_app_ids``).
        pick: One ``state.manual_picks`` entry.

    Returns:
        Whether this pick still counts toward the lock.
    """
    app_id = pick.get("app_id")
    if app_id is None or app_id in state.finished_app_ids:
        return False
    if pick.get("released_at"):
        return False

    started_at = pick.get("started_at") or ""
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return True
        if datetime.now(UTC) >= started + timedelta(days=MANUAL_LOCK_DAYS):
            return False

    return True


def active_manual_picks(state: State) -> list[dict[str, Any]]:
    """Return the manual picks that still hold the lock, oldest first.

    Args:
        state: The loaded enforcer state.

    Returns:
        The subset of ``state.manual_picks`` that is neither released,
        finished nor past its own deadline.
    """
    return [p for p in state.manual_picks if _pick_is_active(state, p)]


def drop_inactive_picks(state: State) -> list[dict[str, Any]]:
    """Forget every pick that no longer holds the lock; return the dropped ones.

    Released, finished and expired picks stay installed and playable for as
    long as the user wants. Only an explicit choice of another game (a new
    manual pick, or accepting the next assignment) calls this and so lets
    enforcement remove them. Does not save.

    Args:
        state: The enforcer state to mutate.

    Returns:
        The dropped pick entries, oldest first.
    """
    active = active_manual_picks(state)
    dropped = [p for p in state.manual_picks if p not in active]
    state.manual_picks = active
    return dropped


def allowed_games(state: State) -> list[tuple[int, str]]:
    """Return ``(app_id, name)`` for every game the enforcer must keep.

    That is the current assignment plus every stored manual pick, including
    released and expired ones: a game is only removed once the user has
    explicitly chosen something else.

    Args:
        state: The loaded enforcer state.

    Returns:
        Allowed games as ``(app_id, name)`` pairs, without duplicates. The
        current assignment comes first.
    """
    games: list[tuple[int, str]] = []
    if state.current_app_id is not None:
        games.append((state.current_app_id, state.current_game_name))
    for pick in state.manual_picks:
        app_id = pick.get("app_id")
        if app_id is not None and all(app_id != aid for aid, _ in games):
            games.append((app_id, pick.get("game_name", "")))
    return games
