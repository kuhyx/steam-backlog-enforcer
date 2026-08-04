"""CLI handlers for the daily gaming budget.

Every ``_echo`` / ``input`` / ``sys.exit`` for this feature lives here rather
than in :mod:`steam_backlog_enforcer._playtime` or
:mod:`steam_backlog_enforcer._playtime_block`, so the MCP server can import
those modules' leaf helpers without any risk of writing to stdout — which is
the JSON-RPC channel.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import TYPE_CHECKING

from steam_backlog_enforcer._enforce_loop import do_enforce
from steam_backlog_enforcer._playtime import (
    PlaytimeState,
    gaming_day_key,
    load_state,
    rules_for,
    save_state,
    state_path,
)
from steam_backlog_enforcer._playtime_block import (
    block_targets,
    mounted_targets,
    release_block,
)
from steam_backlog_enforcer.game_install import _echo

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

_DEMO_FLAG = "--demo"


def cmd_enforce(config: Config, state: State, args: list[str]) -> int:
    """Run the enforcement loop.

    Args:
        config: Enforcer configuration.
        state: Current enforcer state.
        args: Arguments after the command name.

    Returns:
        Process exit code.
    """
    unknown = [arg for arg in args if arg != _DEMO_FLAG]
    if unknown:
        # Never ignore an unrecognised flag here: a mistyped "--Demo" would
        # silently run the real 8-hour budget during what was meant to be a
        # 60-second demo, and the mistake only shows up hours later.
        _echo(f"Unknown argument(s): {' '.join(unknown)}")
        _echo(f"Usage: enforce [{_DEMO_FLAG}]")
        return 2

    demo = _DEMO_FLAG in args
    if demo:
        _echo("DEMO MODE: gaming budget is 60 seconds, using a separate state file.")
    do_enforce(config, state, demo=demo)
    return 0


def cmd_gaming_status(config: Config, _state: State) -> None:
    """Print today's gaming-budget usage and block state.

    Args:
        config: Enforcer configuration.
        _state: Unused; required by the command dispatch signature.
    """
    for demo in (False, True):
        rules = rules_for(config, demo=demo)
        stored = load_state(demo=demo)
        if stored is None and demo:
            continue
        _echo(f"{'Demo' if demo else 'Gaming'} budget:")
        _echo(f"  state file:     {state_path(demo=demo)}")
        _echo(f"  budget_seconds: {rules.budget_seconds:.0f}")
        if stored is None:
            _echo("  (no state recorded yet)")
        else:
            remaining = max(0.0, rules.budget_seconds - stored.seconds)
            _echo(f"  gaming day:     {stored.day_key} (starts 06:00 local)")
            _echo(f"  used:           {stored.seconds:.0f}s")
            _echo(f"  remaining:      {remaining:.0f}s")
            _echo(f"  blocked:        {stored.is_blocked()}")

    masked = mounted_targets()
    _echo(f"Masked launchers: {len(masked)}/{len(block_targets())}")
    for target in sorted(masked):
        _echo(f"  {target}")


def cmd_gaming_reset(config: Config, _state: State) -> int:
    """Zero today's gaming counter and lift the block.

    Args:
        config: Enforcer configuration.
        _state: Unused; required by the command dispatch signature.

    Returns:
        Process exit code.
    """
    if os.geteuid() != 0:
        _echo("gaming-reset requires root (it releases bind mounts).")
        return 1

    _echo("This resets today's gaming counter and lifts the block.")
    if input("Type YES to confirm: ").strip() != "YES":
        _echo("Aborted.")
        return 1

    released = release_block()
    now = datetime.now(timezone.utc).astimezone()
    save_state(
        PlaytimeState(day_key=gaming_day_key(now), last_tick_at=now.timestamp()),
        demo=rules_for(config, demo=False).demo,
    )
    _echo(f"Gaming counter reset. Released {len(released)} mount(s).")
    return 0


def cmd_gaming_unblock(args: list[str]) -> int:
    """Release every playtime mount unconditionally.

    The recovery hatch: it consults no state at all, so it works when the state
    file is unreadable, the daemon is down, or a block was left behind by a
    previous run.

    Args:
        args: Arguments after the command name.

    Returns:
        Process exit code.
    """
    if args:
        _echo(f"Unknown argument(s): {' '.join(args)}")
        return 2
    if os.geteuid() != 0:
        _echo("gaming-unblock requires root (it releases bind mounts).")
        return 1

    released = release_block()
    if not released:
        _echo("No playtime mounts were active.")
        return 0
    for target in released:
        _echo(f"Released {target}")
    return 0
