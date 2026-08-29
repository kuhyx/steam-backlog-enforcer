"""Game scanning, selection, checking, and enforcement daemon."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_types import (
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
)
from steam_backlog_enforcer._pick_completion import mark_finished, report_completion
from steam_backlog_enforcer._scanning_assign import (
    _NO_CONF_MSG,
    _assign_chosen_game,
    _pick_next_game_sequential,
    _prompt_user_pick,
)
from steam_backlog_enforcer._scanning_candidates import (
    _collect_qualified_candidates,
    _collect_top_candidates,
    _pick_next_shortest_candidate,
    _pick_playable_candidate,
    _sort_key,
)
from steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _report_poll_confidence,
)
from steam_backlog_enforcer._scanning_tampering import (
    _check_game_tampering,
    detect_tampering,
)
from steam_backlog_enforcer._snapshot import load_snapshot, save_snapshot
from steam_backlog_enforcer.enforcer import (
    send_notification,
)
from steam_backlog_enforcer.game_install import (
    _echo,
)
from steam_backlog_enforcer.hltb import (
    fetch_hltb_times_cached,
)
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer.config import Config, State

# These helpers moved to the _scanning_* leaf modules, but callers and tests
# have always imported them from here. mypy's --no-implicit-reexport needs
# them listed explicitly.
__all__ = [
    "_check_game_tampering",
    "_collect_top_candidates",
    "_pick_next_shortest_candidate",
    "_pick_playable_candidate",
    "detect_tampering",
]

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Scanning & game selection
# ──────────────────────────────────────────────────────────────


def do_scan(config: Config, state: State) -> list[GameInfo]:
    """Full library scan: Steam API + HLTB times."""
    client = SteamAPIClient(config.steam_api_key, config.steam_id)

    start = time.time()
    done_count = 0

    def progress(current: int, total: int) -> None:
        nonlocal done_count
        done_count = current
        if current % 50 == 0 or current == total:
            _echo(f"\r  Scanning achievements: {current}/{total}", end="", flush=True)

    _echo("Scanning Steam library...")
    games = client.build_game_list(
        progress_callback=progress,
    )
    elapsed = time.time() - start
    _echo(f"\n  Scanned {len(games)} games with achievements in {elapsed:.1f}s")

    # Fetch HLTB times (cached).
    incomplete = [(g.app_id, g.name) for g in games if not g.is_complete]
    if incomplete:
        _echo(f"Fetching HLTB completion times for {len(incomplete)} games...")

        def hltb_progress(done: int, total: int, found: int, name: str) -> None:
            pct = done * 100 // total
            bar_w = 30
            filled = bar_w * done // total
            bar = "█" * filled + "░" * (bar_w - filled)
            _echo(
                f"\r  HLTB [{bar}] {done}/{total} ({pct}%) "
                f"| {found} found | {name[:30]:<30s}",
                end="",
                flush=True,
            )

        hltb_cache = fetch_hltb_times_cached(incomplete, progress_cb=hltb_progress)
        _echo("")  # newline after progress bar
        polls_cache = load_hltb_polls_cache()
        count_comp_cache = load_hltb_count_comp_cache()
        for g in games:
            hours = hltb_cache.get(g.app_id, -1)
            g.completionist_hours = hours
            g.comp_100_count = polls_cache.get(g.app_id, 0)
            g.count_comp = count_comp_cache.get(g.app_id, 0)
        found = sum(1 for h in hltb_cache.values() if h > 0)
        _echo(f"  HLTB data: {found} games have completion estimates")

    # Save snapshot.
    save_snapshot([g.to_snapshot() for g in games])

    complete = [g for g in games if g.is_complete]
    incomplete_games = [g for g in games if not g.is_complete]
    _echo(f"\nResults: {len(complete)} complete, {len(incomplete_games)} incomplete")

    # Auto-pick a game if none assigned.
    if state.current_app_id is None:
        pick_next_game(games, state, config)
    else:
        # Show confidence info for the already-assigned game too.
        current = next(
            (g for g in games if g.app_id == state.current_app_id),
            None,
        )
        if current is not None:
            _echo(f"\n>>> CURRENT: {current.name} (AppID={current.app_id})")
            _report_poll_confidence(current, games, state)

    return games


# How many candidates to check per ProtonDB batch.


def pick_next_game(
    games: list[GameInfo],
    state: State,
    config: Config,
    *,
    on_select: Callable[[GameInfo], bool] | None = None,
) -> None:
    """Present a ranked list of eligible games and let the user pick one.

    Games are ranked by shortest completionist time first.  Games with
    silver-or-worse ProtonDB ratings (or gold trending downward) are
    excluded as unplayable on Linux.

    If ``on_select`` is provided, the legacy 10-candidate picker is
    bypassed: the function instead presents the shortest playable
    candidate to ``on_select`` (typically a yes/no prompt) and, if the
    callback rejects it, records a 7-day skip and re-evaluates.
    """
    if on_select is not None:
        _pick_next_game_sequential(games, state, config, on_select)
        return

    skip = set(state.finished_app_ids) | state.active_skipped_ids()
    candidates = [g for g in games if not g.is_complete and g.app_id not in skip]

    if not candidates:
        _echo(_NO_CONF_MSG)
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    candidates.sort(key=_sort_key)
    _apply_cached_confidence_to_candidates(candidates)
    qualified, confidence_skipped, linux_skipped = _collect_qualified_candidates(
        candidates
    )

    if not qualified:
        _echo(
            _NO_CONF_MSG
            if confidence_skipped > 0 and linux_skipped == 0
            else "\nNo playable games left (all have poor ProtonDB ratings)!"
        )
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    idx = _prompt_user_pick(qualified)
    _assign_chosen_game(qualified[idx], games, state, config)


# ──────────────────────────────────────────────────────────────
# Checking & tampering detection
# ──────────────────────────────────────────────────────────────


def do_check(config: Config, state: State) -> None:
    """Check assigned game completion status; detect tampering."""
    report_completion(config, state)
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    client = SteamAPIClient(config.steam_api_key, config.steam_id)
    _echo(f"Checking {state.current_game_name} (AppID={state.current_app_id})...")

    game = client.refresh_single_game(state.current_app_id, state.current_game_name)
    if game is None:
        _echo("  Could not fetch achievement data.")
        return

    _echo(
        f"  Progress: {game.unlocked_achievements}/{game.total_achievements}"
        f" ({game.completion_pct:.1f}%)"
    )

    if game.is_complete:
        _echo(f"\n  COMPLETED: {state.current_game_name}!")
        mark_finished(state, state.current_app_id)
        send_notification(
            "Game Complete!",
            f"You finished {state.current_game_name}! Picking next game...",
        )

        # Load snapshot and pick next.
        snapshot_data = load_snapshot()
        if snapshot_data:
            games = [GameInfo.from_snapshot(d) for d in snapshot_data]
            pick_next_game(games, state, config)
        else:
            state.current_app_id = None
            state.current_game_name = ""
            state.save()
            _echo("  Run 'scan' to pick the next game.")
    else:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"  {remaining} achievements remaining. Keep going!")

    # Tampering detection on snapshot.
    detect_tampering(config, state)
