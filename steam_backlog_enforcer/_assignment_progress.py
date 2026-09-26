"""The "earn one new achievement" release rule, and the bookkeeping behind it.

A game (the current assignment or a manual pick) no longer has to reach 100%
achievements before the user may move on: one achievement unlocked after the
game was assigned is enough. Requiring 100% kept the user stuck on one game for
weeks, which proved ineffective.

``State.finished_app_ids`` still means *100% complete* and nothing else, so the
stats built on it stay honest. A game released below 100% goes back into the
pool behind a cooldown and is ordered least-recently-assigned-first, so it
comes round again only after the rest of the backlog has had a turn.

Leaf, stdout-free module: safe for the MCP server and importable from
``config.py`` without a cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from steam_backlog_enforcer._allowed_games import active_manual_picks

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State
    from steam_backlog_enforcer.steam_api import AchievementInfo, GameInfo

# Days a released game stays out of the auto-assignment pool; matches the
# "n = skip" answer of the done prompt.
RELEASE_COOLDOWN_DAYS = 7


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def iso_to_epoch(iso: str) -> float | None:
    """Return *iso* as epoch seconds, or ``None`` when empty or malformed."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def record_assignment(
    state: State, app_id: int, game_name: str, at: str | None = None
) -> None:
    """Make *app_id* the current assignment, stamping when it happened.

    The single writer of ``current_assigned_at`` and ``last_assigned_at``, so
    every assignment path starts the "new achievement" clock the same way.
    Does not save.

    Args:
        state: The enforcer state to mutate.
        app_id: The newly assigned game.
        game_name: Its display name.
        at: ISO timestamp of the assignment; defaults to now.
    """
    stamp = at or _now_iso()
    state.current_app_id = app_id
    state.current_game_name = game_name
    state.current_assigned_at = stamp
    state.last_assigned_at[str(app_id)] = stamp
    if not state.enforcement_started_at:
        state.enforcement_started_at = stamp


def last_assigned_epoch(state: State, app_id: int) -> float:
    """Return when *app_id* was last assigned, ``0.0`` if never (sorts first)."""
    return iso_to_epoch(state.last_assigned_at.get(str(app_id), "")) or 0.0


def assignment_baseline(state: State, app_id: int) -> str:
    """Return the ISO time after which a new achievement on *app_id* counts.

    An active manual pick counts from its own ``started_at`` (a released or
    expired one must not: its old unlocks would release a later assignment of
    the same game at once); otherwise the current
    assignment counts from ``current_assigned_at``. Anything else has no
    baseline (``""``), which never releases.
    """
    for pick in active_manual_picks(state):
        if pick.get("app_id") == app_id and pick.get("started_at"):
            return str(pick["started_at"])
    if app_id == state.current_app_id:
        return state.current_assigned_at
    return ""


def newest_unlock_since(game: GameInfo, since_iso: str) -> AchievementInfo | None:
    """Return the most recent achievement unlocked after *since_iso*, if any.

    An empty or malformed baseline returns ``None``: for an enforcement tool,
    an unknown start must never read as progress.
    """
    since = iso_to_epoch(since_iso)
    if since is None:
        return None
    fresh = [a for a in game.achievements if a.achieved and a.unlock_time > since]
    return max(fresh, key=lambda a: a.unlock_time) if fresh else None


def release_verdict(state: State, game: GameInfo) -> tuple[bool, str]:
    """Judge *game* against the release rule: 100%, or one new achievement.

    Args:
        state: The enforcer state (for the assignment baseline).
        game: Freshly refreshed achievement data for the game.

    Returns:
        Whether the user may move on, and a one-line reason for the CLI.
    """
    baseline = assignment_baseline(state, game.app_id)
    newest = newest_unlock_since(game, baseline)
    if game.is_complete:
        return True, f"COMPLETED: {game.name} (100% achievements)!"
    if newest is not None:
        return True, f"NEW ACHIEVEMENT on {game.name}: '{newest.display_name}'!"
    since = baseline[:10] if baseline else "its assignment"
    return False, (
        f"No new achievement since {since}. Earn at least one to move on. Keep going!"
    )


def mark_finished(state: State, app_id: int) -> bool:
    """Record *app_id* as 100% finished, without duplicating an existing record.

    The single place a completion is written, so the manual-pick sweep and the
    ``done``/``check`` paths cannot both append the same id.

    Args:
        state: The enforcer state to mutate (not saved here).
        app_id: The completed app id.

    Returns:
        Whether this call actually added the id.
    """
    if app_id in state.finished_app_ids:
        return False
    state.finished_app_ids.append(app_id)
    return True


def release_game(state: State, game: GameInfo) -> None:
    """Let the user move on from *game*, which has met the release rule.

    Marks it finished only when it really is at 100%, frees any manual-pick
    slot it holds, remembers when it was released (for tampering detection),
    and puts it on the cooldown so the next pick is a different game. Does not
    save and does not reassign.
    """
    now = _now_iso()
    if game.is_complete:
        mark_finished(state, game.app_id)
    for pick in state.manual_picks:
        if pick.get("app_id") == game.app_id and not pick.get("released_at"):
            pick["released_at"] = now
    state.released_at[str(game.app_id)] = now
    state.skip_for_days(game.app_id, RELEASE_COOLDOWN_DAYS)
