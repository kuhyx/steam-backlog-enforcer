"""The research record: strict parse, atomic root-only storage.

One JSON file in ``/var/lib/steam-backlog-enforcer`` (the unit's
``StateDirectory``: root only, 0700), not in the user-owned config directory,
so the unprivileged user can neither forge a window nor delete the used-up
marker. It holds numbers and two latches only; no free text. Anything that
does not parse exactly, or that no legitimate open could have produced, is an
error: the caller treats that as "no window" (fail closed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Final

from steam_backlog_enforcer.config import atomic_write

MAX_WINDOW_SECONDS: Final = 48 * 3600.0
RESEARCH_FILE: Final = Path("/var/lib/steam-backlog-enforcer/total_block_research.json")

_NUMBER_KEYS: Final = ("lock_started_at", "lock_until", "opened_at", "until")
_FLAG_KEYS: Final = ("closed", "store_reblocked")


class ResearchStateError(ValueError):
    """The record exists but cannot be trusted."""


@dataclass(frozen=True)
class ResearchRecord:
    """One research window, bound to the total-block lock it was spent on."""

    lock_started_at: float
    lock_until: float
    opened_at: float
    until: float
    closed: bool = False
    """Latched once the deadline passed: a clock set back cannot reopen it."""
    store_reblocked: bool = False
    """Latched once the normal store block is back after the window."""

    def is_open(self, at: float) -> bool:
        """Whether the window is open at *at* (epoch seconds)."""
        return not self.closed and self.opened_at <= at < self.until

    def to_json(self) -> str:
        """The record as the JSON text stored on disk."""
        return json.dumps(asdict(self), indent=2) + "\n"


def _number(data: dict[str, object], key: str) -> float:
    """A finite real number from *data*; booleans and strings are refused."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{key} is not a number"
        raise ResearchStateError(msg)
    try:
        number = float(value)
    except OverflowError as exc:
        msg = f"{key} is out of range"
        raise ResearchStateError(msg) from exc
    if not math.isfinite(number):
        msg = f"{key} is not finite"
        raise ResearchStateError(msg)
    return number


def _flag(data: dict[str, object], key: str) -> bool:
    """A real boolean from *data*, False when absent."""
    value = data.get(key, False)
    if not isinstance(value, bool):
        msg = f"{key} is not a boolean"
        raise ResearchStateError(msg)
    return value


def parse_record(raw: str) -> ResearchRecord:
    """Parse and validate the stored text; there is no repair.

    Raises:
        ResearchStateError: If it is not JSON, has a missing or ill-typed
            field, or breaks the policy (see :func:`_check_policy`).
    """
    try:
        data = json.loads(raw)
    except ValueError as exc:
        msg = "not JSON"
        raise ResearchStateError(msg) from exc
    if not isinstance(data, dict):
        msg = "not a JSON object"
        raise ResearchStateError(msg)
    numbers = {key: _number(data, key) for key in _NUMBER_KEYS}
    flags = {key: _flag(data, key) for key in _FLAG_KEYS}
    record = ResearchRecord(**numbers, **flags)
    _check_policy(record)
    return record


def _check_policy(record: ResearchRecord) -> None:
    """Refuse a record no legitimate open could have produced."""
    if not record.lock_started_at < record.lock_until:
        msg = "lock ends before it starts"
    elif not record.opened_at < record.until:
        msg = "window ends before it opens"
    elif record.until - record.opened_at > MAX_WINDOW_SECONDS:
        msg = "window is longer than 48 h"
    elif record.until > record.lock_until:
        msg = "window outlives its lock"
    else:
        return
    raise ResearchStateError(msg)


def read_record() -> ResearchRecord | None:
    """The stored record, or ``None`` when no window was ever opened.

    Raises:
        ResearchStateError: If the file exists but is unreadable or invalid.
    """
    try:
        raw = RESEARCH_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read {RESEARCH_FILE}: {exc}"
        raise ResearchStateError(msg) from exc
    return parse_record(raw)


def write_record(record: ResearchRecord) -> None:
    """Store *record* atomically, root only (0600, directory 0700)."""
    RESEARCH_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write(RESEARCH_FILE, record.to_json(), mode=0o600)
