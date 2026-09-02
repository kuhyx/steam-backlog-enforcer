"""The daily playtime budget: its state, its rules, and its persistence.

A gaming "day" runs 06:00-05:59 local, so late-night sessions count against
the day they started in. State is written atomically and re-read every tick,
which is what lets the enforcer survive a restart mid-session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._budget_resolve import resolve_budget
from steam_backlog_enforcer._whitelist import _try_set_immutable, unlock_for_write
from steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

PLAYTIME_STATE_FILE = CONFIG_DIR / "playtime_state.json"
PLAYTIME_DEMO_STATE_FILE = CONFIG_DIR / "playtime_demo_state.json"

# Unchanged by per-game attribution: `load_state` keeps only keys that are
# dataclass fields, so a record written before `per_game` existed loads with
# the field's empty default. A bump would buy nothing and would route the
# live file through the fail-closed unknown-schema path.
_SCHEMA_VERSION = 1

# The daemon runs as root, and ``mkstemp`` would leave this at 0600 — which
# silently broke every unprivileged reader: ``load_state`` swallows the
# resulting ``PermissionError`` and reports "no state recorded yet", so both the
# MCP ``get_gaming_time`` tool and the web UI showed an empty budget while the
# file on disk held a live count. World-*readable* costs nothing here: the file
# holds no secrets, and root ownership plus the immutable flag are what stop it
# being rewritten.
STATE_MODE = 0o644

# The gaming day starts here, local time. 05:59 belongs to the previous day.
_DAY_BOUNDARY_HOURS = 6

# Each tick's measured delta is capped at this many tick intervals. Two is the
# smallest value that tolerates one skipped tick without inflating the count.
_DELTA_CLAMP_FACTOR = 2.0

_DEMO_BUDGET_SECONDS = 60.0

# Seconds remaining at which to warn, descending.
_WARN_AT: tuple[int, ...] = (3600, 1800, 600, 300)
_DEMO_WARN_AT: tuple[int, ...] = (30, 10)

# Grace between "budget exhausted" and masking the Steam binaries. Masking
# makes `steam -shutdown` a no-op, so Steam must be given a moment to close
# its games cleanly first — otherwise every single cutoff is a hard SIGTERM.
_SHUTDOWN_GRACE_SECONDS = 3.0
_SIGKILL_AFTER_SECONDS = 30.0
_DEMO_SIGKILL_AFTER_SECONDS = 10.0


@dataclass
class PlaytimeState:
    """Per-gaming-day playtime accounting, persisted between ticks."""

    schema_version: int = _SCHEMA_VERSION
    day_key: str = ""
    """Gaming day this record covers, ``YYYY-MM-DD``, 06:00-shifted."""
    seconds: float = 0.0
    """Qualifying seconds accrued during ``day_key``."""
    last_tick_at: float = 0.0
    """Epoch seconds of the last accounting tick; ``0.0`` means never ticked."""
    blocked_at: float = 0.0
    """Epoch seconds when the cutoff engaged; ``0.0`` means not blocked."""
    per_game: dict[str, float] = field(default_factory=dict)
    """Attribution key to seconds credited during ``day_key``.

    Only ever a *subset* of ``seconds``: a tick that cannot be attributed to one
    game still bills, and ``backdate`` refunds can outpace what one key holds.
    The difference is rendered as "Unattributed" rather than stored, so the
    invariant is ``sum(per_game.values()) <= seconds`` — never equality.
    """
    last_credited_key: str = ""
    """Key credited by the most recent billing tick.

    Exists so ``backdate``'s idle-grace refund can debit the same key it
    credited; without it every engaged-to-paused edge would drift the parts
    above the whole.
    """
    warned_seconds: list[int] = field(default_factory=list)
    """Warning thresholds already fired during ``day_key``."""

    def is_blocked(self) -> bool:
        """Whether the cutoff has engaged for this gaming day.

        Deliberately a method rather than a field: ``save`` serialises
        ``self.__dict__``, so a derived field would be persisted and could
        drift out of step with ``blocked_at``.
        """
        return self.blocked_at > 0.0


@dataclass(frozen=True)
class PlaytimeRules:
    """Resolved budget policy for one tick.

    Frozen and passed explicitly so that every decision function stays pure
    and testable without touching ``Config`` or the clock.
    """

    budget_seconds: float
    warn_at: tuple[int, ...]
    sigkill_after: float
    count_launchers: bool
    enforcement: bool
    demo: bool
    # What earned today's budget, carried here rather than resolved a second
    # time: _budget_view reads the breakdown off these fields, so there stays
    # exactly one resolution site.
    base_seconds: float = 0.0
    workout_seconds: float = 0.0
    leetcode_seconds: float = 0.0
    budget_reason: str = ""


def rules_for(config: Config, *, demo: bool) -> PlaytimeRules:
    """Build the policy for this tick from *config*.

    Demo mode changes the budget and the warning thresholds and nothing else —
    in particular it uses the same qualifying-process predicate as production,
    because a demo that exercises different logic proves nothing about it.

    Args:
        config: Loaded user configuration.
        demo: Whether this is a short-budget demo run.

    Returns:
        The rules governing this tick.
    """
    # Production budget is resolved, not read straight off config: it is a
    # floor plus a bonus per earner. Resolving it *here* rather than at each
    # caller is what stops the daemon (which holds one Config for its whole
    # life) and _budget_view (which reloads Config per HTTP request) from
    # reporting different budgets.
    resolved = None if demo else resolve_budget(config)
    return PlaytimeRules(
        budget_seconds=_DEMO_BUDGET_SECONDS if resolved is None else resolved.seconds,
        warn_at=_DEMO_WARN_AT if demo else _WARN_AT,
        sigkill_after=(_DEMO_SIGKILL_AFTER_SECONDS if demo else _SIGKILL_AFTER_SECONDS),
        count_launchers=config.count_launcher_processes,
        enforcement=config.playtime_enforcement,
        demo=demo,
        base_seconds=_DEMO_BUDGET_SECONDS
        if resolved is None
        else resolved.base_seconds,
        workout_seconds=0.0 if resolved is None else resolved.workout_seconds,
        leetcode_seconds=0.0 if resolved is None else resolved.leetcode_seconds,
        budget_reason=("demo run" if resolved is None else resolved.reason),
    )


def gaming_day_key(now: datetime) -> str:
    """Return the ``YYYY-MM-DD`` gaming day containing *now*.

    The boundary is 06:00 local, so 02:00 on the 5th belongs to the 4th.

    Args:
        now: Timezone-aware local timestamp.

    Returns:
        The gaming day key.
    """
    return (now - timedelta(hours=_DAY_BOUNDARY_HOURS)).date().isoformat()


def state_path(*, demo: bool) -> Path:
    """Return the state file for a demo or production run.

    Demo runs use a separate file so a demo can never consume or clobber the
    real day's counter.

    Args:
        demo: Whether this is a demo run.

    Returns:
        Path to the state file.
    """
    return PLAYTIME_DEMO_STATE_FILE if demo else PLAYTIME_STATE_FILE


def load_state(*, demo: bool) -> PlaytimeState | None:
    """Load persisted state, or ``None`` if it is absent or unusable.

    ``None`` deliberately covers "missing", "corrupt" and "written by a
    different schema" alike: the caller's recovery path is the same for all
    three, and treating an unreadable file as a fresh day is exactly the
    reset-by-deletion the immutable flag exists to prevent.

    Args:
        demo: Whether this is a demo run.

    Returns:
        The stored state, or ``None`` if it could not be read.
    """
    path = state_path(demo=demo)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        logger.warning("Playtime state at %s is unreadable; assuming tampered.", path)
        return None
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        logger.warning("Playtime state at %s has an unknown schema.", path)
        return None
    fields = PlaytimeState.__dataclass_fields__
    return PlaytimeState(**{k: v for k, v in data.items() if k in fields})


def save_state(state: PlaytimeState, *, demo: bool) -> None:
    """Persist *state*, re-applying the immutable flag for production runs.

    ``_atomic_write`` finishes with ``rename(2)``, which fails ``EPERM`` against
    an immutable destination — so clearing the flag first is mandatory, not
    decorative. Demo state is left mutable: it carries no enforcement weight and
    an immutable copy could not be deleted during cleanup, even by root.

    Args:
        state: State to write.
        demo: Whether this is a demo run.
    """
    path = state_path(demo=demo)
    if not demo:
        unlock_for_write(path)
    _atomic_write(path, json.dumps(state.__dict__, indent=2) + "\n", mode=STATE_MODE)
    if not demo:
        _try_set_immutable(path, immutable=True)
