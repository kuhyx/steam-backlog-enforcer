"""Tests for the windowed re-fetch and progress reporting of detect_tampering."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _scanning_tampering as tamper
from steam_backlog_enforcer._progress import use_progress
from steam_backlog_enforcer.config import Config, State

_PKG = "steam_backlog_enforcer._scanning_tampering"


def _entry(app_id: int, **overrides: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "app_id": app_id,
        "name": f"G{app_id}",
        "total_achievements": 10,
        "unlocked_achievements": 5,
        "playtime_minutes": 60,
    }
    return entry | overrides


def _client(unlocked_by_id: dict[int, int]) -> MagicMock:
    client = MagicMock()

    def refresh(app_id: int, _name: str, _playtime: int) -> MagicMock | None:
        if app_id not in unlocked_by_id:
            return None
        return MagicMock(unlocked_achievements=unlocked_by_id[app_id])

    client.refresh_single_game.side_effect = refresh
    return client


class TestNeedsRefetch:
    def test_exempt_complete_and_unplayed_games_are_not_worth_a_request(self) -> None:
        assert not tamper._needs_refetch(_entry(1), {1})
        assert not tamper._needs_refetch(_entry(1, unlocked_achievements=10), set())
        assert not tamper._needs_refetch(_entry(1, playtime_minutes=0), set())

    def test_an_unfinished_played_game_is_checked(self) -> None:
        assert tamper._needs_refetch(_entry(1), set())


class TestRefetchInOrder:
    def test_yields_every_entry_in_order_beyond_the_window(self) -> None:
        entries = [_entry(i) for i in range(tamper._TAMPER_WINDOW * 2 + 3)]
        client = _client({e["app_id"]: 5 for e in entries})
        seen = [e["app_id"] for e, _ in tamper._refetch_in_order(client, entries)]
        assert seen == [e["app_id"] for e in entries]

    def test_a_game_steam_cannot_answer_for_comes_back_as_none(self) -> None:
        pairs = list(tamper._refetch_in_order(_client({}), [_entry(1)]))
        assert pairs[0][1] is None

    def test_closing_early_stops_asking(self) -> None:
        entries = [_entry(i) for i in range(tamper._TAMPER_WINDOW * 4)]
        client = _client({e["app_id"]: 5 for e in entries})
        stream = tamper._refetch_in_order(client, entries)
        next(stream)
        stream.close()
        assert client.refresh_single_game.call_count < len(entries)


class TestDetectTamperingProgress:
    def _run(self, entries: list[dict[str, Any]], client: MagicMock) -> MagicMock:
        progress = MagicMock()
        with (
            patch(f"{_PKG}.load_snapshot", return_value=entries),
            patch(f"{_PKG}.SteamAPIClient", return_value=client),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}.send_notification"),
            use_progress(progress),
        ):
            tamper.detect_tampering(Config(steam_api_key="k", steam_id="i"), State())
        return progress

    def test_one_step_per_game_checked(self) -> None:
        entries = [_entry(1), _entry(2), _entry(3, unlocked_achievements=10)]
        progress = self._run(entries, _client({1: 5, 2: 5}))
        progress.phase.assert_called_once_with("Checking other games for tampering", 2)
        assert [c.args[0] for c in progress.advance.call_args_list] == ["G1", "G2"]

    def test_hitting_the_limit_completes_the_bar(self) -> None:
        entries = [_entry(i) for i in range(6)]
        progress = self._run(entries, _client(dict.fromkeys(range(6), 6)))
        assert progress.advance.call_args_list[-1].kwargs == {"step": 6}
