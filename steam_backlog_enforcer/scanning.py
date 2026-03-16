"""Game scanning, selection, checking, and enforcement daemon."""

from __future__ import annotations

import logging
import time
from typing import Any

from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    load_snapshot,
    save_snapshot,
)
from python_pkg.steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from python_pkg.steam_backlog_enforcer.game_install import (
    PROTECTED_APP_IDS,
    _echo,
    get_installed_games,
    install_game,
    is_game_installed,
    uninstall_game,
    uninstall_other_games,
)
from python_pkg.steam_backlog_enforcer.hltb import fetch_hltb_times_cached
from python_pkg.steam_backlog_enforcer.library_hider import hide_other_games
from python_pkg.steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient
from python_pkg.steam_backlog_enforcer.store_blocker import block_store

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
        for g in games:
            hours = hltb_cache.get(g.app_id, -1)
            g.completionist_hours = hours
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
        _echo("\nCongratulations! All games are complete!")
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

    # Filter out Linux-incompatible games via ProtonDB.
    chosen = _pick_playable_candidate(candidates)

    if chosen is None:
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
        hours_str = f" (~{chosen.completionist_hours:.1f}h to 100%)"
    _echo(f"\n>>> ASSIGNED: {chosen.name} (AppID={chosen.app_id}){hours_str}")
    _echo(
        f"    Progress: {chosen.unlocked_achievements}/{chosen.total_achievements}"
        f" ({chosen.completion_pct:.1f}%)"
    )

    # Uninstall all other games first, then auto-install the assigned one.
    if config.uninstall_other_games:
        count = uninstall_other_games(chosen.app_id)
        if count:
            _echo(f"\n  Uninstalled {count} non-assigned games")

    if not is_game_installed(chosen.app_id):
        _echo(f"\n  Auto-installing {chosen.name}...")
        install_game(chosen.app_id, chosen.name, config.steam_id)


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


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def get_all_owned_app_ids(config: Config) -> list[int]:
    """Get all owned game app IDs from the snapshot or Steam API."""
    snapshot = load_snapshot()
    if snapshot:
        return [d["app_id"] for d in snapshot]

    # Fall back to a quick API call.
    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        return [g["appid"] for g in owned]
    except (OSError, RuntimeError, ValueError):
        logger.warning("Could not fetch owned game list for hiding.")
        return []


# ──────────────────────────────────────────────────────────────
# Enforce mode (daemon loop)
# ──────────────────────────────────────────────────────────────

# How often the enforce loop runs (seconds).
ENFORCE_INTERVAL = 3


def _guard_installed_games(allowed_app_id: int | None) -> int:
    """Remove any unauthorized game manifests + files.  Runs every loop.

    Returns number of games removed this pass.
    """
    installed = get_installed_games()
    count = 0
    for app_id, name in installed:
        if app_id == allowed_app_id:
            continue
        if app_id in PROTECTED_APP_IDS:
            continue

        logger.warning(
            "Unauthorized game detected — removing: %s (AppID=%d)", name, app_id
        )
        if uninstall_game(app_id, name):
            count += 1
            send_notification(
                "Game Removed!",
                f"Uninstalled {name} (AppID={app_id}). "
                f"Only the assigned game is allowed.",
            )
    return count


def _enforce_setup(config: Config, state: State) -> None:
    """Perform initial setup for enforcement mode.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    # Initial store block.
    if config.block_store:
        if block_store():
            _echo("  Steam store: BLOCKED")
        else:
            _echo("  Steam store: FAILED (need sudo?)")

    # Initial cleanup.
    if config.uninstall_other_games:
        _echo("  Uninstalling non-assigned games...")
        count = uninstall_other_games(state.current_app_id)
        _echo(f"  Uninstalled {count} games")

    # Auto-install the assigned game.
    _enforce_auto_install(config, state)

    # Hide all other games in the Steam library.
    _enforce_hide_games(config, state)


def _enforce_auto_install(config: Config, state: State) -> None:
    """Auto-install the assigned game if not already installed.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    app_id = state.current_app_id
    if app_id is None:
        return
    if not is_game_installed(app_id):
        _echo(f"  Auto-installing {state.current_game_name}...")
        if install_game(app_id, state.current_game_name, config.steam_id):
            send_notification(
                "Game Installing",
                f"{state.current_game_name} is being downloaded.",
            )
        else:
            _echo("  Could not auto-install. Install manually from Steam.")
    else:
        _echo(f"  Assigned game already installed: {state.current_game_name}")


def _enforce_hide_games(config: Config, state: State) -> None:
    """Hide non-assigned games in the Steam library.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
            _echo(f"  Library: hid {hidden} games (only assigned game visible)")
        else:
            _echo("  Library: games already hidden")
    else:
        _echo("  Library hiding: skipped (no owned game list — run 'scan' first)")


def _enforce_loop_iteration(config: Config, state: State) -> None:
    """Perform one iteration of the enforcement loop.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    # A) Kill unauthorized game processes.
    if config.kill_unauthorized_games:
        violations = enforce_allowed_game(
            state.current_app_id,
            kill_unauthorized=True,
        )
        for pid, app_id in violations:
            _echo(f"  Killed unauthorized game: AppID={app_id} (PID={pid})")
            send_notification(
                "Game Blocked!",
                f"Killed unauthorized game (AppID={app_id}). "
                f"Focus on {state.current_game_name}!",
            )

    # B) Remove any newly-installed unauthorized games.
    if config.uninstall_other_games:
        removed = _guard_installed_games(state.current_app_id)
        if removed > 0:
            _echo(f"  Guard removed {removed} unauthorized game(s)")

    # C) Re-install assigned game if it was somehow removed.
    app_id = state.current_app_id
    if app_id is not None and not is_game_installed(app_id):
        logger.info(
            "Assigned game disappeared — re-installing %s",
            state.current_game_name,
        )
        install_game(
            app_id,
            state.current_game_name,
            config.steam_id,
        )


def do_enforce(config: Config, state: State) -> None:
    """Run the enforcer: block store, uninstall other games, kill processes.

    This is a persistent loop that continuously:
    1. Keeps the Steam store blocked.
    2. Removes any newly-installed unauthorized games.
    3. Auto-installs the assigned game if missing.
    4. Kills any running unauthorized game processes.
    """
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    _echo(f"Enforcing: {state.current_game_name} (AppID={state.current_app_id})")
    _enforce_setup(config, state)

    _echo(f"  Enforce loop: ACTIVE (every {ENFORCE_INTERVAL}s)")
    _echo("  Guarding: processes + installs + store")
    _echo("  Press Ctrl+C to stop.\n")
    try:
        while True:
            _enforce_loop_iteration(config, state)
            time.sleep(ENFORCE_INTERVAL)
    except KeyboardInterrupt:
        _echo("\nEnforcer stopped.")
