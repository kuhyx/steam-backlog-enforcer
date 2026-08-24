"""Steam Web API client for fetching games and achievement data."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

logger = logging.getLogger(__name__)

STEAM_API_BASE = "https://api.steampowered.com"
MAX_WORKERS = 20


@dataclass
class AchievementInfo:
    """Single achievement state."""

    api_name: str
    display_name: str
    achieved: bool
    unlock_time: int


@dataclass
class GameInfo:
    """Info about an owned Steam game."""

    app_id: int
    name: str
    total_achievements: int
    unlocked_achievements: int
    playtime_minutes: int
    achievements: list[AchievementInfo] = field(default_factory=list)
    completionist_hours: float = -1
    comp_100_count: int = 0
    count_comp: int = 0

    @property
    def completion_pct(self) -> float:
        """Achievement completion percentage."""
        if self.total_achievements == 0:
            return 100.0
        return (self.unlocked_achievements / self.total_achievements) * 100.0

    @property
    def is_complete(self) -> bool:
        """True if all achievements are unlocked."""
        return (
            self.total_achievements > 0
            and self.unlocked_achievements >= self.total_achievements
        )

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "app_id": self.app_id,
            "name": self.name,
            "total_achievements": self.total_achievements,
            "unlocked_achievements": self.unlocked_achievements,
            "playtime_minutes": self.playtime_minutes,
            "completionist_hours": self.completionist_hours,
            "comp_100_count": self.comp_100_count,
            "count_comp": self.count_comp,
            "achievements": [
                {
                    "api_name": a.api_name,
                    "display_name": a.display_name,
                    "achieved": a.achieved,
                    "unlock_time": a.unlock_time,
                }
                for a in self.achievements
            ],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> GameInfo:
        """Deserialize from a cached snapshot dict."""
        achievements = [
            AchievementInfo(
                api_name=a["api_name"],
                display_name=a.get("display_name", a["api_name"]),
                achieved=a["achieved"],
                unlock_time=a.get("unlock_time", 0),
            )
            for a in data.get("achievements", [])
        ]
        return cls(
            app_id=data["app_id"],
            name=data["name"],
            total_achievements=data["total_achievements"],
            unlocked_achievements=data["unlocked_achievements"],
            playtime_minutes=data.get("playtime_minutes", 0),
            completionist_hours=data.get("completionist_hours", -1),
            comp_100_count=data.get("comp_100_count", 0),
            count_comp=data.get("count_comp", 0),
            achievements=achievements,
        )
