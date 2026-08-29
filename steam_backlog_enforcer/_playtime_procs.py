"""Identifying gaming processes by their /proc cmdline.

Process-name matching alone misses launchers run through an interpreter
(``lutris`` is a Python script; several Minecraft launchers are ``java -jar``),
so this reads argv and looks past the interpreter to the real program.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from steam_backlog_enforcer._counted_procs import key_by_name, load_counted_processes
from steam_backlog_enforcer._playtime_kill import (
    _INIT_PID,
    _MAX_PROCESS_TREE_DEPTH,
    _read_ppid,
)
from steam_backlog_enforcer._total_block_launchers import LAUNCHER_PROCESS_NAMES
from steam_backlog_enforcer.enforcer import (
    get_pids_by_process_names,
    get_running_steam_game_pids,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules

_PROC = Path("/proc")

# argv[0] basenames that tell us nothing: the real program is argv[1].
_INTERPRETERS = frozenset({"bash", "env", "java", "perl", "python", "python3", "sh"})

# An interpreter invocation needs at least `<interp> <script>` to name a program.
_MIN_ARGV_FOR_INTERPRETER = 2


def get_pids_by_cmdline_names(names: frozenset[str]) -> dict[int, str]:
    """Scan ``/proc/*/cmdline`` for processes whose program name is in *names*.

    Complements ``enforcer.get_pids_by_process_names``, which matches on
    ``comm`` and therefore cannot see interpreter-launched programs: the kernel
    records ``/usr/bin/lutris`` as ``python3``. When ``argv[0]``'s basename is a
    known interpreter this falls through to ``argv[1]``.

    The daemon itself runs under ``python3``, so its own PID is skipped.

    Args:
        names: Program basenames to match.

    Returns:
        Mapping of PID to the matched name.
    """
    own_pid = os.getpid()
    found: dict[int, str] = {}

    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == own_pid:
            continue
        matched = _match_cmdline(entry, names)
        if matched is not None:
            found[pid] = matched

    return found


def _match_cmdline(entry: Path, names: frozenset[str]) -> str | None:
    """Return the name in *names* that *entry*'s cmdline runs, if any.

    Args:
        entry: A ``/proc/<pid>`` directory.
        names: Program basenames to match.

    Returns:
        The matched name, or ``None``.
    """
    try:
        raw = (entry / "cmdline").read_bytes()
    except OSError, ValueError:
        return None

    argv = [
        part for part in raw.decode("utf-8", errors="replace").split("\x00") if part
    ]
    if not argv:
        return None

    first = Path(argv[0]).name
    if first in names:
        return first
    if first not in _INTERPRETERS or len(argv) < _MIN_ARGV_FOR_INTERPRETER:
        return None
    second = Path(argv[1]).name
    return second if second in names else None


def process_name(pid: int) -> str | None:
    """Return *pid*'s program name, or ``None`` if it is no longer running.

    Existence is the point as much as the name: callers resolve PIDs recorded
    earlier, and a PID that has since been recycled would otherwise be reported
    under whatever process now holds the number.

    Args:
        pid: Process id to look up.

    Returns:
        The contents of ``/proc/<pid>/comm``, or ``None``.
    """
    try:
        return (_PROC / str(pid) / "comm").read_text(encoding="utf-8").strip() or None
    except OSError, ValueError:
        return None


def _merge_named(found: dict[int, str], keys: dict[str, str]) -> None:
    """Add name-matched PIDs to *found* without displacing existing keys.

    ``setdefault`` is the point: a Steam game already attributed by its
    ``SteamAppId`` must keep that key even if its ``comm`` also happens to match
    a launcher name.

    A scanner can only return names it was asked for, so an unmapped name is
    unreachable in production — it is skipped rather than raising, because the
    alternative is a ``KeyError`` inside the enforce loop.

    Args:
        found: Accumulating PID-to-key mapping, mutated in place.
        keys: Program basename to attribution key.
    """
    names = frozenset(keys)
    for source in (get_pids_by_process_names(names), get_pids_by_cmdline_names(names)):
        for pid, name in source.items():
            key = keys.get(name)
            if key is not None:
                found.setdefault(pid, key)


def qualifying_pids(rules: PlaytimeRules) -> dict[int, str]:
    """Return PIDs whose runtime counts against the daily budget, with owners.

    Steam games are identified by the ``SteamAppId`` environment variable, using
    the same ``!= 0`` predicate ``enforcer.enforce_allowed_game`` uses to exclude
    the Steam client tree — browsing the store is not gaming.

    The value is an attribution key (``app:<id>``, ``launcher:<name>`` or
    ``proc:<id>``) so that the budget can record *which* game it billed. The
    app id was previously destructured and dropped on the first line here, one
    step before accumulation.

    ``counted_processes`` is deliberately *not* gated on ``count_launchers``:
    that switch covers the sixteen hardcoded launchers, and turning it off must
    not silently stop billing a game the user explicitly listed.

    Args:
        rules: Policy for this tick.

    Returns:
        Mapping of qualifying PID to its attribution key.
    """
    found: dict[int, str] = {
        pid: f"app:{app_id}"
        for pid, app_id in get_running_steam_game_pids().items()
        if app_id != 0
    }
    if rules.count_launchers:
        _merge_named(
            found, {name: f"launcher:{name}" for name in LAUNCHER_PROCESS_NAMES}
        )

    counted = key_by_name(load_counted_processes())
    if counted:
        _merge_named(found, counted)
    return found


def attributed_key(qualifying: dict[int, str], focus_pid: int | None) -> str:
    """Return the single attribution key this tick should be credited to.

    The focused window decides it, walking ancestry the same way
    ``_engagement_probes.focus_qualifies`` does — a Proton game's window belongs
    to a child of the process carrying ``SteamAppId``.

    Falling back to "the only game running" keeps attribution working when the
    focus probe is unavailable (no X, or a toolkit that omits ``_NET_WM_PID``).
    With two games running and no focus signal there is no honest answer, so it
    returns ``""``: the tick still bills, and the gap shows up as Unattributed
    rather than being charged to a guess.

    Args:
        qualifying: Mapping of qualifying PID to attribution key.
        focus_pid: PID owning the focused window, or ``None``.

    Returns:
        The attribution key, or ``""`` if none can be determined.
    """
    if focus_pid is not None:
        pid = focus_pid
        for _ in range(_MAX_PROCESS_TREE_DEPTH):
            key = qualifying.get(pid)
            if key is not None:
                return key
            if pid <= _INIT_PID:
                break
            parent = _read_ppid(pid)
            if parent is None:
                break
            pid = parent

    distinct = set(qualifying.values())
    return distinct.pop() if len(distinct) == 1 else ""
