"""How each job command behaves: lock, cancel and privilege flags.

Pure data, deliberately free of command imports. The web server imports
this (through the job store and the catalog) from inside
``steam_backlog_enforcer.main`` → ``misc`` → ``_web_server``; importing the
command modules from here would close that loop into a circular import.
The handlers live in :mod:`._registry`, which only the job subprocess loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class JobFlags:
    """How one command runs as a job.

    Attributes:
        mutating: Takes the one-mutating-job lock.
        cancellable: SIGTERM cancels it (only where stopping midway is safe).
        privileged: Runs in the root daemon; never spawned as a job.
    """

    mutating: bool = True
    cancellable: bool = False
    privileged: bool = False


_PRIVILEGED = JobFlags(privileged=True)

JOB_FLAGS: Final[dict[str, JobFlags]] = {
    # check is mutating: a new achievement releases the game and assigns
    # the next one, exactly like done.
    "check": JobFlags(),
    "scan": JobFlags(cancellable=True),
    "done": JobFlags(),
    "pick": JobFlags(),
    "pick-manual": JobFlags(),
    "abandon-pick": JobFlags(),
    "install": JobFlags(),
    "uninstall": JobFlags(),
    "hide": JobFlags(),
    "unhide": JobFlags(),
    "add-exception": JobFlags(),
    "reset": JobFlags(),
    "restore-backup": JobFlags(),
    "stats": JobFlags(mutating=False, cancellable=True),
    "list": JobFlags(mutating=False, cancellable=True),
    # Only the demo runs as a job (see is_privileged).
    "enforce": JobFlags(cancellable=True),
    "gaming-reset": _PRIVILEGED,
    "gaming-unblock": _PRIVILEGED,
    "block-gaming": _PRIVILEGED,
    "unblock": _PRIVILEGED,
    "buy-dlc": _PRIVILEGED,
}


def is_privileged(command: str, params: Mapping[str, object]) -> bool:
    """Whether *command* with *params* must go to the root daemon.

    ``enforce`` is both: its 60-second demo runs as a job, anything else is
    the real enforcer, which only the daemon may (re)start.
    """
    if command == "enforce":
        return not params.get("demo")
    flags = JOB_FLAGS.get(command)
    return flags is not None and flags.privileged
