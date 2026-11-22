"""Control-socket op ``add_exception``: whitelist one game as root.

``approved_exceptions.json`` carries ``chattr +i``, so the unprivileged web
server and CLI cannot replace it (2026-11-22: every web add-exception died
with ``PermissionError``). The daemon writes it instead: it clears the flag,
writes, and sets it again.

The client sends only the app id, the reason and the typed phrase. The daemon
looks the name up itself (falling back to ``AppID=<id>``, as the CLI does) and
re-checks the reason, the phrase, the locks and duplicates, so talking to the
socket directly skips none of them.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_context import (
    check_locks,
    hold_tick,
    int_arg,
    require_phrase,
    str_arg,
)
from steam_backlog_enforcer._ctl_protocol import INVALID_PARAMS, OP_FAILED, CtlError
from steam_backlog_enforcer._snapshot import snapshot_game_name
from steam_backlog_enforcer._whitelist import validate_reason
from steam_backlog_enforcer._whitelist_locking import add_pending_exception
from steam_backlog_enforcer._whitelist_relock import (
    NOT_LOCKED_MESSAGE,
    ExceptionNotLockedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._ctl_context import CtlContext

logger = logging.getLogger(__name__)

_MAX_APP_ID: Final = 2**31 - 1


def op_add_exception(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Add a whitelist exception, active immediately, as ``add-exception`` does."""
    app_id = int_arg(args, "app_id", 1, _MAX_APP_ID)
    reason = str_arg(args, "reason")
    err = validate_reason(reason)
    if err is not None:
        raise CtlError(INVALID_PARAMS, err)
    game_name = snapshot_game_name(app_id) or f"AppID={app_id}"
    require_phrase("add-exception", args.get("phrase"), game_name=game_name)
    with hold_tick(ctx):
        check_locks("add-exception")
        try:
            message = add_pending_exception(app_id, reason)
        except ExceptionNotLockedError as exc:
            logger.exception("Exception for %s saved, file left unlocked", app_id)
            raise CtlError(OP_FAILED, NOT_LOCKED_MESSAGE) from exc
        except ValueError as exc:  # already approved
            raise CtlError(INVALID_PARAMS, str(exc)) from exc
        except OSError as exc:
            raise CtlError(
                OP_FAILED, f"could not write the exceptions file: {exc}"
            ) from exc
    logger.warning("Exception approved for %s (control socket)", app_id)
    return {"app_id": app_id, "game_name": game_name, "message": message}


EXCEPTION_OPS: Final[
    dict[str, Callable[[CtlContext, dict[str, object]], dict[str, object]]]
] = {"add_exception": op_add_exception}
