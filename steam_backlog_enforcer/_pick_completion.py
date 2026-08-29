"""Achievement-based retirement of finished manual picks.

A manual pick stops holding its slot once its app id is in
``State.finished_app_ids`` -- that is what ``_allowed_games._pick_is_active``
reads. Historically only ``State.current_app_id`` was ever checked for
completion (``cmd_done``, ``do_check``), so a manual pick that was *not* the
current assignment had no achievement-based release path at all: it sat on a
slot until the 14-day lock expired or the user abandoned it by hand.

This module closes that gap by checking every active pick and retiring the ones
at 100%. It deliberately stops there -- freeing a slot is not a request for a
replacement game, so nothing here calls ``pick_next_game``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._allowed_games import active_manual_picks
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.steam_api import SteamAPIClient

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

# How long the enforce daemon waits between achievement re-checks. That loop
# ticks every 3s; re-checking every tick would be ~1200 Steam API calls an hour
# for a fact that changes a few times a year. CLI commands do not throttle.
MANUAL_PICK_RECHECK_TTL_SECONDS = 900

logger = logging.getLogger(__name__)


class _DaemonSweep:
    """The enforce daemon's re-check gate, plus what it has retired.

    An object rather than module-level values because rebinding those would
    need a ``global`` statement; attribute writes do not.

    ``retired`` exists so the daemon can *record* a completion without
    *evicting* the game: retiring drops a pick out of ``allowed_app_ids``, and
    the daemon would then kill and uninstall it mid-session, seconds after the
    last achievement popped. Unioning these ids back into the allowed set
    defers that to a user-invoked command; the freed slot is visible at once.
    """

    def __init__(self) -> None:
        self.last: float | None = None
        self.retired: set[int] = set()

    def due(self, now: float, ttl: float) -> bool:
        """Return whether a check is due, recording *now* when it is.

        Args:
            now: Current ``time.monotonic()`` reading.
            ttl: Minimum seconds between checks.

        Returns:
            Whether the caller should run the check.
        """
        if self.last is not None and now - self.last < ttl:
            return False
        self.last = now
        return True


# Process-local by design: the daemon is long-lived, and a restart re-checking
# once immediately is harmless.
daemon_sweep = _DaemonSweep()


@dataclass(frozen=True)
class PickProgress:
    """Achievement progress for one active manual pick.

    ``determinable`` is ``False`` when Steam returned nothing for this app (no
    achievements, or the call failed); ``unlocked``/``total`` are 0 then, and
    callers must read it as "unknown", never as "complete".
    """

    app_id: int
    game_name: str
    unlocked: int
    total: int
    retired: bool
    determinable: bool

    def describe(self) -> str:
        """Return a one-line human summary for CLI output."""
        if not self.determinable:
            return f"  {self.game_name}: progress unavailable (no achievements)"
        if self.retired:
            return (
                f"  {self.game_name}: {self.unlocked}/{self.total} (100%)"
                " - COMPLETE, freeing its slot"
            )
        pct = (self.unlocked / self.total) * 100.0 if self.total else 0.0
        return (
            f"  {self.game_name}: {self.unlocked}/{self.total}"
            f" ({pct:.0f}%) - still in progress"
        )


def mark_finished(state: State, app_id: int) -> bool:
    """Record *app_id* as finished, without duplicating an existing record.

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


def retire_completed_manual_picks(
    config: Config,
    state: State,
    *,
    client: SteamAPIClient | None = None,
) -> list[PickProgress]:
    """Mark every 100%-complete manual pick finished, freeing its slot.

    Mutates and saves ``state`` only when something was actually retired. Does
    **not** assign a replacement game, uninstall anything, or touch
    ``current_app_id``: the caller decides what a freed slot means.

    A pick whose achievements cannot be read stays locked: for an enforcement
    tool, Steam being unreachable must never look like completion.

    Args:
        config: Enforcer configuration (for the Steam credentials).
        state: The enforcer state to inspect, mutate and save.
        client: Pre-built API client, for reuse and for tests.

    Returns:
        One entry per *active* pick, in pick order -- including the ones left
        alone, so callers can report progress rather than only retirements.
    """
    picks = active_manual_picks(state)
    if not picks:
        return []

    if client is None:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)

    results: list[PickProgress] = []
    retired_any = False
    for pick in picks:
        # active_manual_picks has already dropped entries without an app_id.
        app_id = pick["app_id"]
        name = pick.get("game_name", "") or f"AppID={app_id}"

        game = client.refresh_single_game(app_id, name)
        if game is None:
            results.append(
                PickProgress(app_id, name, 0, 0, retired=False, determinable=False)
            )
            continue

        if game.is_complete and mark_finished(state, app_id):
            retired_any = True
            logger.info("Manual pick retired at 100%%: %s (AppID=%s)", name, app_id)
        results.append(
            PickProgress(
                app_id,
                name,
                game.unlocked_achievements,
                game.total_achievements,
                retired=game.is_complete,
                determinable=True,
            )
        )

    if retired_any:
        state.save()
    return results


def report_completion(config: Config, state: State) -> list[PickProgress]:
    """Run the sweep and print a per-pick progress block.

    Args:
        config: Enforcer configuration.
        state: The enforcer state to inspect, mutate and save.

    Returns:
        Only the picks whose slots this call freed.
    """
    results = retire_completed_manual_picks(config, state)
    if not results:
        return []
    _echo("\nChecking your manual picks for completion...")
    for result in results:
        _echo(result.describe())
    return [r for r in results if r.retired]


def warn_stale_assignment(state: State, retired: list[PickProgress]) -> None:
    """Warn when a just-retired pick is still the current assignment.

    Only reachable from the ``pick-manual`` abort path: on the success path
    ``apply_manual_pick`` overwrites ``current_app_id`` with the new pick.

    Args:
        state: The enforcer state (for ``current_app_id``).
        retired: Picks whose slots were freed by this run.
    """
    for pick in retired:
        if pick.app_id == state.current_app_id:
            _echo(
                f"\nNote: {pick.game_name} is recorded as complete but is still"
                "\n      your current assignment. Run './run.sh done' to get"
                "\n      your next game."
            )
            return


def retire_completed_manual_picks_throttled(
    config: Config,
    state: State,
) -> list[PickProgress]:
    """Rate-limited :func:`retire_completed_manual_picks` for the enforce loop.

    Records what it retired in :data:`daemon_sweep` so the caller can keep
    those games in the allowed set rather than evicting them unattended.

    Args:
        config: Enforcer configuration.
        state: The enforcer state to inspect, mutate and save.

    Returns:
        The per-pick progress list, or ``[]`` when throttled.
    """
    if not daemon_sweep.due(time.monotonic(), MANUAL_PICK_RECHECK_TTL_SECONDS):
        return []
    results = retire_completed_manual_picks(config, state)
    daemon_sweep.retired.update(r.app_id for r in results if r.retired)
    return results
