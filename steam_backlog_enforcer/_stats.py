"""Backlog completion-time statistics for Steam Backlog Enforcer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._hltb_types import (
    _read_raw_cache,
)
from steam_backlog_enforcer._snapshot import load_snapshot
from steam_backlog_enforcer._stats_display import (
    _format_completion_date,
    _print_pace_scenario,
    _print_worst_example,
    _sum_hours,
)
from steam_backlog_enforcer._stats_gathering import (
    _ensure_completed_rush_data,
    _ensure_rush_data,
    _filter_qualifying_games,
    _refresh_recently_played_completions,
)
from steam_backlog_enforcer._stats_types import _GameTimes
from steam_backlog_enforcer._web_dataset import (
    PaceVsHLTB,
    compute_pace_vs_hltb,
    count_complete_since_start,
)
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.steam_api import (
    GameInfo,
)

# _GameTimes lives in the _stats_types leaf so both this module and its
# helper modules can share it; it is re-exported here because callers (and
# tests) have always imported it from _stats. Without __all__, mypy's
# --no-implicit-reexport rejects those imports.
__all__ = ["_GameTimes"]

if TYPE_CHECKING:
    from steam_backlog_enforcer.config import Config, State

logger = logging.getLogger(__name__)

_HOURS_PER_DAY_PRESETS = (2.0, 4.0, 6.0, 8.0)

_LINE = "─" * 70


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


def _print_player_speed_scenario(
    pace: PaceVsHLTB | None,
    rush_total: float,
    leisure_total: float,
) -> None:
    """Print player pace vs HLTB averages and an extrapolated backlog estimate."""
    _echo(f"\n{_LINE}")
    _echo("\n  5. YOUR PLAY STYLE vs HLTB AVERAGES")

    if pace is None or pace.calibration_count == 0:
        _echo("    No calibration data available.")
        _echo(
            "    Finish some games (100 % achievements) and re-run 'stats'"
            " to enable this estimate."
        )
        return

    _echo(f"\n    Calibration games: {pace.calibration_count}")
    if pace.ratio_vs_rush > 0:
        _echo(f"    vs Rush:           {pace.ratio_vs_rush:.2f}x rush pace")
    if pace.ratio_vs_leisure > 0:
        _echo(f"    vs Leisure:        {pace.ratio_vs_leisure:.2f}x leisure pace")
    if pace.interpolation_t != -1.0:
        _echo(
            f"    Interpolation t:   {pace.interpolation_t:.3f}"
            "  (0 = rush speed, 1 = leisure speed)"
        )

    style_labels = {
        "faster_than_rush": "Faster than rush",
        "rush_to_leisure": "Between rush and leisure",
        "slower_than_leisure": "Slower than leisure",
        "unknown": "Unknown",
    }
    style = style_labels.get(pace.player_style, pace.player_style)
    _echo(f"    Play style:        {style}")

    if pace.interpolation_t != -1.0 and rush_total > 0 and leisure_total > 0:
        est = rush_total + pace.interpolation_t * (leisure_total - rush_total)
    elif pace.ratio_vs_rush > 0 and rush_total > 0:
        est = rush_total * pace.ratio_vs_rush
    else:
        est = -1.0

    if est > 0:
        _echo(f"\n    Estimated backlog total at your pace: {est:,.1f} h")
        for daily in _HOURS_PER_DAY_PRESETS:
            estimate = _format_completion_date(est, daily)
            _echo(f"    @ {daily:.0f} h/day → {estimate}")


def cmd_stats(_config: Config, state: State) -> None:
    """Display backlog completion-time statistics.

    Filters games by the same HLTB-confidence and Linux-compatibility rules
    used when picking the next game.  Auto-fetches missing rush/leisure detail
    data before printing.  Shows five scenarios:

    1. At your current pace (games finished per day since enforcement started).
    2. Rush   — avg comp_100 + DLC completion time per HLTB.
    3. Leisure — comp_100_h (slowest 100 %) + DLC leisure per HLTB.
    4. Worst   — absolute maximum recorded time (any category) per HLTB.
    5. Your play style — extrapolated from completed-game calibration vs HLTB.
    """
    snapshot = load_snapshot()
    if snapshot is None:
        _echo("No snapshot found. Run 'scan' first.")
        return

    games = [GameInfo.from_snapshot(d) for d in snapshot]
    games = _refresh_recently_played_completions(games, _config)
    # Count all 100%-achievement games in library (more accurate than
    # finished_app_ids, which only tracks enforcer-assigned completions).
    games_done = sum(1 for g in games if g.is_complete)
    # Only count games completed on/after enforcement start for pace — pre-start
    # completions are not representative of the enforcer period's throughput.
    games_done_since_start = count_complete_since_start(
        games, state.enforcement_started_at
    )

    # Ensure completed games have rush/leisure data for pace calibration.
    _ensure_completed_rush_data(games)

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
    _print_pace_scenario(state, total_q, games_done_since_start)

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

    # Pace calibration uses the freshly-updated cache (both fetches above ran).
    raw_cache = _read_raw_cache()
    pace_vs_hltb = compute_pace_vs_hltb(games, raw_cache)
    _print_player_speed_scenario(pace_vs_hltb, rush_total, leisure_total)

    _echo(f"\n{_LINE}\n")
