"""``pick`` and ``pick-manual`` keep the games already allowed.

Picking a game used to replace the assignment: the outgoing game and every
released manual pick were dropped from the allowed set and uninstalled. In
keep mode the outgoing assignment is parked in ``state.manual_picks`` as a
*released* entry instead, so it reuses the existing model end to end: it
stays in :func:`allowed_games` (installed, visible, never killed), holds no
lock and no pick slot, and leaves only on an explicit ``pick --replace``,
``done``/``check`` reassignment or ``abandon-pick``. ``pick-manual`` parks it
the same way and shares the cap (:func:`allowed_cap_refusal`).

Stdout-free and state-only, like :mod:`._actions`: callers print and exit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._allowed_games import allowed_games

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


def keep_outgoing_assignment(state: State) -> dict[str, Any] | None:
    """Park the current assignment as a released pick so it stays allowed.

    Must run before the new assignment overwrites ``current_app_id``. A game
    already stored as a pick (an active ``pick-manual`` lock, or an earlier
    released entry) is left exactly as it is: it is allowed already, and a
    second entry would double-count it. Does not save.

    Args:
        state: The enforcer state to mutate.

    Returns:
        The appended entry, or ``None`` when nothing needed parking.
    """
    app_id = state.current_app_id
    if app_id is None or any(p.get("app_id") == app_id for p in state.manual_picks):
        return None
    now = datetime.now(UTC).isoformat()
    entry: dict[str, Any] = {
        "app_id": app_id,
        "game_name": state.current_game_name,
        "started_at": state.current_assigned_at or now,
        # Released, not active: allowed, but no lock and no pick slot.
        "released_at": now,
    }
    state.manual_picks.append(entry)
    return entry


def keep_refusal(config: Config, state: State) -> str | None:
    """Why ``pick`` (keep mode) cannot add another game, or ``None`` if it can.

    Args:
        config: Enforcer configuration (for ``max_manual_picks``).
        state: The loaded enforcer state.

    Returns:
        A message naming every game using a slot and how to free one.
    """
    return allowed_cap_refusal(state, config.max_manual_picks, offer_replace=True)


def allowed_cap_refusal(
    state: State,
    max_picks: int,
    adding: int | None = None,
    *,
    offer_replace: bool = False,
) -> str | None:
    """Why one more allowed game would break the cap, or ``None`` if it fits.

    The one rule ``pick`` and ``pick-manual`` share: at most ``max_picks + 1``
    games (the assignment plus the manual picks) may be allowed at once.

    Args:
        state: The loaded enforcer state.
        max_picks: The manual-pick cap (``Config.max_manual_picks``).
        adding: The app about to be allowed. One already allowed (a kept
            game picked again) does not grow the set, so it always fits.
        offer_replace: Also suggest ``pick --replace`` (only ``pick`` has it).

    Returns:
        A message naming every game using a slot and how to free one.
    """
    games = allowed_games(state)
    cap = max_picks + 1
    if len(games) < cap or any(app_id == adding for app_id, _ in games):
        return None
    picked = {p.get("app_id") for p in state.manual_picks}
    header = (
        f"You already have {len(games)} games allowed (cap is {cap}: your"
        f" assignment plus {max_picks} manual pick(s)):"
    )
    lines = [header]
    for app_id, name in games:
        role = "current assignment" if app_id == state.current_app_id else "kept"
        # Only a stored pick can be abandoned; the bare assignment cannot.
        how = f"; free it with 'abandon-pick {app_id}'" if app_id in picked else ""
        lines.append(f"  - {name} (AppID={app_id}): {role}{how}")
    tail = "Free a slot with 'abandon-pick <app_id>'"
    if offer_replace:
        tail += (
            ", or run 'pick --replace' to swap them all for the new game"
            " (uninstalls them)"
        )
    lines.append(tail + ".")
    return "\n".join(lines)


def kept_alongside(state: State, app_id: int) -> list[str]:
    """Names of the allowed games that stay installed next to *app_id*."""
    return [name for aid, name in allowed_games(state) if aid != app_id]
