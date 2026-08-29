"""Finding and stopping the processes a playtime cutoff must end.

Killing Steam's own PIDs is not enough: a running game is a *descendant* of
the client, so the tree is walked from the launcher roots downwards. The
enforcer's own process chain is excluded, since it is itself a child of the
same session on a desktop install.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
import shutil
import signal

from steam_backlog_enforcer._counted_procs import kill_target_names
from steam_backlog_enforcer._playtime_run import _run
from steam_backlog_enforcer._total_block_launchers import (
    LAUNCHER_PROCESS_NAMES,
    STEAM_CLIENT_PROCESS_NAMES,
)
from steam_backlog_enforcer.enforcer import get_pids_by_process_names

logger = logging.getLogger(__name__)

_PROC = Path("/proc")

_STAT_PPID_INDEX = 1
_MAX_PROCESS_TREE_DEPTH = 32

# Walking past pid 1 is walking off the top of the process tree.
_INIT_PID = 1


def request_steam_shutdown() -> None:
    """Ask Steam to close cleanly, without waiting for it.

    ``library_hider._shutdown_steam`` polls for up to 30 seconds, which would
    stall the 3-second enforce loop for ten ticks. The cutoff sequence gives
    Steam its grace period across ticks instead.
    """
    steam = shutil.which("steam")
    if steam is None:
        logger.info("Steam binary not on PATH; skipping clean shutdown.")
        return
    _run([steam, "-shutdown"])


def steam_and_launcher_pids() -> set[int]:
    """Return PIDs of the Steam client and every known game launcher.

    Returns:
        The launcher and client PIDs.
    """
    names = STEAM_CLIENT_PROCESS_NAMES | LAUNCHER_PROCESS_NAMES | kill_target_names()
    return set(get_pids_by_process_names(names))


def _read_ppid(pid: int) -> int | None:
    """Return the parent PID of *pid*, or ``None`` if it cannot be read.

    ``/proc/<pid>/stat`` embeds ``comm`` in parentheses and ``comm`` may contain
    spaces and parentheses, so the fields after it are found by splitting on the
    last ``") "`` rather than by whitespace position.

    Args:
        pid: Process to inspect.

    Returns:
        The parent PID, or ``None``.
    """
    try:
        raw = (_PROC / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError, ValueError:
        return None
    _, _, rest = raw.rpartition(") ")
    fields = rest.split()
    if len(fields) <= _STAT_PPID_INDEX:
        return None
    try:
        return int(fields[_STAT_PPID_INDEX])
    except ValueError:
        return None


def _child_map() -> dict[int, list[int]]:
    """Build a parent-PID to child-PIDs map from ``/proc``.

    Returns:
        Mapping of parent PID to its direct children.
    """
    children: dict[int, list[int]] = {}
    try:
        entries = list(_PROC.iterdir())
    except OSError:
        return children

    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        ppid = _read_ppid(pid)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
    return children


def descendant_pids(roots: set[int]) -> set[int]:
    """Return every process descended from *roots*.

    A Lutris-launched Wine game carries no ``SteamAppId`` and its ``comm`` is
    the game's own binary, so neither of the budget matchers can see it. Walking
    down from the launcher is the only thing that does.

    The daemon's own process and its ancestors are excluded, so a misidentified
    root cannot make the enforcer kill itself.

    Args:
        roots: Processes to walk down from.

    Returns:
        The transitive descendants, excluding *roots* themselves.
    """
    children = _child_map()
    protected = _own_process_chain()

    found: set[int] = set()
    frontier = [pid for pid in roots if pid not in protected]
    for _ in range(_MAX_PROCESS_TREE_DEPTH):
        if not frontier:
            break
        nxt: list[int] = []
        for pid in frontier:
            for child in children.get(pid, []):
                if child in found or child in protected:
                    continue
                found.add(child)
                nxt.append(child)
        frontier = nxt
    return found


def _own_process_chain() -> set[int]:
    """Return this process and its ancestors.

    Returns:
        PIDs that must never be signalled.
    """
    chain: set[int] = set()
    pid: int | None = os.getpid()
    for _ in range(_MAX_PROCESS_TREE_DEPTH):
        if pid is None or pid <= 0 or pid in chain:
            break
        chain.add(pid)
        pid = _read_ppid(pid)
    return chain


def kill_gaming_processes(pids: set[int], *, force: bool) -> list[int]:
    """Signal every process in *pids*, plus everything descended from them.

    Args:
        pids: Processes to terminate.
        force: Send ``SIGKILL`` instead of ``SIGTERM``.

    Returns:
        The PIDs actually signalled.
    """
    protected = _own_process_chain()
    targets = (pids | descendant_pids(pids)) - protected
    sig = signal.SIGKILL if force else signal.SIGTERM

    signalled: list[int] = []
    for pid in sorted(targets):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, sig)
            signalled.append(pid)
    return signalled
