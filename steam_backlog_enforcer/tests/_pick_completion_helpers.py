"""Shared builders for the manual-pick completion tests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from steam_backlog_enforcer.steam_api import AchievementInfo, GameInfo


def game(app_id: int, unlocked: int, total: int, *, new: bool = False) -> GameInfo:
    """Build a GameInfo with the given achievement progress.

    Args:
        app_id: Steam application id.
        unlocked: Unlocked achievement count.
        total: Total achievement count.
        new: Whether one of the unlocks happened just now (after any pick).

    Returns:
        A GameInfo carrying that progress.
    """
    now = int(datetime.now(UTC).timestamp())
    achievements = [
        AchievementInfo(f"a{i}", f"Ach{i}", i < unlocked, now if new and i == 0 else 1)
        for i in range(total)
    ]
    return GameInfo(
        app_id=app_id,
        name="G",
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=0,
        achievements=achievements,
    )


def client_returning(*games: GameInfo | None) -> MagicMock:
    """Build a fake SteamAPIClient yielding *games* in order.

    Args:
        games: What each ``refresh_single_game`` call should return.

    Returns:
        A MagicMock standing in for SteamAPIClient.
    """
    fake = MagicMock()
    fake.refresh_single_game.side_effect = list(games)
    return fake
