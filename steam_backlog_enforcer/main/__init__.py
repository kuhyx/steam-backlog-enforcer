"""Main CLI for Steam Backlog Enforcer.

The command implementations live in sibling modules (``status``, ``install``,
``picks``, ``abandon``, ``misc``) and are re-exported here, so
``steam_backlog_enforcer.main`` stays the single import surface it was when
this was one module. ``python -m steam_backlog_enforcer.main`` still works via
:mod:`steam_backlog_enforcer.main.__main__`.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import MANUAL_GRACE_DAYS as _MANUAL_GRACE_DAYS
from steam_backlog_enforcer._allowed_games import (
    MANUAL_LOCK_DAYS as _MANUAL_LOCK_DAYS,
)
from steam_backlog_enforcer._cmd_done import cmd_done
from steam_backlog_enforcer._cmd_playtime import (
    cmd_enforce,
    cmd_gaming_reset,
    cmd_gaming_status,
    cmd_gaming_unblock,
)
from steam_backlog_enforcer._stats import cmd_stats
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.main._registry import _make_all_commands
from steam_backlog_enforcer.main._registry import (
    _print_usage as _print_usage_for,
)
from steam_backlog_enforcer.main._registry import (
    _resolve_command as _resolve_command_in,
)
from steam_backlog_enforcer.main._shared import (
    _MANUAL_LOCK_EXEMPT_COMMANDS,
    _MIN_CLI_ARGS,
    _TOTAL_BLOCK_EXEMPT_COMMANDS,
    _describe_pick,
    _enforce_manual_pick_lock,
    _enforce_total_block_lock,
    _is_manual_pick_locked,
    _show_manual_pick_lock_message,
    _show_total_block_lock_message,
)
from steam_backlog_enforcer.main.abandon import cmd_abandon_pick
from steam_backlog_enforcer.main.install import (
    cmd_hide,
    cmd_install,
    cmd_installed,
    cmd_unhide,
    cmd_uninstall,
)
from steam_backlog_enforcer.main.misc import (
    cmd_add_exception,
    cmd_block_gaming,
    cmd_buy_dlc,
    cmd_reset,
    cmd_serve,
    cmd_setup,
    cmd_unblock,
)
from steam_backlog_enforcer.main.picks import (
    _resolve_game_name,
    cmd_pick,
    cmd_pick_manual,
)
from steam_backlog_enforcer.main.status import cmd_list, cmd_status
from steam_backlog_enforcer.scanning import do_check, do_scan

if TYPE_CHECKING:
    from collections.abc import Callable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Private helpers are re-exported too: they were importable from this module
# before it became a package, and the test-suite reaches for them by name.
__all__ = [
    "COMMANDS",
    "_MANUAL_GRACE_DAYS",
    "_MANUAL_LOCK_DAYS",
    "_MANUAL_LOCK_EXEMPT_COMMANDS",
    "_TOTAL_BLOCK_EXEMPT_COMMANDS",
    "_describe_pick",
    "_enforce_manual_pick_lock",
    "_enforce_total_block_lock",
    "_is_manual_pick_locked",
    "_print_usage",
    "_resolve_command",
    "_resolve_game_name",
    "_show_manual_pick_lock_message",
    "_show_total_block_lock_message",
    "cmd_abandon_pick",
    "cmd_add_exception",
    "cmd_block_gaming",
    "cmd_buy_dlc",
    "cmd_done",
    "cmd_hide",
    "cmd_install",
    "cmd_installed",
    "cmd_list",
    "cmd_pick",
    "cmd_pick_manual",
    "cmd_reset",
    "cmd_serve",
    "cmd_setup",
    "cmd_stats",
    "cmd_status",
    "cmd_unblock",
    "cmd_unhide",
    "cmd_uninstall",
    "main",
]

COMMANDS: dict[str, tuple[str, Callable[[Config, State], object]]] = {
    "scan": ("Scan library & assign a game", do_scan),
    "check": ("Check assigned game completion", do_check),
    "status": ("Show current status", cmd_status),
    "list": ("List games from snapshot", cmd_list),
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
    "gaming-status": ("Show today's gaming time and block state", cmd_gaming_status),
    "gaming-reset": ("Reset today's gaming counter (root + YES)", cmd_gaming_reset),
}

# Extra commands with non-standard arg handling (shown in help but not in COMMANDS).
_EXTRA_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "add-exception": "Request 24h-locked whitelist exception (use --reason)",
    "pick-manual": f"Pick a game by app_id, lock enforcer for {_MANUAL_LOCK_DAYS} days",
    "abandon-pick": (
        f"Undo a manual pick within {_MANUAL_GRACE_DAYS} days (needs app_id)"
    ),
    "block-gaming": "Block ALL gaming for <days> days, no in-app undo",
    "enforce": "Run enforcer: block, uninstall, kill, hide (--demo for a 60s budget)",
    "gaming-unblock": "Force-release playtime bind mounts (root; recovery hatch)",
}

_ALL_COMMANDS: dict[str, str] = _make_all_commands(
    COMMANDS, _EXTRA_COMMAND_DESCRIPTIONS
)


def _resolve_command(raw: str) -> str | None:
    """Map a raw argv[1] onto a known command name (see :mod:`._registry`)."""
    return _resolve_command_in(raw, _ALL_COMMANDS)


def _print_usage(unknown: str | None = None) -> None:
    """Print the command list, optionally explaining a bad command."""
    _print_usage_for(_ALL_COMMANDS, unknown)


def _dispatch_extra_command(command: str, config: Config, state: State) -> bool:
    """Dispatch commands whose arguments do not fit the ``COMMANDS`` signature.

    Split out of :func:`main` to keep its branch count within the complexity
    limit; every entry here takes raw ``sys.argv`` tail arguments rather than
    the ``(config, state)`` pair ``COMMANDS`` callables receive.

    Args:
        command: Canonical command name.
        config: Loaded configuration.
        state: Loaded state.

    Returns:
        True if *command* was handled here.
    """
    if command == "add-exception":
        cmd_add_exception(sys.argv[2:])
        return True
    if command == "block-gaming":
        cmd_block_gaming(sys.argv[2:])
        return True
    if command == "pick-manual":
        cmd_pick_manual(config, state, sys.argv[2:])
        return True
    if command == "abandon-pick":
        cmd_abandon_pick(config, state, sys.argv[2:])
        return True
    if command == "enforce":
        sys.exit(cmd_enforce(config, state, sys.argv[2:]))
    if command == "gaming-unblock":
        sys.exit(cmd_gaming_unblock(sys.argv[2:]))
    return False


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

    if _dispatch_extra_command(command, config, state):
        return

    _, func = COMMANDS[command]
    func(config, state)
