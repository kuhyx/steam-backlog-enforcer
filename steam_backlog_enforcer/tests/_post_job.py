"""Shared POST-time friction test helpers: drive ``create_job_view`` once."""

from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _web_jobs
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._web_request import make_request

if TYPE_CHECKING:
    from collections.abc import Iterable
    from contextlib import AbstractContextManager
    from http import HTTPStatus

WEB = "steam_backlog_enforcer._web_jobs"


def post_job(
    command: str,
    params: dict[str, object],
    phrase: str | None,
    *,
    running: bool = False,
    extra: Iterable[AbstractContextManager[object]] = (),
) -> tuple[object, MagicMock]:
    """POST *command* with the job store and the game guard patched.

    Returns the reply (or the ``ApiError`` raised) and the ``create_job`` mock.
    """
    body: dict[str, object] = {"command": command, "params": params}
    if phrase is not None:
        body["confirm_phrase"] = phrase
    with ExitStack() as stack:
        create = stack.enter_context(patch(f"{WEB}.create_job", return_value="j1"))
        stack.enter_context(patch(f"{WEB}.read_job", return_value={"id": "j1"}))
        stack.enter_context(patch(f"{WEB}.game_is_running", return_value=running))
        for patcher in extra:
            stack.enter_context(patcher)
        try:
            reply: object = _web_jobs.create_job_view(make_request(body=body))
        except ApiError as exc:
            reply = exc
    return reply, create


def assert_refused(
    reply: object,
    create: MagicMock,
    code: str,
    status: HTTPStatus | None = None,
) -> None:
    """The POST was refused with *code* (and *status*) and no job was made."""
    assert isinstance(reply, ApiError)
    assert reply.code == code
    if status is not None:
        assert reply.status == status
    create.assert_not_called()
