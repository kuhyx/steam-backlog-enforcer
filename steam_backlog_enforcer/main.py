"""Main CLI for Steam Backlog Enforcer."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from python_pkg.steam_backlog_enforcer.config import (
    Config,
    State,
    interactive_setup,
    load_snapshot,
    save_snapshot,
)
from python_pkg.steam_backlog_enforcer.enforcer import (
    enforce_allowed_game,
    send_notification,
)
from python_pkg.steam_backlog_enforcer.hltb import (
    fetch_hltb_times_cached,
    load_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.library_hider import (
    hide_other_games,
    restart_steam,
    unhide_all_games,
)
from python_pkg.steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient
from python_pkg.steam_backlog_enforcer.store_blocker import (
    block_store,
    is_store_blocked,
    unblock_store,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _echo(msg: str = "", *, end: str = "\n", flush: bool = False) -> None:
    """Write user-facing CLI output to stdout.

    Args:
        msg: Text to output.
        end: String appended after the message.
        flush: Whether to flush stdout immediately.
    """
    sys.stdout.write(msg + end)
    if flush:
        sys.stdout.flush()


# Steam infrastructure app IDs that should NEVER be uninstalled.
PROTECTED_APP_IDS = {
    228980,  # Steamworks Common Redistributables
    1070560,  # Steam Linux Runtime 1.0 (scout)
    1391110,  # Steam Linux Runtime 2.0 (soldier)
    1628350,  # Steam Linux Runtime 3.0 (sniper)
    961940,  # Steam Linux Runtime (legacy)
    # Proton versions (never uninstall these)
    858280,  # Proton 3.7 (Beta)
    930400,  # Proton 3.16 (Beta)
    1054830,  # Proton 4.2
    1113280,  # Proton 4.11
    1245040,  # Proton 5.0
    1420170,  # Proton 5.13
    1580130,  # Proton 6.3
    1887720,  # Proton 7.0
    2230260,  # Proton 7.0 (alt)
    2348590,  # Proton 8.0
    2805730,  # Proton 9.0
    3201940,  # Proton 9.0 (alt)
    3658110,  # Proton 10.0
    2180100,  # Proton Hotfix
    1493710,  # Proton Experimental
    1161040,  # Proton BattlEye Runtime
    1007020,  # Proton EasyAntiCheat Runtime
    # Games allowed to be installed anytime
    3949040,  # RV There Yet?
}

STEAMAPPS_PATH = Path("~/.local/share/Steam/steamapps").expanduser()

_LIST_DISPLAY_LIMIT = 50
_MIN_CLI_ARGS = 2
_TAMPER_CHECK_LIMIT = 3


# ──────────────────────────────────────────────────────────────
# Game install management
# ──────────────────────────────────────────────────────────────


def _get_real_user() -> str | None:
    """Get the real (non-root) user when running under sudo."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER")


def _get_uid_gid_for_user(username: str) -> tuple[int, int]:
    """Get (uid, gid) for a username."""
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return 1000, 1000
    else:
        return pw.pw_uid, pw.pw_gid


def is_game_installed(app_id: int) -> bool:
    """Check if a game is installed by looking for its appmanifest.

    A manifest with StateFlags != 4 (FullyInstalled) means the game is
    still downloading or queued, which still counts as "install triggered".
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    return manifest.exists()


def _ensure_steam_running() -> None:
    """Start the Steam client if it is not already running."""
    # Check if any steam process is running (main client, not just helpers).
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-f", "steam.sh"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logger.debug("Steam client already running")
            return
    except FileNotFoundError:
        pass

    real_user = _get_real_user()
    logger.info("Starting Steam client...")

    try:
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, _ = _get_uid_gid_for_user(real_user)
            dbus_default = f"unix:path=/run/user/{uid}/bus"
            dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", dbus_default)
            xauth_default = f"/home/{real_user}/.Xauthority"
            xauth = os.environ.get("XAUTHORITY", xauth_default)
            cmd = [
                "sudo",
                "-u",
                real_user,
                "env",
                f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
                f"XAUTHORITY={xauth}",
                f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
                "steam",
                "-silent",
            ]
        else:
            cmd = ["steam", "-silent"]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give Steam time to initialize and start scanning manifests.
        time.sleep(15)
    except FileNotFoundError:
        logger.exception("Steam executable not found")


def install_game(app_id: int, game_name: str, steam_id: str) -> bool:
    """Install a game by writing an appmanifest that triggers Steam's download.

    Creates a minimal appmanifest with StateFlags=1026 (UpdateRequired |
    UpdateStarted) in the steamapps directory.  The running Steam client
    detects the new manifest and automatically queues the download — no
    dialog or user interaction required.

    If Steam is not running it will be started in silent mode first.

    Args:
        app_id: Steam application ID.
        game_name: Human-readable game name.
        steam_id: Steam64 ID of the account that owns the game.

    Returns True if the manifest was written successfully.
    """
    label = game_name or f"AppID={app_id}"

    if is_game_installed(app_id):
        logger.info("Game already installed: %s", label)
        return True

    # Build a minimal appmanifest.  StateFlags 1026 = UpdateRequired (2) +
    # UpdateStarted (1024), which tells Steam "this app needs downloading".
    manifest_content = (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{app_id}"\n'
        '\t"universe"\t\t"1"\n'
        f'\t"name"\t\t"{game_name}"\n'
        '\t"StateFlags"\t\t"1026"\n'
        f'\t"installdir"\t\t"{game_name}"\n'
        '\t"LastUpdated"\t\t"0"\n'
        '\t"LastPlayed"\t\t"0"\n'
        '\t"SizeOnDisk"\t\t"0"\n'
        '\t"StagingSize"\t\t"0"\n'
        '\t"buildid"\t\t"0"\n'
        f'\t"LastOwner"\t\t"{steam_id}"\n'
        '\t"UpdateResult"\t\t"0"\n'
        '\t"BytesToDownload"\t\t"0"\n'
        '\t"BytesDownloaded"\t\t"0"\n'
        '\t"BytesToStage"\t\t"0"\n'
        '\t"BytesStaged"\t\t"0"\n'
        '\t"TargetBuildID"\t\t"0"\n'
        '\t"AutoUpdateBehavior"\t\t"0"\n'
        '\t"AllowOtherDownloadsWhileRunning"\t\t"0"\n'
        '\t"ScheduledAutoUpdate"\t\t"0"\n'
        '\t"InstalledDepots"\n'
        "\t{\n"
        "\t}\n"
        '\t"UserConfig"\n'
        "\t{\n"
        "\t}\n"
        '\t"MountedConfig"\n'
        "\t{\n"
        "\t}\n"
        "}\n"
    )

    manifest_path = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"

    try:
        with manifest_path.open("w", encoding="utf-8") as fh:
            fh.write(manifest_content)

        # Fix ownership so the Steam client (running as the real user) can
        # read and update the manifest.
        real_user = _get_real_user()
        if os.geteuid() == 0 and real_user and real_user != "root":
            uid, gid = _get_uid_gid_for_user(real_user)
            os.chown(manifest_path, uid, gid)

        logger.info("Created appmanifest for %s — Steam will auto-download", label)
    except OSError:
        logger.exception("Failed to create appmanifest for %s", label)
        return False

    # Make sure Steam is running so it picks up the manifest.
    _ensure_steam_running()

    return True


# ──────────────────────────────────────────────────────────────
# Game uninstall management
# ──────────────────────────────────────────────────────────────


def get_installed_games() -> list[tuple[int, str]]:
    """Parse appmanifest files to find installed games.

    Returns: list of (app_id, game_name) tuples.
    """
    installed: list[tuple[int, str]] = []

    for manifest_file in STEAMAPPS_PATH.glob("appmanifest_*.acf"):
        with contextlib.suppress(OSError):
            content = manifest_file.read_text(encoding="utf-8")
            app_id_match = re.search(r'"appid"\s+"(\d+)"', content)
            name_match = re.search(r'"name"\s+"([^"]+)"', content)
            if app_id_match:
                app_id = int(app_id_match.group(1))
                name = name_match.group(1) if name_match else f"Unknown ({app_id})"
                installed.append((app_id, name))

    installed.sort(key=lambda x: x[1].lower())
    return installed


def _read_install_dir(manifest: Path) -> Path | None:
    """Read installdir from a game's appmanifest file."""
    if not manifest.exists():
        return None
    try:
        content = manifest.read_text(encoding="utf-8")
        match = re.search(r'"installdir"\s+"([^"]+)"', content)
        if match:
            return STEAMAPPS_PATH / "common" / match.group(1)
    except OSError:
        pass
    return None


def _remove_manifest(manifest: Path, game_name: str, app_id: int) -> bool:
    """Remove a game manifest file.

    Args:
        manifest: Path to the appmanifest file.
        game_name: Human-readable game name for logging.
        app_id: Steam application ID.
    """
    try:
        if manifest.exists():
            manifest.unlink()
            logger.info(
                "Removed manifest for %s (AppID=%d)", game_name or app_id, app_id
            )
    except OSError:
        logger.exception("Failed to remove manifest for AppID=%d", app_id)
        return False
    return True


def _remove_game_dirs(install_dir: Path | None, app_id: int) -> bool:
    """Remove game installation directory and cache directories.

    Args:
        install_dir: Path to the game's install directory, or None.
        app_id: Steam application ID.
    """
    success = True
    if install_dir and install_dir.is_dir():
        try:
            shutil.rmtree(install_dir)
            logger.info("Removed game files: %s", install_dir)
        except OSError:
            logger.exception("Failed to remove game dir %s", install_dir)
            success = False

    for subdir in ("shadercache", "compatdata"):
        cache_path = STEAMAPPS_PATH / subdir / str(app_id)
        if cache_path.is_dir():
            with contextlib.suppress(OSError):
                shutil.rmtree(cache_path)
                logger.debug("Removed %s/%d", subdir, app_id)

    return success


def uninstall_game(app_id: int, game_name: str = "") -> bool:
    """Uninstall a single game by removing its manifest and game files.

    Uses direct file removal instead of `steam://uninstall` URI to avoid
    GUI popups and to work when Steam is not running.
    """
    manifest = STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    install_dir = _read_install_dir(manifest)
    success = _remove_manifest(manifest, game_name, app_id)
    if not _remove_game_dirs(install_dir, app_id):
        success = False
    return success


def uninstall_other_games(allowed_app_id: int | None) -> int:
    """Uninstall all installed games except the assigned one and protected IDs.

    Returns: number of games uninstalled.
    """
    installed = get_installed_games()
    count = 0

    for app_id, name in installed:
        if app_id == allowed_app_id:
            logger.info("KEEPING assigned game: %s (AppID=%d)", name, app_id)
            continue
        if app_id in PROTECTED_APP_IDS:
            logger.debug("Skipping protected: %s (AppID=%d)", name, app_id)
            continue

        logger.info("UNINSTALLING: %s (AppID=%d)", name, app_id)
        if uninstall_game(app_id, name):
            count += 1

    return count


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
    owned_ids = _get_all_owned_app_ids(config)
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


# ──────────────────────────────────────────────────────────────
# CLI commands
# ──────────────────────────────────────────────────────────────


def cmd_status(_config: Config, state: State) -> None:
    """Show current status."""
    _echo("=== Steam Backlog Enforcer ===\n")

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
    real_games = [(aid, n) for aid, n in installed if aid not in PROTECTED_APP_IDS]
    _echo(f"Installed games: {len(real_games)}")

    if state.current_app_id:
        is_assigned_installed = any(aid == state.current_app_id for aid, _ in installed)
        _echo(f"Assigned game installed: {is_assigned_installed}")


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


def cmd_unblock(_config: Config, _state: State) -> None:
    """Remove store blocking."""
    if unblock_store():
        _echo("Steam store unblocked.")
    else:
        _echo("Failed to unblock. Run with sudo.")


def cmd_buy_dlc(config: Config, state: State) -> None:
    """Temporarily unblock the store so the user can buy DLC."""
    if state.current_app_id is None:
        _echo("No game currently assigned.")
        return

    _echo(f"Current game: {state.current_game_name} (AppID={state.current_app_id})")
    _echo("Unblocking Steam store for DLC purchase...")

    if not unblock_store():
        _echo("Failed to unblock store. Run with sudo.")
        return

    _echo("\nStore UNBLOCKED — buy your DLC now.")
    _echo("Press Enter when you're done to re-block the store...")
    input()

    if config.block_store:
        if block_store():
            _echo("Store re-blocked. Restarting Steam to clear DNS cache...")
            restart_steam()
            _echo("Done.")
        else:
            _echo("Warning: failed to re-block store.")


def cmd_reset(config: Config, state: State) -> None:
    """Reset all state (unblock, unhide, clear assignment)."""
    unblock_store()

    # Unhide all games in the library.
    try:
        owned = _get_all_owned_app_ids(config)
        if owned:
            count = unhide_all_games(owned)
            if count:
                _echo(f"Unhidden {count} games.")
    except (OSError, RuntimeError, ValueError) as exc:
        _echo(f"Warning: could not unhide games: {exc}")

    state.current_app_id = None
    state.current_game_name = ""
    state.finished_app_ids = []
    state.save()
    _echo("State reset. Store unblocked.")


def cmd_installed(_config: Config, state: State) -> None:
    """Show installed games."""
    installed = get_installed_games()
    _echo(f"\nInstalled games ({len(installed)}):\n")
    for app_id, name in installed:
        protected = " [PROTECTED]" if app_id in PROTECTED_APP_IDS else ""
        assigned = " <<< ASSIGNED" if app_id == state.current_app_id else ""
        _echo(f"  {app_id:>8d}  {name}{protected}{assigned}")


def cmd_uninstall(_config: Config, state: State) -> None:
    """Uninstall all games except the assigned one."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    installed = get_installed_games()
    to_remove = [
        (aid, n)
        for aid, n in installed
        if aid != state.current_app_id and aid not in PROTECTED_APP_IDS
    ]

    if not to_remove:
        _echo("No games to uninstall (only assigned game and runtimes installed).")
        return

    _echo(f"\nWill uninstall {len(to_remove)} games, keeping:")
    _echo(f"  - {state.current_game_name} (AppID={state.current_app_id})")
    _echo("  - Steam runtimes and Proton versions\n")
    _echo("Games to remove:")
    for aid, name in to_remove:
        _echo(f"  - {name} (AppID={aid})")

    _echo()
    confirm = input("Type YES to confirm: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    count = uninstall_other_games(state.current_app_id)
    _echo(f"\nUninstalled {count} games.")


def cmd_setup(_config: Config, _state: State) -> None:
    """Run interactive setup."""
    interactive_setup()


def cmd_install(config: Config, state: State) -> None:
    """Manually trigger install of the assigned game."""
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    if is_game_installed(state.current_app_id):
        _echo(f"{state.current_game_name} is already installed.")
        return

    _echo(f"Installing {state.current_game_name} (AppID={state.current_app_id})...")
    if install_game(state.current_app_id, state.current_game_name, config.steam_id):
        _echo("Done!")
    else:
        _echo("Failed to create install manifest.")


def _get_all_owned_app_ids(config: Config) -> list[int]:
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


def cmd_hide(config: Config, state: State) -> None:
    """Hide all non-assigned games in the Steam library."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    owned_ids = _get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("No owned game list available. Run 'scan' first.")
        return

    _echo(f"Hiding all games except {state.current_game_name}...")
    hidden = hide_other_games(owned_ids, state.current_app_id)
    _echo(f"Hidden {hidden} games.")

    if hidden > 0:
        _echo("Done! Only the assigned game should be visible in your library.")


def cmd_unhide(config: Config, _state: State) -> None:
    """Unhide all games in the Steam library."""
    owned_ids = _get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("No owned game list available. Run 'scan' first.")
        return

    _echo("Unhiding all games...")
    count = unhide_all_games(owned_ids)
    _echo(f"Unhidden {count} games.")

    if count > 0:
        _echo("Done!")


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
    for g in all_games:
        cached_hours = hltb_cache.get(g.app_id, -1.0)
        if cached_hours > 0:
            g.completionist_hours = cached_hours
    skip = set(config.skip_app_ids) | set(state.finished_app_ids)
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
    pick_next_game(games, state, config)

    if state.current_app_id is None:
        _echo("  No more games to assign!")
        return

    owned_ids = _get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, state.current_app_id)
        if hidden > 0:
            _echo(f"\n  Library: hid {hidden} games")

    send_notification(
        "Game Complete!",
        f"Finished {game_name}! Now playing: {state.current_game_name}",
    )
    _echo(f"\nAll done! Go play {state.current_game_name}!")


def cmd_done(config: Config, state: State) -> None:
    """Check completion, pick next game, uninstall & hide.

    All-in-one command for after finishing a game:
    1. Verify 100% achievements on Steam.
    2. Pick the next game (shortest HLTB 100% time).
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
        _echo(f"  HLTB 100% estimate: {hours:.1f} hours")

    if _try_reassign_shorter_game(hltb_cache, app_id, hours, state, config):
        return

    if not game.is_complete:
        remaining = game.total_achievements - game.unlocked_achievements
        _echo(f"\n  NOT COMPLETE: {remaining} achievements remaining. Keep going!")
        return

    _finalize_completion(config, state, game_name, app_id)


COMMANDS = {
    "scan": ("Scan library & assign a game", do_scan),
    "check": ("Check assigned game completion", do_check),
    "status": ("Show current status", cmd_status),
    "list": ("List games from snapshot", cmd_list),
    "enforce": ("Run enforcer: block, uninstall, kill, hide", do_enforce),
    "install": ("Install the assigned game", cmd_install),
    "hide": ("Hide all non-assigned games in library", cmd_hide),
    "unhide": ("Unhide all games in library", cmd_unhide),
    "unblock": ("Remove store blocking", cmd_unblock),
    "buy-dlc": ("Temporarily unblock store to buy DLC", cmd_buy_dlc),
    "reset": ("Reset all state", cmd_reset),
    "installed": ("List installed games", cmd_installed),
    "uninstall": ("Uninstall all non-assigned games", cmd_uninstall),
    "setup": ("Run first-time setup", cmd_setup),
    "done": ("Finish game, open HLTB, pick next", cmd_done),
}


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < _MIN_CLI_ARGS or sys.argv[1] not in COMMANDS:
        _echo("Steam Backlog Enforcer\n")
        _echo("Usage: python -m python_pkg.steam_backlog_enforcer.main <command>\n")
        _echo("Commands:")
        for name, (desc, _) in COMMANDS.items():
            _echo(f"  {name:<12s}  {desc}")
        sys.exit(1)

    command = sys.argv[1]
    config = Config.load()

    if command != "setup" and not config.steam_api_key:
        _echo("Not configured. Run 'setup' first.")
        sys.exit(1)

    state = State.load()
    _, func = COMMANDS[command]
    func(config, state)


if __name__ == "__main__":
    main()
