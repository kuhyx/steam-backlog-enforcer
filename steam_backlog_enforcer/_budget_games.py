"""Rolling billed time up into the per-game slices the UI plots.

Two rules live here rather than in the chart component, so that the HTTP
payload and the MCP payload cannot disagree with what is drawn:

**Unattributed is computed, never stored.** ``per_game`` only ever sums to at
most the day's total — a tick the focus probe could not pin to one game still
bills, ``backdate`` refunds scale the parts, and a fail-closed day has a full
budget with no breakdown at all. The shortfall is surfaced as its own slice
instead of being hidden or charged to a guess. Days written before per-game
attribution existed have no breakdown, so their whole bar is this slice.

**The window is capped at six games plus "Other".** Six is not arbitrary: it is
the size of the shared categorical ramp, which cannot be extended to seven
distinguishable hues under simulated colour-vision deficiency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._attribution_labels import label_for
from steam_backlog_enforcer._playtime_history import load_labels

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_history import HistoryDay
    from steam_backlog_enforcer._playtime_state import PlaytimeState

UNATTRIBUTED_KEY: Final = "unattributed"
OTHER_KEY: Final = "other"

# Matches the categorical ramp's six hues; see the module docstring.
_TOP_N: Final = 6


def _label(key: str, stored: dict[str, str]) -> str:
    """Return a display label for *key*.

    The stored map is preferred because it was written while the game was
    installed — an uninstalled game's appmanifest is gone, so a live lookup
    could not recover its name. The live lookup is the fallback for *today*,
    whose keys have not reached the history file yet.

    Args:
        key: Attribution key.
        stored: Labels persisted alongside the history.

    Returns:
        The display label.
    """
    if key == UNATTRIBUTED_KEY:
        return "Unattributed"
    if key == OTHER_KEY:
        return "Other"
    return stored.get(key) or label_for(key)


def _residual(total: float, games: dict[str, float]) -> float:
    """Return the part of *total* that no key accounts for.

    Floored at zero: proportional refunds make the parts drift by fractions of
    a second, and a negative segment would render as an inverted bar.

    Args:
        total: Seconds billed that day.
        games: Attribution key to seconds.

    Returns:
        The unattributed remainder.
    """
    return max(0.0, total - sum(games.values()))


def today_games(state: PlaytimeState) -> list[dict[str, Any]]:
    """Return every game billed today, largest first, with the remainder last.

    Uncapped on purpose: the fortnight chart has six colours to spend, but the
    "Today" list is text and can show everything.

    Args:
        state: Loaded accounting state.

    Returns:
        Serialisable slices, each with ``key``, ``label``, ``seconds`` and
        ``fraction`` of the day's billed total.
    """
    stored = load_labels()
    slices = sorted(state.per_game.items(), key=lambda item: -item[1])
    residual = _residual(state.seconds, state.per_game)
    if residual > 0:
        slices.append((UNATTRIBUTED_KEY, residual))

    total = state.seconds or 1.0
    return [
        {
            "key": key,
            "label": _label(key, stored),
            "seconds": round(seconds, 1),
            "fraction": round(seconds / total, 4),
        }
        for key, seconds in slices
        if seconds > 0
    ]


def _window_top_keys(days: list[HistoryDay]) -> list[str]:
    """Return the keys worth their own colour across the whole window.

    Ranked by total across the window rather than per day, so a game keeps the
    same colour in every bar it appears in.

    Args:
        days: The days being plotted.

    Returns:
        At most ``_TOP_N`` keys, largest total first.
    """
    totals: dict[str, float] = {}
    for day in days:
        for key, seconds in day.games.items():
            totals[key] = totals.get(key, 0.0) + seconds
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [key for key, _ in ranked[:_TOP_N]]


def _day_segments(day: HistoryDay, top: list[str]) -> dict[str, float]:
    """Fold one day's breakdown into the capped key set.

    Args:
        day: The day to fold.
        top: Keys that keep their own identity.

    Returns:
        Mapping of rendered key to seconds.
    """
    segments: dict[str, float] = {}
    for key, seconds in day.games.items():
        rendered = key if key in top else OTHER_KEY
        segments[rendered] = segments.get(rendered, 0.0) + seconds
    residual = _residual(day.seconds, day.games)
    if residual > 0:
        segments[UNATTRIBUTED_KEY] = segments.get(UNATTRIBUTED_KEY, 0.0) + residual
    return segments


def history_view(
    days: list[HistoryDay],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return the plottable days and the legend they share.

    Segment order is the legend order, identical for every day, so a stacked
    bar's bands line up across the window and each key keeps one colour.

    Args:
        days: Recorded days, oldest first.

    Returns:
        The days and the legend, in render order.
    """
    top = _window_top_keys(days)
    folded = [(day, _day_segments(day, top)) for day in days]

    def present(key: str) -> bool:
        return any(key in seg for _, seg in folded)

    # The two sentinels always trail the real games, in that order.
    order = [key for key in top if present(key)]
    order.extend(key for key in (OTHER_KEY, UNATTRIBUTED_KEY) if present(key))

    stored = load_labels()
    legend = [{"key": key, "label": _label(key, stored)} for key in order]
    plotted = [
        {
            "day": day.day,
            "seconds": round(day.seconds, 1),
            "segments": [
                {"key": key, "seconds": round(segments[key], 1)}
                for key in order
                if segments.get(key, 0.0) > 0
            ],
        }
        for day, segments in folded
    ]
    return plotted, legend


def billing_label(key: str) -> str:
    """Return the display label for the key currently being credited.

    Distinct from the backlog *assignment* the session block already reports:
    that is the game the enforcer told you to play, this is the one the budget
    is actually charging. They can legitimately differ — a counted non-Steam
    game is never the assignment.

    Args:
        key: Attribution key, or ``""`` when nothing has billed yet.

    Returns:
        The label, or ``""``.
    """
    return _label(key, load_labels()) if key else ""
