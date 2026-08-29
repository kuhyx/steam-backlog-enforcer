"""Constants and lock helpers shared by the CLI command modules.

Leaf module: it imports from the wider package but never from a sibling in
``main``, so the command modules can all depend on it without creating an
import cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sys
from typing import TYPE_CHECKING

from steam_backlog_enforcer._actions import (
    active_manual_picks,
    manual_pick_age_days,
)
from steam_backlog_enforcer._actions import (
    is_manual_pick_locked as _is_manual_pick_locked,
)
from steam_backlog_enforcer._allowed_games import (
    MANUAL_LOCK_DAYS as _MANUAL_LOCK_DAYS,
)
from steam_backlog_enforcer._total_block import (
    TotalBlockStatus,
    get_total_block_status,
    is_total_block_active,
)
from steam_backlog_enforcer.game_install import _echo

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State

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
        # The daily gaming budget is orthogonal to which game is assigned, and
        # gaming-unblock is a recovery hatch for a stuck bind mount - locking
        # it behind a manual pick would leave Steam masked with no way back.
        "gaming-status",
        "gaming-unblock",
        "gaming-reset",
    }
)

# Commands that remain usable while a total gaming block is active. Far
# stricter than _MANUAL_LOCK_EXEMPT_COMMANDS: no done/pick/reset/
# add-exception - there is no in-app way to shorten a total block.
#
# gaming-unblock is included because a playtime bind mount makes the total
# block's own `pacman -R steam` fail EBUSY - it must stay reachable exactly
# when the two collide. gaming-reset is NOT included: it shortens enforcement.
_TOTAL_BLOCK_EXEMPT_COMMANDS = frozenset(
    {"status", "enforce", "gaming-status", "gaming-unblock"}
)


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
            days_left = (deadline - datetime.now(UTC)).days
            _echo(f"    Locked since: {started.strftime('%Y-%m-%d')}")
            _echo(
                f"    Deadline:     {deadline.strftime('%Y-%m-%d')}"
                f" ({max(0, days_left)} day(s) remaining)"
            )
        except ValueError:
            pass

    age_days = manual_pick_age_days(state, int(str(app_id)))
    if age_days is not None:
        _echo(
            f"    Undo:         abandon-pick {app_id}"
            f"  (picked {age_days:.1f} day(s) ago)"
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
