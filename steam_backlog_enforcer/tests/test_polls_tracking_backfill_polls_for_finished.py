"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _cmd_done
from steam_backlog_enforcer.config import State

if TYPE_CHECKING:
    from pathlib import Path

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestBackfillPollsForFinished:
    """Tests for Backfill Polls For Finished."""

    def test_no_missing_returns_existing(self, tmp_path: Path) -> None:
        """Test no missing returns existing."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"1": {"hours": 1.0, "polls": 5}}), encoding="utf-8"
        )
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_CMD}.load_snapshot", return_value=[{"app_id": 1, "name": "G"}]),
        ):
            result = _cmd_done._backfill_polls_for_finished(_state([1]))
        assert result == {1: 5}

    def test_no_snapshot_no_missing(self) -> None:
        """Test no snapshot no missing."""
        with (
            patch(f"{_CMD}.load_hltb_polls_cache", return_value={}),
            patch(f"{_CMD}.load_snapshot", return_value=None),
        ):
            assert _cmd_done._backfill_polls_for_finished(_state([1])) == {}

    def test_missing_triggers_fetch(self, tmp_path: Path) -> None:
        """Test missing triggers fetch."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"1": {"hours": 2.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": 2.0, "polls": 9}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: 2.0 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_CMD}.load_snapshot", return_value=[{"app_id": 1, "name": "G"}]),
            patch(f"{_CMD}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
            patch(f"{_CMD}._echo"),
        ):
            result = _cmd_done._backfill_polls_for_finished(_state([1]))
        assert result == {1: 9}

    def test_extra_app_id_with_zero_polls_added(self, tmp_path: Path) -> None:
        """Test extra app id with zero polls added."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"7": {"hours": 1.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": 1.0, "polls": 4}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: 1.0 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_CMD}.load_snapshot", return_value=[{"app_id": 7, "name": "G"}]),
            patch(f"{_CMD}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
            patch(f"{_CMD}._echo"),
        ):
            result = _cmd_done._backfill_polls_for_finished(
                _state([], current=7), extra_app_id=7
            )
        assert result == {7: 4}

    def test_preserves_prior_hours_on_miss(self, tmp_path: Path) -> None:
        """Test preserves prior hours on miss."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"3": {"hours": 4.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            # Simulate a refetch returning a miss (hours -1, polls 0).
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": -1, "polls": 0}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: -1 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_CMD}.load_snapshot", return_value=[{"app_id": 3, "name": "G"}]),
            patch(f"{_CMD}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
            patch(f"{_CMD}._echo"),
        ):
            _cmd_done._backfill_polls_for_finished(_state([3]))
        # Prior hours should be preserved on miss.
        final = json.loads(cache_file.read_text(encoding="utf-8"))
        assert final["3"]["hours"] == 4.0
