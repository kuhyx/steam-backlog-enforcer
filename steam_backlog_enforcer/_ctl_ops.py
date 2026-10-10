"""The allowlisted ops of the control socket.

``OPS`` is the whole attack surface: a request naming anything else is
refused as an unknown command. There is no stop, no disable and no generic
command execution -- every op does one named, bounded thing. Each privileged
op re-checks its own typed phrase, argument bounds and the same locks the CLI
honours, because the web server in front of it is not trusted to have done so.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_context import (
    check_locks,
    hold_tick,
    int_arg,
    require_phrase,
)
from steam_backlog_enforcer._ctl_protocol import OP_FAILED, CtlError
from steam_backlog_enforcer._ctl_reset import RESET_OPS
from steam_backlog_enforcer._ctl_restart import RESTART_OPS, restart_available_at
from steam_backlog_enforcer._playtime_block import release_block
from steam_backlog_enforcer._store_window import MAX_WINDOW_MINUTES, open_store_window
from steam_backlog_enforcer._total_block import (
    get_total_block_status,
    start_total_block,
)
from steam_backlog_enforcer.config import CONFIG_DIR, STATE_FILE, State

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._ctl_context import CtlContext

logger = logging.getLogger(__name__)

UNIT_NAME: Final = "steam-backlog-enforcer.service"
DEFAULT_JOURNAL_LINES: Final = 50
MAX_JOURNAL_LINES: Final = 200
_MAX_LINE_CHARS: Final = 500
_JOURNAL_TIMEOUT_SECONDS: Final = 5
_JOURNALCTL: Final = "/usr/bin/journalctl"
# A block is irreversible from the app; a typo like 3650 must not be one
# confirmation away. The phrase repeats the number, which is the other half.
MAX_BLOCK_DAYS: Final = 365


def op_ping(_ctx: CtlContext, _args: dict[str, object]) -> dict[str, object]:
    """Liveness probe."""
    return {"pong": True}


def op_status(ctx: CtlContext, _args: dict[str, object]) -> dict[str, object]:
    """The daemon's state, start time, pid and when a restart is next allowed."""
    return {
        "state": "restarting" if ctx.restart_event.is_set() else "running",
        "started_at": ctx.started_at.isoformat(),
        "pid": os.getpid(),
        "restart_available_at": restart_available_at(),
    }


def op_journal_tail(_ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """The last *lines* journal lines of the enforcer unit (capped)."""
    lines = (
        int_arg(args, "lines", 1, MAX_JOURNAL_LINES)
        if "lines" in args
        else DEFAULT_JOURNAL_LINES
    )
    try:
        result = subprocess.run(
            [
                _JOURNALCTL,
                "-u",
                UNIT_NAME,
                "-n",
                str(lines),
                "--no-pager",
                "-q",
                "-o",
                "short-iso",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_JOURNAL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CtlError(OP_FAILED, f"journalctl failed: {exc}") from exc
    return {
        "lines": [line[:_MAX_LINE_CHARS] for line in result.stdout.splitlines()],
    }


def _hand_back_state_file() -> None:
    """Give state.json back to the desktop user if root just created it.

    ``State.save`` keeps an existing file's owner, but a file that did not
    exist yet comes out root-owned and would lock the unprivileged CLI (and
    web server) out of its own state.
    """
    with contextlib.suppress(OSError):
        owner = CONFIG_DIR.stat()
        if STATE_FILE.stat().st_uid != owner.st_uid:
            os.chown(STATE_FILE, owner.st_uid, owner.st_gid)


def op_store_unblock(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Open the timed store window (1 to 30 minutes), as ``run.sh unblock`` does."""
    minutes = int_arg(args, "minutes", 1, MAX_WINDOW_MINUTES)
    require_phrase("unblock", args.get("phrase"), minutes=minutes)
    with hold_tick(ctx):
        check_locks("unblock")
        try:
            until = open_store_window(State.load(), minutes)
        except RuntimeError as exc:
            raise CtlError(OP_FAILED, str(exc)) from exc
        finally:
            _hand_back_state_file()
    logger.warning("Store window opened for %d min (control socket)", minutes)
    return {"minutes": minutes, "until": until.isoformat()}


def op_block_gaming(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Start a total gaming block of *days* days. There is no undo."""
    days = int_arg(args, "days", 1, MAX_BLOCK_DAYS)
    require_phrase("block-gaming", args.get("phrase"), days=days)
    with hold_tick(ctx):
        check_locks("block-gaming")
        logger.warning("Total gaming block for %d day(s) requested (socket)", days)
        if not start_total_block(days):
            raise CtlError(OP_FAILED, "failed to engage the block (see the log)")
    until = get_total_block_status().until
    return {"days": days, "until": until.isoformat() if until else None}


def op_gaming_unblock(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Release every playtime mount (the recovery hatch)."""
    require_phrase("gaming-unblock", args.get("phrase"))
    with hold_tick(ctx):
        check_locks("gaming-unblock")
        released = release_block()
    return {"released": [str(path) for path in released]}


OPS: Final[dict[str, Callable[[CtlContext, dict[str, object]], dict[str, object]]]] = {
    "ping": op_ping,
    "status": op_status,
    "journal_tail": op_journal_tail,
    "store_unblock": op_store_unblock,
    "block_gaming": op_block_gaming,
    "gaming_unblock": op_gaming_unblock,
    **RESET_OPS,
    **RESTART_OPS,
}
