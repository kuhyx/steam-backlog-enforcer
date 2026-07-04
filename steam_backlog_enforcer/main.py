"""Main CLI for Steam Backlog Enforcer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import sys
import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._cmd_done import cmd_done
from steam_backlog_enforcer._enforce_loop import (
    do_enforce,
    get_all_owned_app_ids,
)
from steam_backlog_enforcer._hltb_types import load_hltb_cache
from steam_backlog_enforcer._stats import cmd_stats
from steam_backlog_enforcer._total_block import (
    TotalBlockStatus,
    get_total_block_status,
    is_total_block_active,
    start_total_block,
)
from steam_backlog_enforcer._web_server import serve
from steam_backlog_enforcer._whitelist import (
    WHITELIST_COOLDOWN_SECONDS,
    add_pending_exception,
    list_pending_exceptions,
    validate_reason,
)
from steam_backlog_enforcer.config import (
    Config,
    State,
    interactive_setup,
    load_snapshot,
)
from steam_backlog_enforcer.game_install import (
    _echo,
    get_installed_games,
    install_game,
    is_game_installed,
    is_protected_app,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import (
    hide_other_games,
    restart_steam,
    unhide_all_games,
)
from steam_backlog_enforcer.scanning import (
    do_check,
    do_scan,
    pick_next_game,
)
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIClient, SteamAPIError
from steam_backlog_enforcer.store_blocker import (
    block_store,
    is_store_blocked,
    unblock_store,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_LIST_DISPLAY_LIMIT = 50
_MIN_CLI_ARGS = 2

# Days before the manual-pick lock automatically expires.
_MANUAL_LOCK_DAYS = 14

# Commands that remain usable while the manual pick lock is active.
# Principle: only what is needed to release the lock (done/check) or
# that cannot change the game assignment (status, enforce, setup, serve).
_MANUAL_LOCK_EXEMPT_COMMANDS = frozenset(
    {"done", "check", "status", "enforce", "setup", "serve"}
)

# Commands that remain usable while a total gaming block is active. Far
# stricter than _MANUAL_LOCK_EXEMPT_COMMANDS: no done/pick/reset/
# add-exception - there is no in-app way to shorten a total block.
_TOTAL_BLOCK_EXEMPT_COMMANDS = frozenset({"status", "enforce"})


# ──────────────────────────────────────────────────────────────
# Total gaming block lock helpers
# ──────────────────────────────────────────────────────────────


def _show_total_block_lock_message(status: TotalBlockStatus) -> None:
    """Print the total-gaming-block-active message to stdout."""
    _echo("\n" + "=" * 60)
    _echo("  *** TOTAL GAMING BLOCK ACTIVE ***")
    _echo("=" * 60)

    if status.until is not None:
        _echo(f"\nBlocked until: {status.until.strftime('%Y-%m-%d %H:%M UTC')}")
        _echo(f"Days remaining: {status.days_remaining:.1f}")

    _echo(
        "\nSteam has been uninstalled, all known game/launcher processes are"
        "\nbeing killed on sight, and Steam + game-website domains are blocked."
        "\nThere is NO in-app command to lift this early."
        f"\n\nAllowed commands: {', '.join(sorted(_TOTAL_BLOCK_EXEMPT_COMMANDS))}"
    )
    _echo("=" * 60 + "\n")


def _enforce_total_block_lock(command: str) -> None:
    """Exit with a lock message if command is blocked by an active total block."""
    if not is_total_block_active():
        return
    if command in _TOTAL_BLOCK_EXEMPT_COMMANDS:
        return
    _show_total_block_lock_message(get_total_block_status())
    sys.exit(1)


# ──────────────────────────────────────────────────────────────
# Manual pick lock helpers
# ──────────────────────────────────────────────────────────────


def _is_manual_pick_locked(state: State) -> bool:
    """Return True if the manual-pick lock is currently in force."""
    if state.manual_pick_app_id is None:
        return False

    # Lock released once the game appears in finished_app_ids.
    if state.manual_pick_app_id in state.finished_app_ids:
        return False

    # Lock released after 14 days from the pick timestamp.
    if state.manual_pick_started_at:
        try:
            started = datetime.fromisoformat(state.manual_pick_started_at)
            deadline = started + timedelta(days=_MANUAL_LOCK_DAYS)
            if datetime.now(timezone.utc) >= deadline:
                return False
        except ValueError:
            pass

    return True


def _show_manual_pick_lock_message(state: State) -> None:
    """Print the aggressive lock-active message to stdout."""
    _echo("\n" + "=" * 60)
    _echo("  *** MANUAL PICK LOCK ACTIVE ***")
    _echo("=" * 60)
    _echo(
        f"\nYou manually picked: {state.manual_pick_game_name}"
        f" (AppID={state.manual_pick_app_id})"
    )

    if state.manual_pick_started_at:
        try:
            started = datetime.fromisoformat(state.manual_pick_started_at)
            deadline = started + timedelta(days=_MANUAL_LOCK_DAYS)
            days_left = (deadline - datetime.now(timezone.utc)).days
            _echo(f"Locked since:  {started.strftime('%Y-%m-%d')}")
            _echo(
                f"Deadline:      {deadline.strftime('%Y-%m-%d')}"
                f" ({max(0, days_left)} day(s) remaining)"
            )
        except ValueError:
            pass

    _echo(
        "\nYou CANNOT use any other feature until you finish this game"
        "\n(100% achievements) or the 2-week deadline passes."
        "\n\nTo release the lock: finish the game, then run 'done' or 'check'."
        f"\n\nAllowed commands: {', '.join(sorted(_MANUAL_LOCK_EXEMPT_COMMANDS))}"
    )
    _echo("=" * 60 + "\n")


def _enforce_manual_pick_lock(command: str, state: State) -> None:
    """Exit with a lock message if command is blocked by the manual pick."""
    if not _is_manual_pick_locked(state):
        return
    if command in _MANUAL_LOCK_EXEMPT_COMMANDS:
        return
    _show_manual_pick_lock_message(state)
    sys.exit(1)


# ──────────────────────────────────────────────────────────────
# CLI commands
# ──────────────────────────────────────────────────────────────


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

    if _is_manual_pick_locked(state):
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
        owned = get_all_owned_app_ids(config)
        if owned:
            count = unhide_all_games(owned)
            if count:
                _echo(f"Unhidden {count} games.")
    except (OSError, RuntimeError, ValueError) as exc:
        _echo(f"Warning: could not unhide games: {exc}")

    state.current_app_id = None
    state.current_game_name = ""
    state.finished_app_ids = []
    state.manual_pick_app_id = None
    state.manual_pick_game_name = ""
    state.manual_pick_started_at = ""
    state.save()
    _echo("State reset. Store unblocked.")


def cmd_installed(_config: Config, state: State) -> None:
    """Show installed games."""
    installed = get_installed_games()
    _echo(f"\nInstalled games ({len(installed)}):\n")
    for app_id, name in installed:
        protected = " [PROTECTED]" if is_protected_app(app_id) else ""
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
        if aid != state.current_app_id and not is_protected_app(aid)
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


_MIN_ADD_EXCEPTION_ARGS = 3
_ADD_EXCEPTION_USAGE = (
    'Usage: add-exception <app_id> --reason "<justification>"\n'
    "  app_id   : numeric Steam application ID\n"
    "  --reason : genuine justification (>= 5 words)\n\n"
    "Example:\n"
    "  add-exception 440 --reason "
    '"TF2 is needed for a community event this weekend"\n\n'
    f"Exceptions become active after a {WHITELIST_COOLDOWN_SECONDS // 3600}h "
    "cooldown."
)


def cmd_add_exception(args: list[str]) -> None:
    """Request a time-locked whitelist exception.

    Usage: add-exception <app_id> --reason "<text>"

    The exception becomes active after a 24-hour cooldown.  The reason must be
    a genuine justification of at least 5 words with sufficient entropy.

    Args:
        args: CLI argument list after the command name.
    """
    if len(args) < _MIN_ADD_EXCEPTION_ARGS or "--reason" not in args:
        _echo(_ADD_EXCEPTION_USAGE)
        sys.exit(1)

    try:
        app_id = int(args[0])
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{args[0]}'.")
        sys.exit(1)

    reason_idx = args.index("--reason")
    reason_parts = args[reason_idx + 1 :]
    if not reason_parts:
        _echo("Error: --reason requires a value.")
        sys.exit(1)
    reason = " ".join(reason_parts)

    # Show validation feedback before attempting to add.
    err = validate_reason(reason)
    if err is not None:
        _echo(f"Invalid reason: {err}")
        sys.exit(1)

    try:
        msg = add_pending_exception(app_id, reason)
    except ValueError as exc:
        _echo(f"Error: {exc}")
        sys.exit(1)

    _echo(msg)

    # Show current pending list.
    pending = list_pending_exceptions()
    if pending:
        _echo(f"\nPending exceptions ({len(pending)}):")
        now = time.time()
        for entry in pending:
            aid = int(entry["app_id"])
            elapsed = now - float(entry["requested_at"])
            remaining = max(0.0, WHITELIST_COOLDOWN_SECONDS - elapsed)
            hrs = int(remaining // 3600)
            mins = int((remaining % 3600) // 60)
            status = "ready" if remaining == 0.0 else f"approves in {hrs}h {mins}m"
            _echo(f"  AppID={aid}  [{status}]")


def cmd_install(config: Config, state: State) -> None:
    """Manually trigger install of the assigned game."""
    if state.current_app_id is None:
        _echo("No game currently assigned. Run 'scan' first.")
        return

    if is_game_installed(state.current_app_id):
        _echo(f"{state.current_game_name} is already installed.")
        return

    _echo(f"Installing {state.current_game_name} (AppID={state.current_app_id})...")
    if install_game(
        state.current_app_id,
        state.current_game_name,
        config.steam_id,
        use_steam_protocol=True,
    ):
        _echo("Done!")
    else:
        _echo("Failed to create install manifest.")


def cmd_hide(config: Config, state: State) -> None:
    """Hide all non-assigned games in the Steam library."""
    if state.current_app_id is None:
        _echo("No game assigned. Run 'scan' first.")
        return

    owned_ids = get_all_owned_app_ids(config)
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
    owned_ids = get_all_owned_app_ids(config)
    if not owned_ids:
        _echo("No owned game list available. Run 'scan' first.")
        return

    _echo("Unhiding all games...")
    count = unhide_all_games(owned_ids)
    _echo(f"Unhidden {count} games.")

    if count > 0:
        _echo("Done!")


def cmd_pick(config: Config, state: State) -> None:
    """Manually pick a new game from the shortest-first candidate list."""
    snapshot_data = load_snapshot()
    if not snapshot_data:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot_data]
    hltb_cache = load_hltb_cache()
    for game in games:
        if game.app_id in hltb_cache:
            game.completionist_hours = hltb_cache[game.app_id]

    pick_next_game(games, state, config)

    if state.current_app_id is not None:
        owned_ids = get_all_owned_app_ids(config)
        if owned_ids:
            hidden = hide_other_games(owned_ids, state.current_app_id)
            if hidden > 0:
                _echo(f"\n  Library: hid {hidden} games")


def cmd_serve(_config: Config, _state: State) -> None:
    """Start the interactive web UI server (read-only, localhost only)."""
    serve()


def _resolve_game_name(config: Config, app_id: int) -> str | None:
    """Look up a game name by app_id, checking snapshot then Steam API.

    Returns the game name, or None if not found.
    """
    # Fast path: snapshot already on disk.
    snapshot = load_snapshot()
    if snapshot:
        for entry in snapshot:
            if entry.get("app_id") == app_id:
                return str(entry["name"])

    # Slower path: owned games API.
    try:
        client = SteamAPIClient(config.steam_api_key, config.steam_id)
        owned = client.get_owned_games()
        for g in owned:
            if g.get("appid") == app_id:
                return str(g.get("name", f"Unknown ({app_id})"))
    except (SteamAPIError, OSError, RuntimeError, ValueError):
        return None

    return None


def cmd_pick_manual(config: Config, state: State, args: list[str]) -> None:
    """Manually pick a game by Steam app_id, locking the enforcer for 2 weeks.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).
    """
    raw_id = args[0] if args else input("Enter Steam app_id: ").strip()

    try:
        app_id = int(raw_id)
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{raw_id}'.")
        return

    _echo(f"Looking up AppID={app_id}...")
    game_name = _resolve_game_name(config, app_id)
    if game_name is None:
        _echo(
            f"Error: AppID={app_id} not found in your Steam library or snapshot.\n"
            "Run 'scan' first, or verify the app_id is correct."
        )
        return

    _echo(f"\nGame found: {game_name} (AppID={app_id})")
    _echo(
        f"\nWARNING: Picking this game will:"
        f"\n  - Override your current assignment"
        f"\n  - Lock ALL other commands for {_MANUAL_LOCK_DAYS} DAYS or until"
        f"\n    you reach 100% achievements"
        f"\n  - Only 'done', 'check', 'status', 'enforce', 'setup', 'serve'"
        f"\n    will remain usable during this period"
    )
    _echo()
    confirm = input(
        f"Type YES to confirm you will play {game_name} until completion: "
    ).strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    state.manual_pick_app_id = app_id
    state.manual_pick_game_name = game_name
    state.manual_pick_started_at = datetime.now(timezone.utc).isoformat()
    state.current_app_id = app_id
    state.current_game_name = game_name
    if not state.enforcement_started_at:
        state.enforcement_started_at = datetime.now(timezone.utc).isoformat()
    state.save()

    _echo(f"\nManual pick confirmed: {game_name} (AppID={app_id})")
    _echo(f"Lock active from now until 100% achievements or {_MANUAL_LOCK_DAYS} days.")
    _echo("Run 'done' or 'check' once you have 100% to release the lock.\n")

    # Post-assignment: mirror what _assign_chosen_game + cmd_pick do.
    if config.uninstall_other_games:
        _echo("  Uninstalling non-assigned games...")
        count = uninstall_other_games(app_id)
        if count:
            _echo(f"  Uninstalled {count} non-assigned game(s)")

    if not is_game_installed(app_id):
        _echo(f"  Installing {game_name}...")
        install_game(app_id, game_name, config.steam_id, use_steam_protocol=True)
    else:
        _echo(f"  {game_name} is already installed.")

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden = hide_other_games(owned_ids, app_id)
        if hidden > 0:
            _echo(f"  Library: hid {hidden} games")


_BLOCK_GAMING_USAGE = (
    "Usage: block-gaming <days>\n"
    "  days : whole number of days to block ALL gaming:\n"
    "         Steam uninstalled, all known game/launcher processes killed,\n"
    "         Steam + game-website domains blocked.\n\n"
    "There is NO in-app command to undo this early once confirmed."
)


def cmd_block_gaming(args: list[str]) -> None:
    """Start a total gaming block for a fixed number of days.

    Usage: block-gaming <days>

    Args:
        args: Remaining CLI args (first element should be the day count).
    """
    if not args:
        _echo(_BLOCK_GAMING_USAGE)
        sys.exit(1)

    try:
        days = int(args[0])
    except ValueError:
        _echo(f"Error: days must be a whole number, got '{args[0]}'.")
        sys.exit(1)

    if days < 1:
        _echo("Error: days must be at least 1.")
        sys.exit(1)

    _echo(
        f"\nWARNING: This will, for the next {days} day(s):"
        f"\n  - Uninstall Steam"
        f"\n  - Kill Steam and all known game-launcher processes on sight"
        f"\n  - Block all Steam network domains AND known browser/flash"
        f"\n    game websites"
        f"\n\nThere is NO in-app command to undo this early. It can only be"
        f"\nlifted by waiting out the {days} day(s), or by manual root-level"
        f"\nsystem administration outside this tool."
    )
    _echo()
    confirm = input(f"Type YES to confirm a {days}-day total gaming block: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    _echo("\nStarting total gaming block...")
    if start_total_block(days):
        _echo(f"Total gaming block ACTIVE for {days} day(s).")
        _echo("Run 'status' to check remaining time.")
    else:
        _echo("Error: failed to engage the block (see logs). Run with sudo?")
        sys.exit(1)


COMMANDS: dict[str, tuple[str, Callable[[Config, State], object]]] = {
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
    "pick": ("Manually pick your next game from candidates", cmd_pick),
    "stats": ("Show backlog completion-time estimates", cmd_stats),
    "serve": ("Start the interactive web UI (browser) server", cmd_serve),
}

# Extra commands with non-standard arg handling (shown in help but not in COMMANDS).
_EXTRA_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "add-exception": "Request 24h-locked whitelist exception (use --reason)",
    "pick-manual": f"Pick a game by app_id, lock enforcer for {_MANUAL_LOCK_DAYS} days",
    "block-gaming": "Block ALL gaming for <days> days, no in-app undo",
}

_ALL_COMMANDS: dict[str, str] = {
    name: desc for name, (desc, _) in COMMANDS.items()
} | _EXTRA_COMMAND_DESCRIPTIONS


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < _MIN_CLI_ARGS or sys.argv[1] not in _ALL_COMMANDS:
        _echo("Steam Backlog Enforcer\n")
        _echo("Usage: python -m steam_backlog_enforcer.main <command>\n")
        _echo("Commands:")
        for name, desc in _ALL_COMMANDS.items():
            _echo(f"  {name:<14s}  {desc}")
        sys.exit(1)

    command = sys.argv[1]

    config = Config.load()

    if command not in {"setup", "add-exception"} and not config.steam_api_key:
        _echo("Not configured. Run 'setup' first.")
        sys.exit(1)

    state = State.load()

    # Total block is the most restrictive lock - check it first.
    _enforce_total_block_lock(command)

    # Enforce the manual-pick lock before dispatching any command.
    # This also covers add-exception (previously dispatched before state load).
    _enforce_manual_pick_lock(command, state)

    # add-exception, pick-manual, and block-gaming have non-standard
    # argument structures.
    if command == "add-exception":
        cmd_add_exception(sys.argv[2:])
        return

    if command == "block-gaming":
        cmd_block_gaming(sys.argv[2:])
        return

    if command == "pick-manual":
        cmd_pick_manual(config, state, sys.argv[2:])
        return

    _, func = COMMANDS[command]
    func(config, state)


if __name__ == "__main__":
    main()
