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

from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._budget_games import (
    billing_label,
    history_view,
    today_games,
)
from steam_backlog_enforcer._budget_log_tail import last_verdict
from steam_backlog_enforcer._playtime_block import mounted_targets
from steam_backlog_enforcer._playtime_history import load_history
from steam_backlog_enforcer._playtime_state import (
    load_state,
    rules_for,
    state_path,
)
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState

READABLE: Final = "ok"
MISSING: Final = "missing"
DENIED: Final = "denied"
CORRUPT: Final = "corrupt"

_STATUS_MESSAGES: Final[dict[str, str]] = {
    DENIED: (
        "Cannot read the budget state file. It is owned by root, and only "
        "becomes world-readable once the enforcer has rewritten it — restart "
        "steam-backlog-enforcer.service."
    ),
    MISSING: "No gaming time has been recorded yet today.",
    CORRUPT: (
        "The budget state file could not be parsed. The enforcer treats that "
        "as tampering and will start the day fail-closed."
    ),
}

_HISTORY_DAYS: Final = 14


def state_access(path: Path) -> str:
    """Classify why the state file did or did not open.

    ``load_state`` deliberately collapses "missing", "corrupt" and "unreadable"
    into ``None`` — its caller is the enforcer, whose recovery is the same for
    all three. A display needs to tell them apart, because "you have not gamed
    today" and "I am not allowed to look" are opposite messages.

    The read is attempted rather than pre-checked with ``os.access``: the
    kernel's answer to the actual open is the only one that cannot disagree
    with what ``load_state`` just experienced. The file is a couple of hundred
    bytes, so reading it twice costs nothing.

    Args:
        path: The state file.

    Returns:
        ``READABLE``, ``MISSING`` or ``DENIED``.
    """
    try:
        path.read_bytes()
    except FileNotFoundError:
        return MISSING
    except OSError:
        return DENIED
    return READABLE


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
    return {
        "gaming_day": state.day_key,
        "day_starts_at": "06:00 local",
        "seconds_used": round(state.seconds, 1),
        "budget_seconds": rules.budget_seconds,
        "seconds_remaining": round(remaining, 1),
        "fraction_used": round(min(1.0, max(0.0, fraction)), 4),
        "blocked": state.is_blocked(),
        "blocked_at": state.blocked_at,
        "next_warning_seconds": next_warning(state, rules),
        "warned_seconds": list(state.warned_seconds),
        "games": today_games(state),
    }


def build_rules(rules: PlaytimeRules) -> dict[str, Any]:
    """Compose the rules block.

    An explicit allowlist, never ``Config.__dict__``: that carries
    ``steam_api_key``, and this payload is served over HTTP.

    Args:
        rules: Policy in force.

    Returns:
        Serialisable rules block.
    """
    return {
        "budget_seconds": rules.budget_seconds,
        "enforcement": rules.enforcement,
        "counts_launchers": rules.count_launchers,
        "engagement_gate": rules.engagement_gate,
        "idle_grace_seconds": rules.idle_grace_seconds,
        "require_game_focus": rules.require_game_focus,
        "warn_at": list(rules.warn_at),
        "demo": rules.demo,
        "masked_launchers": sorted(str(path) for path in mounted_targets()),
        # Read off the rules, never re-resolved: resolving a second time here
        # is what would let this view report a budget the daemon is not
        # enforcing. See _budget_resolve's "one seam".
        "budget_reason": rules.budget_reason,
        "bonuses": {
            "base": rules.base_seconds,
            "workout": rules.workout_seconds,
            "leetcode": rules.leetcode_seconds,
        },
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
        "error": _STATUS_MESSAGES.get(status),
        "today": build_today(stored, rules) if stored is not None else None,
        "session": {
            # What the budget is actually charging — a different question from
            # the backlog assignment reported as "game_name" below.
            "billing_label": billing_label(stored.last_credited_key if stored else ""),
            "available": session.available,
            "observed_at": session.observed_at,
            "state": session.state,
            "reason": session.reason,
            "causes": session.causes,
            "idle_seconds": session.idle_seconds,
            "screen_held": session.screen_held,
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
