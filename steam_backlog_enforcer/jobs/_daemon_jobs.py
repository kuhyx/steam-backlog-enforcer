"""Record privileged actions, carried out by the root daemon, as jobs.

A daemon op is one blocking socket call, not a subprocess, so it has no pid
for :mod:`._view` to watch. The job dir is therefore written only once the
call has returned, all at once: ``request.json``, the full event sequence
(``queued`` → ``running`` → ``log`` → ``result`` → final ``state``) and
``result.json``, the same files a real job leaves behind. Written earlier,
a 10-minute ``block_gaming`` would be failed by the dead-pid reconciler
half-way through and then get a second, contradictory result.

The phrase the user typed is never stored: it is not a secret, but it is
also not something history needs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Any

from steam_backlog_enforcer.config import _atomic_write
from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._events import REQUEST_NAME, RESULT_NAME, EventWriter

if TYPE_CHECKING:
    from collections.abc import Mapping

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


@dataclass(frozen=True)
class DaemonOutcome:
    """How a daemon op ended, as the job records it.

    Attributes:
        ok: Whether the op did what was asked.
        summary: One line for the job list and the ``result`` event.
        exit_code: ``0`` ok, ``1`` failed, ``2`` refused.
        data: Optional result data for the ``result`` event.
    """

    ok: bool
    summary: str
    exit_code: int
    data: Mapping[str, Any] | None = None


def record_daemon_job(
    command: str,
    params: Mapping[str, object],
    *,
    created_at: str,
    outcome: DaemonOutcome,
) -> str:
    """Write a finished job for a daemon op and return its id.

    Args:
        command: The contract command name (``unblock``, ``gaming-reset``…).
        params: The validated params the op ran with.
        created_at: ISO time the request arrived (before the daemon call).
        outcome: How the op ended.
    """
    ok, summary, data = outcome.ok, outcome.summary, outcome.data
    _store.prune(_store.MAX_JOBS - 1)
    path = _store.JOBS_DIR / _store.new_job_id()
    path.mkdir(parents=True, mode=0o700)
    request = {
        "command": command,
        "params": dict(params),
        "created_at": created_at,
        "via": "daemon",
    }
    (path / REQUEST_NAME).write_text(json.dumps(request) + "\n", encoding="utf-8")
    writer = EventWriter(path)
    state = "succeeded" if ok else "failed"
    writer.emit("state", state="queued")
    writer.emit("state", state="running")
    writer.emit("log", level="info" if ok else "error", message=summary)
    result: dict[str, Any] = {"ok": ok, "summary": summary}
    if data is not None:
        result["data"] = json.loads(json.dumps(dict(data), default=str))
    writer.emit("result", **result)
    final = result | {"state": state, "exit_code": outcome.exit_code}
    _atomic_write(path / RESULT_NAME, json.dumps(final, indent=2) + "\n")
    writer.emit("state", state=state)
    return path.name
