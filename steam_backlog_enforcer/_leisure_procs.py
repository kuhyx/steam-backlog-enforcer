"""Who a leisure kill may touch: browsers, players, lockers, the desktop user.

Read straight from ``/proc`` (the daemon is root), never from ``comm`` alone:
Firefox content processes rename it ("Isolated Web Co") and Chromium children
run as ``/proc/self/exe``, so a browser is named by its ``exe`` basename.

Nothing here signals anything; :mod:`_leisure_kill` does, after
:func:`is_protected` says no to root/system processes, the enforcer's own
chain, and every locker and its children.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from leisure_watch.facts import DESKTOP_UID

_PROC: Final = Path("/proc")

# THE browser list (Phase 2): exempt from focus/media kills because the
# extension redirects instead, and swept when the watcher cannot be trusted.
# Matched as the exe basename, or that name plus a "-"/"_" suffix
# (vivaldi-bin, firefox-bin, helium_crashpad_handler).
BROWSER_FAMILIES: Final = (
    "helium",
    "chromium",
    "chrome",
    "google-chrome",
    "brave",
    "vivaldi",
    "opera",
    "msedge",
    "microsoft-edge",
    "firefox",
    "librewolf",
    "zen",
    "thorium",
    "floorp",
    "waterfox",
    "mullvad-browser",
)
MEDIA_PLAYERS: Final = ("mpv", "vlc", "totem", "freetube")
_WSG_NAMES: Final = frozenset({"wsg_grabber", "wsg-grabber"})
# Headless `wsg-grabber scrape` never counts as leisure (Q7): never swept.
_WSG_HEADLESS: Final = "scrape"
# A process whose argv names one of these -- or any ancestor's does -- is a
# locker (or the accountant itself) and is never signalled.
LOCKER_NAMES: Final = frozenset(
    {
        "i3lock",
        "xss_lock",
        "gatelock",
        "screen_locker",
        "leetcode_guard",
        "leetcode_guard_tray",
        "book_guard",
        "diet_guard",
        "anki_guard",
        "home_guard",
        "meal_gate",
        "workout_locker",
        "steam_backlog_enforcer",
        "leisure_watch",
    }
)
_STAT_PPID: Final = 1
_STAT_START: Final = 19
_MAX_DEPTH: Final = 32


def _read(pid: int, name: str) -> str | None:
    try:
        return (_PROC / str(pid) / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def exe_name(pid: int) -> str:
    """Lower-case basename of the pid's binary (``comm`` if exe is unreadable)."""
    try:
        return (_PROC / str(pid) / "exe").readlink().name.lower()
    except OSError:
        return (_read(pid, "comm") or "").strip().lower()


def argv(pid: int) -> tuple[str, ...]:
    """The pid's command line, ``()`` if gone."""
    raw = _read(pid, "cmdline") or ""
    return tuple(arg for arg in raw.split("\0") if arg)


def real_uid(pid: int) -> int | None:
    """The real uid from ``status``, ``None`` if unreadable."""
    for line in (_read(pid, "status") or "").splitlines():
        if line.startswith("Uid:"):
            fields = line.split()
            return int(fields[1]) if fields[1:] and fields[1].isdigit() else None
    return None


def _stat_field(pid: int, index: int) -> int | None:
    # comm may hold spaces and parentheses: split after the last ") ".
    rest = (_read(pid, "stat") or "").rpartition(") ")[2].split()
    if len(rest) <= index or not rest[index].isdigit():
        return None
    return int(rest[index])


def parent(pid: int) -> int | None:
    """The parent pid, ``None`` if unreadable."""
    return _stat_field(pid, _STAT_PPID)


def start_time(pid: int) -> int | None:
    """Start time in clock ticks: with the pid, the process's identity."""
    return _stat_field(pid, _STAT_START)


def _family(name: str, families: tuple[str, ...]) -> bool:
    return any(
        name == fam or name.startswith((f"{fam}-", f"{fam}_")) for fam in families
    )


def is_browser(pid: int) -> bool:
    """Whether *pid* runs a browser binary (any process of it)."""
    return _family(exe_name(pid), BROWSER_FAMILIES)


def _arg_names(pid: int) -> set[str]:
    # "/x/leetcode_guard_tray.py" -> leetcode_guard_tray; "-m screen_locker._web"
    # -> screen_locker; "book-guard" -> book_guard.
    names = set()
    for arg in argv(pid):
        stem = Path(arg).name.lower().removesuffix(".py").partition(".")[0]
        names.add(stem.replace("-", "_"))
    return names


def _ancestry(pid: int) -> list[int]:
    chain: list[int] = []
    current: int | None = pid
    while current is not None and current > 0 and current not in chain:
        if len(chain) >= _MAX_DEPTH:
            break
        chain.append(current)
        current = parent(current)
    return chain


def own_chain() -> set[int]:
    """This daemon and its ancestors: never signalled."""
    return set(_ancestry(os.getpid()))


def is_protected(pid: int, chain: set[int]) -> bool:
    """Whether *pid* must never be signalled by a leisure kill.

    Args:
        pid: Candidate process.
        chain: :func:`own_chain`, computed once per tick.

    Returns:
        True for anything not the desktop user's (root, system, other users,
        unreadable or gone), the enforcer's own chain, and lockers with
        everything under them.
    """
    if pid in chain or real_uid(pid) != DESKTOP_UID:
        return True
    return any(_arg_names(p) & LOCKER_NAMES for p in _ancestry(pid) if p > 1)


def _wsg_reviewer(pid: int) -> bool:
    args = argv(pid)
    for i, arg in enumerate(args):
        if Path(arg).name in _WSG_NAMES:
            return args[i + 1 : i + 2] != (_WSG_HEADLESS,)
    return False


def sweep_targets() -> dict[int, str]:
    """Every browser, media player and wsg-grabber reviewer on the machine.

    The kill set while the watcher cannot be trusted (stale, missing or badly
    signed ``now.json``).

    Returns:
        Pid to a ``sweep:...`` key naming why it was picked.
    """
    try:
        pids = [int(e.name) for e in _PROC.iterdir() if e.name.isdigit()]
    except OSError:
        return {}
    found: dict[int, str] = {}
    for pid in sorted(pids):
        name = exe_name(pid)
        if _family(name, BROWSER_FAMILIES):
            found[pid] = f"sweep:browser:{name}"
        elif _family(name, MEDIA_PLAYERS):
            found[pid] = f"sweep:media:{name}"
        elif _wsg_reviewer(pid):
            found[pid] = "sweep:wsg-grabber"
    return found
