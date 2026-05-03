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
    fetch_hltb_confidence_cached,
    fetch_hltb_times_cached,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.library_hider import hide_other_games
from python_pkg.steam_backlog_enforcer.scanning import (
    _confidence_fail_reasons,
    _pick_next_shortest_candidate,
    _refresh_candidate_confidence,
    pick_next_game,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

_REASSIGN_REFRESH_LIMIT = 50


def _backfill_polls_for_finished(
    state: State,
    extra_app_id: int | None = None,
) -> dict[int, int]:
    """Lazily fetch poll counts for already-finished games missing them.

    If ``extra_app_id`` is provided and its poll count is missing, it is
    refreshed alongside finished games (used to populate polls for the
    currently-assigned game on first run after the schema upgrade).
    """
    polls_cache = load_hltb_polls_cache()
    snapshot_data = load_snapshot() or []
    name_by_id = {d["app_id"]: d["name"] for d in snapshot_data}
    candidate_ids = list(state.finished_app_ids)
    if extra_app_id is not None and polls_cache.get(extra_app_id, 0) == 0:
        candidate_ids.append(extra_app_id)
    missing = [
        (aid, name_by_id[aid])
        for aid in candidate_ids
        if aid in name_by_id and polls_cache.get(aid, 0) == 0
    ]
    if not missing:
        return polls_cache

    _echo(f"  Backfilling HLTB poll counts for {len(missing)} game(s)...")
    cache = load_hltb_cache()
    preserved_hours = {aid: cache[aid] for aid, _ in missing if aid in cache}
    for aid, _name in missing:
        cache.pop(aid, None)
    save_hltb_cache(cache, polls_cache)

    fetch_hltb_confidence_cached(missing)

    refreshed_hours = load_hltb_cache()
    refreshed_polls = load_hltb_polls_cache()
    for aid, prior_hours in preserved_hours.items():
        if prior_hours > 0 and refreshed_hours.get(aid, -1) <= 0:
            refreshed_hours[aid] = prior_hours
    save_hltb_cache(refreshed_hours, refreshed_polls)
    return refreshed_polls


def _report_assigned_confidence(
    app_id: int,
    state: State,
) -> None:
    """Print HLTB poll-count confidence for the currently-assigned game."""
    polls_cache = _backfill_polls_for_finished(state, extra_app_id=app_id)
    chosen_polls = polls_cache.get(app_id, 0)

    finished_polls = [
        (polls_cache[aid], aid)
        for aid in state.finished_app_ids
        if polls_cache.get(aid, 0) > 0 and aid != app_id
    ]
    snapshot_data = load_snapshot() or []
    name_by_id = {d["app_id"]: d["name"] for d in snapshot_data}

    warning = ""
    if finished_polls:
        min_polls = min(p for p, _ in finished_polls)
        if 0 < chosen_polls < min_polls:
            warning = "  ⚠ NEW LOW — estimate may be unreliable"
        elif chosen_polls == 0:
            warning = "  ⚠ no polls recorded — estimate may be unreliable"
    elif chosen_polls == 0:
        warning = "  ⚠ no polls recorded — estimate may be unreliable"

    _echo(f"  HLTB confidence: {chosen_polls} polled completionist times{warning}")
    if finished_polls:
        min_polls, min_aid = min(finished_polls)
        min_name = name_by_id.get(min_aid, f"AppID={min_aid}")
        _echo(f"  Historical min among finished: {min_polls} ({min_name})")


def _apply_cached_hours_to_games(
    games: list[GameInfo],
    hltb_cache: dict[int, float],
) -> None:
    """Overlay cached HLTB hours onto games (including cached misses)."""
    for game in games:
        if game.app_id in hltb_cache:
            game.completionist_hours = hltb_cache[game.app_id]


def _apply_cached_confidence_to_games(games: list[GameInfo]) -> None:
    """Overlay cached confidence counters onto snapshot-backed game objects."""
    polls_cache = load_hltb_polls_cache()
    count_comp_cache = load_hltb_count_comp_cache()
    for game in games:
        if game.app_id in polls_cache:
            game.comp_100_count = polls_cache[game.app_id]
        if game.app_id in count_comp_cache:
            game.count_comp = count_comp_cache[game.app_id]


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


def _should_reassign_candidate(
    playable: GameInfo,
    current_hours: float,
    *,
    force_reassign: bool,
) -> bool:
    """Return whether a playable candidate should trigger reassignment."""
    if force_reassign:
        return True
    if current_hours > 0:
        return playable.completionist_hours < current_hours
    return True


def _echo_reassign_decision(
    playable: GameInfo,
    current_hours: float,
    current_fail_reasons: list[str],
    *,
    force_reassign: bool,
) -> None:
    """Emit a human-readable reassignment reason."""
    if force_reassign:
        _echo(
            f"\n  Reassigning: current game confidence too low "
            f"({'; '.join(current_fail_reasons)})"
        )
        return
    if current_hours > 0:
        _echo(
            f"\n  Reassigning: {playable.name} is shorter"
            f" (~{playable.completionist_hours:.1f}h vs ~{current_hours:.1f}h)"
        )
        return
    _echo(
        f"\n  Reassigning: current game has no usable HLTB time; "
        f"picked {playable.name} (~{playable.completionist_hours:.1f}h)"
    )


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
    _apply_cached_confidence_to_games(all_games)
    current_game = next((g for g in all_games if g.app_id == app_id), None)
    if current_game is not None and _confidence_fail_reasons(current_game):
        _refresh_candidate_confidence(current_game)
    current_fail_reasons = (
        _confidence_fail_reasons(current_game) if current_game is not None else []
    )
    force_reassign = bool(current_fail_reasons)
    candidates = [
        g
        for g in all_games
        if not g.is_complete and g.app_id not in skip and g.completionist_hours > 0
    ]
    if not force_reassign and hours > 0:
        candidates = [g for g in candidates if g.completionist_hours < hours]

    candidates.sort(key=lambda g: g.completionist_hours)
    candidates = [c for c in candidates if c.app_id != app_id]
    if not candidates:
        return False

    playable, _confidence_skipped, _linux_skipped = _pick_next_shortest_candidate(
        candidates,
    )
    if playable is None:
        return False

    if not _should_reassign_candidate(
        playable,
        hours,
        force_reassign=force_reassign,
    ):
        return False
    _echo_reassign_decision(
        playable,
        hours,
        current_fail_reasons,
        force_reassign=force_reassign,
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

    # Reconcile library: hide non-assigned games and unhide the assigned one.
    # Without this, an interrupted earlier completion can leave the new
    # assigned game hidden and stale games visible.
    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
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

    if _try_reassign_shorter_game(hltb_cache, app_id, hours, state, config):
        return

    if not game.is_complete:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"\n  NOT COMPLETE: {remaining} achievements remaining. Keep going!")
        _enforce_on_done(config, state)
        return

    _finalize_completion(config, state, game_name, app_id)
