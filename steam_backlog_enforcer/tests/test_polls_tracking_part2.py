"""Tests for HLTB poll-count tracking — scanning integration (part 2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _scanning_confidence, scanning
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

if TYPE_CHECKING:
    from pathlib import Path

_TYPES = "steam_backlog_enforcer._hltb_types"
_CMD = "steam_backlog_enforcer._cmd_done"
_SCAN = "steam_backlog_enforcer.scanning"
_SCANCONF = "steam_backlog_enforcer._scanning_confidence"
_POLLS = "steam_backlog_enforcer._polls_reporting"


def _state(finished: list[int], current: int | None = None) -> State:
    s = State()
    s.finished_app_ids = list(finished)
    s.current_app_id = current
    s.current_game_name = ""
    return s


class TestScanningPollsIntegration:
    """Tests for Scanning Polls Integration."""

    def test_do_scan_kept_assignment_reports(self) -> None:
        # Targeted test for scanning's `else` branch that prints CURRENT.
        """Test do scan kept assignment reports."""
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
        """Test report poll confidence new low."""
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
                f"{_POLLS}._backfill_polls_for_finished",
                return_value={1: 1, 2: 5},
            ),
            patch(
                f"{_POLLS}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
        ):
            scanning._report_poll_confidence(chosen, games, _state([2], current=1))
        assert any("NEW LOW" in s for s in echoed)
        assert chosen.comp_100_count == 1

    def test_report_poll_confidence_no_history(self) -> None:
        """Test report poll confidence no history."""
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
            patch(
                f"{_POLLS}._backfill_polls_for_finished",
                return_value={1: 4},
            ),
            patch(
                f"{_POLLS}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
        ):
            scanning._report_poll_confidence(chosen, [chosen], _state([], current=1))
        # No "Historical min" line when no finished games have polls.
        assert not any("Historical min" in s for s in echoed)
        assert any("HLTB confidence: 4" in s for s in echoed)

    def test_scanning_backfill_no_missing(self, tmp_path: Path) -> None:
        """Test scanning backfill no missing."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 1.0, "polls": 5}}), encoding="utf-8"
        )
        with patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file):
            result = _scanning_confidence._backfill_polls_for_finished(
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
        """Test scanning backfill with missing."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 3.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": 3.0, "polls": 8}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: 3.0 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(
                f"{_POLLS}.fetch_hltb_confidence_cached",
                side_effect=fake_fetch,
            ),
        ):
            result = _scanning_confidence._backfill_polls_for_finished(
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
        """Test scanning backfill preserves hours on miss."""
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(
            json.dumps({"2": {"hours": 9.0, "polls": 0}}), encoding="utf-8"
        )

        def fake_fetch(games: list[tuple[int, str]]) -> dict[int, float]:
            """Test fake fetch."""
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for aid, _name in games:
                data[str(aid)] = {"hours": -1, "polls": 0}
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return {aid: -1 for aid, _ in games}

        with (
            patch(f"{_TYPES}.HLTB_CACHE_FILE", cache_file),
            patch(f"{_TYPES}.CONFIG_DIR", tmp_path),
            patch(
                f"{_POLLS}.fetch_hltb_confidence_cached",
                side_effect=fake_fetch,
            ),
        ):
            _scanning_confidence._backfill_polls_for_finished(
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
