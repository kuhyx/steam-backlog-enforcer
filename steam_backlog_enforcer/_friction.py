"""Typed-phrase friction shared by the CLI, the web job runner and the daemon.

One table, so a phrase cannot be strict in one front end and lax in another.
The phrase is checked wherever the action is actually carried out (the job
subprocess or the root daemon), never only in the browser: a check that
``curl`` can skip is decoration, not friction.

Templates use ``str.format`` fields; the caller supplies every field the
template names (``days``, ``minutes``, ``game_name``, ``count``, ``backup_id``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Friction:
    """The friction attached to one command.

    Attributes:
        phrase_template: Text the user must type, with ``{field}`` slots.
        countdown_seconds: Armed wait with heartbeats before commit (0 = none).
    """

    phrase_template: str
    countdown_seconds: int = 0


GAMING_RESET_COUNTDOWN_SECONDS: Final = 300

FRICTION: Final[dict[str, Friction]] = {
    "gaming-reset": Friction(
        "reset today's gaming budget", GAMING_RESET_COUNTDOWN_SECONDS
    ),
    "block-gaming": Friction("block all gaming for {days} days"),
    "unblock": Friction("unblock the store for {minutes} minutes"),
    "buy-dlc": Friction("unblock the store for {minutes} minutes"),
    "gaming-unblock": Friction("force release playtime mounts"),
    "abandon-pick": Friction("abandon {game_name}"),
    "pick-manual": Friction("lock in {game_name}"),
    "add-exception": Friction("request exception for {game_name}"),
    "uninstall": Friction("uninstall {count} games"),
    "reset": Friction("wipe all enforcer state"),
    "restore-backup": Friction("restore backup {backup_id}"),
}


def expected_phrase(command: str, **fields: object) -> str | None:
    """Return the exact phrase *command* requires, or ``None`` if it has none.

    Raises:
        KeyError: If the template names a field missing from *fields*.
    """
    friction = FRICTION.get(command)
    if friction is None:
        return None
    return friction.phrase_template.format(**fields)


def phrase_matches(expected: str, typed: str) -> bool:
    """Compare a typed phrase to the expected one.

    Only surrounding whitespace is forgiven. Case and inner spacing must
    match: retyping the sentence exactly is the point.
    """
    return typed.strip() == expected
