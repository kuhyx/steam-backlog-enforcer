"""Which command runs as which job, and how.

Every handler is the CLI command itself, run under the job's output sink,
progress reporter and prompter (installed by :mod:`._runner`), so a job
cannot drift from what ``./run.sh <cmd>`` does. Params arrive validated
(:mod:`steam_backlog_enforcer._command_params`) and are turned back into
the argument list the CLI function already parses.

Privileged commands are registered too, with a handler that refuses: they
run in the root daemon, and the web server routes them there before a job
would ever be created (see :func:`._specs.is_privileged`).

Only the job subprocess (:mod:`._runner`) imports this module: it pulls in
every command, and the web server must not (see :mod:`._specs`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._backups import restore_backup
from steam_backlog_enforcer._cmd_playtime import cmd_enforce
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._prompter import PromptAbortedError, confirm_phrase
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs._errors import PrivilegedViaDaemonError
from steam_backlog_enforcer.main import (
    cmd_abandon_pick,
    cmd_add_exception,
    cmd_done,
    cmd_hide,
    cmd_install,
    cmd_list,
    cmd_pick,
    cmd_pick_manual,
    cmd_reset,
    cmd_stats,
    cmd_unhide,
    cmd_uninstall,
)
from steam_backlog_enforcer.scanning import do_check, do_scan

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from steam_backlog_enforcer._command_params import ParamValue
    from steam_backlog_enforcer._progress import Progress
    from steam_backlog_enforcer._prompter import Prompter

type JobResult = dict[str, object] | None
type JobHandler = Callable[[Mapping[str, ParamValue], Progress, Prompter], JobResult]


def _assignment(state: State) -> dict[str, object]:
    """The result data every backlog job returns: what is assigned now."""
    return {
        "current_app_id": state.current_app_id,
        "current_game_name": state.current_game_name or None,
    }


def _cli(command: Callable[[Config, State], object]) -> JobHandler:
    """Wrap a ``(config, state)`` CLI command as a job handler."""

    def handler(
        _params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
    ) -> JobResult:
        state = State.load()
        command(Config.load(), state)
        return _assignment(state)

    return handler


def _with_args(
    command: Callable[[Config, State, list[str]], object], param: str
) -> JobHandler:
    """Wrap a ``(config, state, args)`` command taking one positional arg."""

    def handler(
        params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
    ) -> JobResult:
        state = State.load()
        command(Config.load(), state, [str(params[param])])
        return _assignment(state)

    return handler


def _add_exception(
    params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
) -> JobResult:
    """``add-exception <app_id> --reason <reason>``."""
    cmd_add_exception([str(params["app_id"]), "--reason", str(params["reason"])])
    return {"app_id": params["app_id"]}


def _enforce_demo(
    params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
) -> JobResult:
    """``enforce --demo``: the 60-second budget, until cancelled."""
    if not params.get("demo"):
        command = "enforce"
        raise PrivilegedViaDaemonError(command)
    return {"exit_code": cmd_enforce(Config.load(), State.load(), ["--demo"])}


def _restore_backup(
    params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
) -> JobResult:
    """Replace ``state.json`` with a backup, after the typed phrase."""
    backup_id = str(params["backup_id"])
    if not confirm_phrase(
        "restore-backup",
        f"Replace the current state with backup {backup_id}?",
        backup_id=backup_id,
    ):
        msg = "Aborted."
        raise PromptAbortedError(msg)
    previous = restore_backup(backup_id)
    _echo(f"Restored backup {backup_id}.")
    if previous is not None:
        _echo(f"The replaced state was saved as backup {previous.id}.")
    return {"restored": backup_id, "previous_backup": previous and previous.id}


def _via_daemon(command: str) -> JobHandler:
    """A placeholder for a privileged command: it always refuses."""

    def handler(
        _params: Mapping[str, ParamValue], _progress: Progress, _prompter: Prompter
    ) -> JobResult:
        raise PrivilegedViaDaemonError(command)

    return handler


# (params, progress, prompter) -> result data, one per job command; the
# lock/cancel/privilege flags for the same commands are in _specs.JOB_FLAGS.
HANDLERS: dict[str, JobHandler] = {
    "check": _cli(do_check),
    "scan": _cli(do_scan),
    "done": _cli(cmd_done),
    "pick": _cli(cmd_pick),
    "pick-manual": _with_args(cmd_pick_manual, "app_id"),
    "abandon-pick": _with_args(cmd_abandon_pick, "app_id"),
    "install": _cli(cmd_install),
    "uninstall": _cli(cmd_uninstall),
    "hide": _cli(cmd_hide),
    "unhide": _cli(cmd_unhide),
    "add-exception": _add_exception,
    "reset": _cli(cmd_reset),
    "restore-backup": _restore_backup,
    "stats": _cli(cmd_stats),
    "list": _cli(cmd_list),
    "enforce": _enforce_demo,
} | {
    command: _via_daemon(command)
    for command in (
        "gaming-reset",
        "gaming-unblock",
        "block-gaming",
        "unblock",
        "buy-dlc",
    )
}
