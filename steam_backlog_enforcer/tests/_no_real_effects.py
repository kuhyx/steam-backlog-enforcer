"""Autouse backstop: no test may signal a foreign process or drive Steam.

The module-level ``subprocess`` patches in ``_no_subprocess`` only cover
the call sites someone remembered to list. On 2026-10-10 a stale test let
the real ``enforce --demo`` loop run: it read the live process table, billed
the game the developer was playing and SIGTERMed it, then shut Steam down.
Nothing stopped it, because nothing guarded ``os.kill``.

This guard sits under every call site instead of beside them:

* ``os.kill`` / ``os.killpg`` reach only pytest itself and processes it
  spawned (by ppid walk over the *real* ``/proc``, plus every pid the
  ``Popen`` wrapper let through, which survives a reparent to a subreaper).
  Signal 0 is a probe and always passes; pids <= 0 never do.
* ``subprocess.Popen`` refuses any argv that names a Steam/kill tool.

A blocked call raises :class:`RealEffectError` (a ``BaseException``, so an
``except Exception`` in the code under test cannot swallow it) *and* is
recorded, and the test fails at teardown even if something caught it.
Tests that patch ``os.kill`` or a module's ``subprocess`` themselves
override this layer for their duration, as before.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath
import shlex
import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    _Args = str | bytes | os.PathLike[str] | Sequence[str | bytes | os.PathLike[str]]

# Hardcoded on purpose: the package's own _PROC constants are redirected to
# empty tmp dirs by other fixtures, which would make every child look foreign.
_REAL_PROC = Path("/proc")
# Captured at import: _no_subprocess patches ``subprocess.Popen`` on the shared
# module for every test, so the name alone would resolve to its MagicMock.
# Guarding the class itself also covers code that bound it before that.
_REAL_POPEN = subprocess.Popen
_MAX_ANCESTRY = 64
_DENIED_TOOLS = frozenset(
    {
        "steam",
        "steam.sh",
        "steam-game-installer",
        "xdg-open",
        "pkill",
        "killall",
        "kill",
    }
)


class RealEffectError(BaseException):
    """A test reached a real process signal or a real Steam command."""


def _parent_of(pid: int) -> int | None:
    """Return *pid*'s parent from the real ``/proc``, or None if unreadable."""
    try:
        raw = (_REAL_PROC / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm may contain spaces and parens; the state and ppid follow the last ")".
    fields = raw.rsplit(")", 1)[-1].split()
    return int(fields[1]) if len(fields) > 1 else None


def _is_ours(pid: int, spawned: set[int]) -> bool:
    """Tell whether *pid* is pytest itself or one of its descendants."""
    if pid <= 0:
        return False
    owners = spawned | {os.getpid()}
    current: int | None = pid
    for _ in range(_MAX_ANCESTRY):
        if current is None or current <= 1:
            return False
        if current in owners:
            return True
        current = _parent_of(current)
    return False


def _argv(args: _Args, *, via_shell: bool) -> list[str]:
    """Normalise Popen's *args* into a flat list of strings."""
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(args)
        return shlex.split(text) if via_shell else [text]
    return [os.fsdecode(arg) for arg in args]


def _drives_steam(argv: Sequence[str]) -> bool:
    """Tell whether *argv* would launch, stop or signal Steam or a game."""
    for arg in argv:
        if PurePath(arg).name in _DENIED_TOOLS:
            return True
        if arg.startswith("steam://") or arg == "-shutdown":
            return True
    return False


def _fail_if_blocked(blocked: Sequence[str]) -> None:
    """Fail the test if anything was blocked, even if the code caught it."""
    if blocked:
        pytest.fail("real side effect(s) blocked: " + "; ".join(blocked))


@pytest.fixture(autouse=True)
def _no_real_effects() -> Iterator[list[str]]:
    """Block foreign signals and Steam-driving spawns; fail the test if hit.

    Yields the list of blocked calls, so a test of the guard itself can
    inspect and clear it before teardown.
    """
    blocked: list[str] = []
    spawned: set[int] = set()
    real_kill, real_killpg = os.kill, os.killpg
    real_popen_init: Callable[..., None] = _REAL_POPEN.__init__

    def _refuse(what: str) -> RealEffectError:
        blocked.append(what)
        return RealEffectError(f"test tried a real effect: {what}")

    def guarded_kill(pid: int, sig: int) -> None:
        if sig != 0 and not _is_ours(pid, spawned):
            msg = f"os.kill(pid={pid}, sig={sig})"
            raise _refuse(msg)
        real_kill(pid, sig)

    def guarded_killpg(pgid: int, sig: int) -> None:
        if sig != 0 and not _is_ours(pgid, spawned):
            msg = f"os.killpg(pgid={pgid}, sig={sig})"
            raise _refuse(msg)
        real_killpg(pgid, sig)

    def guarded_popen_init(
        self: subprocess.Popen[Any], args: _Args, *a: object, **kw: object
    ) -> None:
        argv = _argv(args, via_shell=bool(kw.get("shell")))
        exe = kw.get("executable")
        if isinstance(exe, (str, bytes, os.PathLike)):
            argv.append(os.fsdecode(exe))
        if _drives_steam(argv):
            # Popen.__del__ reads this; without it a refused spawn warns.
            vars(self)["_child_created"] = False
            msg = f"subprocess.Popen({argv!r})"
            raise _refuse(msg)
        real_popen_init(self, args, *a, **kw)
        spawned.add(self.pid)

    def tripwire(*_args: object, **_kwargs: object) -> None:
        msg = "unpatched enforce --demo loop (playtime_tick)"
        raise _refuse(msg)

    with (
        patch.object(os, "kill", guarded_kill),
        patch.object(os, "killpg", guarded_killpg),
        patch.object(_REAL_POPEN, "__init__", guarded_popen_init),
        # The demo loop never ends on its own; a test reaching it unpatched
        # must fail at once rather than hang (test_enforce_demo patches it).
        patch("steam_backlog_enforcer._enforce_demo.playtime_tick", tripwire),
    ):
        yield blocked
    _fail_if_blocked(blocked)


# ──────────────────────────────────────────────────────────────
# Live process-table isolation
#
# Steam games are found by scanning the real /proc for SteamAppId
# (enforcer.get_running_steam_game_pids hardcodes the path). Unpatched,
# that reads the *developer's* process table: running the suite while
# playing made three restart tests fail on 2026-08-28, and let a demo
# loop bill and kill the live game on 2026-10-10. Tests that care
# patch these names themselves.
# ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_live_games() -> Iterator[None]:
    """Report no running games unless a test says otherwise."""
    with (
        patch(
            "steam_backlog_enforcer._steam_restart_guard.get_running_steam_game_pids",
            return_value={},
        ),
        patch(
            "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
            return_value={},
        ),
    ):
        yield
