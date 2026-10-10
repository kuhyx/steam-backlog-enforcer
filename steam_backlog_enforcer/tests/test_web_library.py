"""Tests for _web_library — the owned-games join behind ``GET /api/library``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_library
from steam_backlog_enforcer import config as _config
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.steam_api import GameInfo
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

_PKG = "steam_backlog_enforcer._web_library"


@pytest.fixture(autouse=True)
def _fresh_memos(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module keeps process-wide memos; every test starts without them."""
    monkeypatch.setattr(_web_library, "_MEMOS", _web_library._Memos())


def _write_snapshot(rows: list[dict[str, Any]]) -> None:
    _config.SNAPSHOT_FILE.write_text(json.dumps(rows), encoding="utf-8")


def _row(app_id: int, **extra: object) -> dict[str, Any]:
    return {"app_id": app_id, "name": f"G{app_id}", **extra}


class TestSnapshotGames:
    def test_no_snapshot_file(self) -> None:
        assert _web_library._snapshot_games() == {}

    def test_rows_become_games_and_are_memoised(self) -> None:
        _write_snapshot(
            [
                _row(1, total_achievements=10, unlocked_achievements=4),
                {"name": "no id"},
                _row(2, completionist_hours=7.5, playtime_minutes=30),
            ]
        )
        games = _web_library._snapshot_games()
        assert sorted(games) == [1, 2]
        assert games[1].total_achievements == 10
        assert games[2].completionist_hours == 7.5
        assert games[1].completionist_hours == -1
        with patch(f"{_PKG}.load_snapshot") as load:
            assert _web_library._snapshot_games() is games
        load.assert_not_called()

    def test_a_changed_file_is_reparsed(self) -> None:
        _write_snapshot([_row(1)])
        assert sorted(_web_library._snapshot_games()) == [1]
        _write_snapshot([_row(1), _row(2, name=None)])
        got = _web_library._snapshot_games()
        assert sorted(got) == [1, 2]
        assert got[2].name == ""

    def test_missing_snapshot_content_is_empty(self) -> None:
        _write_snapshot([_row(1)])
        with patch(f"{_PKG}.load_snapshot", return_value=None):
            assert _web_library._snapshot_games() == {}


class TestOwnedRecords:
    def test_cached_records(self) -> None:
        records = [{"app_id": 1}, {"name": "no id"}]
        with patch(f"{_PKG}.load_owned_records", return_value=records):
            got = _web_library._owned_records(Config(steam_id="s"))
        assert got == {1: {"app_id": 1}}

    def test_fetched_once_when_nothing_is_cached(self) -> None:
        with (
            patch(f"{_PKG}.load_owned_records", return_value=None),
            patch(f"{_PKG}.refresh_owned_records", return_value=[{"app_id": 2}]),
        ):
            assert list(_web_library._owned_records(Config())) == [2]

    def test_steam_unreachable_is_empty(self) -> None:
        with (
            patch(f"{_PKG}.load_owned_records", return_value=None),
            patch(f"{_PKG}.refresh_owned_records", return_value=None),
        ):
            assert _web_library._owned_records(Config()) == {}


class TestHltbHours:
    def test_prefers_the_hltb_cache(self) -> None:
        game = GameInfo(1, "g", 1, 0, 0, completionist_hours=9.0)
        assert _web_library._hltb_hours(1, game, {1: {"hours": 12.34}}) == 12.3

    def test_falls_back_to_the_snapshot(self) -> None:
        game = GameInfo(1, "g", 1, 0, 0, completionist_hours=9.0)
        assert _web_library._hltb_hours(1, game, {}) == 9.0

    def test_unknown_without_either(self) -> None:
        assert _web_library._hltb_hours(1, None, {}) is None
        game = GameInfo(1, "g", 1, 0, 0)
        assert _web_library._hltb_hours(1, game, {}) is None


class TestOwnedAppIds:
    def test_union_of_snapshot_and_records_memoised_by_stamp(self) -> None:
        _write_snapshot([_row(1)])
        records = [{"app_id": 2}, {"x": 1}]
        with (
            patch(f"{_PKG}.owned_cache_stamp", return_value=(1, 1)),
            patch(f"{_PKG}.load_owned_records", return_value=records) as load,
        ):
            assert _web_library.owned_app_ids() == {1, 2}
            assert _web_library.owned_app_ids() == {1, 2}
        load.assert_called_once()

    def test_a_new_stamp_reloads_and_none_means_empty(self) -> None:
        with (
            patch(f"{_PKG}.owned_cache_stamp", side_effect=[(1, 1), (2, 2)]),
            patch(f"{_PKG}.load_owned_records", side_effect=[[{"app_id": 5}], None]),
        ):
            assert _web_library.owned_app_ids() == {5}
            assert _web_library.owned_app_ids() == set()


class TestReason:
    def test_no_achievements_flag(self) -> None:
        got = _web_library._reason(1, None, {"has_stats": False}, State(), set())
        assert got == "No achievements"

    def test_not_scanned_yet(self) -> None:
        got = _web_library._reason(1, None, {"has_stats": True}, State(), set())
        assert got == "Not scanned yet"

    def test_otherwise_the_pick_rule(self) -> None:
        assert _web_library._reason(1, None, {}, State(), set()) == (
            "No achievement data"
        )
        game = GameInfo(1, "g", 2, 0, 0)
        assert _web_library._reason(1, game, {}, State(), set()) is None


class TestLibraryRows:
    def test_joins_every_source(self) -> None:
        _write_snapshot(
            [_row(1, total_achievements=4, unlocked_achievements=1, playtime_minutes=5)]
        )
        records = [
            {"app_id": 1, "name": "One", "playtime_minutes": 60, "last_played": 99},
            {"app_id": 2, "has_stats": False},
        ]
        with (
            patch(f"{_PKG}.load_owned_records", return_value=records),
            patch(f"{_PKG}._read_raw_cache", return_value={1: {"hours": 3.0}}),
            patch(f"{_PKG}.get_installed_games", return_value=[(1, "One")]),
            patch(f"{_PKG}.allowed_app_ids", return_value={1}),
        ):
            rows = {
                r["app_id"]: r for r in _web_library.library_rows(State(), Config())
            }
        assert rows[1] == {
            "app_id": 1,
            "name": "One",
            "achievements_total": 4,
            "achievements_unlocked": 1,
            "hltb_hours": 3.0,
            "playtime_minutes": 60,
            "last_played": 99,
            "installed": True,
            "assigned": True,
            "ineligible_reason": None,
        }
        assert rows[2]["name"] == "2"
        assert rows[2]["last_played"] is None
        assert rows[2]["ineligible_reason"] == "No achievements"

    def test_snapshot_only_game_uses_its_own_name_and_playtime(self) -> None:
        _write_snapshot([_row(3, playtime_minutes=8)])
        with (
            patch(f"{_PKG}.load_owned_records", return_value=[]),
            patch(f"{_PKG}._read_raw_cache", return_value={}),
            patch(f"{_PKG}.get_installed_games", return_value=[]),
        ):
            (row,) = _web_library.library_rows(State(), Config())
        assert (row["name"], row["playtime_minutes"]) == ("G3", 8)

    def test_view_wraps_the_rows(self) -> None:
        with patch(f"{_PKG}.library_rows", return_value=[{"app_id": 1}]):
            reply = _web_library.library_view(make_request())
        assert payload_of(reply) == {"games": [{"app_id": 1}]}
