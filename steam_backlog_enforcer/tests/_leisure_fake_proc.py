"""A tiny fake ``/proc`` for the leisure kill tests: one directory per pid."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Fields after ``comm``: state, ppid, then 17 more, then starttime (index 19).
_FILLER_BEFORE_START = 17
_FILLER_AFTER_START = 5


@dataclass(frozen=True)
class FakeProc:
    """What one fake ``/proc/<pid>`` holds."""

    pid: int
    exe: str = "/usr/bin/mpv"
    argv: tuple[str, ...] = ("mpv",)
    comm: str = "mpv"
    uid: int = 1000
    ppid: int = 1
    start: int = 100


def add_proc(root: Path, spec: FakeProc) -> None:
    """Create ``root/<pid>`` with exe, cmdline, comm, status and stat.

    Args:
        root: The fake ``/proc``.
        spec: The process to plant (a dangling ``exe`` target is fine).
    """
    proc = root / str(spec.pid)
    proc.mkdir(parents=True)
    (proc / "exe").symlink_to(spec.exe)
    (proc / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in spec.argv))
    (proc / "comm").write_text(spec.comm + "\n", encoding="utf-8")
    uid = spec.uid
    (proc / "status").write_text(
        f"Name:\t{spec.comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8"
    )
    rest = ["S", str(spec.ppid), *["0"] * _FILLER_BEFORE_START, str(spec.start)]
    rest += ["0"] * _FILLER_AFTER_START
    line = f"{spec.pid} ({spec.comm}) {' '.join(rest)}\n"
    (proc / "stat").write_text(line, encoding="utf-8")
