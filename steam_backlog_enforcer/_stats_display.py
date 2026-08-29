"""Formatting helpers for the ``stats`` command's printed report.

Split out of :mod:`steam_backlog_enforcer._stats` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``_stats``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from steam_backlog_enforcer._hltb_types import (
    HLTB_BASE_URL,
    load_hltb_game_id_cache,
)
from steam_backlog_enforcer._stats_types import _HLTB_SEARCH_BASE, _GameTimes
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.hltb import fetch_hltb_detail_missing

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import State


def _print_worst_example(entries: list[_GameTimes]) -> None:
    """Print a randomly selected example from the worst-case qualified games."""
    examples = [e for e in entries if e.worst_hours > 0]
    if not examples:
        return
    example = secrets.choice(examples)
    _echo(f"\n  Example game: {example.game.name!r}")
    _echo(f"    Worst case: {example.worst_hours:.1f} h")
    if example.rush_hours > 0:
        _echo(f"    Rush:       {example.rush_hours:.1f} h")
    if example.leisure_100h > 0:
        _echo(f"    Leisure:    {example.leisure_100h:.1f} h")
    hltb_game_id = example.hltb_game_id
    if hltb_game_id == 0:
        # On-demand backfill: one search to get the HLTB game ID for this game.
        fetch_hltb_detail_missing([(example.game.app_id, example.game.name)])
        hltb_game_id = load_hltb_game_id_cache().get(example.game.app_id, 0)
    if hltb_game_id > 0:
        _echo(f"    HLTB:       {HLTB_BASE_URL}/game/{hltb_game_id}")
    else:
        _echo(f"    HLTB:       {_HLTB_SEARCH_BASE}{quote_plus(example.game.name)}")


def _sum_hours(entries: list[_GameTimes], attr: str) -> tuple[float, int]:
    """Sum a time attribute across entries; return (total_hours, missing_count).

    Games where the attribute is ≤ 0 contribute 0 to the sum and are counted
    in ``missing_count`` so the user knows the estimate may be an undercount.
    """
    total = 0.0
    missing = 0
    for e in entries:
        val: float = getattr(e, attr)
        if val > 0:
            total += val
        else:
            missing += 1
    return round(total, 1), missing


def _format_completion_date(hours: float, daily_hours: float) -> str:
    """Return 'N days (YYYY-MM-DD)' for finishing hours at daily_hours per day."""
    if hours <= 0 or daily_hours <= 0:
        return "N/A"
    days = int(hours / daily_hours)
    target = datetime.now(UTC) + timedelta(days=days)
    return f"{days} days ({target.strftime('%Y-%m-%d')})"


def _print_pace_scenario(state: State, remaining: int, games_done: int) -> None:
    """Print the pace-based completion estimate.

    ``games_done`` must be the count of games completed ON OR AFTER
    ``state.enforcement_started_at`` (use ``count_complete_since_start``).
    Pre-enforcement completions inflate the rate and are excluded.
    """
    _echo("\n  1. AT YOUR CURRENT PACE")
    if not state.enforcement_started_at:
        _echo("    No start date recorded.")
        _echo("    Set enforcement_started_at in state.json (ISO-8601 UTC)")
        _echo("    to enable this estimate.")
        return

    try:
        started = datetime.fromisoformat(state.enforcement_started_at)
    except ValueError:
        _echo(f"    Invalid enforcement_started_at: {state.enforcement_started_at!r}")
        return

    now = datetime.now(UTC)
    days_elapsed = max(1, (now - started).days)

    if games_done == 0:
        _echo(f"    Started: {started.strftime('%Y-%m-%d')}")
        _echo("    No games finished yet — pace cannot be estimated.")
        return

    rate = games_done / days_elapsed
    _echo(f"    Started:        {started.strftime('%Y-%m-%d')}")
    _echo(
        f"    Finished:       {games_done} games in {days_elapsed} days "
        "(since enforcement start)"
    )
    _echo(
        f"    Pace:           {rate:.4f} games/day  (1 game every {1 / rate:.1f} days)"
    )
    _echo(f"    Remaining:      {remaining} games")

    days_to_go = int(remaining / rate)
    finish = now + timedelta(days=days_to_go)
    _echo(f"    Est. complete:  {days_to_go} days ({finish.strftime('%Y-%m-%d')})")
