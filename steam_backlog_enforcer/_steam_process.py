"""Spawning processes as the desktop user, and reaping them.

Split out of :mod:`steam_backlog_enforcer._steam_launch` to keep both under
the 250-line cap. Owns the fire-and-forget process registry so it has a single
owner rather than a global shared across responsibilities.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from steam_backlog_enforcer._desktop_env import desktop_user_cmd

logger = logging.getLogger(__name__)

# Handles for fire-and-forget launches, kept only so they can be reaped.
_SPAWNED: list[subprocess.Popen[bytes]] = []


def spawn_detached(cmd: list[str]) -> subprocess.Popen[bytes]:
    """Start ``cmd`` and hand back the process, output discarded.

    Fire-and-forget on purpose: the process must outlive the calling scope
    (Steam itself, a desktop notifier), so it is polled or reaped later rather
    than waited on in a ``with`` block here.

    The unit is KillMode=control-group, so a Steam started from here used to
    stay in the service's cgroup and a daemon restart SIGTERMed it together
    with the running game (2026-07-26, 2026-10-02). A transient scope moves it
    out; ``--scope`` execs in place, so the returned handle is still the child.
    """
    if os.geteuid() == 0 and shutil.which("systemd-run"):
        cmd = ["systemd-run", "--scope", "--quiet", "--collect", *cmd]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _reap_spawned() -> None:
    """Clear out previously launched processes that have since exited.

    Launches here are fire-and-forget: Steam is meant to outlive the call, so
    it is never waited on. That leaves any launch which dies immediately - a
    missing binary, a broken wrapper - sitting as a zombie that still carries
    the name ``steam``, which anything scanning /proc reads as "Steam is
    running". Polling the old handles reaps them and retires the name.
    """
    _SPAWNED[:] = [proc for proc in _SPAWNED if proc.poll() is None]


def _run_as_user(cmd: list[str], user: str | None) -> None:
    """Run a command, dropping to *user* if currently root.

    Refuses to run at all when root and no desktop user resolves: the command
    would otherwise execute *as root* on the user's session, which is how the
    enforcer put a root Steam ("Cannot run as root user") on screen.
    Failing closed costs one skipped pass; failing open costs a modal.
    """
    _reap_spawned()
    if os.geteuid() == 0 and (not user or user == "root"):
        logger.error(
            "Refusing to run %s as root: no desktop user resolved "
            "(is STEAM_ENFORCER_DESKTOP_USER set?)",
            cmd[0] if cmd else "<empty>",
        )
        return
    full_cmd = desktop_user_cmd(cmd, user)

    _SPAWNED.append(spawn_detached(full_cmd))
