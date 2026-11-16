"""Why the budget state file did or did not open, for the budget view.

Split from :mod:`_budget_view` (250-line cap); that module re-exports every name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

READABLE: Final = "ok"
MISSING: Final = "missing"
DENIED: Final = "denied"
CORRUPT: Final = "corrupt"

STATUS_MESSAGES: Final[dict[str, str]] = {
    DENIED: (
        "Cannot read the budget state file. It is owned by root, and only "
        "becomes world-readable once the enforcer has rewritten it — restart "
        "steam-backlog-enforcer.service."
    ),
    MISSING: "No gaming time has been recorded yet today.",
    CORRUPT: (
        "The budget state file could not be parsed. The enforcer treats that "
        "as tampering and will start the day fail-closed."
    ),
}


def state_access(path: Path) -> str:
    """Classify why the state file did or did not open.

    ``load_state`` deliberately collapses "missing", "corrupt" and "unreadable"
    into ``None`` — its caller is the enforcer, whose recovery is the same for
    all three. A display needs to tell them apart, because "you have not gamed
    today" and "I am not allowed to look" are opposite messages.

    The read is attempted rather than pre-checked with ``os.access``: the
    kernel's answer to the actual open is the only one that cannot disagree
    with what ``load_state`` just experienced. The file is a couple of hundred
    bytes, so reading it twice costs nothing.

    Args:
        path: The state file.

    Returns:
        ``READABLE``, ``MISSING`` or ``DENIED``.
    """
    try:
        path.read_bytes()
    except FileNotFoundError:
        return MISSING
    except OSError:
        return DENIED
    return READABLE
