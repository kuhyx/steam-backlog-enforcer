"""Stop and start the Steam client around operations it would otherwise fight.

Steam owns `appmanifest_*.acf` while it runs: it rewrites them from its own
in-memory state, so anything this tool writes underneath a live client is
discarded. It also actively writes into `steamapps/downloading/<appid>/`, so
adopting a staged tree while it runs races a live download.

The client is only ever asked to leave politely (`steam -shutdown`). Nothing
here sends a signal: SIGKILLing a client mid-write is how a manifest ends up
truncated, and a hung Steam is a reason to stop and tell the user, not to
escalate.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable

from steam_installer import recognize

SHUTDOWN_TIMEOUT = 60.0
POLL_INTERVAL = 0.5


class SteamStillRunning(Exception):
    """Steam was asked to exit and did not."""


def stop(
    logger: logging.Logger,
    *,
    timeout: float = SHUTDOWN_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Shut Steam down. Returns True if it had been running, False if it wasn't.

    Raises SteamStillRunning if it refuses to exit, so callers can abort
    without having touched anything.
    """
    if not recognize.steam_client_pids():
        return False

    logger.info("Shutting down the Steam client...")
    subprocess.run(["steam", "-shutdown"], check=False, capture_output=True)

    waited = 0.0
    while waited < timeout:
        if not recognize.steam_client_pids():
            logger.info("Steam exited after %.0fs.", waited)
            return True
        sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

    pids = recognize.steam_client_pids()
    raise SteamStillRunning(
        f"Steam is still running after {timeout:.0f}s (pid "
        f"{', '.join(str(p) for p in pids)}). Close it by hand and re-run."
    )


def start(logger: logging.Logger) -> None:
    """Relaunch Steam, detached, so it outlives this process."""
    logger.info("Restarting the Steam client...")
    # Detached on purpose: Steam outlives this process and is never waited on.
    subprocess.Popen(
        ["steam"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
