"""Parsing the stored playtime-history values.

Split from :mod:`steam_backlog_enforcer._playtime_history` to keep both modules
under the 250-line cap. Everything here is pure: it turns already-deserialised
JSON into validated values and touches neither the clock nor the disk.

The history file is user-owned and neither root-owned nor immutable, so an
unprivileged process can replace it with anything at all and the web server
will parse whatever it finds. Every field is therefore checked rather than
trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HistoryDay:
    """One gaming day's total, as plotted."""

    day: str
    """Gaming day, ``YYYY-MM-DD``, 06:00-shifted."""
    seconds: float
    """Qualifying seconds billed during ``day``."""
    games: dict[str, float] = field(default_factory=dict)
    """Attribution key to seconds. Sums to at most ``seconds``; see below.

    Empty for days written under schema 1, and short of ``seconds`` whenever a
    tick could not be attributed. The shortfall is rendered rather than stored.
    """


def _parse_day(day: str, value: object) -> HistoryDay | None:
    """Build a :class:`HistoryDay` from one stored day value.

    Args:
        day: The gaming day key.
        value: Either a schema-1 bare float or a schema-2 object.

    Returns:
        The parsed day, or ``None`` if the value is not usable.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return HistoryDay(day=day, seconds=float(value))
    if not isinstance(value, dict):
        return None
    seconds = value.get("seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return HistoryDay(day=day, seconds=float(seconds), games=_parse_games(value))


def _parse_games(value: dict[str, object]) -> dict[str, float]:
    """Return the validated ``games`` mapping of a stored day.

    Args:
        value: A schema-2 day object.

    Returns:
        Attribution key to seconds, dropping anything malformed.
    """
    games = value.get("games")
    if not isinstance(games, dict):
        return {}
    return {
        key: float(seconds)
        for key, seconds in games.items()
        if isinstance(key, str)
        and isinstance(seconds, (int, float))
        and not isinstance(seconds, bool)
    }


def _parse_labels(value: object) -> dict[str, str]:
    """Return the validated ``key -> label`` mapping.

    Args:
        value: The stored ``labels`` value.

    Returns:
        The mapping, dropping anything malformed.
    """
    if not isinstance(value, dict):
        return {}
    return {
        key: label
        for key, label in value.items()
        if isinstance(key, str) and isinstance(label, str)
    }
