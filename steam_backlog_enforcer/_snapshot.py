"""Persistence for the cached achievement snapshot.

Split out of :mod:`steam_backlog_enforcer.config` when that module reached the
250-line cap. The dependency runs one way — this module imports the paths from
``config``, never the reverse — so callers import these two names from here.
"""

from __future__ import annotations

import json
from typing import Any

from steam_backlog_enforcer import config
from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._steam_models import GameInfo
from steam_backlog_enforcer.config import _atomic_write


def save_snapshot(data: list[dict[str, Any]]) -> None:
    """Save an achievement snapshot to disk.

    Args:
        data: The snapshot rows to persist.
    """
    _atomic_write(
        config.SNAPSHOT_FILE,
        json.dumps(data, indent=2) + "\n",
    )


def load_snapshot() -> list[dict[str, Any]] | None:
    """Load the cached achievement snapshot.

    Returns:
        The snapshot rows, or ``None`` when no snapshot has been written.
    """
    if config.SNAPSHOT_FILE.exists():
        result: list[dict[str, Any]] = json.loads(
            config.SNAPSHOT_FILE.read_text(encoding="utf-8")
        )
        return result
    return None


def snapshot_game_name(app_id: int) -> str | None:
    """The name the last snapshot recorded for ``app_id``, or ``None``."""
    for entry in load_snapshot() or []:
        if entry.get("app_id") == app_id:
            return str(entry["name"])
    return None


def require_snapshot_games() -> list[GameInfo] | None:
    """The last snapshot as games, or ``None`` after telling the user to scan."""
    snapshot = load_snapshot()
    if snapshot is None:
        _echo("No snapshot found. Run 'scan' first.")
        return None
    return [GameInfo.from_snapshot(d) for d in snapshot]
