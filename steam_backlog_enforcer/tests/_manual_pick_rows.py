"""Shared manual-pick row builders for the ``_actions`` core tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def iso_days_ago(days: float) -> str:
    """Return the UTC ISO timestamp ``days`` days before now."""
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def pick_row(app_id: int = 440, name: str = "TF2", days_ago: float = 1.0) -> dict:
    """Return one ``State.manual_picks`` entry started ``days_ago`` days ago."""
    return {
        "app_id": app_id,
        "game_name": name,
        "started_at": iso_days_ago(days_ago),
    }
