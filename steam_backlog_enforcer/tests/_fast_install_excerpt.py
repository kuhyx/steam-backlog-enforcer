"""The recorded installer log excerpt shared by the fast-install progress tests.

The fixture is a verbatim excerpt of a real Baldur's Gate 3 run (the per-file
lines of the big depots trimmed). It is stored with LF endings and written
back with CRLF, which is what the installer's pty actually produces.
"""

from __future__ import annotations

from pathlib import Path

MOD = "steam_backlog_enforcer._fast_install_progress"
EXCERPT = (Path(__file__).parent / "fast_install_log_excerpt.txt").read_text(
    encoding="utf-8"
)
LINES = EXCERPT.splitlines()


def upto(marker: str, *, extra: int = 0) -> str:
    """The excerpt through the line equal to *marker*, else the first it starts.

    Exact first: ``Downloading depot 228989`` is also the start of the earlier
    ``Downloading depot 228989 manifest``.
    """
    exact = [i for i, line in enumerate(LINES) if line == marker]
    index = (exact or [i for i, ln in enumerate(LINES) if ln.startswith(marker)])[0]
    return "".join(f"{line}\r\n" for line in LINES[: index + 1 + extra])
