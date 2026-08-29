"""User-declared non-Steam processes that count against the gaming budget.

Steam games announce themselves through ``SteamAppId``; everything else has to
be named. :mod:`_total_block_launchers` already names sixteen *launchers*, but
that frozenset is consumed by the total-block killer, so adding a game to it
silently makes the game killable. This module is the separate, user-editable
list: ``counted_processes`` in ``config.json``.

Loading is deliberately independent of :class:`~config.Config`. The two kill
paths that need these names — ``_playtime_kill.steam_and_launcher_pids`` and
``_total_block.enforce_total_block_tick`` — take no arguments and never build a
``Config``, so a ``Config``-only accessor could not reach them.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any

from steam_backlog_enforcer import config

logger = logging.getLogger(__name__)

# Names that must never be matched. Every name here is either an interpreter
# that hosts unrelated programs or a shell: `counted_processes` entries are
# kill targets, and `sh` in the set would SIGTERM every shell on the system.
# osu!lazer is launched through a `/bin/sh` wrapper, so this is a live hazard,
# not a hypothetical one.
FORBIDDEN_NAMES = frozenset(
    {
        "bash",
        "dash",
        "dotnet",
        "env",
        "java",
        "mono",
        "node",
        "perl",
        "python",
        "python3",
        "ruby",
        "sh",
        "wine",
        "wine64",
        "zsh",
    }
)


@dataclass(frozen=True)
class CountedProcess:
    """One user-declared non-Steam game that bills the budget."""

    id: str
    """Stable slug; forms the ``proc:<id>`` attribution key."""
    label: str
    """Display name shown in the UI and stored in history labels."""
    names: frozenset[str]
    """Process basenames to match against ``comm`` and argv."""


# osu!lazer ships as the AUR `osu-lazer-bin` package: `/usr/bin/osu-lazer` is a
# `/bin/sh` wrapper that execs `/opt/osu-lazer/osu.AppImage`, which self-mounts
# a squashfs and execs the game itself. All three layers are named so that
# whichever one the detector sees first, the time is billed.
DEFAULT_COUNTED_PROCESSES: tuple[CountedProcess, ...] = (
    CountedProcess(
        id="osu-lazer",
        label="osu!lazer",
        names=frozenset({"osu-lazer", "osu.AppImage", "osu!"}),
    ),
)


def parse_counted_processes(raw: object) -> tuple[CountedProcess, ...]:
    """Build validated entries from ``config.json``'s ``counted_processes``.

    Invalid entries are dropped with a warning rather than raising: a typo in a
    hand-edited config must not take the whole enforcer down, and the failure
    mode of dropping one entry (that game stops billing) is visible in the UI.

    Args:
        raw: The deserialised ``counted_processes`` value.

    Returns:
        The valid entries, in file order.
    """
    if not isinstance(raw, list):
        logger.warning("counted_processes is not a list; ignoring it.")
        return ()

    entries: list[CountedProcess] = []
    seen: set[str] = set()
    for item in raw:
        entry = _parse_entry(item)
        if entry is None or entry.id in seen:
            continue
        seen.add(entry.id)
        entries.append(entry)
    return tuple(entries)


def _parse_entry(item: object) -> CountedProcess | None:
    """Validate one ``counted_processes`` element.

    Args:
        item: A single deserialised entry.

    Returns:
        The entry, or ``None`` if it is unusable.
    """
    if not isinstance(item, dict):
        logger.warning("counted_processes entry is not an object; skipping.")
        return None

    entry_id = _text(item.get("id"))
    if not entry_id:
        logger.warning("counted_processes entry has no id; skipping.")
        return None

    names = _clean_names(entry_id, item.get("names"))
    if not names:
        logger.warning("counted_processes entry %r has no usable names.", entry_id)
        return None

    return CountedProcess(
        id=entry_id,
        label=_text(item.get("label")) or entry_id,
        names=names,
    )


def _clean_names(entry_id: str, raw: object) -> frozenset[str]:
    """Return the matchable names in *raw*, dropping forbidden ones.

    Args:
        entry_id: Owning entry id, for the warning message.
        raw: The deserialised ``names`` value.

    Returns:
        The usable names.
    """
    if not isinstance(raw, list):
        return frozenset()

    names: set[str] = set()
    for value in raw:
        name = _text(value)
        if not name:
            continue
        if name in FORBIDDEN_NAMES:
            logger.warning(
                "counted_processes entry %r names %r, which hosts unrelated "
                "programs and is a kill target; refusing it.",
                entry_id,
                name,
            )
            continue
        names.add(name)
    return frozenset(names)


def _text(value: object) -> str:
    """Return *value* as a stripped string, or ``""`` if it is not one.

    Args:
        value: Any deserialised JSON value.

    Returns:
        The trimmed string.
    """
    return value.strip() if isinstance(value, str) else ""


def load_counted_processes() -> tuple[CountedProcess, ...]:
    """Read ``counted_processes`` straight from ``config.json``.

    Used by the kill paths, which have no ``Config`` to consult. A missing or
    unreadable file yields the defaults, so a fresh install still bills
    osu!lazer.

    Returns:
        The configured entries, or :data:`DEFAULT_COUNTED_PROCESSES`.
    """
    try:
        data: Any = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return DEFAULT_COUNTED_PROCESSES

    if not isinstance(data, dict) or "counted_processes" not in data:
        return DEFAULT_COUNTED_PROCESSES
    return parse_counted_processes(data["counted_processes"])


def counted_process_names(entries: tuple[CountedProcess, ...]) -> frozenset[str]:
    """Return every matchable name across *entries*.

    Args:
        entries: Configured entries.

    Returns:
        The union of their names.
    """
    if not entries:
        return frozenset()
    return frozenset().union(*(entry.names for entry in entries))


def key_by_name(entries: tuple[CountedProcess, ...]) -> dict[str, str]:
    """Map each matchable name to its ``proc:<id>`` attribution key.

    Args:
        entries: Configured entries.

    Returns:
        Mapping of process name to attribution key.
    """
    return {name: f"proc:{entry.id}" for entry in entries for name in entry.names}


def labels_by_key(entries: tuple[CountedProcess, ...]) -> dict[str, str]:
    """Map each ``proc:<id>`` key to its display label.

    Args:
        entries: Configured entries.

    Returns:
        Mapping of attribution key to label.
    """
    return {f"proc:{entry.id}": entry.label for entry in entries}


def kill_target_names() -> frozenset[str]:
    """Return the counted-process names the kill paths should also target.

    The budget cutoff and the total block kill these; the
    ``kill_unauthorized_games`` path does not — it matches on ``SteamAppId``,
    which a non-Steam game never sets, so it excludes them for free.

    Returns:
        Every configured matchable name.
    """
    return counted_process_names(load_counted_processes())
