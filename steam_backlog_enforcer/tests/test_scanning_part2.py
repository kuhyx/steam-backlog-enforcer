"""Tests for scanning module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.scanning import (
    _check_game_tampering,
    detect_tampering,
)

PKG = "python_pkg.steam_backlog_enforcer.scanning"


def _entry(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 5,
    playtime: int = 60,
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": playtime,
    }


class TestCheckGameTampering:
    """Tests for _check_game_tampering."""

    def test_current_game_skipped(self) -> None:
        state = State(current_app_id=1)
        result = _check_game_tampering(MagicMock(), _entry(app_id=1), state)
        assert result is None

    def test_already_complete_skipped(self) -> None:
        state = State()
        result = _check_game_tampering(
            MagicMock(),
            _entry(unlocked=10, total=10),
            state,
        )
        assert result is None

    def test_zero_playtime_skipped(self) -> None:
        state = State()
        result = _check_game_tampering(
            MagicMock(),
            _entry(playtime=0),
            state,
        )
        assert result is None

    def test_no_new_achievements(self) -> None:
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 5
        client.refresh_single_game.return_value = game
        state = State()
        result = _check_game_tampering(client, _entry(unlocked=5), state)
        assert result is None

    def test_tampering_detected(self) -> None:
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 8
        client.refresh_single_game.return_value = game
        state = State()
        entry = _entry(app_id=99, name="Cheated", unlocked=5)
        result = _check_game_tampering(client, entry, state)
        assert result is not None
        assert result == ("Cheated", 99, 3)

    def test_refresh_returns_none(self) -> None:
        client = MagicMock()
        client.refresh_single_game.return_value = None
        state = State()
        result = _check_game_tampering(client, _entry(), state)
        assert result is None


class TestDetectTampering:
    """Tests for detect_tampering."""

    def test_no_snapshot(self) -> None:
        with patch(f"{PKG}.load_snapshot", return_value=None):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())

    def test_no_tampering(self) -> None:
        entries = [_entry(app_id=1)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=entries),
            patch(f"{PKG}.SteamAPIClient"),
            patch(f"{PKG}._check_game_tampering", return_value=None),
            patch(f"{PKG}._echo"),
        ):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())

    def test_tampering_found(self) -> None:
        entries = [_entry(app_id=1, name="BadGame")]
        with (
            patch(f"{PKG}.load_snapshot", return_value=entries),
            patch(f"{PKG}.SteamAPIClient"),
            patch(
                f"{PKG}._check_game_tampering",
                return_value=("BadGame", 1, 3),
            ),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.send_notification"),
        ):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())
        assert any("TAMPERING" in str(c) for c in mock_echo.call_args_list)

    def test_stops_at_limit(self) -> None:
        """Stops after _TAMPER_CHECK_LIMIT suspicious games."""
        entries = [_entry(app_id=i, name=f"G{i}") for i in range(10)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=entries),
            patch(f"{PKG}.SteamAPIClient"),
            patch(
                f"{PKG}._check_game_tampering",
                return_value=("Game", 1, 1),
            ) as mock_check,
            patch(f"{PKG}._echo"),
            patch(f"{PKG}.send_notification"),
        ):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())
        # Should stop after 3 (_TAMPER_CHECK_LIMIT)
        assert mock_check.call_count == 3
