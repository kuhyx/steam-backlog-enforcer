"""Main CLI for Steam Backlog Enforcer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import difflib
import logging
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import (
    ABANDON_COOLDOWN_DAYS as _ABANDON_COOLDOWN_DAYS,
)
from steam_backlog_enforcer._actions import (
    MANUAL_GRACE_DAYS as _MANUAL_GRACE_DAYS,
)
from steam_backlog_enforcer._actions import (
    MANUAL_LOCK_DAYS as _MANUAL_LOCK_DAYS,
)
from steam_backlog_enforcer._actions import (
    abandon_manual_pick,
    active_manual_picks,
    allowed_app_ids,
    allowed_games,
    apply_manual_pick,
    can_abandon_manual_pick,
    find_manual_pick,
    manual_pick_grace_remaining,
    manual_pick_slots_left,
)
from steam_backlog_enforcer._actions import (
    is_manual_pick_locked as _is_manual_pick_locked,
)
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
    add_pending_exception,
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
    uninstall_game,
    uninstall_other_games,
)
from steam_backlog_enforcer.library_hider import (
    restart_steam,
    try_hide_other_games,
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

# Commands that remain usable while the manual pick lock is active.
# Principle: only what is needed to release the lock (done/check) or
# that cannot change the game assignment (status, enforce, setup, serve).
_MANUAL_LOCK_EXEMPT_COMMANDS = frozenset(
    {
        "done",
        "check",
        "status",
        "enforce",
        "setup",
        "serve",
        "abandon-pick",
        # Allowed so a second game can be locked in alongside the first; the
        # cap inside cmd_pick_manual is what stops this being a way out.
        "pick-manual",
    }
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
# (the predicate itself lives in _actions so the MCP server can reuse it)
# ──────────────────────────────────────────────────────────────


def _describe_pick(state: State, pick: dict[str, object]) -> bool:
    """Print one manual pick's deadline and grace status; return if abandonable.

    Args:
        state: Current enforcer state.
        pick: One active entry from ``state.manual_picks``.

    Returns:
        Whether this pick is still inside its grace window.
    """
    app_id = pick["app_id"]
    _echo(f"\n  {pick['game_name']} (AppID={app_id})")

    started_at = str(pick.get("started_at") or "")
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            deadline = started + timedelta(days=_MANUAL_LOCK_DAYS)
            days_left = (deadline - datetime.now(timezone.utc)).days
            _echo(f"    Locked since: {started.strftime('%Y-%m-%d')}")
            _echo(
                f"    Deadline:     {deadline.strftime('%Y-%m-%d')}"
                f" ({max(0, days_left)} day(s) remaining)"
            )
        except ValueError:
            pass

    grace_left = manual_pick_grace_remaining(state, int(str(app_id)))
    if grace_left is not None and grace_left > 0:
        _echo(
            f"    Undo:         abandon-pick {app_id}"
            f"  ({grace_left:.1f} of {_MANUAL_GRACE_DAYS} grace day(s) left)"
        )
        return True
    return False


def _show_manual_pick_lock_message(state: State) -> None:
    """Print the aggressive lock-active message to stdout."""
    picks = active_manual_picks(state)
    _echo("\n" + "=" * 60)
    _echo("  *** MANUAL PICK LOCK ACTIVE ***")
    _echo("=" * 60)
    _echo(f"\nYou manually picked {len(picks)} game(s):")

    any_in_grace = False
    for pick in picks:
        any_in_grace |= _describe_pick(state, pick)

    _echo(
        "\nYou CANNOT use any other feature until you finish these games"
        "\n(100% achievements) or their 2-week deadlines pass."
        "\n\nTo release the lock: finish them, then run 'done' or 'check'."
    )

    # 'abandon-pick' is dropped from the allowed list once no pick is still
    # inside its window, rather than offered as a command that would refuse.
    usable = set(_MANUAL_LOCK_EXEMPT_COMMANDS)
    if not any_in_grace:
        usable.discard("abandon-pick")
    _echo(f"\nAllowed commands: {', '.join(sorted(usable))}")
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

    picks = active_manual_picks(state)
    if picks:
        _echo(f"\nManual picks ({len(picks)}):")
        for pick in picks:
            grace = manual_pick_grace_remaining(state, pick["app_id"])
            undo = (
                f" — undoable for {grace:.1f} more day(s)"
                if grace is not None and grace > 0
                else ""
            )
            _echo(f"  {pick['game_name']} (AppID={pick['app_id']}){undo}")
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
    state.manual_picks = []
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

    allowed = allowed_app_ids(state)
    installed = get_installed_games()
    to_remove = [
        (aid, n)
        for aid, n in installed
        if aid not in allowed and not is_protected_app(aid)
    ]

    if not to_remove:
        _echo("No games to uninstall (only allowed games and runtimes installed).")
        return

    _echo(f"\nWill uninstall {len(to_remove)} games, keeping:")
    for aid, name in allowed_games(state):
        _echo(f"  - {name} (AppID={aid})")
    _echo("  - Steam runtimes and Proton versions\n")
    _echo("Games to remove:")
    for aid, name in to_remove:
        _echo(f"  - {name} (AppID={aid})")

    _echo()
    confirm = input("Type YES to confirm: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    count = uninstall_other_games(allowed_app_ids(state))
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
    "Exceptions become active immediately."
)


def cmd_add_exception(args: list[str]) -> None:
    """Add a whitelist exception, active immediately.

    Usage: add-exception <app_id> --reason "<text>"

    The exception becomes active right away (no cooldown).  The reason must be
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
    hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
    if skipped is not None:
        _echo(f"Library hiding: skipped ({skipped})")
        return
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
            hidden, skipped = try_hide_other_games(owned_ids, allowed_app_ids(state))
            if skipped is not None:
                _echo(f"\n  Library hiding: skipped ({skipped})")
            elif hidden > 0:
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


def _report_pick_slots(config: Config, state: State) -> list[dict[str, object]]:
    """Show which manual picks are already locked in; exit if the cap is full.

    Args:
        config: Enforcer configuration (for ``max_manual_picks``).
        state: Current enforcer state.

    Returns:
        The currently-active manual picks.
    """
    existing = active_manual_picks(state)
    if existing:
        _echo(f"\nAlready locked in ({len(existing)}/{config.max_manual_picks}):")
        for pick in existing:
            _echo(f"  - {pick['game_name']} (AppID={pick['app_id']})")

    if manual_pick_slots_left(state, config.max_manual_picks) == 0:
        _echo(
            f"\nError: you already have {config.max_manual_picks} manual pick(s)."
            f"\nFinish one, or undo one with 'abandon-pick <app_id>' while it is"
            f"\nstill inside its {_MANUAL_GRACE_DAYS}-day grace window."
        )
        sys.exit(1)

    return existing


def _apply_allowed_set(config: Config, state: State) -> None:
    """Make the filesystem and library match the allowed set.

    Uninstalls everything outside it, installs every allowed game that is
    missing, and hides the rest of the library. Operating on the whole set
    (rather than one app id) is what lets a second manual pick coexist with
    the first instead of tearing it down.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
    """
    allowed = allowed_app_ids(state)

    if config.uninstall_other_games:
        _echo("  Uninstalling non-allowed games...")
        count = uninstall_other_games(allowed)
        if count:
            _echo(f"  Uninstalled {count} non-allowed game(s)")

    for app_id, name in allowed_games(state):
        if is_game_installed(app_id):
            _echo(f"  {name} is already installed.")
            continue
        _echo(f"  Installing {name}...")
        install_game(app_id, name, config.steam_id, use_steam_protocol=True)

    owned_ids = get_all_owned_app_ids(config)
    if owned_ids:
        hidden, skipped = try_hide_other_games(owned_ids, allowed)
        if skipped is not None:
            _echo(f"  Library hiding: skipped ({skipped})")
        elif hidden > 0:
            _echo(f"  Library: hid {hidden} games")


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

    existing = _report_pick_slots(config, state)

    _echo(
        f"\nWARNING: Picking this game will:"
        f"\n  - Add it to your allowed games ({len(existing) + 1} of"
        f" {config.max_manual_picks} slot(s) used)"
        f"\n  - Lock ALL other commands for {_MANUAL_LOCK_DAYS} DAYS or until"
        f"\n    you reach 100% achievements on every pick"
        f"\n  - Leave only these commands usable:"
        f"\n    {', '.join(sorted(_MANUAL_LOCK_EXEMPT_COMMANDS))}"
        f"\n  - Stay undoable via 'abandon-pick {app_id}' for the first"
        f"\n    {_MANUAL_GRACE_DAYS} days"
    )
    _echo()
    confirm = input(
        f"Type YES to confirm you will play {game_name} until completion: "
    ).strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    # State mutation is the shared, stdout-free core (also used by the MCP
    # server); the destructive post-assignment cascade below stays CLI-only.
    refused = apply_manual_pick(
        state,
        app_id,
        game_name,
        max_picks=config.max_manual_picks,
    )
    if refused is not None:
        _echo(f"\nError: {refused}")
        sys.exit(1)

    _echo(f"\nManual pick confirmed: {game_name} (AppID={app_id})")
    _echo(f"Lock active from now until 100% achievements or {_MANUAL_LOCK_DAYS} days.")
    _echo("Run 'done' or 'check' once you have 100% to release the lock.\n")

    # Post-assignment: mirror what _assign_chosen_game + cmd_pick do, but for
    # the whole allowed set so an earlier pick is not torn down by a later one.
    _apply_allowed_set(config, state)


_ABANDON_PICK_USAGE = (
    "Usage: abandon-pick <app_id>\n"
    "  app_id : the manually-picked game you want to back out of.\n\n"
    f"Only works within {_MANUAL_GRACE_DAYS} days of the pick."
)


def _abandon_pick_target(state: State, args: list[str]) -> int | None:
    """Validate the abandon-pick argument against the active manual pick.

    Requiring the explicit app_id (rather than defaulting to the current pick)
    makes an accidental abandon impossible to trigger by muscle memory.

    Args:
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).

    Returns:
        The validated app id, or ``None`` if the input was unusable (a message
        has already been printed in that case).
    """
    if not args:
        _echo(_ABANDON_PICK_USAGE)
        return None

    try:
        app_id = int(args[0])
    except ValueError:
        _echo(f"Error: app_id must be a number, got '{args[0]}'.")
        return None

    picks = active_manual_picks(state)
    if not picks:
        _echo("No manual pick is active — nothing to abandon.")
        return None

    if find_manual_pick(state, app_id) is None:
        listed = ", ".join(f"{p['game_name']} (AppID={p['app_id']})" for p in picks)
        _echo(
            f"Error: AppID={app_id} is not one of your manual picks.\nActive: {listed}."
        )
        return None

    return app_id


def cmd_abandon_pick(_config: Config, state: State, args: list[str]) -> None:
    """Back out of a manual pick while still inside the grace period.

    Args:
        _config: Enforcer configuration (unused, kept for dispatch symmetry).
        state: Current enforcer state.
        args: Remaining CLI args (first element should be the app_id).
    """
    app_id = _abandon_pick_target(state, args)
    if app_id is None:
        sys.exit(1)

    pick = find_manual_pick(state, app_id)
    game_name = str(pick["game_name"]) if pick else ""

    if not can_abandon_manual_pick(state, app_id):
        # ``remaining`` is negative once the window has closed, so its
        # magnitude is how long ago that happened.
        remaining = manual_pick_grace_remaining(state, app_id)
        elapsed = (
            f"{abs(remaining):.1f} day(s) ago"
            if remaining is not None
            else "at an unknown time"
        )
        _echo(
            f"\nGrace period EXPIRED for {game_name} (AppID={app_id}).\n"
            f"The {_MANUAL_GRACE_DAYS}-day window closed {elapsed}.\n"
            "Finish the game (100% achievements) or wait out the lock."
        )
        sys.exit(1)

    others = [p for p in active_manual_picks(state) if p["app_id"] != app_id]
    _echo(f"\nAbandoning manual pick: {game_name} (AppID={app_id})")
    _echo(
        f"\nThis will:"
        f"\n  - Drop this pick from your allowed games"
        f"\n  - Uninstall {game_name}"
        f"\n  - Keep it out of auto-assignment for"
        f" {_ABANDON_COOLDOWN_DAYS} days"
    )
    if others:
        kept = ", ".join(f"{p['game_name']} (AppID={p['app_id']})" for p in others)
        _echo(f"\n  Your other pick(s) stay locked in: {kept}")
    else:
        _echo("\n  - Leaves you with no assigned game (run 'scan' to get one)")
    _echo()
    confirm = input(f"Type YES to abandon {game_name}: ").strip()
    if confirm != "YES":
        _echo("Aborted.")
        return

    if not abandon_manual_pick(state, app_id):
        # Should be unreachable: the grace check above already passed.
        _echo("Error: the grace period closed before the pick could be abandoned.")
        sys.exit(1)

    _echo(f"\nManual pick abandoned: {game_name}")

    if is_game_installed(app_id):
        _echo(f"  Uninstalling {game_name}...")
        if uninstall_game(app_id, game_name):
            _echo("  Uninstalled.")
        else:
            _echo("  Warning: could not uninstall — remove it from Steam manually.")

    if state.current_app_id is None:
        _echo("\nNo game is assigned now. Run 'scan' to get a new assignment,")
        _echo("or 'pick-manual <app_id>' to choose one yourself.\n")
    else:
        _echo(f"\nStill assigned: {state.current_game_name}\n")


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
    "abandon-pick": (
        f"Undo a manual pick within {_MANUAL_GRACE_DAYS} days (needs app_id)"
    ),
    "block-gaming": "Block ALL gaming for <days> days, no in-app undo",
}

_ALL_COMMANDS: dict[str, str] = {
    name: desc for name, (desc, _) in COMMANDS.items()
} | _EXTRA_COMMAND_DESCRIPTIONS


def _resolve_command(raw: str) -> str | None:
    """Map a raw argv[1] onto a known command name.

    Subcommands are bare words, but the CLI does use flags elsewhere
    (``add-exception --reason``), so ``--abandon-pick`` is the natural
    muscle-memory guess. Leading dashes carry no meaning in this slot,
    so they are simply stripped rather than rejected.

    Parameters:
    raw (str): The first CLI argument, exactly as the user typed it.

    Returns:
    str | None: The canonical command name, or None if unrecognised.
    """
    if raw in _ALL_COMMANDS:
        return raw
    if raw.startswith("-"):
        stripped = raw.lstrip("-")
        if stripped in _ALL_COMMANDS:
            return stripped
    return None


def _print_usage(unknown: str | None = None) -> None:
    """Print the command list, optionally explaining a bad command.

    Parameters:
    unknown (str | None): The unrecognised argument to report. When None
        (the no-arguments case) only the usage block is printed.
    """
    if unknown is not None:
        _echo(f"Unknown command: {unknown}")
        close = difflib.get_close_matches(
            unknown.lstrip("-"), _ALL_COMMANDS, n=1, cutoff=0.6
        )
        if close:
            _echo(f"Did you mean '{close[0]}'?")
        _echo("")
    _echo("Steam Backlog Enforcer\n")
    _echo("Usage: python -m steam_backlog_enforcer.main <command> [args]\n")
    _echo("Commands:")
    for name, desc in _ALL_COMMANDS.items():
        _echo(f"  {name:<14s}  {desc}")


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < _MIN_CLI_ARGS:
        _print_usage()
        sys.exit(1)

    # Locks below are always given the canonical name, never raw argv,
    # so a dashed spelling can never be used to dodge one.
    command = _resolve_command(sys.argv[1])
    if command is None:
        _print_usage(sys.argv[1])
        sys.exit(1)
    if command != sys.argv[1]:
        _echo(f"Note: treating '{sys.argv[1]}' as '{command}'.")

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

    if command == "abandon-pick":
        cmd_abandon_pick(config, state, sys.argv[2:])
        return

    _, func = COMMANDS[command]
    func(config, state)


if __name__ == "__main__":
    main()
