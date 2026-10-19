"""The persisted per-gaming-day record, split from ``_playtime_state``.

Split at the 250-line cap when the shadow leisure fields (contract C4) were
added. ``_playtime_state`` re-imports :class:`PlaytimeState`, so every
existing ``from _playtime_state import PlaytimeState`` keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Unchanged by per-game attribution: `load_state` keeps only keys that are
# dataclass fields, so a record written before `per_game` existed loads with
# the field's empty default. A bump would buy nothing and would route the
# live file through the fail-closed unknown-schema path.
_SCHEMA_VERSION = 1


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
    budget_seconds: float = 0.0
    """Highest budget in force during ``day_key``; ``0.0`` if unset.

    What ``held_today`` holds the day at when a live re-resolution dips.
    """
    # Shadow leisure accounting (C4): measured, never enforced. No field
    # above is ever written by the shadow path, and these never feed a cutoff.
    shadow_seconds: float = 0.0
    """Leisure seconds billed during ``day_key`` (wall clock, once per tick)."""
    shadow_budget_seconds: float = 0.0
    """Highest ``resolve(leisure=True)`` budget of ``day_key``, in seconds."""
    shadow_per_source: dict[str, float] = field(default_factory=dict)
    """Source key to shadow seconds; overlapping sources split a tick."""
    shadow_paused_seconds: float = 0.0
    """Seconds a held locker grab or i3lock paused shadow billing."""

    def is_blocked(self) -> bool:
        """Whether the cutoff has engaged for this gaming day.

        Deliberately a method rather than a field: ``save`` serialises
        ``self.__dict__``, so a derived field would be persisted and could
        drift out of step with ``blocked_at``.
        """
        return self.blocked_at > 0.0
