"""The enforce loop's handle on the control socket.

``start_control`` is the only thing the loop calls. It never raises and never
blocks the enforcer: if the socket cannot be served (not root, demo run, no
desktop user, bind failure) the loop gets an inert handle and carries on
exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
import pwd
import threading
from typing import TYPE_CHECKING

from steam_backlog_enforcer._ctl_context import CtlContext
from steam_backlog_enforcer._ctl_gap import record_exit
from steam_backlog_enforcer._ctl_server import CtlServer
from steam_backlog_enforcer._desktop_env import resolve_desktop_user
from steam_backlog_enforcer._playtime import playtime_tick

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_session import PlaytimeSession
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)


class DaemonControl:
    """Lock + restart flag shared with the control socket (inert if none)."""

    def __init__(self, ctx: CtlContext, server: CtlServer | None) -> None:
        """Wrap the shared context and the (optional) running server.

        Args:
            ctx: Shared op context; owns the tick lock and restart event.
            server: The running socket server, or ``None`` when inert.
        """
        self.ctx = ctx
        self._server = server

    @property
    def tick_lock(self) -> threading.Lock:
        """Held by the loop for each iteration so ops never interleave with one."""
        return self.ctx.tick_lock

    @property
    def restart_requested(self) -> bool:
        """Whether the ``restart`` op has been accepted."""
        return self.ctx.restart_event.is_set()

    def flush_for_restart(
        self, config: Config, session: PlaytimeSession, *, interval: float, demo: bool
    ) -> bool:
        """Bill the time up to now before the process exits for a restart.

        Everything else the enforcer relies on is already on disk after each
        tick (the budget state, the cutoff time, fired warnings, the store
        window deadline); the only thing a restart can lose is the seconds
        since the last tick, so one more accounting tick closes that gap. Call
        with the tick lock held.

        Returns:
            Whether the loop should exit now.
        """
        if not self.restart_requested:
            return False
        playtime_tick(config, interval=interval, session=session, demo=demo)
        record_exit()
        logger.warning("State flushed; exiting so systemd restarts the enforcer.")
        return True

    def close(self) -> None:
        """Stop serving and remove the socket file."""
        if self._server is not None:
            self._server.stop()


def _is_supervised() -> bool:
    """Whether systemd started this process (it sets ``INVOCATION_ID``)."""
    return bool(os.environ.get("INVOCATION_ID"))


def start_control(config: Config, *, demo: bool) -> DaemonControl:
    """Start the control socket if this process is the real root daemon.

    Args:
        config: The daemon's configuration.
        demo: Whether this is a ``--demo`` run (never serves: it could take the
            socket from the real daemon).

    Returns:
        A handle; inert when the socket is not being served.
    """
    ctx = CtlContext(
        config=config,
        tick_lock=threading.Lock(),
        restart_event=threading.Event(),
        started_at=datetime.now(UTC),
        supervised=_is_supervised(),
    )
    if demo or os.geteuid() != 0:
        return DaemonControl(ctx, None)
    user = resolve_desktop_user()
    try:
        entry = pwd.getpwnam(user) if user else None
    except KeyError:
        entry = None
    if entry is None or entry.pw_uid == 0:
        # Fail closed: without a known unprivileged owner there is nobody the
        # socket could safely be for.
        logger.error("Control socket disabled: no desktop user (%r)", user)
        return DaemonControl(ctx, None)
    server = CtlServer(ctx, desktop_uid=entry.pw_uid, desktop_gid=entry.pw_gid)
    return DaemonControl(ctx, server if server.start() else None)
