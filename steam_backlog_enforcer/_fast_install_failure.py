"""Why a steam-game-installer run failed, in the installer's own words.

A bare exit status hid the BG3 run of 2026-10-23: 160 GB downloaded, then a
refusal to mark it installed, and the job still read "Succeeded". The console
output ends with ``Run log (send this): <path>``; that run log tags every line
with its level, so its ERROR lines are exactly the reasons the run gave up.

Both files are read from the end only: a depotdownloader run writes a line
per downloaded file, tens of megabytes of them.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final

# The reasons and the run log line are printed last; 64 KiB holds them.
_TAIL_BYTES: Final = 1 << 16
_RUN_LOG: Final = re.compile(r"^Run log(?: \(send this\))?: (/.+)$")
_ERROR: Final = re.compile(r"^\S+ \S+ ERROR\s+[\w.]+: (.*)$")


def _tail_lines(path: Path) -> list[str]:
    """The last lines of *path* (empty if unreadable), first partial one dropped."""
    try:
        with path.open("rb") as log:
            size = log.seek(0, 2)
            log.seek(max(0, size - _TAIL_BYTES))
            data = log.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > _TAIL_BYTES else lines


def _run_log_errors(console: list[str]) -> list[str]:
    """ERROR messages of the run log the console output names last."""
    for line in reversed(console):
        if match := _RUN_LOG.match(line.strip()):
            run_log = _tail_lines(Path(match.group(1)))
            return [m.group(1).strip() for ln in run_log if (m := _ERROR.match(ln))]
    return []


def failure_reason(console_log: Path, returncode: int) -> str:
    """One line saying why the run that just wrote *console_log* failed."""
    console = _tail_lines(console_log)
    errors = _run_log_errors(console)
    if errors:
        # Callers add their own full stop.
        return " ".join(errors).rstrip(".")
    # Died before the installer could log a reason (a traceback, a kill).
    last = next((ln.strip() for ln in reversed(console) if ln.strip()), "")
    return f"exit {returncode}: {last}" if last else f"exit {returncode}"
