"""Shared value types for the ``stats`` command.

A leaf module: imported by :mod:`steam_backlog_enforcer._stats` and by its
helper modules, so it must not import either of them back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

_HLTB_SEARCH_BASE = "https://howlongtobeat.com/?q="


@dataclass
class _GameTimes:
    """Per-game time estimates for stats display."""

    game: GameInfo
    worst_hours: float
    rush_hours: float
    leisure_100h: float
    hltb_game_id: int = field(default=0)
