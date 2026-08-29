"""Tampering detection for installed games.

Split out of :mod:`steam_backlog_enforcer.scanning` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``scanning``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._allowed_games import allowed_games
from steam_backlog_enforcer.config import load_snapshot
from steam_backlog_enforcer.enforcer import send_notification
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.steam_api import SteamAPIClient

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)

_TAMPER_CHECK_LIMIT = 3


def _legitimately_played(state: State) -> set[int]:
    """Return every app id the user was allowed to earn achievements on.

    Wider than ``allowed_app_ids`` on purpose. A manual pick that has been
    completed is no longer *allowed* -- it leaves the active set the moment it
    lands in ``finished_app_ids`` -- but the achievements that finished it were
    earned legitimately, so comparing it against a stale snapshot would report
    the user's own completion as tampering. Every game ever manually picked,
    plus every finished game, is therefore exempt.

    Args:
        state: Current enforcer state.

    Returns:
        App ids whose achievement progress must not be treated as suspicious.
    """
    exempt = {app_id for app_id, _ in allowed_games(state)}
    exempt.update(state.finished_app_ids)
    exempt.update(
        pick["app_id"] for pick in state.manual_picks if pick.get("app_id") is not None
    )
    return exempt


def _check_game_tampering(
    client: SteamAPIClient,
    entry: dict[str, Any],
    state: State,
) -> tuple[str, int, int] | None:
    """Check if a single game has unexpected achievement progress.

    Args:
        client: Steam API client.
        entry: Snapshot entry for the game.
        state: Current enforcer state.

    Returns:
        Tuple of (name, app_id, diff) if tampering detected, else None.
    """
    app_id = entry["app_id"]
    if app_id in _legitimately_played(state):
        return None
    if entry["unlocked_achievements"] >= entry["total_achievements"]:
        return None
    if entry.get("playtime_minutes", 0) <= 0:
        return None
    game = client.refresh_single_game(
        app_id, entry["name"], entry.get("playtime_minutes", 0)
    )
    if game and game.unlocked_achievements > entry["unlocked_achievements"]:
        diff = game.unlocked_achievements - entry["unlocked_achievements"]
        return (entry["name"], app_id, diff)
    return None


def detect_tampering(config: Config, state: State) -> None:
    """Check if achievements were unlocked on non-assigned games."""
    old_snapshot = load_snapshot()
    if old_snapshot is None:
        return

    client = SteamAPIClient(config.steam_api_key, config.steam_id)

    # Quick check: only re-fetch a few random non-assigned games.
    suspicious: list[tuple[str, int, int]] = []
    for entry in old_snapshot:
        result = _check_game_tampering(client, entry, state)
        if result:
            suspicious.append(result)
        if len(suspicious) >= _TAMPER_CHECK_LIMIT:
            break

    if suspicious:
        _echo("\n  TAMPERING DETECTED:")
        for name, app_id, diff in suspicious:
            _echo(f"    {name} (AppID={app_id}): +{diff} new achievements!")
        send_notification(
            "Tampering Detected!",
            f"Achievements unlocked on {len(suspicious)} non-assigned games!",
        )
