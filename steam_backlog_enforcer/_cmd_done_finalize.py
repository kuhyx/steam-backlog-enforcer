"""Finalising a completed game and re-enforcing afterwards.

Split out of :mod:`steam_backlog_enforcer._cmd_done` to keep both files
under the 250-line cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import allowed_app_ids
from steam_backlog_enforcer._cmd_done import (
    _apply_cached_hours_to_games,
    _prompt_keep_or_skip,
    _refresh_uncached_shortlist_hours,
    _report_assigned_confidence,
)
from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer._pick_completion import mark_finished
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from steam_backlog_enforcer.game_install import (
    _echo,
    install_game,
    is_game_installed,
    uninstall_other_games,
)
from steam_backlog_enforcer.hltb import (
    fetch_hltb_times_cached,
    load_hltb_cache,
)
from steam_backlog_enforcer.library_hider import try_hide_other_games
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

_REASSIGN_REFRESH_LIMIT = 50
_SKIP_DAYS = 7
logger = logging.getLogger(__name__)


def _finalize_completion(
    config: Config,
    state: State,
    game_name: str,
    app_id: int,
) -> None:
    """Mark game complete, pick next, hide non-assigned games, notify."""
    _echo(f"\n  COMPLETED: {game_name}!")
    mark_finished(state, app_id)

    snapshot_data = load_snapshot()
    _echo("\nPicking next game...")
    if not snapshot_data:
        _echo("  No snapshot found. Run 'scan' first.")
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    hltb_cache = load_hltb_cache()
    skip = set(state.finished_app_ids) | state.active_skipped_ids()
    _refresh_uncached_shortlist_hours(games, hltb_cache, skip)
    _apply_cached_hours_to_games(games, hltb_cache)
    pick_next_game(games, state, config, on_select=_prompt_keep_or_skip)

    if state.current_app_id is None:
        _echo("  No more games to assign!")
        return

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
        if skipped is not None:
            _echo(f"\n  Library hiding: skipped ({skipped})")
        elif hidden > 0:
            _echo(f"\n  Library: hid {hidden} games")

    if not is_game_installed(state.current_app_id):
        logger.info(
            "Assigned game still missing after library reconciliation; "
            "re-triggering install"
        )
        _echo(
            "\n  Assigned game still missing after library reconciliation; "
            "re-triggering install..."
        )
        _echo(f"\n  Auto-installing {state.current_game_name}...")
        install_game(
            state.current_app_id,
            state.current_game_name,
            config.steam_id,
            use_steam_protocol=True,
        )

    send_notification(
        "Game Complete!",
        f"Finished {game_name}! Now playing: {state.current_game_name}",
    )
    _echo(f"\nAll done! Go play {state.current_game_name}!")


def _enforce_on_done(config: Config, state: State) -> None:
    """Run a single enforcement pass during the 'done' command.

    Kills unauthorized game processes, uninstalls unauthorized games,
    and ensures the assigned game is installed.
    """
    if state.current_app_id is None:
        return

    if config.kill_unauthorized_games:
        violations = enforce_allowed_game(
            allowed_app_ids(state),
            kill_unauthorized=True,
        )
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")

    if config.uninstall_other_games:
        count = uninstall_other_games(allowed_app_ids(state))
        if count:
            _echo(f"  Uninstalled {count} unauthorized game(s)")

    if not is_game_installed(state.current_app_id):
        _echo(f"  Re-installing {state.current_game_name}...")
        install_game(
            state.current_app_id,
            state.current_game_name,
            config.steam_id,
            use_steam_protocol=True,
        )

    # Reconcile library: hide non-assigned games and unhide the assigned one.
    # Without this, an interrupted earlier completion can leave the new
    # assigned game hidden and stale games visible.
    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
        if skipped is not None:
            _echo(f"  Library hiding: skipped ({skipped})")
        elif hidden > 0:
            _echo(f"  Library: hid {hidden} games")


def cmd_done(config: Config, state: State) -> None:
    """Check completion, pick next game, uninstall & hide.

    All-in-one command for after finishing a game:
    1. Verify 100% achievements on Steam.
    2. Pick the next game (shortest HLTB leisure+dlc time).
    3. Uninstall all non-assigned games.
    4. Hide all non-assigned games in the Steam library.
    5. Install the newly assigned game.
    """
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    client = SteamAPIClient(config.steam_api_key, config.steam_id)
    game_name = state.current_game_name
    app_id = state.current_app_id

    _echo(f"Checking {game_name} (AppID={app_id})...")
    game = client.refresh_single_game(app_id, game_name)
    if game is None:
        _echo("  Could not fetch achievement data from Steam.")
        return

    _echo(
        f"  Progress: {game.unlocked_achievements}/{game.total_achievements}"
        f" ({game.completion_pct:.1f}%)"
    )

    hltb_cache = load_hltb_cache()
    hours = hltb_cache.get(app_id, -1.0)
    if hours < 0:
        hltb_cache = fetch_hltb_times_cached([(app_id, game_name)])
        hours = hltb_cache.get(app_id, -1.0)
    if hours > 0:
        _echo(f"  HLTB leisure+dlc estimate: {hours:.1f} hours")
    _report_assigned_confidence(app_id, state)

    if not game.is_complete:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"\n  NOT COMPLETE: {remaining} achievements remaining. Keep going!")
        _enforce_on_done(config, state)
        return

    _finalize_completion(config, state, game_name, app_id)
