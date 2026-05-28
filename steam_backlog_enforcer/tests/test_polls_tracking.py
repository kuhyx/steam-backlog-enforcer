"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _cmd_done
from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_game_id_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from pathlib import Path

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"


class TestCacheSchema:
    """Tests for the new cache schema and back-compat migration."""

    def test_legacy_float_migrates(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": 10.5}), encoding="utf-8")
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 10.5}
            assert load_hltb_polls_cache() == {440: 0}
            assert load_hltb_count_comp_cache() == {440: 0}

    def test_new_dict_schema(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"440": {"hours": 10.5, "polls": 7, "count_comp": 20}}),
            encoding="utf-8",
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 10.5}
            assert load_hltb_polls_cache() == {440: 7}
            assert load_hltb_count_comp_cache() == {440: 20}

    def test_invalid_app_id_skipped(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"notanint": 1.0, "440": 5.0}), encoding="utf-8"
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {440: 5.0}

    def test_unparseable_value_skipped(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": "notafloat"}), encoding="utf-8")
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            assert load_hltb_cache() == {}

    def test_save_with_polls_roundtrip(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5}, {440: 7}, _HLTBExtras(count_comp={440: 20}))
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {
                "440": {
                    "hours": 10.5,
                    "polls": 7,
                    "count_comp": 20,
                    "rush_hours": -1,
                    "leisure_100h": -1,
                    "hltb_game_id": 0,
                }
            }

    def test_save_without_polls_defaults_zero(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {
                "440": {
                    "hours": 10.5,
                    "polls": 0,
                    "count_comp": 0,
                    "rush_hours": -1,
                    "leisure_100h": -1,
                    "hltb_game_id": 0,
                }
            }

    def test_load_game_id_cache(self, tmp_path: Path) -> None:
        """load_hltb_game_id_cache returns the hltb_game_id portion of the cache."""
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5}, extras=_HLTBExtras(hltb_game_id={440: 99}))
            assert load_hltb_game_id_cache() == {440: 99}


class TestHltbResultPolls:
    def test_default_zero(self) -> None:
        r = HLTBResult(app_id=1, game_name="x", completionist_hours=1.0, similarity=1)
        assert r.comp_100_count == 0
        assert r.count_comp == 0

    def test_explicit(self) -> None:
        r = HLTBResult(
            app_id=1,
            game_name="x",
            completionist_hours=1.0,
            similarity=1,
            comp_100_count=42,
            count_comp=100,
        )
        assert r.comp_100_count == 42
        assert r.count_comp == 100


class TestGameInfoPolls:
    def test_snapshot_roundtrip(self) -> None:
        g = GameInfo(
            app_id=1,
            name="X",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=30,
            comp_100_count=8,
            count_comp=20,
        )
        snap = g.to_snapshot()
        assert snap["comp_100_count"] == 8
        assert snap["count_comp"] == 20
        restored = GameInfo.from_snapshot(snap)
        assert restored.comp_100_count == 8
        assert restored.count_comp == 20

    def test_snapshot_missing_field_defaults(self) -> None:
        snap = {
            "app_id": 1,
            "name": "X",
            "total_achievements": 0,
            "unlocked_achievements": 0,
        }
        restored = GameInfo.from_snapshot(snap)
        assert restored.comp_100_count == 0
        assert restored.count_comp == 0


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestBackfillPollsForFinished:
    def test_no_missing_returns_existing(self, tmp_path: Path) -> None:
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
        with (
            patch(f"{_CMD}.load_hltb_polls_cache", return_value={}),
            patch(f"{_CMD}.load_snapshot", return_value=None),
        ):
            assert _cmd_done._backfill_polls_for_finished(_state([1])) == {}

    def test_missing_triggers_fetch(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"1": {"hours": 2.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
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
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"7": {"hours": 1.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
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
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"3": {"hours": 4.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            # Simulate a refetch returning a miss (hours -1, polls 0).
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


class TestReportAssignedConfidence:
    def test_new_low_warning(self) -> None:
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 1, 2: 5, 3: 10},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "OldShortest"},
                    {"app_id": 3, "name": "Other"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2, 3], current=1))
        assert any("NEW LOW" in s for s in echoed)
        assert any("Historical min" in s and "OldShortest" in s for s in echoed)

    def test_zero_polls_warning_with_history(self) -> None:
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 0, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert any("no polls recorded" in s for s in echoed)

    def test_zero_polls_warning_no_history(self) -> None:
        echoed: list[str] = []
        with (
            patch(f"{_CMD}._backfill_polls_for_finished", return_value={1: 0}),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([], current=1))
        assert any("no polls recorded" in s for s in echoed)
        assert not any("Historical min" in s for s in echoed)

    def test_healthy_no_warning(self) -> None:
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 50, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
        assert any("HLTB confidence: 50" in s for s in echoed)

    def test_unknown_finished_uses_appid_label(self) -> None:
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 50, 99: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([99], current=1))
        assert any("AppID=99" in s for s in echoed)

    def test_chosen_equals_min_no_warning(self) -> None:
        # Edge case: chosen_polls == min_polls (not a new low).
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 5, 2: 5},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                    {"app_id": 2, "name": "Old"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([2], current=1))
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)
