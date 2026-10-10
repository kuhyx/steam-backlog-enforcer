"""Tampering detection for installed games.

Split out of :mod:`steam_backlog_enforcer.scanning` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``scanning``.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from itertools import islice
import logging
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer._allowed_games import allowed_games
from steam_backlog_enforcer._assignment_progress import iso_to_epoch
from steam_backlog_enforcer._progress import current_progress
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer._steam_models import MAX_WORKERS
from steam_backlog_enforcer._whitelist_locking import get_approved_exception_ids
from steam_backlog_enforcer.enforcer import send_notification
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.steam_api import SteamAPIClient

if TYPE_CHECKING:
    from collections.abc import Generator

    from steam_backlog_enforcer.config import Config, State
    from steam_backlog_enforcer.steam_api import GameInfo

logger = logging.getLogger(__name__)

_TAMPER_CHECK_LIMIT = 3
# Requests kept in flight while re-fetching; same width as the library scan.
_TAMPER_WINDOW = MAX_WORKERS


def _legitimately_played(state: State) -> set[int]:
    """Return every app id the user was allowed to earn achievements on.

    Wider than ``allowed_app_ids`` on purpose. A manual pick that has been
    completed is no longer *allowed* -- it leaves the active set the moment it
    lands in ``finished_app_ids`` -- but the achievements that finished it were
    earned legitimately, so comparing it against a stale snapshot would report
    the user's own completion as tampering. Every game ever manually picked,
    plus every finished game and every approved whitelist exception, is therefore
    exempt.

    Args:
        state: Current enforcer state.

    Returns:
        App ids whose achievement progress must not be treated as suspicious.
    """
    exempt = {app_id for app_id, _ in allowed_games(state)}
    exempt.update(state.finished_app_ids)
    exempt.update(get_approved_exception_ids())
    exempt.update(
        pick["app_id"] for pick in state.manual_picks if pick.get("app_id") is not None
    )
    return exempt


def _needs_refetch(entry: dict[str, Any], exempt: set[int]) -> bool:
    """Whether *entry* could show tampering, so is worth a Steam request.

    Args:
        entry: Snapshot entry for the game.
        exempt: App ids from :func:`_legitimately_played`.
    """
    if entry["app_id"] in exempt:
        return False
    if entry["unlocked_achievements"] >= entry["total_achievements"]:
        return False
    playtime: int = entry.get("playtime_minutes", 0)
    return playtime > 0


def _unexpected_unlocks(
    entry: dict[str, Any], game: GameInfo, state: State
) -> tuple[str, int, int] | None:
    """Compare fresh achievement data with the snapshot entry.

    Returns:
        Tuple of (name, app_id, diff) if tampering detected, else None.
    """
    app_id = entry["app_id"]
    released = iso_to_epoch(state.released_at.get(str(app_id), ""))
    if released is not None:
        # Released below 100%: the snapshot predates the unlocks earned while
        # it was assigned, so only unlocks after the release are suspicious.
        diff = sum(
            1 for a in game.achievements if a.achieved and a.unlock_time > released
        )
    else:
        diff = game.unlocked_achievements - entry["unlocked_achievements"]
    if diff > 0:
        return (entry["name"], app_id, diff)
    return None


def _refetch(client: SteamAPIClient, entry: dict[str, Any]) -> GameInfo | None:
    """Re-fetch one snapshot entry's achievements from Steam."""
    return client.refresh_single_game(
        entry["app_id"], entry["name"], entry.get("playtime_minutes", 0)
    )


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
    if not _needs_refetch(entry, _legitimately_played(state)):
        return None
    game = _refetch(client, entry)
    if game is None:
        return None
    return _unexpected_unlocks(entry, game, state)


def _refetch_in_order(
    client: SteamAPIClient, entries: list[dict[str, Any]]
) -> Generator[tuple[dict[str, Any], GameInfo | None]]:
    """Yield ``(entry, fresh game)`` in *entries* order, fetching ahead.

    A sliding window keeps :data:`_TAMPER_WINDOW` requests in flight (the
    client's own rate limiter still caps requests per second), so the caller
    can stop early without having asked Steam about the whole library. Closing
    the generator drops queued requests instead of waiting for them, which is
    also what makes a cancelled job stop promptly.
    """
    pool = ThreadPoolExecutor(max_workers=_TAMPER_WINDOW)
    pending: deque[tuple[dict[str, Any], Future[GameInfo | None]]] = deque()
    upcoming = iter(entries)
    try:
        for entry in islice(upcoming, _TAMPER_WINDOW):
            pending.append((entry, pool.submit(_refetch, client, entry)))
        while pending:
            entry, future = pending.popleft()
            nxt = next(upcoming, None)
            if nxt is not None:
                pending.append((nxt, pool.submit(_refetch, client, nxt)))
            yield entry, future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def detect_tampering(config: Config, state: State) -> None:
    """Check if achievements were unlocked on non-assigned games."""
    old_snapshot = load_snapshot()
    if old_snapshot is None:
        return

    client = SteamAPIClient(config.steam_api_key, config.steam_id)
    exempt = _legitimately_played(state)
    to_check = [e for e in old_snapshot if _needs_refetch(e, exempt)]

    # Stops at the first few hits, in snapshot order, like the serial loop did.
    suspicious: list[tuple[str, int, int]] = []
    progress = current_progress()
    progress.phase("Checking other games for tampering", len(to_check))
    with closing(_refetch_in_order(client, to_check)) as fetched:
        for entry, game in fetched:
            progress.advance(str(entry.get("name", "")))
            result = None if game is None else _unexpected_unlocks(entry, game, state)
            if result:
                suspicious.append(result)
            if len(suspicious) >= _TAMPER_CHECK_LIMIT:
                progress.advance(step=len(to_check))
                break

    if suspicious:
        _echo("\n  TAMPERING DETECTED:")
        for name, app_id, diff in suspicious:
            _echo(f"    {name} (AppID={app_id}): +{diff} new achievements!")
        send_notification(
            "Tampering Detected!",
            f"Achievements unlocked on {len(suspicious)} non-assigned games!",
        )
