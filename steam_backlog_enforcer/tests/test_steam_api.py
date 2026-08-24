"""Tests for steam_api module."""

from __future__ import annotations

from typing import Any

from steam_backlog_enforcer.steam_api import (
    AchievementInfo,
    GameInfo,
)


class TestAchievementInfo:
    """Tests for AchievementInfo."""

    def test_create(self) -> None:
        """Test create."""
        a = AchievementInfo(
            api_name="ACH_1", display_name="First", achieved=True, unlock_time=1000
        )
        assert a.api_name == "ACH_1"
        assert a.achieved is True


class TestGameInfo:
    """Tests for GameInfo."""

    def test_completion_pct_zero_achievements(self) -> None:
        """Test completion pct zero achievements."""
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=0,
            unlocked_achievements=0,
            playtime_minutes=0,
        )
        assert g.completion_pct == 100.0

    def test_completion_pct_partial(self) -> None:
        """Test completion pct partial."""
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=0,
        )
        assert g.completion_pct == 50.0

    def test_is_complete_true(self) -> None:
        """Test is complete true."""
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=5,
            unlocked_achievements=5,
            playtime_minutes=0,
        )
        assert g.is_complete is True

    def test_is_complete_false(self) -> None:
        """Test is complete false."""
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=5,
            unlocked_achievements=3,
            playtime_minutes=0,
        )
        assert g.is_complete is False

    def test_is_complete_zero(self) -> None:
        """Test is complete zero."""
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=0,
            unlocked_achievements=0,
            playtime_minutes=0,
        )
        assert g.is_complete is False

    def test_to_snapshot(self) -> None:
        """Test to snapshot."""
        ach = AchievementInfo(
            api_name="A1", display_name="Ach1", achieved=True, unlock_time=99
        )
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=1,
            unlocked_achievements=1,
            playtime_minutes=60,
            achievements=[ach],
            completionist_hours=5.0,
        )
        snap = g.to_snapshot()
        assert snap["app_id"] == 1
        assert snap["achievements"][0]["api_name"] == "A1"
        assert snap["completionist_hours"] == 5.0

    def test_from_snapshot(self) -> None:
        """Test from snapshot."""
        data: dict[str, Any] = {
            "app_id": 2,
            "name": "G2",
            "total_achievements": 3,
            "unlocked_achievements": 1,
            "playtime_minutes": 120,
            "completionist_hours": 10.0,
            "achievements": [
                {
                    "api_name": "A1",
                    "display_name": "First",
                    "achieved": False,
                    "unlock_time": 0,
                },
            ],
        }
        g = GameInfo.from_snapshot(data)
        assert g.app_id == 2
        assert g.completionist_hours == 10.0
        assert len(g.achievements) == 1

    def test_from_snapshot_defaults(self) -> None:
        """Test from snapshot defaults."""
        data: dict[str, Any] = {
            "app_id": 3,
            "name": "G3",
            "total_achievements": 0,
            "unlocked_achievements": 0,
        }
        g = GameInfo.from_snapshot(data)
        assert g.playtime_minutes == 0
        assert g.completionist_hours == -1
        assert g.achievements == []

    def test_from_snapshot_achievement_defaults(self) -> None:
        """Test from snapshot achievement defaults."""
        data: dict[str, Any] = {
            "app_id": 4,
            "name": "G4",
            "total_achievements": 1,
            "unlocked_achievements": 0,
            "achievements": [{"api_name": "X", "achieved": False}],
        }
        g = GameInfo.from_snapshot(data)
        assert g.achievements[0].display_name == "X"
        assert g.achievements[0].unlock_time == 0
