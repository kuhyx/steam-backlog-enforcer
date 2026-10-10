"""The web API's error type and how every lower-level error maps onto it.

Every refusal leaves the server as ``{"error": "<code>", "message": "…"}``
with the status below (``DOCS-web-control-api.md``, "Endpoints"). The job
store raises :class:`~steam_backlog_enforcer.jobs._errors.JobError` and the
daemon client raises :class:`~steam_backlog_enforcer._ctl_protocol.CtlError`
/ ``DaemonUnreachableError``; the converters here are the only place their codes
become HTTP statuses, so one code always means one status.
"""

from __future__ import annotations

from http import HTTPStatus
import math
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from steam_backlog_enforcer._ctl_protocol import CtlError
    from steam_backlog_enforcer.jobs._errors import JobError

STATUS_BY_CODE: Final[dict[str, HTTPStatus]] = {
    "bad_token": HTTPStatus.FORBIDDEN,
    "bad_origin": HTTPStatus.FORBIDDEN,
    "bad_host": HTTPStatus.FORBIDDEN,
    "unknown_command": HTTPStatus.BAD_REQUEST,
    "invalid_params": HTTPStatus.BAD_REQUEST,
    "wrong_phrase": HTTPStatus.BAD_REQUEST,
    "not_found": HTTPStatus.NOT_FOUND,
    "locked": HTTPStatus.CONFLICT,
    "busy": HTTPStatus.CONFLICT,
    "countdown_running": HTTPStatus.CONFLICT,
    "not_cancellable": HTTPStatus.CONFLICT,
    "pending_lapsed": HTTPStatus.GONE,
    "rate_limited": HTTPStatus.TOO_MANY_REQUESTS,
    "daemon_unreachable": HTTPStatus.SERVICE_UNAVAILABLE,
    "server_stale": HTTPStatus.SERVICE_UNAVAILABLE,
    "op_failed": HTTPStatus.BAD_GATEWAY,
    "unsupported": HTTPStatus.NOT_IMPLEMENTED,
}


class ApiError(Exception):
    """A request the server answers with a contract error body.

    Attributes:
        code: The contract's ``ApiErrorCode``.
        message: Human text for the body.
        status: HTTP status (defaults to the code's entry in the table).
        retry_after: Seconds the client should wait (``Retry-After``), if any.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: HTTPStatus | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the code, message, status and optional retry delay."""
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status or STATUS_BY_CODE.get(code, HTTPStatus.BAD_GATEWAY)
        self.retry_after = retry_after

    def body(self) -> dict[str, object]:
        """The JSON object sent to the client."""
        out: dict[str, object] = {"error": self.code, "message": self.message}
        if self.retry_after is not None:
            out["retry_after_seconds"] = self.retry_after
        return out

    def headers(self) -> dict[str, str]:
        """Extra response headers (``Retry-After`` when a delay is known)."""
        if self.retry_after is None:
            return {}
        return {"Retry-After": str(max(1, math.ceil(self.retry_after)))}


def not_found(message: str) -> ApiError:
    """A ``not_found`` 404 for an unknown job, backup or endpoint."""
    return ApiError(message, code="not_found")


def from_job_error(exc: JobError) -> ApiError:
    """Convert a job-store refusal (an unknown job id is ``not_found``)."""
    return ApiError(exc.message, code=exc.code)


def from_ctl_error(exc: CtlError) -> ApiError:
    """Convert a daemon refusal; codes the contract lacks become ``op_failed``."""
    code = exc.code if exc.code in STATUS_BY_CODE else "op_failed"
    retry = exc.data.get("retry_after_seconds") if exc.data else None
    return ApiError(
        exc.message or exc.code,
        code=code,
        retry_after=float(retry) if isinstance(retry, int | float) else None,
    )


def daemon_unreachable(detail: str) -> ApiError:
    """The 503 for a daemon that did not answer on its socket."""
    msg = f"The enforcer daemon is not answering on its control socket ({detail})."
    return ApiError(msg, code="daemon_unreachable")
