"""Act on a running job: answer its prompt, or cancel it.

Both only touch files and signals the job already watches, so they work
the same whether the job was started by this server process or a previous
one.
"""

from __future__ import annotations

import os
import signal

from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    ANSWERS_NAME,
    CANCEL_NAME,
    TERMINAL_STATES,
    append_jsonl,
    read_events,
    read_jsonl,
)
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS
from steam_backlog_enforcer.jobs._view import pid_of, read_job


def _open_prompt_id(job_id: str) -> str | None:
    """The id of the prompt the job is waiting on, if it is waiting."""
    path = _store.job_dir(job_id)
    prompts = [e for e in read_events(path) if e.get("type") == "prompt"]
    if not prompts:
        return None
    answered = {a.get("prompt_id") for a in read_jsonl(path / ANSWERS_NAME)}
    latest = str(prompts[-1]["prompt_id"])
    return None if latest in answered else latest


def write_answer(job_id: str, prompt_id: str, value: str) -> None:
    """Deliver the user's answer to the prompt the job is waiting on.

    The answer is not judged here — the job re-checks it — but it must be
    for the prompt that is actually open, so a stale or replayed answer
    cannot land on a later question.

    Raises:
        JobError: ``not_found`` for an unknown job; ``invalid_params`` for a
            finished job or a ``prompt_id`` that is not the open prompt.
    """
    job = read_job(job_id)
    if job["state"] in TERMINAL_STATES:
        msg = f"Job {job_id} has already finished."
        raise JobError(msg, code="invalid_params")
    if _open_prompt_id(job_id) != prompt_id:
        msg = f"Prompt {prompt_id!r} is not waiting for an answer."
        raise JobError(msg, code="invalid_params")
    path = _store.job_dir(job_id)
    append_jsonl(path / ANSWERS_NAME, {"prompt_id": prompt_id, "value": value})


def cancel(job_id: str) -> None:
    """Ask a job to stop: any job waiting on a prompt, else cancellable ones.

    A cancellable job gets SIGTERM, to its own process only.

    Only the job's pid is signalled, never its process group: a job may
    have started Steam, and cancelling a scan must not take Steam down.

    Raises:
        JobError: ``not_cancellable`` for a command that is unsafe to stop
            midway; ``not_found`` for an unknown job; ``invalid_params`` for
            a finished one.
    """
    job = read_job(job_id)
    if job["state"] == "waiting_input":
        # Blocked on a prompt, so nothing is half-done: any command may stop
        # here. The job's own prompt loop sees the marker and cancels itself.
        (_store.job_dir(job_id) / CANCEL_NAME).touch()
        return
    flags = JOB_FLAGS.get(job["command"])
    if flags is None or not flags.cancellable:
        msg = f"{job['command']} cannot be cancelled once started."
        raise JobError(msg, code="not_cancellable")
    if job["state"] in TERMINAL_STATES:
        msg = f"Job {job_id} has already finished."
        raise JobError(msg, code="invalid_params")
    pid = pid_of(_store.job_dir(job_id))
    if pid is None:
        msg = f"Job {job_id} has no running process."
        raise JobError(msg, code="invalid_params")
    os.kill(pid, signal.SIGTERM)
