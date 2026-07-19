"""Done-flow helpers and cmd_done command for Steam Backlog Enforcer."""

from __future__ import annotations

import logging
import sys

from steam_backlog_enforcer._enforce_loop import get_all_owned_app_ids
from steam_backlog_enforcer.config import Config, State, load_snapshot
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
    fetch_hltb_confidence_cached,
    fetch_hltb_times_cached,
    load_hltb_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.library_hider import try_hide_other_games
from steam_backlog_enforcer.scanning import pick_next_game
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

_REASSIGN_REFRESH_LIMIT = 50
_SKIP_DAYS = 7
logger = logging.getLogger(__name__)


def _prompt_keep_or_skip(game: GameInfo) -> bool:
    """Ask the user whether to keep the freshly-picked ``game``.

    Returns ``True`` to accept the pick, ``False`` to skip it (which the
    caller will translate into a 7-day skip entry on ``State``). When
    stdin is not a TTY (e.g. background daemon, piped invocation), the
    pick is accepted silently to preserve the legacy non-interactive
    behaviour.
    """
    if not sys.stdin.isatty():
        return True
    hours_str = ""
    if game.completionist_hours > 0:
        hours_str = f" (~{game.completionist_hours:.1f}h leisure+dlc)"
    _echo(f"\n  Next pick: {game.name} (AppID={game.app_id}){hours_str}")
    while True:
        try:
            answer = (
                input(f"  Keep this game? [Y/n] (n = skip for {_SKIP_DAYS} days): ")
                .strip()
                .lower()
            )
        except EOFError:
            return True
        if answer in {"", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        _echo("  Please answer 'y' or 'n'.")


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
    skip = set(state.finished_app_ids) | state.active_skipped_ids()
    _refresh_uncached_shortlist_hours(games, hltb_cache, skip)
    _apply_cached_hours_to_games(games, hltb_cache)
    pick_next_game(games, state, config, on_select=_prompt_keep_or_skip)

    if state.current_app_id is None:
        _echo("  No more games to assign!")
        return

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden, skipped = try_hide_other_games(owned_ids, state.current_app_id)
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
        hidden, skipped = try_hide_other_games(owned_ids, state.current_app_id)
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
