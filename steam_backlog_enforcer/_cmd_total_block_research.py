"""``total-block-research``: lend Steam for one bounded window, Librarian only.

kuhy 2026-11-11: game-design research needs "Librarian: Tidy Up the Arcane
Library" actually played during a 6-day total block. This command opens ONE
window per lock, ending at ``--until`` (never past the lock's end). While it is
open, one rerun with a later ``--until`` extends it (again to the lock's end at
most); nothing shortens it. It only validates and records the window; the
enforcer daemon opens Steam within a pass and re-applies the full block at the
deadline (:mod:`steam_backlog_enforcer._research_tick`).

Root-only: the record sits in a root-only state directory. The lock and its
end date are untouched, so this can never shorten or end a total block.
"""

from __future__ import annotations

from datetime import datetime
import os

from steam_backlog_enforcer import _research_window as window
from steam_backlog_enforcer._echo import _echo

_USAGE = (
    "Usage: total-block-research --until <ISO time, local unless it has an offset>"
    "\n  e.g. total-block-research --until 2026-11-13T00:00"
    "\n  One window per total block, up to its end, extendable once. Librarian only."
)


def _until_argument(args: list[str]) -> str | None:
    """The value of ``--until X`` or ``--until=X``, or None for any other shape."""
    match args:
        case ["--until", value]:
            return value
        case [single] if single.startswith("--until="):
            return single.partition("=")[2]
        case _:
            return None


def cmd_total_block_research(args: list[str]) -> int:
    """Open the research window.

    Args:
        args: Arguments after the command name: ``--until <time>``.

    Returns:
        Process exit code: 0 recorded, 1 refused or not root, 2 bad usage.
    """
    raw = _until_argument(args)
    if raw is None:
        _echo(_USAGE)
        return 2
    try:
        until = window.parse_until(raw)
    except ValueError as exc:
        _echo(f"{exc}\n{_USAGE}")
        return 2
    if os.geteuid() != 0:
        _echo("total-block-research requires root (the record is root-only).")
        return 1
    try:
        record = window.open_research_window(until)
    except window.ResearchRefusedError as exc:
        _echo(f"Refused: {exc}")
        return 1
    ends = datetime.fromtimestamp(record.ends_at).astimezone()
    extended = record.extended_until is not None
    verb = "extended" if extended else "recorded"
    _echo(f"Research window {verb} until {ends:%Y-%m-%d %H:%M %Z}.")
    _echo(f"Only {window.LIBRARIAN_NAME} (AppID {window.LIBRARIAN_APP_ID}) may run.")
    _echo("The enforcer opens Steam on its next pass and re-applies the full")
    _echo("total block at the deadline (the Steam folder is kept).")
    _echo(
        "That was the one extension; it is never reopened."
        if extended
        else "It is extendable once, never reopened."
    )
    return 0
