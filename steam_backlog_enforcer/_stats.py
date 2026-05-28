"""Backlog completion-time statistics for Steam Backlog Enforcer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from python_pkg.steam_backlog_enforcer._hltb_types import (
    HLTB_BASE_URL,
    load_hltb_cache,
    load_hltb_game_id_cache,
    load_hltb_leisure_100h_cache,
    load_hltb_rush_cache,
)
from python_pkg.steam_backlog_enforcer._scanning_confidence import (
    _apply_cached_confidence_to_candidates,
    _confidence_fail_reasons,
    _refresh_candidate_confidence_batch,
)
from python_pkg.steam_backlog_enforcer.config import load_snapshot
from python_pkg.steam_backlog_enforcer.game_install import _echo
from python_pkg.steam_backlog_enforcer.hltb import fetch_hltb_detail_missing
from python_pkg.steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from python_pkg.steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)

_HOURS_PER_DAY_PRESETS = (2.0, 4.0, 6.0, 8.0)

_LINE = "─" * 70

_HLTB_SEARCH_BASE = "https://howlongtobeat.com/?q="


@dataclass
class _GameTimes:
    """Per-game time estimates for stats display."""

    game: GameInfo
    worst_hours: float
    rush_hours: float
    leisure_100h: float
    hltb_game_id: int = field(default=0)


def _filter_qualifying_games(
    games: list[GameInfo],
    state: State,
) -> tuple[list[_GameTimes], int, int, int]:
    """Return qualifying incomplete games with their time estimates.

    Applies the same HLTB-confidence and Linux-compatibility filters as the
    game picker.  The current game and already-finished games are excluded.

    Returns:
        (qualified_list, hltb_skipped, linux_skipped, no_data_skipped)
    """
    rush_cache = load_hltb_rush_cache()
    leisure_100h_cache = load_hltb_leisure_100h_cache()
    game_id_cache = load_hltb_game_id_cache()
    hours_cache = load_hltb_cache()

    exclude = set(state.finished_app_ids)
    if state.current_app_id is not None:
        exclude.add(state.current_app_id)

    candidates = [g for g in games if not g.is_complete and g.app_id not in exclude]
    _apply_cached_confidence_to_candidates(candidates)
    _refresh_candidate_confidence_batch(candidates)

    hltb_skipped = 0
    linux_skipped = 0
    no_data_skipped = 0
    app_ids_to_check: list[int] = []

    conf_ok: list[GameInfo] = []
    for game in candidates:
        if _confidence_fail_reasons(game):
            hltb_skipped += 1
            continue
        conf_ok.append(game)
        app_ids_to_check.append(game.app_id)

    ratings: dict[int, ProtonDBRating] = {}
    if app_ids_to_check:
        ratings = fetch_protondb_ratings(app_ids_to_check)

    qualified: list[_GameTimes] = []
    for game in conf_ok:
        rating = ratings.get(game.app_id, ProtonDBRating(app_id=game.app_id))
        if not rating.is_playable:
            linux_skipped += 1
            continue

        rush = rush_cache.get(game.app_id, -1)
        leisure = leisure_100h_cache.get(game.app_id, -1)

        # worst_hours = max of: snapshot completionist, HLTB hours cache (fallback
        # when snapshot is stale/missing), and leisure_100h (slowest 100% time).
        snap_hours = game.completionist_hours if game.completionist_hours > 0 else -1
        cache_hours = hours_cache.get(game.app_id, -1)
        worst_candidates = [v for v in (snap_hours, cache_hours, leisure) if v > 0]
        worst = max(worst_candidates) if worst_candidates else -1

        if worst <= 0 and rush <= 0 and leisure <= 0:
            no_data_skipped += 1
            continue

        qualified.append(
            _GameTimes(
                game=game,
                worst_hours=worst,
                rush_hours=rush,
                leisure_100h=leisure,
                hltb_game_id=game_id_cache.get(game.app_id, 0),
            )
        )

    return qualified, hltb_skipped, linux_skipped, no_data_skipped


def _ensure_rush_data(qualified: list[_GameTimes]) -> bool:
    """Auto-fetch rush/leisure detail for games that are missing it.

    Returns True when a fetch was performed; the caller should then re-run
    ``_filter_qualifying_games`` to pick up the updated caches.
    """
    total_q = len(qualified)
    missing = sum(1 for e in qualified if e.rush_hours <= 0)
    if not qualified or not missing:
        return False
    _echo(f"Fetching HLTB detail for {missing}/{total_q} games missing rush/leisure...")
    game_pairs = [(e.game.app_id, e.game.name) for e in qualified]
    fetch_hltb_detail_missing(game_pairs)
    return True


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
    if example.hltb_game_id > 0:
        _echo(f"    HLTB:       {HLTB_BASE_URL}/game/{example.hltb_game_id}")
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
    target = datetime.now(timezone.utc) + timedelta(days=days)
    return f"{days} days ({target.strftime('%Y-%m-%d')})"


def _print_scenario(
    label: str,
    total_hours: float,
    missing: int,
    total_games: int,
) -> None:
    """Print a single time-scenario block."""
    _echo(f"\n  {label}")
    if total_hours <= 0:
        _echo("    No data available.")
        return

    missing_note = (
        f"  ({missing}/{total_games} games had no data, hours underestimated)"
        if missing
        else ""
    )
    _echo(f"    Total: {total_hours:,.1f} h{missing_note}")
    for daily in _HOURS_PER_DAY_PRESETS:
        estimate = _format_completion_date(total_hours, daily)
        _echo(f"    @ {daily:.0f} h/day → {estimate}")


def _print_pace_scenario(state: State, remaining: int, games_done: int) -> None:
    """Print the pace-based completion estimate.

    ``games_done`` should be the count of 100%-complete games in the library
    snapshot (``sum(1 for g in games if g.is_complete)``), not the enforcer's
    own ``finished_app_ids`` list, which misses games completed outside the
    enforcer flow.
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

    now = datetime.now(timezone.utc)
    days_elapsed = max(1, (now - started).days)

    if games_done == 0:
        _echo(f"    Started: {started.strftime('%Y-%m-%d')}")
        _echo("    No games finished yet — pace cannot be estimated.")
        return

    rate = games_done / days_elapsed
    _echo(f"    Started:        {started.strftime('%Y-%m-%d')}")
    _echo(f"    Finished:       {games_done} games in {days_elapsed} days")
    _echo(
        f"    Pace:           {rate:.4f} games/day  (1 game every {1 / rate:.1f} days)"
    )
    _echo(f"    Remaining:      {remaining} games")

    days_to_go = int(remaining / rate)
    finish = now + timedelta(days=days_to_go)
    _echo(f"    Est. complete:  {days_to_go} days ({finish.strftime('%Y-%m-%d')})")


def cmd_stats(_config: Config, state: State) -> None:
    """Display backlog completion-time statistics.

    Filters games by the same HLTB-confidence and Linux-compatibility rules
    used when picking the next game.  Auto-fetches missing rush/leisure detail
    data before printing.  Shows four scenarios:

    1. At your current pace (games finished per day since enforcement started).
    2. Rush   — avg comp_100 + DLC completion time per HLTB.
    3. Leisure — comp_100_h (slowest 100 %) + DLC leisure per HLTB.
    4. Worst   — absolute maximum recorded time (any category) per HLTB.
    """
    snapshot = load_snapshot()
    if snapshot is None:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot]
    # Count all 100%-achievement games in library (more accurate than
    # finished_app_ids, which only tracks enforcer-assigned completions).
    games_done = sum(1 for g in games if g.is_complete)

    qualified, hltb_skip, linux_skip, no_data_skip = _filter_qualifying_games(
        games, state
    )
    if _ensure_rush_data(qualified):
        # Re-filter picks up updated rush/leisure caches; ProtonDB is now cached.
        qualified, hltb_skip, linux_skip, no_data_skip = _filter_qualifying_games(
            games, state
        )
    total_q = len(qualified)

    _echo(f"\n{'═' * 70}")
    _echo("  BACKLOG COMPLETION ESTIMATES")
    _echo(f"{'═' * 70}")
    _echo(f"\n  Qualifying games:  {total_q}")
    if hltb_skip:
        _echo(f"  HLTB-skipped:      {hltb_skip} (confidence too low)")
    if linux_skip:
        _echo(f"  Linux-skipped:     {linux_skip} (poor ProtonDB rating)")
    if no_data_skip:
        _echo(f"  No-data-skipped:   {no_data_skip} (no HLTB hours at all)")

    missing_rush_final = sum(1 for e in qualified if e.rush_hours <= 0)
    if missing_rush_final:
        _echo(
            f"\n  Note: {missing_rush_final}/{total_q} games still missing"
            " rush/leisure data (HLTB search may not have matched them)."
        )
    elif total_q:
        _echo(
            f"\n  Detail data: rush + leisure available for all {total_q}"
            " qualifying games."
        )

    if state.current_app_id:
        _echo(
            f"\n  Current game:      {state.current_game_name} (excluded from totals)"
        )
    _echo(f"  Finished games:    {games_done} (excluded from totals)")

    _echo(f"\n{_LINE}")
    _print_pace_scenario(state, total_q, games_done)

    worst_total, worst_missing = _sum_hours(qualified, "worst_hours")
    rush_total, rush_missing = _sum_hours(qualified, "rush_hours")
    leisure_total, leisure_missing = _sum_hours(qualified, "leisure_100h")

    _echo(f"\n{_LINE}")
    _print_scenario(
        "2. RUSH (avg comp_100 + DLC — typical fast completionist)",
        rush_total,
        rush_missing,
        total_q,
    )

    _echo(f"\n{_LINE}")
    _print_scenario(
        "3. LEISURE (comp_100_h + DLC — slow/comfortable 100 %)",
        leisure_total,
        leisure_missing,
        total_q,
    )

    _echo(f"\n{_LINE}")
    _print_scenario(
        "4. WORST CASE (max recorded time, any category, + DLC)",
        worst_total,
        worst_missing,
        total_q,
    )
    _print_worst_example(qualified)

    _echo(f"\n{_LINE}\n")
