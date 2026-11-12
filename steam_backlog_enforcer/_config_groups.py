"""Field groups of :class:`~config.Config` and :class:`~config.State`.

Each group is stored flat in its record's JSON file (see ``_flat_record``):
the keys below are the exact keys of ``config.json`` / ``state.json``.
A leaf module, so ``config`` can import it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EarnSources:
    """Where each earned-time bonus is read from (``config.json``)."""

    book_ledger_path: str = "~/.local/share/book_guard/ledger.json"
    """book-guard's signed ledger: the reading hour's only transport."""
    workout_status_url: str = "http://127.0.0.1:8770/api/status"
    """Where to ask whether today has a counted workout. Loopback only."""
    workout_log_path: str = "~/src/screen-locker/screen_locker/log.json"
    """screen-locker's log.json; a change re-asks that URL at once."""
    leetcode_ledger_path: str = "~/.local/share/leetcode_guard/ledger.json"
    leetcode_status_url: str = "http://127.0.0.1:8771/api/status"
    """LeetCode's transports: ledger first, this loopback URL as fallback."""


@dataclass
class PlaytimePolicy:
    """What counts against the daily gaming budget (``config.json``)."""

    count_launcher_processes: bool = True
    """Whether time spent in non-Steam launchers counts against the budget.

    Set False if a launcher legitimately idles in the tray all day. Leaving it
    True is the safer default: under-counting is the failure mode that quietly
    defeats the budget entirely.
    """
    counted_processes: list[dict[str, Any]] | None = None
    """Non-Steam games that count against the budget, beyond the launcher set.

    Each entry is ``{"id": ..., "label": ..., "names": [...]}``. ``None`` means
    "use the built-in defaults" (osu!lazer); an explicit ``[]`` means "none",
    which is why this is not simply an empty list. Parsed and validated by
    ``leisure_watch.procscan`` (once ``_counted_procs``) — the field exists
    here only so that ``save()`` round-trips a hand-edited list instead of
    dropping it.

    Deliberately separate from ``LAUNCHER_PROCESS_NAMES``: that frozenset is
    also the total-block kill list, so adding a game there has side effects
    this list does not.
    """
    playtime_enforcement: bool = True
    """Master switch for the daily gaming budget.

    Disabling stops the cutoff but never strands a live block — the release
    path runs regardless, so "disabled" cannot come to mean "blocked forever".
    """


@dataclass
class LegacyManualPick:
    """Legacy single-slot manual pick, migrated into ``manual_picks`` on load.

    Stored as ``manual_pick_app_id`` / ``_game_name`` / ``_started_at`` so an
    older ``state.json`` still deserialises; blanked once migrated.
    """

    app_id: int | None = None
    game_name: str = ""
    started_at: str = ""


@dataclass
class AssignmentTimes:
    """When games were assigned and released (``state.json``)."""

    current_assigned_at: str = ""
    """ISO time the current game was assigned; unlocks after it release it."""
    last_assigned_at: dict[str, str] = field(default_factory=dict)
    """``str(app_id)`` → ISO time of its latest assignment (pick ordering)."""
    released_at: dict[str, str] = field(default_factory=dict)
    """``str(app_id)`` → ISO time it was released below 100% (tampering)."""
