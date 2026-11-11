"""Tests for scanning module — part 2 (missing coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.scanning import (
    _check_game_tampering,
    detect_tampering,
)
from steam_backlog_enforcer.tests._main_helpers import snap

PKG = "steam_backlog_enforcer._scanning_tampering"


def _entry(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 5,
    playtime: int = 60,
) -> dict[str, Any]:
    # A scan entry is a snapshot entry without the HLTB hours column.
    entry = snap(app_id, name, total, unlocked)
    del entry["completionist_hours"]
    entry["playtime_minutes"] = playtime
    return entry


class TestCheckGameTampering:
    """Tests for _check_game_tampering."""

    def test_current_game_skipped(self) -> None:
        """The assigned game is never checked for tampering."""
        state = State(current_app_id=1)
        result = _check_game_tampering(MagicMock(), _entry(app_id=1), state)
        assert result is None

    def test_finished_manual_pick_is_not_tampering(self) -> None:
        # The completion that retired the pick is legitimate progress; the
        # snapshot is simply stale. Reported as TAMPERING before this exemption.
        """New unlocks on a finished manual pick are legitimate progress."""
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 16
        client.refresh_single_game.return_value = game
        state = State(
            current_app_id=475150,
            finished_app_ids=[588730],
            manual_picks=[
                {"app_id": 588730, "game_name": "Majotori", "started_at": ""}
            ],
        )
        entry = _entry(app_id=588730, name="Majotori", total=16, unlocked=13)
        assert _check_game_tampering(client, entry, state) is None

    def test_active_second_pick_is_not_tampering(self) -> None:
        # A second manual pick is allowed but is not current_app_id.
        """New unlocks on an active second manual pick are allowed."""
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 9
        client.refresh_single_game.return_value = game
        state = State(
            current_app_id=475150,
            manual_picks=[
                {"app_id": 412830, "game_name": "STEINS;GATE", "started_at": ""}
            ],
        )
        entry = _entry(app_id=412830, name="STEINS;GATE", total=42, unlocked=5)
        assert _check_game_tampering(client, entry, state) is None

    def test_unrelated_game_still_flagged(self) -> None:
        # The detector must keep working for games never allowed.
        """New unlocks on a game never allowed are reported with the gain."""
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 8
        client.refresh_single_game.return_value = game
        state = State(current_app_id=475150, finished_app_ids=[588730])
        entry = _entry(app_id=813780, name="AoE2", unlocked=5)
        assert _check_game_tampering(client, entry, state) == ("AoE2", 813780, 3)

    def test_already_complete_skipped(self) -> None:
        """A game that was already 100% is not checked."""
        state = State()
        result = _check_game_tampering(
            MagicMock(),
            _entry(unlocked=10, total=10),
            state,
        )
        assert result is None

    def test_zero_playtime_skipped(self) -> None:
        """A game never played is not checked."""
        state = State()
        result = _check_game_tampering(
            MagicMock(),
            _entry(playtime=0),
            state,
        )
        assert result is None

    def test_no_new_achievements(self) -> None:
        """An unchanged unlock count is not tampering."""
        client = MagicMock()
        game = MagicMock()
        game.unlocked_achievements = 5
        client.refresh_single_game.return_value = game
        state = State()
        result = _check_game_tampering(client, _entry(unlocked=5), state)
        assert result is None

    def test_tampering_detected(self) -> None:
        """More unlocks than the snapshot is reported as name, id and gain."""
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
        """A failed refresh is not tampering."""
        client = MagicMock()
        client.refresh_single_game.return_value = None
        state = State()
        result = _check_game_tampering(client, _entry(), state)
        assert result is None


def _client_showing(extra: dict[int, int]) -> MagicMock:
    """A Steam client whose games each show ``extra[app_id]`` new unlocks (5 -> 5+n)."""
    client = MagicMock()

    def refresh(app_id: int, _name: str, _playtime: int) -> MagicMock:
        game = MagicMock()
        game.unlocked_achievements = 5 + extra.get(app_id, 0)
        return game

    client.refresh_single_game.side_effect = refresh
    return client


class TestDetectTampering:
    """Tests for detect_tampering."""

    notify: MagicMock

    def _run(self, entries: list[dict[str, Any]], client: MagicMock) -> MagicMock:
        with (
            patch(f"{PKG}.load_snapshot", return_value=entries),
            patch(f"{PKG}.SteamAPIClient", return_value=client),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.send_notification") as notify,
        ):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())
        self.notify = notify
        return mock_echo

    def test_no_snapshot(self) -> None:
        """With no snapshot, detection returns quietly."""
        with patch(f"{PKG}.load_snapshot", return_value=None):
            detect_tampering(Config(steam_api_key="k", steam_id="i"), State())

    def test_no_tampering(self) -> None:
        """Clean games produce no output and no notification."""
        mock_echo = self._run([_entry(app_id=1)], _client_showing({}))
        mock_echo.assert_not_called()
        self.notify.assert_not_called()

    def test_tampering_found(self) -> None:
        """A tampered game is echoed with its gain and notified once."""
        entries = [_entry(app_id=1, name="BadGame")]
        mock_echo = self._run(entries, _client_showing({1: 3}))
        assert any("TAMPERING" in str(c) for c in mock_echo.call_args_list)
        assert any("BadGame (AppID=1): +3" in str(c) for c in mock_echo.call_args_list)
        self.notify.assert_called_once()

    def test_stops_at_limit(self) -> None:
        """Reports only the first _TAMPER_CHECK_LIMIT suspicious games."""
        entries = [_entry(app_id=i, name=f"G{i}") for i in range(10)]
        mock_echo = self._run(entries, _client_showing(dict.fromkeys(range(10), 1)))
        reported = [c for c in mock_echo.call_args_list if "AppID=" in str(c)]
        assert len(reported) == 3
        assert "G0" in str(reported[0])
