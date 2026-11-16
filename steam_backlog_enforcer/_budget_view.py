"""One read-only view of the gaming budget, shared by MCP and the web API.

Both transports answer the same question — "how much have I played today, and
is the cutoff on?" — so both compose it here. The MCP tool used to build its
reply inline; a second copy in the HTTP handler would have been a second thing
to keep in step with ``PlaytimeRules``.

Everything here is a read. Changing the budget, resetting it and blocking stay
on the privileged paths, which is why the web server can serve this without
gaining a single mutating verb.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._budget_games import (
    billing_label,
    history_view,
    today_games,
)
from steam_backlog_enforcer._budget_log_tail import last_verdict
from steam_backlog_enforcer._budget_state_access import (
    CORRUPT,
    DENIED,
    MISSING,
    READABLE,
    STATUS_MESSAGES,
    state_access,
)
from steam_backlog_enforcer._ledger_earners import registry_for
from steam_backlog_enforcer._playtime_block import mounted_targets
from steam_backlog_enforcer._playtime_history import load_history
from steam_backlog_enforcer._playtime_state import (
    load_state,
    rules_for,
    state_path,
)
from steam_backlog_enforcer._shadow_view import shadow_view
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    import earned_time

    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

_HISTORY_DAYS: Final = 14

# Re-exported: the status classifier moved to _budget_state_access (250-line cap).
__all__ = [
    "CORRUPT",
    "DENIED",
    "MISSING",
    "READABLE",
    "build_budget_snapshot",
    "build_rules",
    "build_today",
    "next_warning",
    "state_access",
]


def next_warning(state: PlaytimeState, rules: PlaytimeRules) -> int | None:
    """Return the next warning threshold that has yet to be reached.

    Not ``_playtime_budget.pending_warning``: that returns a threshold already
    *crossed* and awaiting its notification, which the daemon fires within one
    tick — so an external reader sees ``None`` virtually always. This is the
    forward-looking one, the threshold the countdown is heading towards.

    Args:
        state: Current accounting state.
        rules: Policy in force.

    Returns:
        Seconds-remaining at which the next warning fires, or ``None`` when
        every threshold has been passed.
    """
    remaining = rules.budget_seconds - state.seconds
    upcoming = [
        threshold
        for threshold in rules.warn_at
        if threshold < remaining and threshold not in state.warned_seconds
    ]
    return max(upcoming) if upcoming else None


def build_today(state: PlaytimeState, rules: PlaytimeRules) -> dict[str, Any]:
    """Compose the "today" block from loaded state.

    Args:
        state: Loaded accounting state.
        rules: Policy in force.

    Returns:
        Serialisable today-block.
    """
    remaining = max(0.0, rules.budget_seconds - state.seconds)
    fraction = state.seconds / rules.budget_seconds if rules.budget_seconds else 1.0
    unlimited = not rules.gaming_enforced
    return {
        "gaming_day": state.day_key,
        "day_starts_at": "06:00 local",
        "seconds_used": round(state.seconds, 1),
        # No budget since 2026-11-16: the day is "unlimited" and carries no
        # number a reader could take for a limit. Past days keep their history.
        "unlimited": unlimited,
        "budget_seconds": None if unlimited else rules.budget_seconds,
        "seconds_remaining": None if unlimited else round(remaining, 1),
        "fraction_used": (
            None if unlimited else round(min(1.0, max(0.0, fraction)), 4)
        ),
        "blocked": False if unlimited else state.is_blocked(),
        "blocked_at": 0.0 if unlimited else state.blocked_at,
        "next_warning_seconds": None if unlimited else next_warning(state, rules),
        "warned_seconds": [] if unlimited else list(state.warned_seconds),
        "games": today_games(state),
        "shadow": shadow_view(state, unlimited=unlimited),
    }


def _most(earner: earned_time.Earner) -> int:
    """Gaming minutes a fully done day pays (earned_time >= 0.5 knows units)."""
    return int(getattr(earner, "max_gaming_minutes", earner.gaming_minutes))


def build_rules(rules: PlaytimeRules) -> dict[str, Any]:
    """Compose the rules block.

    An explicit allowlist, never ``Config.__dict__``: that carries
    ``steam_api_key``, and this payload is served over HTTP.

    Args:
        rules: Policy in force.

    Returns:
        Serialisable rules block.
    """
    unlimited = not rules.gaming_enforced
    return {
        "unlimited": unlimited,
        "budget_seconds": None if unlimited else rules.budget_seconds,
        "enforcement": rules.enforcement,
        "counts_launchers": rules.count_launchers,
        "warn_at": [] if unlimited else list(rules.warn_at),
        "demo": rules.demo,
        "masked_launchers": sorted(str(path) for path in mounted_targets()),
        # Read off the rules, never re-resolved: resolving a second time here
        # is what would let this view report a budget the daemon is not
        # enforcing. See _budget_resolve's "one seam".
        "budget_reason": rules.breakdown.reason,
        "bonuses": {
            "base": rules.breakdown.base_seconds,
            "workout": rules.breakdown.workout_seconds,
            "leetcode": rules.breakdown.leetcode_seconds,
            "reading": rules.breakdown.reading_seconds,
        },
        # The registry, in its order: what each earner adds today and what it
        # would add once done. The bar renders "+<icon><size>" for every
        # entry with nothing earned yet, so a new earner needs no bar change
        # beyond an icon -- and no consumer hard-codes a size.
        "earners": [
            {
                "name": earner.name,
                "label": earner.label,
                "earned_seconds": rules.breakdown.earned_seconds.get(earner.name, 0.0),
                # A full day pays up to the tutor's 60 credited units.
                "bonus_seconds": _most(earner) * 60,
            }
            for earner in registry_for(datetime.now().astimezone().date())
            # An earner's gaming pay is a budget term: none when unlimited.
            if not unlimited
        ],
    }


def build_budget_snapshot(*, demo: bool = False) -> dict[str, Any]:
    """Compose the whole budget view: today, live session, history, rules.

    Args:
        demo: Whether to read the demo run's state and log.

    Returns:
        The serialisable payload behind ``GET /api/budget``.
    """
    config = Config.load()
    rules = rules_for(config, demo=demo)
    stored = load_state(demo=demo)
    access = state_access(state_path(demo=demo))
    # A file that opened but did not parse is the remaining case: the enforcer
    # treats that as tampering, and the display should say so rather than
    # implying an empty day.
    status = access if access != READABLE else (READABLE if stored else CORRUPT)
    session = last_verdict(demo=demo)
    # Demo runs have no history by design — HistoryWriter skips them, for the
    # same reason they get their own state file and log. Serving the production
    # days here would plot real 8-hour days against the demo's 60-second budget
    # line, painting every one of them over-budget. `today.games` is still
    # emitted: the demo's own breakdown is real.
    history, legend = ([], []) if demo else history_view(load_history(_HISTORY_DAYS))

    return {
        "ok": True,
        "readable": status == READABLE,
        "state_status": status,
        "error": STATUS_MESSAGES.get(status),
        "today": build_today(stored, rules) if stored is not None else None,
        "session": {
            # What the budget is actually charging — a different question from
            # the backlog assignment reported as "game_name" below.
            "billing_label": billing_label(stored.last_credited_key if stored else ""),
            "available": session.available,
            "observed_at": session.observed_at,
            "state": session.state,
            # A single Proton title qualifies a dozen processes — reaper,
            # srt-bwrap, wineserver, plugplay.exe. Listing those as "games
            # running" would be nonsense, so the headline is the game the
            # enforcer actually assigned and the processes are the detail.
            "game_name": State.load().current_game_name,
            "qualifying_count": len(session.games),
            "processes": [
                {"pid": game.pid, "name": game.name} for game in session.games
            ],
        },
        # Demo runs have no history by design — HistoryWriter skips them, for
        # the same reason they get their own state file and log. Serving the
        # production days here would plot real 8-hour days against the demo's
        # 60-second budget line, painting every one of them over-budget.
        "history": history,
        "legend": legend,
        "rules": build_rules(rules),
    }
