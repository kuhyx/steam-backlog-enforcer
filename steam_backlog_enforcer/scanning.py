"""Game scanning, selection, checking, and enforcement daemon."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import TYPE_CHECKING, Any

from python_pkg.steam_backlog_enforcer._hltb_types import (
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
)
from python_pkg.steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _candidate_passes_hltb_confidence,
    _report_poll_confidence,
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
    fetch_hltb_times_cached,
)
from python_pkg.steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_TAMPER_CHECK_LIMIT = 3

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


_PICK_LIST_SIZE = 10

_NO_CONF_MSG = (
    "\nNo assignable games found "
    "(HLTB confidence thresholds: comp_100 polls>=3, "
    "count_comp>=15, sum>=18)."
)


def _sort_key(g: GameInfo) -> tuple[int, float]:
    """Sort by known HLTB time (shortest first), then unknown games."""
    if g.completionist_hours > 0:
        return (0, g.completionist_hours)
    return (1, g.name.lower().encode().hex().__hash__())


def _collect_qualified_candidates(
    candidates: list[GameInfo],
) -> tuple[list[GameInfo], int, int]:
    """Collect up to _PICK_LIST_SIZE playable, HLTB-confident candidates."""
    qualified: list[GameInfo] = []
    confidence_skipped = 0
    linux_skipped = 0
    for game in candidates:
        if len(qualified) >= _PICK_LIST_SIZE:
            break
        if not _candidate_passes_hltb_confidence(game):
            confidence_skipped += 1
            continue
        playable = _pick_playable_candidate([game])
        if playable is not None:
            qualified.append(playable)
        else:
            linux_skipped += 1
    return qualified, confidence_skipped, linux_skipped


def _prompt_user_pick(qualified: list[GameInfo]) -> int:
    """Present numbered list, return 0-based index of user's choice."""
    for i, g in enumerate(qualified, 1):
        hours_str = (
            f" (~{g.completionist_hours:.1f}h)" if g.completionist_hours > 0 else ""
        )
        _echo(f"  {i}. {g.name} (AppID={g.app_id}){hours_str}")
    while True:
        raw = input("Select game number: ")
        try:
            idx = int(raw)
        except ValueError:
            _echo(f"Invalid input: {raw!r}")
            continue
        if idx < 1 or idx > len(qualified):
            _echo(f"Out of range: {idx}")
            continue
        return idx - 1


def _assign_chosen_game(
    chosen: GameInfo,
    games: list[GameInfo],
    state: State,
    config: Config,
) -> None:
    """Save assignment, announce it, and handle install/uninstall."""
    state.current_app_id = chosen.app_id
    state.current_game_name = chosen.name
    if not state.enforcement_started_at:
        state.enforcement_started_at = datetime.now(timezone.utc).isoformat()
    state.save()
    hours_str = (
        f" (~{chosen.completionist_hours:.1f}h leisure+dlc)"
        if chosen.completionist_hours > 0
        else ""
    )
    _echo(f"\n>>> ASSIGNED: {chosen.name} (AppID={chosen.app_id}){hours_str}")
    _echo(
        f"    Progress: {chosen.unlocked_achievements}/{chosen.total_achievements}"
        f" ({chosen.completion_pct:.1f}%)"
    )
    _report_poll_confidence(chosen, games, state)
    if config.uninstall_other_games:
        count = uninstall_other_games(chosen.app_id)
        if count:
            _echo(f"\n  Uninstalled {count} non-assigned games")
    if not is_game_installed(chosen.app_id):
        _echo(f"\n  Auto-installing {chosen.name}...")
        install_game(
            chosen.app_id, chosen.name, config.steam_id, use_steam_protocol=True
        )


def _pick_next_game_sequential(
    games: list[GameInfo],
    state: State,
    config: Config,
    on_select: Callable[[GameInfo], bool],
) -> None:
    """Pick the next-shortest playable game, asking the user per candidate.

    ``on_select`` is called with each prospective pick. Returning ``True``
    accepts the assignment; returning ``False`` records a 7-day skip on
    ``state`` for that game and the next candidate is evaluated.
    """
    while True:
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
        chosen, confidence_skipped, linux_skipped = _pick_next_shortest_candidate(
            candidates
        )
        if chosen is None:
            _echo(
                _NO_CONF_MSG
                if confidence_skipped > 0 and linux_skipped == 0
                else "\nNo playable games left (all have poor ProtonDB ratings)!"
            )
            state.current_app_id = None
            state.current_game_name = ""
            state.save()
            return

        if not on_select(chosen):
            state.skip_for_days(chosen.app_id, 7)
            state.save()
            _echo(f"\n  Skipped {chosen.name} for 7 days; picking next...")
            continue

        _assign_chosen_game(chosen, games, state, config)
        return


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


def _collect_top_candidates(
    candidates: list[GameInfo],
    n: int = 3,
) -> tuple[list[GameInfo], int, int]:
    """Collect up to n candidates that pass the Linux compatibility gate.

    Args:
        candidates: Pre-sorted list of candidate games.
        n: Maximum number of qualified games to collect.

    Returns:
        Tuple of (qualified_list, conf_skipped, linux_skipped).
    """
    qualified: list[GameInfo] = []
    linux_skipped = 0
    for game in candidates:
        if len(qualified) >= n:
            break
        playable = _pick_playable_candidate([game])
        if playable is not None:
            qualified.append(playable)
        else:
            linux_skipped += 1
    if linux_skipped > 0:
        _echo(f"  Skipped {linux_skipped} game(s) with poor Linux compatibility")
    return qualified, 0, linux_skipped


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
