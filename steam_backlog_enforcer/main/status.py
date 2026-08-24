"""``status`` and ``list`` commands: read-only views of the current state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import (
    active_manual_picks,
    manual_pick_age_days,
)
from steam_backlog_enforcer._total_block import get_total_block_status
from steam_backlog_enforcer.config import load_snapshot
from steam_backlog_enforcer.game_install import (
    _echo,
    get_installed_games,
    is_protected_app,
)
from steam_backlog_enforcer.main._shared import _LIST_DISPLAY_LIMIT
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.store_blocker import is_store_blocked

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State


def cmd_status(_config: Config, state: State) -> None:
    """Show current status."""
    _echo("=== Steam Backlog Enforcer ===\n")

    total_block = get_total_block_status()
    if total_block.active:
        _echo("*** TOTAL GAMING BLOCK ACTIVE ***")
        if total_block.until is not None:
            _echo(f"Blocked until: {total_block.until.strftime('%Y-%m-%d %H:%M UTC')}")
            _echo(f"Days remaining: {total_block.days_remaining:.1f}\n")

    if state.current_app_id:
        _echo(
            f"Assigned game: {state.current_game_name} (AppID={state.current_app_id})"
        )
    else:
        _echo("No game currently assigned.")

    _echo(f"Finished games: {len(state.finished_app_ids)}")
    _echo(f"Store blocked:  {is_store_blocked()}")

    # Show installed games.
    installed = get_installed_games()
    real_games = [(aid, n) for aid, n in installed if not is_protected_app(aid)]
    _echo(f"Installed games: {len(real_games)}")

    if state.current_app_id:
        is_assigned_installed = any(aid == state.current_app_id for aid, _ in installed)
        _echo(f"Assigned game installed: {is_assigned_installed}")

    picks = active_manual_picks(state)
    if picks:
        _echo(f"\nManual picks ({len(picks)}):")
        for pick in picks:
            age = manual_pick_age_days(state, pick["app_id"])
            since = f" — picked {age:.1f} day(s) ago" if age is not None else ""
            _echo(f"  {pick['game_name']} (AppID={pick['app_id']}){since}")
        _echo("\n[MANUAL PICK LOCK is active — most commands are blocked]")


def cmd_list(_config: Config, state: State) -> None:
    """List games from the last snapshot."""
    snapshot = load_snapshot()
    if snapshot is None:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot]
    incomplete = [g for g in games if not g.is_complete]
    complete = [g for g in games if g.is_complete]

    # Sort incomplete by completionist hours.
    def sort_key(g: GameInfo) -> tuple[int, float]:
        if g.completionist_hours > 0:
            return (0, g.completionist_hours)
        return (1, 0.0)

    incomplete.sort(key=sort_key)

    _echo(f"\n{'─' * 70}")
    _echo(f"  INCOMPLETE ({len(incomplete)} games)")
    _echo(f"{'─' * 70}")
    for i, g in enumerate(incomplete[:_LIST_DISPLAY_LIMIT], 1):
        marker = " <<< ASSIGNED" if g.app_id == state.current_app_id else ""
        hrs = f" [{g.completionist_hours:.0f}h]" if g.completionist_hours > 0 else ""
        pct = f"{g.completion_pct:.0f}%"
        _echo(f"  {i:3d}. {g.name[:40]:<40s} {pct:>5s}{hrs}{marker}")

    if len(incomplete) > _LIST_DISPLAY_LIMIT:
        _echo(f"  ... and {len(incomplete) - _LIST_DISPLAY_LIMIT} more")

    _echo(f"\n  COMPLETE: {len(complete)} games")
