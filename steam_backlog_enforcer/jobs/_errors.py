"""Errors the job API raises, carrying the contract's ``ApiErrorCode``."""

from __future__ import annotations

from typing import Literal

JobErrorCode = Literal[
    "unknown_command",
    "invalid_params",
    "not_found",
    "wrong_phrase",
    "locked",
    "busy",
    "not_cancellable",
    "op_failed",
]


class JobError(Exception):
    """A job request the server must refuse (4xx; 502 for ``op_failed``).

    Attributes:
        code: The contract's ``ApiErrorCode`` for the response body.
        message: Human text for the response body.
    """

    def __init__(self, message: str, *, code: JobErrorCode) -> None:
        """Store the code next to the message."""
        super().__init__(message)
        self.code: JobErrorCode = code
        self.message = message


class PrivilegedViaDaemonError(Exception):
    """The command needs root, so it runs in the daemon, never as a job.

    The web server catches this and routes the request to the control
    socket instead (``DOCS-web-control-api.md``, "Control socket").
    """

    def __init__(self, command: str) -> None:
        """Name the command that has to go through the daemon."""
        super().__init__(f"{command} runs in the root daemon, not as a web job.")
        self.command = command


class JobCancelledError(Exception):
    """Raised inside a cancellable job when it receives SIGTERM."""
