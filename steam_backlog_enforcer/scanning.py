"""Game scanning, selection, checking, and enforcement daemon."""

from __future__ import annotations

import logging
import time
from typing import Any

from python_pkg.steam_backlog_enforcer._hltb_types import (
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    load_snapshot,
    save_snapshot,
)
from python_pkg.steam_backlog_enforcer.enforcer import (
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
)
from python_pkg.steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

logger = logging.getLogger(__name__)

_TAMPER_CHECK_LIMIT = 3
_MIN_COMP_100_POLLS = 3
_MIN_COUNT_COMP = 15
_MIN_CONFIDENCE_SUM = 18


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
        skip_app_ids=config.skip_app_ids,
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
_PROTONDB_BATCH_SIZE = 20


def _pick_playable_candidate(
    candidates: list[GameInfo],
) -> GameInfo | None:
    """Return the first candidate with an acceptable ProtonDB rating.

    Checks candidates in batches (sorted by HLTB hours, shortest first).
    Games rated silver-or-worse, or gold-trending-down, are skipped.
    """
    offset = 0
    while offset < len(candidates):
        batch = candidates[offset : offset + _PROTONDB_BATCH_SIZE]
        app_ids = [g.app_id for g in batch]
        ratings = fetch_protondb_ratings(app_ids)

        for game in batch:
            rating = ratings.get(game.app_id, ProtonDBRating(app_id=game.app_id))
            if rating.is_playable:
                if offset > 0 or game is not batch[0]:
                    _echo(
                        f"  Skipped {offset + batch.index(game)} game(s) "
                        f"with poor Linux compatibility"
                    )
                return game
            logger.info(
                "Skipping %s (AppID=%d): ProtonDB %s (trending %s)",
                game.name,
                game.app_id,
                rating.tier,
                rating.trending_tier,
            )

        offset += _PROTONDB_BATCH_SIZE

    return None


def pick_next_game(games: list[GameInfo], state: State, config: Config) -> None:
    """Select the next game: shortest completionist time first.

    Games with silver-or-worse ProtonDB ratings (or gold trending
    downward) are automatically skipped as unplayable on Linux.
    """
    skip = set(config.skip_app_ids) | set(state.finished_app_ids)
    candidates = [g for g in games if not g.is_complete and g.app_id not in skip]

    if not candidates:
        _echo(
            "\nNo assignable games found "
            "(HLTB confidence thresholds: comp_100 polls>=3, "
            "count_comp>=15, sum>=18)."
        )
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    # Sort: games with known HLTB time first (shortest), then unknown.
    def sort_key(g: GameInfo) -> tuple[int, float]:
        if g.completionist_hours > 0:
            return (0, g.completionist_hours)
        return (1, g.name.lower().encode().hex().__hash__())

    candidates.sort(key=sort_key)

    chosen, confidence_skipped, linux_skipped = _pick_next_shortest_candidate(
        candidates
    )

    if chosen is None:
        if confidence_skipped > 0 and linux_skipped == 0:
            _echo(
                "\nNo assignable games found "
                "(HLTB confidence thresholds: comp_100 polls>=3, "
                "count_comp>=15, sum>=18)."
            )
        else:
            _echo("\nNo playable games left (all have poor ProtonDB ratings)!")
        state.current_app_id = None
        state.current_game_name = ""
        state.save()
        return

    state.current_app_id = chosen.app_id
    state.current_game_name = chosen.name
    state.save()

    hours_str = ""
    if chosen.completionist_hours > 0:
        hours_str = f" (~{chosen.completionist_hours:.1f}h leisure+dlc)"
    _echo(f"\n>>> ASSIGNED: {chosen.name} (AppID={chosen.app_id}){hours_str}")
    _echo(
        f"    Progress: {chosen.unlocked_achievements}/{chosen.total_achievements}"
        f" ({chosen.completion_pct:.1f}%)"
    )
    _report_poll_confidence(chosen, games, state)

    # Uninstall all other games first, then auto-install the assigned one.
    if config.uninstall_other_games:
        count = uninstall_other_games(chosen.app_id)
        if count:
            _echo(f"\n  Uninstalled {count} non-assigned games")

    if not is_game_installed(chosen.app_id):
        _echo(f"\n  Auto-installing {chosen.name}...")
        install_game(
            chosen.app_id,
            chosen.name,
            config.steam_id,
            use_steam_protocol=True,
        )


def _confidence_fail_reasons(game: GameInfo) -> list[str]:
    """Return threshold-failure reasons for a game's HLTB confidence data."""
    reasons: list[str] = []
    if game.comp_100_count < _MIN_COMP_100_POLLS:
        reasons.append(f"comp_100 polls {game.comp_100_count} < {_MIN_COMP_100_POLLS}")
    if game.count_comp < _MIN_COUNT_COMP:
        reasons.append(f"count_comp {game.count_comp} < {_MIN_COUNT_COMP}")

    total = game.comp_100_count + game.count_comp
    if total < _MIN_CONFIDENCE_SUM:
        reasons.append(f"comp_100+count_comp {total} < {_MIN_CONFIDENCE_SUM}")

    return reasons


def _refresh_candidate_confidence(game: GameInfo) -> None:
    """Refresh confidence metrics for one candidate when cache looks stale.

    Only refreshes when both metrics are missing (0), which typically means
    the game was cached before confidence fields were added.
    """
    if game.comp_100_count > 0 or game.count_comp > 0:
        return

    _refresh_candidate_confidence_batch([game])


def _force_refresh_candidate_confidence(game: GameInfo) -> None:
    """Force-refresh one candidate's confidence metrics from HLTB."""
    _refresh_candidate_confidence_batch([game], force=True)


def _refresh_candidate_confidence_batch(
    candidates: list[GameInfo],
    *,
    force: bool = False,
) -> None:
    """Refresh missing confidence metrics for candidates in one HLTB batch.

    This prevents O(N) one-game API loops when many snapshot entries predate
    confidence fields and therefore have ``comp_100_count==0`` and
    ``count_comp==0``.
    """
    missing = [
        game
        for game in candidates
        if force or (game.comp_100_count == 0 and game.count_comp == 0)
    ]
    if not missing:
        return

    refresh_slice = missing
    if len(refresh_slice) == 1:
        game = refresh_slice[0]
        _echo(f"  Refreshing HLTB confidence for {game.name} (AppID={game.app_id})...")
    else:
        _echo(f"  Refreshing HLTB confidence for {len(refresh_slice)} candidate(s)...")

    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    count_comp = load_hltb_count_comp_cache()
    app_ids = [game.app_id for game in refresh_slice]
    names = [(game.app_id, game.name) for game in refresh_slice]
    prior_hours = {aid: cache.get(aid, -1) for aid in app_ids}

    for aid in app_ids:
        cache.pop(aid, None)
        polls.pop(aid, None)
        count_comp.pop(aid, None)
    save_hltb_cache(cache, polls, count_comp)

    fetch_hltb_confidence_cached(names)

    refreshed_hours = load_hltb_cache()
    refreshed_polls = load_hltb_polls_cache()
    refreshed_count_comp = load_hltb_count_comp_cache()
    for aid, old_hours in prior_hours.items():
        if old_hours > 0 and refreshed_hours.get(aid, -1) <= 0:
            refreshed_hours[aid] = old_hours
    save_hltb_cache(refreshed_hours, refreshed_polls, refreshed_count_comp)

    for game in refresh_slice:
        game.comp_100_count = refreshed_polls.get(game.app_id, 0)
        game.count_comp = refreshed_count_comp.get(game.app_id, 0)


def _filter_hltb_confident_candidates(
    candidates: list[GameInfo],
) -> list[GameInfo]:
    """Keep only candidates that satisfy HLTB confidence thresholds."""
    _refresh_candidate_confidence_batch(candidates)

    kept: list[GameInfo] = []
    for game in candidates:
        reasons = _confidence_fail_reasons(game)
        if reasons:
            _echo(
                f"  Skipping {game.name} (AppID={game.app_id}): "
                f"HLTB confidence too low ({'; '.join(reasons)})"
            )
            continue
        kept.append(game)
    return kept


def _candidate_passes_hltb_confidence(game: GameInfo) -> bool:
    """Return True if candidate passes confidence with cache-first behavior.

    Only refreshes when confidence fields are missing (both zero), which keeps
    normal runs cache-friendly and avoids repeated refetches for known
    low-confidence entries.
    """
    reasons = _confidence_fail_reasons(game)
    if not reasons:
        return True

    # Re-check once when confidence fields are missing in cache.
    _refresh_candidate_confidence(game)
    reasons = _confidence_fail_reasons(game)
    if reasons:
        _echo(
            f"  Skipping {game.name} (AppID={game.app_id}): "
            f"HLTB confidence too low ({'; '.join(reasons)})"
        )
        return False
    return True


def _pick_next_shortest_candidate(
    candidates: list[GameInfo],
) -> tuple[GameInfo | None, int, int]:
    """Pick next game by checking confidence one candidate at a time.

    The list must be pre-sorted by desired priority (shortest first).
    """
    confidence_skipped = 0
    linux_skipped = 0
    for game in candidates:
        if not _candidate_passes_hltb_confidence(game):
            confidence_skipped += 1
            continue

        # Reuse existing ProtonDB compatibility gate for one candidate.
        playable = _pick_playable_candidate([game])
        if playable is not None:
            if linux_skipped > 0:
                _echo(
                    f"  Skipped {linux_skipped} game(s) with poor Linux compatibility"
                )
            return playable, confidence_skipped, linux_skipped
        linux_skipped += 1

    if linux_skipped > 0:
        _echo(f"  Skipped {linux_skipped} game(s) with poor Linux compatibility")
    return None, confidence_skipped, linux_skipped


def _backfill_polls_for_finished(
    state: State,
    games: list[GameInfo],
) -> dict[int, int]:
    """Lazily fetch poll counts for already-finished games missing them.

    Reads the polls cache, identifies finished games whose poll count is
    still ``0`` (typically because the cache predates the polls schema),
    and triggers a one-shot HLTB search to backfill them. Returns the
    refreshed polls cache.
    """
    polls_cache = load_hltb_polls_cache()
    name_by_id = {g.app_id: g.name for g in games}
    missing = [
        (aid, name_by_id[aid])
        for aid in state.finished_app_ids
        if aid in name_by_id and polls_cache.get(aid, 0) == 0
    ]
    if not missing:
        return polls_cache

    logger.info(
        "Backfilling HLTB poll counts for %d already-finished games...",
        len(missing),
    )
    # Force a fresh search by removing the hours entries we want to refetch.
    # (fetch_hltb_times_cached skips entries already in the hours cache.)
    cache = load_hltb_cache()
    preserved_hours = {aid: cache[aid] for aid, _ in missing if aid in cache}
    for aid, _name in missing:
        cache.pop(aid, None)
    save_hltb_cache(cache, polls_cache)

    fetch_hltb_confidence_cached(missing)

    # Restore any previously-known hours that the refetch may have replaced
    # with a worse match (we trust prior leisure+dlc estimates).
    refreshed_hours = load_hltb_cache()
    refreshed_polls = load_hltb_polls_cache()
    for aid, prior_hours in preserved_hours.items():
        if prior_hours > 0 and refreshed_hours.get(aid, -1) <= 0:
            refreshed_hours[aid] = prior_hours
    save_hltb_cache(refreshed_hours, refreshed_polls)
    return refreshed_polls


def _report_poll_confidence(
    chosen: GameInfo,
    games: list[GameInfo],
    state: State,
) -> None:
    """Print HLTB poll-count confidence info for the just-assigned game.

    Shows the chosen game's ``comp_100_count`` (number of polled
    completionist times on HowLongToBeat) and the historical minimum
    among the user's previously-finished games. Marks a new historical
    low so the user can be skeptical of unreliable estimates.
    """
    polls_cache = _backfill_polls_for_finished(state, games)
    chosen_polls = polls_cache.get(chosen.app_id, chosen.comp_100_count)
    chosen.comp_100_count = chosen_polls

    finished_polls = [
        (polls_cache[aid], aid)
        for aid in state.finished_app_ids
        if polls_cache.get(aid, 0) > 0
    ]
    if not finished_polls:
        _echo(f"    HLTB confidence: {chosen_polls} polled completionist times")
        return

    min_polls, min_aid = min(finished_polls)
    name_by_id = {g.app_id: g.name for g in games}
    min_name = name_by_id.get(min_aid, f"AppID={min_aid}")

    warning = ""
    if 0 < chosen_polls < min_polls:
        warning = "  ⚠ NEW LOW — estimate may be unreliable"
    elif chosen_polls == 0:
        warning = "  ⚠ no polls recorded — estimate may be unreliable"

    _echo(f"    HLTB confidence: {chosen_polls} polled completionist times{warning}")
    _echo(f"    Historical min among finished: {min_polls} ({min_name})")


# ──────────────────────────────────────────────────────────────
# Checking & tampering detection
# ──────────────────────────────────────────────────────────────


def do_check(config: Config, state: State) -> None:
    """Check assigned game completion status; detect tampering."""
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
        state.finished_app_ids.append(state.current_app_id)
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
    if app_id == state.current_app_id:
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
