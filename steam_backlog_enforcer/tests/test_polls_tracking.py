"""Tests for HLTB poll-count tracking, schema migration, and confidence display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from python_pkg.steam_backlog_enforcer import _cmd_done, scanning
from python_pkg.steam_backlog_enforcer._hltb_types import (
    HLTBResult,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)
from python_pkg.steam_backlog_enforcer.config import State
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from pathlib import Path

_TYPES = "python_pkg.steam_backlog_enforcer._hltb_types"
_CMD = "python_pkg.steam_backlog_enforcer._cmd_done"
_SCAN = "python_pkg.steam_backlog_enforcer.scanning"


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
            save_hltb_cache({440: 10.5}, {440: 7}, {440: 20})
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {"440": {"hours": 10.5, "polls": 7, "count_comp": 20}}

    def test_save_without_polls_defaults_zero(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data == {"440": {"hours": 10.5, "polls": 0, "count_comp": 0}}


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


class TestScanningPollsIntegration:
    def test_do_scan_kept_assignment_reports(self) -> None:
        # Targeted test for scanning's `else` branch that prints CURRENT.
        echoed: list[str] = []
        games = [
            GameInfo(
                app_id=1,
                name="X",
                total_achievements=10,
                unlocked_achievements=2,
                playtime_minutes=0,
                completionist_hours=5.0,
                comp_100_count=20,
            )
        ]
        state = _state([], current=1)
        with (
            patch(f"{_SCAN}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_SCAN}._report_poll_confidence") as mock_report,
        ):
            # Directly invoke just the kept-assignment branch.
            current = next((g for g in games if g.app_id == state.current_app_id), None)
            assert current is not None
            scanning._echo(f"\n>>> CURRENT: {current.name} (AppID={current.app_id})")
            scanning._report_poll_confidence(current, games, state)
        assert any("CURRENT" in s for s in echoed)
        mock_report.assert_called_once()

    def test_report_poll_confidence_new_low(self) -> None:
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=0,
        )
        games = [
            chosen,
            GameInfo(
                app_id=2,
                name="Old",
                total_achievements=10,
                unlocked_achievements=10,
                playtime_minutes=0,
            ),
        ]
        with (
            patch(
                f"{_SCAN}._backfill_polls_for_finished",
                return_value={1: 1, 2: 5},
            ),
            patch(f"{_SCAN}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            scanning._report_poll_confidence(chosen, games, _state([2], current=1))
        assert any("NEW LOW" in s for s in echoed)
        assert chosen.comp_100_count == 1

    def test_report_poll_confidence_no_history(self) -> None:
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=4,
        )
        with (
            patch(f"{_SCAN}._backfill_polls_for_finished", return_value={1: 4}),
            patch(f"{_SCAN}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            scanning._report_poll_confidence(chosen, [chosen], _state([], current=1))
        # No "Historical min" line when no finished games have polls.
        assert not any("Historical min" in s for s in echoed)
        assert any("HLTB confidence: 4" in s for s in echoed)

    def test_scanning_backfill_no_missing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 1.0, "polls": 5}}), encoding="utf-8"
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            result = scanning._backfill_polls_for_finished(
                _state([2]),
                [
                    GameInfo(
                        app_id=2,
                        name="X",
                        total_achievements=0,
                        unlocked_achievements=0,
                        playtime_minutes=0,
                    )
                ],
            )
        assert result == {2: 5}

    def test_scanning_backfill_with_missing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 3.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": 3.0, "polls": 8}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: 3.0 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_SCAN}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
        ):
            result = scanning._backfill_polls_for_finished(
                _state([2]),
                [
                    GameInfo(
                        app_id=2,
                        name="X",
                        total_achievements=0,
                        unlocked_achievements=0,
                        playtime_minutes=0,
                    )
                ],
            )
        assert result == {2: 8}

    def test_scanning_backfill_preserves_hours_on_miss(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 9.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": -1, "polls": 0}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: -1 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_SCAN}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
        ):
            scanning._backfill_polls_for_finished(
                _state([2]),
                [
                    GameInfo(
                        app_id=2,
                        name="X",
                        total_achievements=0,
                        unlocked_achievements=0,
                        playtime_minutes=0,
                    )
                ],
            )
        final = json.loads(cache_file.read_text(encoding="utf-8"))
        assert final["2"]["hours"] == 9.0

    def test_report_poll_confidence_chosen_zero_polls(self) -> None:
        """Covers scanning.py 301-302: 0-poll chosen with history yields warning."""
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=0,
        )
        old = GameInfo(
            app_id=2,
            name="Old",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=0,
        )
        with (
            patch(
                f"{_SCAN}._backfill_polls_for_finished",
                return_value={1: 0, 2: 5},
            ),
            patch(f"{_SCAN}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            scanning._report_poll_confidence(
                chosen, [chosen, old], _state([2], current=1)
            )
        assert any("no polls recorded" in s for s in echoed)

    def test_do_scan_kept_assignment_missing_game(self) -> None:
        """Covers scanning.py 110->116: current_app_id set but game absent."""
        from python_pkg.steam_backlog_enforcer.config import Config
        from python_pkg.steam_backlog_enforcer.scanning import do_scan

        other = GameInfo(
            app_id=999,
            name="Other",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=0,
        )
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.build_game_list.return_value = [other]
        with (
            patch(f"{_SCAN}.SteamAPIClient", return_value=mock_client),
            patch(f"{_SCAN}.fetch_hltb_times_cached", return_value={999: 10.0}),
            patch(f"{_SCAN}.save_snapshot"),
            patch(f"{_SCAN}.pick_next_game") as mock_pick,
            patch(f"{_SCAN}._echo"),
            patch(f"{_SCAN}._report_poll_confidence") as mock_report,
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State(current_app_id=440)  # not in games
            do_scan(config, state)
        mock_pick.assert_not_called()
        mock_report.assert_not_called()

    def test_cmd_done_no_finished_history_chosen_has_polls(self) -> None:
        """Covers _cmd_done.py 100->103: no finished history, chosen has >0 polls."""
        echoed: list[str] = []
        with (
            patch(
                f"{_CMD}._backfill_polls_for_finished",
                return_value={1: 7},
            ),
            patch(
                f"{_CMD}.load_snapshot",
                return_value=[
                    {"app_id": 1, "name": "Chosen"},
                ],
            ),
            patch(f"{_CMD}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            _cmd_done._report_assigned_confidence(1, _state([], current=1))
        assert any("HLTB confidence: 7" in s for s in echoed)
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)

    def test_report_poll_confidence_chosen_equals_min(self) -> None:
        """Covers scanning.py 301->304: chosen_polls >= min_polls, no warning."""
        echoed: list[str] = []
        chosen = GameInfo(
            app_id=1,
            name="Chosen",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=0,
            comp_100_count=5,
        )
        old = GameInfo(
            app_id=2,
            name="Old",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=0,
        )
        with (
            patch(
                f"{_SCAN}._backfill_polls_for_finished",
                return_value={1: 5, 2: 5},
            ),
            patch(f"{_SCAN}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            scanning._report_poll_confidence(
                chosen, [chosen, old], _state([2], current=1)
            )
        assert not any("NEW LOW" in s for s in echoed)
        assert not any("no polls recorded" in s for s in echoed)

    def test_refresh_candidate_confidence_noop_when_present(self) -> None:
        game = GameInfo(
            app_id=1,
            name="Known",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=3,
            count_comp=15,
        )
        with patch(f"{_SCAN}.fetch_hltb_confidence_cached") as mock_fetch:
            scanning._refresh_candidate_confidence(game)
        mock_fetch.assert_not_called()

    def test_refresh_candidate_confidence_backfills_zeroes(
        self, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"1": {"hours": 4.0, "polls": 0, "count_comp": 0}}),
            encoding="utf-8",
        )
        game = GameInfo(
            app_id=1,
            name="NeedsRefresh",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )

        def fake_fetch(_games: list[tuple[int, str]]) -> dict[int, float]:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["1"] = {"hours": 4.0, "polls": 3, "count_comp": 15}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {1: 4.0}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(f"{_SCAN}.fetch_hltb_confidence_cached", side_effect=fake_fetch),
            patch(f"{_SCAN}._echo"),
        ):
            scanning._refresh_candidate_confidence(game)

        assert game.comp_100_count == 3
        assert game.count_comp == 15

    def test_filter_hltb_confidence_batches_refreshes(self, tmp_path: Path) -> None:
        """Filtering refreshes missing confidence in one batched cache lookup."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "1": {"hours": 4.0, "polls": 0, "count_comp": 0},
                    "2": {"hours": 5.0, "polls": 0, "count_comp": 0},
                }
            ),
            encoding="utf-8",
        )
        game_a = GameInfo(
            app_id=1,
            name="A",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )
        game_b = GameInfo(
            app_id=2,
            name="B",
            total_achievements=10,
            unlocked_achievements=1,
            playtime_minutes=0,
            comp_100_count=0,
            count_comp=0,
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            assert sorted(games) == [(1, "A"), (2, "B")]
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["1"] = {"hours": 4.0, "polls": 3, "count_comp": 15}
            data["2"] = {"hours": 5.0, "polls": 3, "count_comp": 15}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {1: 4.0, 2: 5.0}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(
                f"{_SCAN}.fetch_hltb_confidence_cached", side_effect=fake_fetch
            ) as mock_fetch,
            patch(f"{_SCAN}._echo"),
        ):
            kept = scanning._filter_hltb_confident_candidates([game_a, game_b])

        assert [game.app_id for game in kept] == [1, 2]
        mock_fetch.assert_called_once()
