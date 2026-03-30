"""Done-flow helpers and cmd_done command for Steam Backlog Enforcer."""

from __future__ import annotations

from python_pkg.steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from python_pkg.steam_backlog_enforcer.config import Config, State, load_snapshot
from python_pkg.steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from python_pkg.steam_backlog_enforcer.game_install import (
    _echo,
    install_game,
    is_game_installed,
    uninstall_other_games,
)
from python_pkg.steam_backlog_enforcer.hltb import (
    fetch_hltb_times_cached,
    load_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.library_hider import hide_other_games
from python_pkg.steam_backlog_enforcer.scanning import (
    _pick_playable_candidate,
    pick_next_game,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

_REASSIGN_REFRESH_LIMIT = 50


def _apply_cached_hours_to_games(
    games: list[GameInfo],
    hltb_cache: dict[int, float],
) -> None:
    """Overlay cached HLTB hours onto games (including cached misses)."""
    for game in games:
        if game.app_id in hltb_cache:
            game.completionist_hours = hltb_cache[game.app_id]


def _refresh_uncached_shortlist_hours(
    games: list[GameInfo],
    hltb_cache: dict[int, float],
    skip: set[int],
    *,
    upper_bound_hours: float | None = None,
) -> None:
    """Refresh likely-short uncached games to avoid stale snapshot decisions."""
    shorter_uncached = [
        (g.app_id, g.name)
        for g in sorted(
            (
                game
                for game in games
                if not game.is_complete
                and game.app_id not in skip
                and game.completionist_hours > 0
                and game.app_id not in hltb_cache
                and (
                    upper_bound_hours is None
                    or game.completionist_hours < upper_bound_hours
                )
            ),
            key=lambda game: game.completionist_hours,
        )[:_REASSIGN_REFRESH_LIMIT]
    ]
    if shorter_uncached:
        refreshed = fetch_hltb_times_cached(shorter_uncached)
        hltb_cache.update(refreshed)


def _try_reassign_shorter_game(
    hltb_cache: dict[int, float],
    app_id: int,
    hours: float,
    state: State,
    config: Config,
) -> bool:
    """Check if a shorter game is available and reassign if so."""
    snapshot_data = load_snapshot()
    if not snapshot_data:
        return False
    all_games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    skip = set(config.skip_app_ids) | set(state.finished_app_ids)
    _refresh_uncached_shortlist_hours(
        all_games,
        hltb_cache,
        skip,
        upper_bound_hours=hours,
    )
    _apply_cached_hours_to_games(all_games, hltb_cache)
    candidates = [
        g
        for g in all_games
        if not g.is_complete and g.app_id not in skip and g.completionist_hours > 0
    ]
    candidates.sort(key=lambda g: g.completionist_hours)
    if not candidates or candidates[0].app_id == app_id:
        return False
    # Filter out Linux-incompatible games before deciding to reassign.
    playable = _pick_playable_candidate(
        [c for c in candidates if c.app_id != app_id],
    )
    if playable is None or playable.completionist_hours >= hours:
        return False
    _echo(
        f"\n  Reassigning: {playable.name} is shorter"
        f" (~{playable.completionist_hours:.1f}h vs ~{hours:.1f}h)"
    )
    pick_next_game(all_games, state, config)

    if state.current_app_id is not None:
        owned_ids = get_all_owned_app_ids(config)
        if owned_ids:
            hidden = hide_other_games(owned_ids, state.current_app_id)
            if hidden > 0:
                _echo(f"\n  Library: hid {hidden} games")

    return True


def _finalize_completion(
    config: Config,
    state: State,
    game_name: str,
    app_id: int,
) -> None:
    """Mark game complete, pick next, hide non-assigned games, notify."""
    _echo(f"\n  COMPLETED: {game_name}!")
    state.finished_app_ids.append(app_id)

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
    skip = set(config.skip_app_ids) | set(state.finished_app_ids)
    _refresh_uncached_shortlist_hours(games, hltb_cache, skip)
    _apply_cached_hours_to_games(games, hltb_cache)
    pick_next_game(games, state, config)

    if state.current_app_id is None:
        _echo("  No more games to assign!")
        return

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
            _echo(f"\n  Library: hid {hidden} games")

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
            state.current_app_id,
            kill_unauthorized=True,
        )
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")

    if config.uninstall_other_games:
        count = uninstall_other_games(state.current_app_id)
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

    if _try_reassign_shorter_game(hltb_cache, app_id, hours, state, config):
        return

    if not game.is_complete:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"\n  NOT COMPLETE: {remaining} achievements remaining. Keep going!")
        _enforce_on_done(config, state)
        return

    _finalize_completion(config, state, game_name, app_id)
