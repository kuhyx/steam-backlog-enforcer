"""Job routes: list, create, read, answer, cancel, and backup restore.

``POST /api/jobs`` decides where a command runs *before* the job store sees
it: privileged commands go to the root daemon
(:func:`._web_privileged.run_privileged`), everything else becomes a job
subprocess. Deciding first matters because the store guards jobs with the
one-mutating-job lock, and an emergency ``gaming-unblock`` must not be
refused as ``busy`` because a scan is running.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._backups import list_backups
from steam_backlog_enforcer._command_params import InvalidParamsError, validate_params
from steam_backlog_enforcer._compat_view import phrase_fields
from steam_backlog_enforcer._friction import expected_phrase, phrase_matches
from steam_backlog_enforcer._steam_restart_guard import (
    GAME_RUNNING_JOB_MSG,
    game_is_running,
)
from steam_backlog_enforcer._web_daemon import confirm_phrase_of
from steam_backlog_enforcer._web_errors import ApiError, from_job_error, not_found
from steam_backlog_enforcer._web_io import Reply, no_content, ok
from steam_backlog_enforcer._web_privileged import run_privileged
from steam_backlog_enforcer.jobs._control import cancel, write_answer
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS, is_privileged
from steam_backlog_enforcer.jobs._store import create_job
from steam_backlog_enforcer.jobs._view import list_jobs, read_job
from steam_installer.errors import InstallerError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from steam_backlog_enforcer._web_io import Request

# The UI's enforce modes onto the job registry's ``demo`` flag; ``restart``
# (demo 0) is the daemon's.
_ENFORCE_MODES = {"demo": 1, "restart": 0}

# Jobs whose phrase and game-running guard are checked here, before a job
# exists, so a refusal never leaves a job behind; the job re-checks both.
_PRECHECKED: Final = frozenset({"repair-ghosts", "map-installed"})

# The phrase slots a prechecked job's template names, from its clean params.
_PHRASE_FIELDS: Final[
    dict[str, Callable[[Mapping[str, object]], dict[str, object]]]
] = {"map-installed": phrase_fields}


def _invalid(message: str) -> ApiError:
    """An ``invalid_params`` 400."""
    return ApiError(message, code="invalid_params")


def _enforce_params(params: dict[str, Any]) -> dict[str, Any]:
    """Translate ``{"mode": "demo"|"restart"}`` into the registry's ``demo``.

    Raises:
        ApiError: ``invalid_params`` for a missing or unknown mode.
    """
    if "mode" not in params and "demo" in params:
        return params
    mode = params.get("mode")
    if set(params) - {"mode"} or mode not in _ENFORCE_MODES:
        msg = "enforce needs params.mode: 'restart' or 'demo'."
        raise _invalid(msg)
    return {"demo": _ENFORCE_MODES[str(mode)]}


def _job_request(request: Request) -> tuple[str, dict[str, Any], str | None]:
    """Unpack a ``JobRequest`` body.

    Raises:
        ApiError: ``invalid_params`` for a malformed body.
    """
    command, params = request.body.get("command"), request.body.get("params", {})
    phrase = request.body.get("confirm_phrase")
    if not isinstance(command, str) or not isinstance(params, dict):
        msg = "Body must be {command: string, params: object}."
        raise _invalid(msg)
    if phrase is not None and not isinstance(phrase, str):
        msg = "confirm_phrase must be a string."
        raise _invalid(msg)
    if command == "enforce":
        params = _enforce_params(params)
    return command, params, phrase


def _phrase_fields(command: str, params: Mapping[str, object]) -> dict[str, object]:
    """The phrase slots for *command*; bad params are a 400, unreadable Steam a 502.

    Raises:
        ApiError: ``invalid_params`` or ``op_failed``.
    """
    fields = _PHRASE_FIELDS.get(command)
    if fields is None:
        return {}
    try:
        return fields(params)
    except InvalidParamsError as exc:
        raise _invalid(str(exc)) from None
    except (InstallerError, OSError, ValueError) as exc:
        raise ApiError(str(exc), code="op_failed") from None


def _precheck(command: str, params: Mapping[str, object], phrase: str | None) -> None:
    """Refuse a :data:`_PRECHECKED` job before it is created.

    The phrase goes first: it is what the user can fix, and it stays
    provable while a game runs. Its slots (``map-installed``'s count) come
    from the params, so a bad id list is refused before either.

    Raises:
        ApiError: ``invalid_params``, ``wrong_phrase``, or ``game_running``
            while a game runs.
    """
    if command not in _PRECHECKED:
        return
    expected = expected_phrase(command, **_phrase_fields(command, params)) or ""
    if not phrase_matches(expected, phrase or ""):
        msg = f'Type "{expected}" to run {command}.'
        raise ApiError(msg, code="wrong_phrase")
    if game_is_running():
        raise ApiError(GAME_RUNNING_JOB_MSG, code="game_running")


def jobs_view(_request: Request) -> Reply:
    """``GET /api/jobs`` — newest first, at most 50."""
    return ok(list_jobs())


def job_view(request: Request) -> Reply:
    """``GET /api/jobs/{id}``."""
    try:
        return ok(read_job(request.args[0]))
    except JobError as exc:
        raise from_job_error(exc) from None


def create_job_view(request: Request) -> Reply:
    """``POST /api/jobs`` — ``201`` Job, or ``202`` PendingAction (reset)."""
    command, params, phrase = _job_request(request)
    if command not in JOB_FLAGS:
        msg = f"{command!r} does not run as a job."
        raise ApiError(msg, code="unknown_command")
    try:
        clean = validate_params(command, params)
    except InvalidParamsError as exc:
        raise _invalid(str(exc)) from None
    if is_privileged(command, clean):
        return run_privileged(command, clean, phrase)
    _precheck(command, clean, phrase)
    try:
        job_id = create_job(command, clean, confirm_phrase=phrase)
    except JobError as exc:
        raise from_job_error(exc) from None
    return Reply(HTTPStatus.CREATED, read_job(job_id))


def answer_view(request: Request) -> Reply:
    """``POST /api/jobs/{id}/answer`` — deliver a ``PromptAnswer``."""
    prompt_id, value = request.body.get("prompt_id"), request.body.get("value")
    if not isinstance(prompt_id, str) or not isinstance(value, str):
        msg = "Body must be {prompt_id: string, value: string}."
        raise _invalid(msg)
    try:
        write_answer(request.args[0], prompt_id, value)
    except JobError as exc:
        raise from_job_error(exc) from None
    return no_content()


def cancel_view(request: Request) -> Reply:
    """``POST /api/jobs/{id}/cancel`` — cancellable, or inside a cancel window."""
    try:
        cancel(request.args[0])
    except JobError as exc:
        raise from_job_error(exc) from None
    return no_content()


def restore_backup_view(request: Request) -> Reply:
    """``POST /api/backups/{id}/restore`` — phrase checked here, then a job.

    The job re-checks the same phrase (it arrives as the job's preset
    answer), so neither layer trusts the other.
    """
    backup_id = request.args[0]
    if backup_id not in {backup.id for backup in list_backups()}:
        msg = f"No such backup: {backup_id!r}"
        raise not_found(msg)
    typed = confirm_phrase_of(request)
    expected = expected_phrase("restore-backup", backup_id=backup_id) or ""
    if not phrase_matches(expected, typed):
        msg = f'Type "{expected}" to restore this backup.'
        raise ApiError(msg, code="wrong_phrase")
    try:
        job_id = create_job(
            "restore-backup", {"backup_id": backup_id}, confirm_phrase=typed
        )
    except JobError as exc:
        raise from_job_error(exc) from None
    return Reply(HTTPStatus.CREATED, read_job(job_id))
