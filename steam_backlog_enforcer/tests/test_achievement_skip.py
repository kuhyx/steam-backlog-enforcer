"""Tests for _achievement_skip: remembering games with no achievements."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _achievement_skip as skip
from steam_backlog_enforcer import config

_PKG = "steam_backlog_enforcer._achievement_skip"
_NOW = 1_000_000_000.0
_STEAM_ID = "sid"


def _store(payload: object) -> None:
    skip._cache_file().write_text(json.dumps(payload), encoding="utf-8")


def _game(app_id: int, *, stats: bool = False) -> dict[str, Any]:
    return {"appid": app_id, "has_community_visible_stats": stats}


class _HttpError(Exception):
    """What ``requests`` raises: an error that carries its response."""

    def __init__(self, response: MagicMock) -> None:
        super().__init__("http error")
        self.response = response


def _failure(status: int | None, body: object = None) -> Exception:
    """An exception whose cause carries an HTTP response (or none)."""
    exc = RuntimeError("achievements failed")
    if status is not None:
        response = MagicMock(status_code=status)
        if isinstance(body, Exception):
            response.json.side_effect = body
        else:
            response.json.return_value = body
        exc.__cause__ = _HttpError(response)
    return exc


class TestCacheFile:
    def test_lives_under_the_config_dir(self) -> None:
        assert skip._cache_file() == config.CONFIG_DIR / "no_achievements_cache.json"


class TestLoadChecked:
    def test_missing_file_is_empty(self) -> None:
        assert skip._load_checked(_STEAM_ID) == {}

    def test_corrupt_file_is_empty(self) -> None:
        skip._cache_file().write_text("{nope", encoding="utf-8")
        assert skip._load_checked(_STEAM_ID) == {}

    @pytest.mark.parametrize("payload", [["list"], {"steam_id": "other"}])
    def test_other_account_or_shape_is_empty(self, payload: object) -> None:
        _store(payload)
        assert skip._load_checked(_STEAM_ID) == {}

    def test_skips_unparsable_entries(self) -> None:
        _store({"steam_id": _STEAM_ID, "checked": {"1": 5, "x": 6, "2": None}})
        assert skip._load_checked(_STEAM_ID) == {1: 5.0}


class TestIsNoStatsAnswer:
    def test_steams_no_stats_answer(self) -> None:
        body = {"playerstats": {"error": "no stats", "success": False}}
        assert skip.is_no_stats_answer(_failure(400, body)) is True

    def test_no_response_is_not_an_answer(self) -> None:
        assert skip.is_no_stats_answer(_failure(None)) is False

    def test_other_status_is_not_an_answer(self) -> None:
        assert skip.is_no_stats_answer(_failure(500, {})) is False

    def test_unparsable_body_is_not_an_answer(self) -> None:
        assert skip.is_no_stats_answer(_failure(400, ValueError("html"))) is False

    def test_body_without_failure_flag_is_not_an_answer(self) -> None:
        assert skip.is_no_stats_answer(_failure(400, {"playerstats": {}})) is False

    def test_non_dict_playerstats_is_not_an_answer(self) -> None:
        assert skip.is_no_stats_answer(_failure(400, {"playerstats": 3})) is False


class TestSkippableAppIds:
    def test_nothing_recorded_skips_nothing(self) -> None:
        assert skip.skippable_app_ids(_STEAM_ID, [_game(1)], _NOW) == set()

    def test_recent_flagless_game_is_skipped(self) -> None:
        _store({"steam_id": _STEAM_ID, "checked": {"1": _NOW - 10}})
        with patch(f"{_PKG}.load_snapshot", return_value=None):
            found = skip.skippable_app_ids(_STEAM_ID, [_game(1)], _NOW)
        assert found == {1}

    def test_flagged_snapshotted_and_stale_games_are_scanned(self) -> None:
        stale = _NOW - skip.RECHECK_AFTER_SECONDS - 1
        _store(
            {
                "steam_id": _STEAM_ID,
                "checked": {"1": _NOW - 10, "2": _NOW - 10, "3": stale, "4": _NOW},
            }
        )
        owned = [_game(1, stats=True), _game(2), _game(3), _game(4), _game(5)]
        with patch(f"{_PKG}.load_snapshot", return_value=[{"app_id": 2}]):
            found = skip.skippable_app_ids(_STEAM_ID, owned, _NOW)
        assert found == {4}


class TestRecordScan:
    def _saved(self) -> dict[str, float]:
        return json.loads(skip._cache_file().read_text(encoding="utf-8"))["checked"]

    def test_records_games_that_came_back_empty(self) -> None:
        skip.record_scan(_STEAM_ID, [_game(1), _game(2)], {2}, _NOW)
        assert self._saved() == {"1": _NOW}

    def test_forgets_games_that_gained_achievements_or_the_flag(self) -> None:
        _store({"steam_id": _STEAM_ID, "checked": {"1": 5, "2": 5, "3": 5}})
        fetched = [_game(1), _game(2, stats=True), _game(3)]
        skip.record_scan(_STEAM_ID, fetched, {1}, _NOW)
        assert self._saved() == {"3": _NOW}

    def test_a_failed_write_is_swallowed(self) -> None:
        with patch(f"{_PKG}._atomic_write", side_effect=OSError("disk full")):
            skip.record_scan(_STEAM_ID, [_game(1)], set(), _NOW)
        assert not skip._cache_file().exists()
