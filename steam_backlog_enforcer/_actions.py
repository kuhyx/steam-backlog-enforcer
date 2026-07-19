"""Stdout-free, state-only core operations shared by the CLI and MCP server.

Every function here is safe to call from a stdio MCP server, where STDOUT
carries the JSON-RPC protocol and any stray write corrupts the stream. That
means: no ``print``/``_echo``/``sys.stdout`` writes, no ``input()``, and no
``sys.exit()``. The interactive CLI (``main.py``) reuses these same functions so
there is a single tested implementation of the underlying behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._total_block import get_total_block_status
from steam_backlog_enforcer.game_install import get_installed_games, is_protected_app
from steam_backlog_enforcer.store_blocker import is_store_blocked

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

# Days before the manual-pick lock automatically expires. Single source of
# truth: both ``main.py`` and the MCP server import it from here.
MANUAL_LOCK_DAYS = 14

# Mistake-correction window: for this many days after a manual pick the user
# may still back out via ``abandon-pick``. Deliberately short — it exists to
# undo a wrong pick, not to serve as an escape hatch from the lock.
MANUAL_GRACE_DAYS = 4

# How long an abandoned pick stays out of the auto-assignment pool, so that
# ``scan`` does not immediately hand back the game the user just rejected.
ABANDON_COOLDOWN_DAYS = 30


def _pick_is_active(state: State, pick: dict[str, Any]) -> bool:
    """Return ``True`` if *pick* still holds the lock.

    A pick stops being active once its game is finished (100% achievements) or
    once ``MANUAL_LOCK_DAYS`` have elapsed. A missing or malformed timestamp
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

    started_at = pick.get("started_at") or ""
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return True
        if datetime.now(timezone.utc) >= started + timedelta(days=MANUAL_LOCK_DAYS):
            return False

    return True


def active_manual_picks(state: State) -> list[dict[str, Any]]:
    """Return the manual picks that still hold the lock, oldest first.

    Args:
        state: The loaded enforcer state.

    Returns:
        The subset of ``state.manual_picks`` that is neither finished nor past
        its own deadline.
    """
    return [p for p in state.manual_picks if _pick_is_active(state, p)]


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


def allowed_games(state: State) -> list[tuple[int, str]]:
    """Return ``(app_id, name)`` for every game the enforcer must keep.

    Same membership as :func:`allowed_app_ids`, but carrying names so callers
    can install and report on each one. The current assignment comes first.

    Args:
        state: The loaded enforcer state.

    Returns:
        Allowed games as ``(app_id, name)`` pairs, without duplicates.
    """
    games: list[tuple[int, str]] = []
    if state.current_app_id is not None:
        games.append((state.current_app_id, state.current_game_name))
    for pick in active_manual_picks(state):
        app_id = pick.get("app_id")
        if app_id is not None and all(app_id != aid for aid, _ in games):
            games.append((app_id, pick.get("game_name", "")))
    return games


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


def manual_pick_grace_remaining(state: State, app_id: int) -> float | None:
    """Return days left in *app_id*'s grace window, or ``None``.

    ``None`` means "no grace window applies": *app_id* is not an active manual
    pick, or its timestamp is missing/malformed. A value <= 0 means the window
    has closed.

    Args:
        state: The loaded enforcer state.
        app_id: The manually-picked app id to measure.

    Returns:
        Fractional days remaining before the pick can no longer be abandoned,
        or ``None`` when the question does not apply.
    """
    pick = find_manual_pick(state, app_id)
    if pick is None or not pick.get("started_at"):
        return None
    try:
        started = datetime.fromisoformat(pick["started_at"])
    except ValueError:
        return None
    deadline = started + timedelta(days=MANUAL_GRACE_DAYS)
    return (deadline - datetime.now(timezone.utc)).total_seconds() / 86400


def can_abandon_manual_pick(state: State, app_id: int) -> bool:
    """Return ``True`` if *app_id* is still inside its grace window.

    Args:
        state: The loaded enforcer state.
        app_id: The manually-picked app id to check.

    Returns:
        Whether ``abandon_manual_pick`` would be accepted right now.
    """
    remaining = manual_pick_grace_remaining(state, app_id)
    return remaining is not None and remaining > 0


def abandon_manual_pick(state: State, app_id: int) -> bool:
    """Drop one manual pick and persist ``state``, if still inside its grace window.

    Only the named pick is dropped: any other active pick keeps its own lock
    and deadline. The abandoned app id goes onto the existing skip cooldown so
    ``scan`` will not hand the same game straight back. State-only: like
    ``apply_manual_pick`` this performs no uninstall/hide cascade, so the MCP
    server can call it without touching the filesystem.

    Args:
        state: The enforcer state to mutate and save.
        app_id: The manually-picked app id to back out of.

    Returns:
        ``True`` if the pick was abandoned, ``False`` if its grace window has
        closed (or it is not an active pick), in which case ``state`` is
        untouched.
    """
    if not can_abandon_manual_pick(state, app_id):
        return False

    state.skip_for_days(app_id, ABANDON_COOLDOWN_DAYS)
    state.manual_picks = [
        p for p in active_manual_picks(state) if p.get("app_id") != app_id
    ]

    # The abandoned pick may also have been the current assignment; hand the
    # assignment to a surviving pick so the enforcer keeps guarding it, or
    # clear it so 'scan' can reassign.
    if state.current_app_id == app_id:
        survivor = state.manual_picks[-1] if state.manual_picks else None
        state.current_app_id = survivor["app_id"] if survivor else None
        state.current_game_name = survivor["game_name"] if survivor else ""

    state.save()
    return True


def status_payload(state: State) -> dict[str, Any]:
    """Build the structured status snapshot that ``cmd_status`` renders as text.

    Pure data, no stdout — safe for the MCP server. Reads only ``State`` and the
    stdout-free leaf helpers; never constructs ``Config`` and never exposes the
    Steam API key.

    Args:
        state: The loaded enforcer state.

    Returns:
        A JSON-ready dict describing the current enforcement status.
    """
    total_block = get_total_block_status()
    installed = get_installed_games()
    real_games = [(aid, name) for aid, name in installed if not is_protected_app(aid)]
    assigned_installed = (
        any(aid == state.current_app_id for aid, _ in installed)
        if state.current_app_id
        else None
    )
    return {
        "current_app_id": state.current_app_id,
        "current_game_name": state.current_game_name or None,
        "finished_count": len(state.finished_app_ids),
        "store_blocked": is_store_blocked(),
        "installed_count": len(real_games),
        "assigned_game_installed": assigned_installed,
        "total_block": {
            "active": total_block.active,
            "days_remaining": round(total_block.days_remaining, 1),
            "until": total_block.until.isoformat() if total_block.until else None,
        },
        "manual_pick_locked": is_manual_pick_locked(state),
        "manual_picks": [
            {
                **pick,
                "grace_days_left": manual_pick_grace_remaining(state, pick["app_id"]),
            }
            for pick in active_manual_picks(state)
        ],
    }
