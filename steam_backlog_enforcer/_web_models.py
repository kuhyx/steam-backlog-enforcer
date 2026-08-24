"""Dataclasses for the web UI's read-only dataset projection.

A leaf module: :mod:`steam_backlog_enforcer._web_dataset` and its helper
modules all import these types, so nothing here may import them back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Mirrors ``_stats._HOURS_PER_DAY_PRESETS`` but mutable/JSON-friendly.
HOURS_PER_DAY_PRESETS = [2.0, 4.0, 6.0, 8.0]


@dataclass
class WebGame:
    """One incomplete candidate game, with raw filterable fields.

    Hour fields use ``-1`` to mean "no data" (matching the cache convention),
    so the client can choose to include or exclude unknown-length games.
    """

    app_id: int
    name: str
    completion_pct: float
    playtime_minutes: int
    rush_hours: float
    leisure_hours: float
    worst_hours: float
    count_comp: int
    comp_100_count: int
    hltb_game_id: int
    protondb_tier: str
    protondb_trending_tier: str
    protondb_score: float


@dataclass
class WebStateInfo:
    """Pace inputs and current-assignment metadata for the UI."""

    current_app_id: int | None
    current_game_name: str
    games_done: int
    games_done_since_start: int
    days_elapsed: int
    enforcement_started_at: str
    pace_games_per_day: float


@dataclass
class WebDefaults:
    """The CLI's hardcoded filter thresholds, surfaced as editable defaults."""

    min_comp_100_polls: int
    min_count_comp: int
    min_confidence_sum: int
    min_playable_tier: str
    hours_per_day_presets: list[float]


@dataclass
class DefaultSummary:
    """Totals the CLI ``stats`` command would print at default thresholds.

    Used as a parity oracle: the client's own default-filtered totals must
    reproduce these numbers.
    """

    qualifying: int
    rush_total: float
    leisure_total: float
    worst_total: float


@dataclass
class PaceVsHLTB:
    """Player pace calibrated against HLTB rush/leisure averages.

    Derived from completed games that have HLTB detail data.  All ratio /
    interpolation fields use ``-1`` to mean "insufficient data", matching the
    cache convention used elsewhere.

    Fields:
        calibration_count: number of completed games used for calibration.
        ratio_vs_rush: actual_hours / rush_hours across calibration games.
        ratio_vs_leisure: actual_hours / leisure_hours (-1 if no leisure data).
        interpolation_t: position between rush (0.0) and leisure (1.0) speed.
            Negative means faster than rush; >1 means slower than leisure.
            -1 means insufficient data.
        player_style: human-readable style label.
    """

    calibration_count: int
    ratio_vs_rush: float
    ratio_vs_leisure: float
    interpolation_t: float
    player_style: str


@dataclass
class WebDataset:
    """Full payload served to the browser."""

    games: list[WebGame]
    state: WebStateInfo
    defaults: WebDefaults
    default_summary: DefaultSummary
    pace_vs_hltb: PaceVsHLTB | None
    generated_at: str = field(default="")
