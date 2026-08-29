"""A durable per-day record of how much gaming time was actually spent.

``PlaytimeState`` only ever describes *today*: ``roll_over`` resets the counter
at the 06:00 boundary and the previous day is gone. The audit log in
``_playtime_log`` does retain per-day figures, but it is a rotating handler —
five 5 MB files — so a busy fortnight can push a day out of the window entirely.
Neither is a series you can plot.

So this module keeps one small file whose only job is the history: a
``day_key -> seconds`` mapping, trimmed to the last month, written world-readable
so an unprivileged reader (the web UI) can plot it.

Writes are throttled rather than tied to roll-over. Upserting today's figure on a
cadence means the outgoing day is already recorded to within ``_FLUSH_DELTA``
seconds of its final value by the time the boundary arrives, which avoids
threading a "previous state" argument through the tick's hot path just to catch
one transition a day.

Like ``BudgetLog``, nothing here may raise: losing a history point is a cosmetic
failure and must never take down the enforcer.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._playtime_state import STATE_MODE
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeState

logger = logging.getLogger(__name__)

HISTORY_FILE: Final = CONFIG_DIR / "playtime_history.json"

_SCHEMA_VERSION: Final = 1

# Days retained. Comfortably more than the fortnight the UI plots, so a chart
# that later grows a longer window has data waiting for it.
_MAX_DAYS: Final = 30

# Rewrite only once the stored figure is this far behind. At a three-second tick
# an unthrottled upsert would rewrite the file 1200 times an hour to move a bar
# by a pixel.
_FLUSH_DELTA: Final = 60.0


@dataclass(frozen=True)
class HistoryDay:
    """One gaming day's total, as plotted."""

    day: str
    """Gaming day, ``YYYY-MM-DD``, 06:00-shifted."""
    seconds: float
    """Qualifying seconds billed during ``day``."""


def _read_days() -> dict[str, float]:
    """Return the stored ``day -> seconds`` mapping, or empty if unusable.

    Unlike the state file this one is neither root-owned nor immutable, and it
    lives in a user-owned directory — so an unprivileged process can replace it
    with anything at all, and the web server parses whatever it finds. Every
    field is therefore checked rather than trusted.

    Returns:
        The mapping, or ``{}`` when the file is missing, unreadable, corrupt or
        of an unknown schema.
    """
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning(
            "Playtime history at %s is unreadable; starting over.", HISTORY_FILE
        )
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != _SCHEMA_VERSION:
        logger.warning("Playtime history at %s has an unknown schema.", HISTORY_FILE)
        return {}
    days = raw.get("days")
    if not isinstance(days, dict):
        return {}
    return {
        key: float(value)
        for key, value in days.items()
        if isinstance(key, str) and isinstance(value, (int, float))
    }


def load_history(limit: int = 14) -> list[HistoryDay]:
    """Return the most recent *limit* days, oldest first.

    Args:
        limit: How many days to return.

    Returns:
        Recorded days in ascending date order, at most *limit* of them.
    """
    days = _read_days()
    ordered = sorted(days.items())[-limit:] if limit > 0 else []
    return [HistoryDay(day=day, seconds=seconds) for day, seconds in ordered]


def record_day(day_key: str, seconds: float) -> None:
    """Upsert one day's total and trim the file to ``_MAX_DAYS``.

    Args:
        day_key: Gaming day to record.
        seconds: Total billed for that day so far.
    """
    days = _read_days()
    days[day_key] = seconds
    trimmed = dict(sorted(days.items())[-_MAX_DAYS:])
    _atomic_write(
        HISTORY_FILE,
        json.dumps({"schema_version": _SCHEMA_VERSION, "days": trimmed}, indent=2)
        + "\n",
        mode=STATE_MODE,
    )


class HistoryWriter:
    """Throttled writer for the per-day history, held across ticks.

    Mirrors how ``TickJournal`` carries its heartbeat state on the session
    rather than in a module global, which is what keeps the throttle testable
    without reaching into module internals between cases.
    """

    def __init__(self) -> None:
        self._last_written: dict[str, float] = {}

    def observe(self, state: PlaytimeState, *, demo: bool) -> None:
        """Record *state*'s day if it is new or has moved far enough.

        Demo runs are skipped for the same reason they get their own state file
        and their own audit log: a 60-second demo must not leave a record
        describing a budget nobody was ever charged.

        Args:
            state: Current accounting state.
            demo: Whether this is a demo run.
        """
        if demo or not state.day_key:
            return
        previous = self._last_written.get(state.day_key)
        if previous is not None and abs(state.seconds - previous) < _FLUSH_DELTA:
            return
        try:
            record_day(state.day_key, state.seconds)
        except OSError as exc:
            # A history point is cosmetic; the enforcer keeps enforcing.
            logger.warning("Could not record playtime history: %s", exc)
            return
        self._last_written = {state.day_key: state.seconds}
