"""``enforce --demo``: the gaming budget alone, on a 60-second budget.

The demo shows the budget's escalation -- warnings, Steam shutdown, killing
the games -- without waiting hours. It runs nothing else of the enforce loop:
the store block, install guard, unassigned-game kills, total-block upkeep and
``chattr`` are the daemon's, and a copy run as the desktop user (the web UI)
could only fail at them, silently. It never touches the real Steam-binary
mounts either (:func:`._playtime_cutoff.reconcile_for`).

Whatever it cannot do, it refuses out loud: under a total gaming block Steam
is uninstalled and the budget is not counted, so there is nothing to show.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._enforce_loop import ENFORCE_INTERVAL
from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer._playtime_session import new_session
from steam_backlog_enforcer._total_block import (
    get_total_block_status,
    is_total_block_active,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config

EXIT_REFUSED = 1


def _refuse_under_total_block(when: str) -> int:
    """Say why a demo cannot run while a total block is on.

    Args:
        when: How the block was found ("cannot start" / "stopped").

    Returns:
        The exit code to leave with.
    """
    days = get_total_block_status().days_remaining
    _echo(
        f"Demo {when}: total gaming block active ({days:.1f} day(s) left). "
        "Steam is uninstalled and the budget is not counted, so there is "
        "nothing for a demo budget to run against."
    )
    return EXIT_REFUSED


def run_demo(config: Config) -> int:
    """Run the demo budget until stopped (Ctrl+C or a cancelled job).

    Args:
        config: Enforcer configuration.

    Returns:
        Process exit code: 0 when stopped, 1 when a total block refused it.
    """
    if is_total_block_active():
        return _refuse_under_total_block("cannot start")
    _echo("DEMO MODE: gaming budget is 60 seconds, using a separate state file.")
    _echo("  Runs the budget only: warnings, Steam shutdown, game kills.")
    _echo("  The store, installs and Steam's binaries stay with the daemon.")
    _echo(f"  Ticking every {ENFORCE_INTERVAL}s until stopped.\n")
    session = new_session(demo=True)
    try:
        while True:
            if is_total_block_active():
                return _refuse_under_total_block("stopped")
            playtime_tick(config, interval=ENFORCE_INTERVAL, session=session, demo=True)
            time.sleep(ENFORCE_INTERVAL)
    except KeyboardInterrupt:
        _echo("\nDemo stopped.")
    return 0
