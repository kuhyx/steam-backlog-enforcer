"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _ensure_completed_rush_data,
    _ensure_rush_data,
    _filter_qualifying_games,
    _format_completion_date,
    _GameTimes,
    _print_pace_scenario,
    _print_player_speed_scenario,
    _print_scenario,
    _print_worst_example,
    _sum_hours,
    cmd_stats,
)
from steam_backlog_enforcer._web_dataset import PaceVsHLTB
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIError

_PKG = "steam_backlog_enforcer._stats"


def _game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=5,
        count_comp=20,
    )


def _unplayable_rating(app_id: int) -> ProtonDBRating:
    return ProtonDBRating(app_id=app_id, tier="borked")


class TestFilterQualifyingGames:
    """Tests for _filter_qualifying_games."""

    def _run(
        self,
        games: list[GameInfo],
        state: State,
        rush_cache: dict[int, float] | None = None,
        leisure_cache: dict[int, float] | None = None,
        game_id_cache: dict[int, int] | None = None,
    ) -> tuple[list[_GameTimes], int, int, int]:
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value=rush_cache or {}),
            patch(
                f"{_PKG}.load_hltb_leisure_100h_cache",
                return_value=leisure_cache or {},
            ),
            patch(
                f"{_PKG}.load_hltb_game_id_cache",
                return_value=game_id_cache or {},
            ),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=[]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value={}),
        ):
            return _filter_qualifying_games(games, state)

    def test_current_app_id_excluded(self) -> None:
        state = State(current_app_id=1)
        g1 = _game(app_id=1)
        g2 = _game(app_id=2)
        qualified, _, _, _ = self._run([g1, g2], state)
        ids = [e.game.app_id for e in qualified]
        assert 1 not in ids
        assert 2 in ids

    def test_no_current_app_id_branch(self) -> None:
        """current_app_id is None — the exclude.add branch is not taken."""
        state = State(current_app_id=None)
        g = _game(app_id=3)
        qualified, _, _, _ = self._run([g], state)
        assert len(qualified) == 1

    def test_finished_app_ids_excluded(self) -> None:
        state = State()
        state.finished_app_ids = [1]
        g1 = _game(app_id=1)
        g2 = _game(app_id=2)
        qualified, _, _, _ = self._run([g1, g2], state)
        assert all(e.game.app_id != 1 for e in qualified)

    def test_complete_games_excluded(self) -> None:
        """Games where is_complete is True are excluded from candidates."""
        state = State()
        complete = _game(app_id=1, total=5, unlocked=5)
        incomplete = _game(app_id=2, total=5, unlocked=0)
        qualified, _, _, _ = self._run([complete, incomplete], state)
        assert len(qualified) == 1
        assert qualified[0].game.app_id == 2

    def test_low_confidence_counts_hltb_skipped(self) -> None:
        state = State()
        g = _game(app_id=1)
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=["low"]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value={}),
        ):
            qualified, hltb_skip, _, _ = _filter_qualifying_games([g], state)
        assert hltb_skip == 1
        assert len(qualified) == 0

    def test_no_candidates_skips_protondb_call(self) -> None:
        """When confidence filters all out, fetch_protondb_ratings is not called."""
        state = State()
        g = _game(app_id=1)
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=["low"]),
            patch(f"{_PKG}.fetch_protondb_ratings") as mock_proton,
        ):
            _filter_qualifying_games([g], state)
        mock_proton.assert_not_called()

    def test_unplayable_rating_counts_linux_skipped(self) -> None:
        state = State()
        g = _game(app_id=1)
        ratings = {1: _unplayable_rating(1)}
        with (
            patch(f"{_PKG}.load_hltb_rush_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_leisure_100h_cache", return_value={}),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
            patch(f"{_PKG}._apply_cached_confidence_to_candidates"),
            patch(f"{_PKG}._refresh_candidate_confidence_batch"),
            patch(f"{_PKG}._confidence_fail_reasons", return_value=[]),
            patch(f"{_PKG}.fetch_protondb_ratings", return_value=ratings),
        ):
            qualified, _, linux_skip, _ = _filter_qualifying_games([g], state)
        assert linux_skip == 1
        assert len(qualified) == 0

    def test_no_data_counts_no_data_skipped(self) -> None:
        """Game with all -1 hours is counted as no_data_skipped."""
        state = State()
        g = _game(app_id=1, hours=-1.0)
        qualified, _, _, no_data_skip = self._run([g], state)
        assert no_data_skip == 1
        assert len(qualified) == 0

    def test_worst_hours_positive_when_completionist_hours_positive(self) -> None:
        state = State()
        g = _game(app_id=1, hours=25.0)
        qualified, _, _, _ = self._run([g], state, rush_cache={1: 10.0})
        assert qualified[0].worst_hours == 25.0

    def test_worst_hours_from_leisure_when_completionist_zero(self) -> None:
        """worst_hours falls back to leisure_100h when completionist_hours is zero."""
        state = State()
        g = _game(app_id=1, hours=0.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 5.0}, leisure_cache={1: 6.0}
        )
        assert qualified[0].worst_hours == 6.0

    def test_worst_hours_is_max_when_leisure_exceeds_completionist(self) -> None:
        """worst_hours is max(completionist, leisure_100h) when leisure is higher."""
        state = State()
        g = _game(app_id=1, hours=25.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 10.0}, leisure_cache={1: 40.0}
        )
        assert qualified[0].worst_hours == 40.0

    def test_worst_hours_negative_when_all_zero(self) -> None:
        """worst_hours = -1 when both completionist_hours and leisure_100h are zero."""
        state = State()
        g = _game(app_id=1, hours=0.0)
        qualified, _, _, _ = self._run([g], state, rush_cache={1: 5.0})
        assert qualified[0].worst_hours == -1

    def test_rush_and_leisure_from_cache(self) -> None:
        state = State()
        g = _game(app_id=1, hours=30.0)
        qualified, _, _, _ = self._run(
            [g], state, rush_cache={1: 12.0}, leisure_cache={1: 40.0}
        )
        assert qualified[0].rush_hours == 12.0
        assert qualified[0].leisure_100h == 40.0

    def test_missing_cache_entry_defaults_to_minus_one(self) -> None:
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state)
        assert qualified[0].rush_hours == -1
        assert qualified[0].leisure_100h == -1

    def test_only_rush_nonzero_qualifies(self) -> None:
        """Game qualifies if only rush_hours is positive (worst <= 0, leisure <= 0)."""
        state = State()
        g = _game(app_id=1, hours=-1.0)
        qualified, _, _, no_data_skip = self._run([g], state, rush_cache={1: 8.0})
        assert no_data_skip == 0
        assert len(qualified) == 1

    def test_game_id_populated_from_cache(self) -> None:
        """hltb_game_id is taken from game_id_cache."""
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state, game_id_cache={1: 57514})
        assert qualified[0].hltb_game_id == 57514

    def test_game_id_defaults_to_zero_when_not_in_cache(self) -> None:
        """hltb_game_id defaults to 0 when not in cache."""
        state = State()
        g = _game(app_id=1, hours=20.0)
        qualified, _, _, _ = self._run([g], state)
        assert qualified[0].hltb_game_id == 0


class TestSumHours:
    """Tests for _sum_hours."""

    def _make_entry(self, worst: float, rush: float, leisure: float) -> _GameTimes:
        return _GameTimes(
            game=_game(), worst_hours=worst, rush_hours=rush, leisure_100h=leisure
        )

    def test_empty_list(self) -> None:
        total, missing = _sum_hours([], "worst_hours")
        assert total == 0.0
        assert missing == 0

    def test_all_positive(self) -> None:
        entries = [
            self._make_entry(10.0, 8.0, 12.0),
            self._make_entry(20.0, 15.0, 25.0),
        ]
        total, missing = _sum_hours(entries, "worst_hours")
        assert total == 30.0
        assert missing == 0

    def test_some_negative(self) -> None:
        entries = [
            self._make_entry(10.0, -1.0, 12.0),
            self._make_entry(-1.0, 8.0, 25.0),
        ]
        total, missing = _sum_hours(entries, "worst_hours")
        assert total == 10.0
        assert missing == 1

    def test_all_negative(self) -> None:
        entries = [self._make_entry(-1.0, -1.0, -1.0)]
        total, missing = _sum_hours(entries, "rush_hours")
        assert total == 0.0
        assert missing == 1


class TestFormatCompletionDate:
    """Tests for _format_completion_date."""

    def test_zero_hours_returns_na(self) -> None:
        assert _format_completion_date(0.0, 4.0) == "N/A"

    def test_negative_hours_returns_na(self) -> None:
        assert _format_completion_date(-5.0, 4.0) == "N/A"

    def test_zero_daily_hours_returns_na(self) -> None:
        assert _format_completion_date(100.0, 0.0) == "N/A"

    def test_negative_daily_hours_returns_na(self) -> None:
        assert _format_completion_date(100.0, -1.0) == "N/A"

    def test_normal_returns_days_and_date(self) -> None:
        result = _format_completion_date(40.0, 4.0)
        # 40 / 4 = 10 days
        assert result.startswith("10 days (")
        assert ")" in result


class TestPrintScenario:
    """Tests for _print_scenario."""

    def test_no_data_prints_no_data_message(self) -> None:
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 0.0, 0, 5)
        assert any("No data available" in s for s in echoed)

    def test_with_data_no_missing(self) -> None:
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 100.0, 0, 5)
        assert any("Total:" in s for s in echoed)
        assert not any("had no data" in s for s in echoed)

    def test_with_data_and_missing(self) -> None:
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_scenario("2. RUSH", 100.0, 2, 5)
        assert any("had no data" in s for s in echoed)


class TestPrintPaceScenario:
    """Tests for _print_pace_scenario."""

    def test_no_start_date(self) -> None:
        state = State()
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("No start date recorded" in s for s in echoed)

    def test_invalid_start_date(self) -> None:
        state = State(enforcement_started_at="not-a-date")
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("Invalid enforcement_started_at" in s for s in echoed)

    def test_no_games_finished(self) -> None:
        started = datetime.now(timezone.utc) - timedelta(days=30)
        state = State(enforcement_started_at=started.isoformat())
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 10, 0)
        assert any("No games finished yet" in s for s in echoed)

    def test_normal_pace(self) -> None:
        started = datetime.now(timezone.utc) - timedelta(days=60)
        state = State(enforcement_started_at=started.isoformat())
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_pace_scenario(state, 5, 3)
        assert any("Pace:" in s for s in echoed)
        assert any("Est. complete:" in s for s in echoed)


class TestCmdStats:
    """Tests for cmd_stats."""

    def _config(self) -> Config:
        return Config(steam_api_key="k", steam_id="i")

    def test_no_snapshot(self) -> None:
        echoed: list[str] = []
        state = State()
        with (
            patch(f"{_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
        ):
            cmd_stats(self._config(), state)
        assert any("No snapshot found" in s for s in echoed)

    def _snapshot_game(self, app_id: int = 1, hours: float = 20.0) -> dict[str, object]:
        return {
            "app_id": app_id,
            "name": f"Game{app_id}",
            "total_achievements": 10,
            "unlocked_achievements": 0,
            "playtime_minutes": 60,
            "completionist_hours": hours,
            "comp_100_count": 5,
            "count_comp": 20,
        }

    def _run_cmd_stats(
        self,
        state: State,
        hltb_skip: int = 0,
        linux_skip: int = 0,
        no_data_skip: int = 0,
    ) -> list[str]:
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], hltb_skip, linux_skip, no_data_skip),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
        ):
            cmd_stats(self._config(), state)
        return echoed

    def test_with_no_current_game(self) -> None:
        state = State()
        echoed = self._run_cmd_stats(state)
        assert any("Qualifying games" in s for s in echoed)
        assert not any("Current game:" in s for s in echoed)

    def test_with_current_game(self) -> None:
        state = State(current_app_id=42, current_game_name="Hollow Knight")
        echoed = self._run_cmd_stats(state)
        assert any("Current game:" in s and "Hollow Knight" in s for s in echoed)

    def test_hltb_skipped_shown(self) -> None:
        state = State()
        echoed = self._run_cmd_stats(state, hltb_skip=3)
        assert any("HLTB-skipped" in s for s in echoed)

    def test_linux_skipped_shown(self) -> None:
        state = State()
        echoed = self._run_cmd_stats(state, linux_skip=2)
        assert any("Linux-skipped" in s for s in echoed)

    def test_no_data_skipped_shown(self) -> None:
        state = State()
        echoed = self._run_cmd_stats(state, no_data_skip=1)
        assert any("No-data-skipped" in s for s in echoed)

    def test_zero_skips_not_shown(self) -> None:
        state = State()
        echoed = self._run_cmd_stats(state)
        assert not any("HLTB-skipped" in s for s in echoed)
        assert not any("Linux-skipped" in s for s in echoed)
        assert not any("No-data-skipped" in s for s in echoed)

    def test_finished_games_count_uses_snapshot_complete(self) -> None:
        """'Finished games' count uses snapshot is_complete, not finished_app_ids."""
        state = State()
        # finished_app_ids has 1 entry, but snapshot has 2 complete games — count = 2.
        state.finished_app_ids = [99]
        snapshot_complete = {
            **self._snapshot_game(app_id=2),
            "unlocked_achievements": 10,
        }
        snapshot = [self._snapshot_game(app_id=1), snapshot_complete]
        game = GameInfo.from_snapshot(self._snapshot_game())
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
        ):
            cmd_stats(self._config(), state)
        assert any("Finished games" in s and "1" in s for s in echoed)

    def test_detail_data_complete_message_shown(self) -> None:
        """'Detail data: ...' shown when all qualifying games have rush hours."""
        state = State()
        echoed = self._run_cmd_stats(state)
        # entry has rush_hours=15.0 > 0, so missing_rush_final == 0 and total_q == 1
        assert any("Detail data" in s for s in echoed)

    def test_note_missing_rush_shown_when_rush_absent(self) -> None:
        """'Note: X games still missing...' shown when rush_hours <= 0 after fetch."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=-1.0, leisure_100h=-1.0
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert any("still missing" in s for s in echoed)

    def test_no_detail_message_when_no_qualifying_games(self) -> None:
        """Neither 'Note' nor 'Detail data' shown when qualified list is empty."""
        state = State()
        snapshot = [self._snapshot_game()]
        echoed: list[str] = []
        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert not any("Detail data" in s for s in echoed)
        assert not any("still missing" in s for s in echoed)

    def test_refilter_called_when_ensure_rush_data_returns_true(self) -> None:
        """_filter_qualifying_games called twice when _ensure_rush_data returns True."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        filter_calls: list[int] = []

        def count_filter(
            _games: object, _state: object
        ) -> tuple[list[_GameTimes], int, int, int]:
            filter_calls.append(1)
            return [entry], 0, 0, 0

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(f"{_PKG}._filter_qualifying_games", side_effect=count_filter),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._ensure_rush_data", return_value=True),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert len(filter_calls) == 2

    def test_games_done_since_start_passed_to_pace(self) -> None:
        """_print_pace_scenario gets only games completed after started_at."""
        from datetime import datetime, timezone

        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        state = State(enforcement_started_at=started.isoformat())

        after_ts = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
        before_ts = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())

        def _ach(ts: int) -> dict[str, object]:
            return {
                "api_name": "A",
                "display_name": "A",
                "achieved": True,
                "unlock_time": ts,
            }

        # app_id=2: completed AFTER enforcement start → should count
        snapshot_after = {
            **self._snapshot_game(app_id=2),
            "unlocked_achievements": 10,
            "achievements": [_ach(after_ts)] * 10,
        }
        # app_id=3: completed BEFORE enforcement start → should NOT count
        snapshot_before = {
            **self._snapshot_game(app_id=3),
            "unlocked_achievements": 10,
            "achievements": [_ach(before_ts)] * 10,
        }
        snapshot = [self._snapshot_game(app_id=1), snapshot_after, snapshot_before]
        game = GameInfo.from_snapshot(self._snapshot_game())
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        captured: dict[str, int] = {}

        def capture_pace(_state: object, _remaining: object, games_done: int) -> None:
            captured["games_done"] = games_done

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}._print_player_speed_scenario"),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario", side_effect=capture_pace),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert captured["games_done"] == 1  # only the post-start game

    def test_player_speed_scenario_called_with_pace_and_totals(self) -> None:
        """_print_player_speed_scenario receives pace, rush_total, and leisure_total."""
        state = State()
        snapshot = [self._snapshot_game()]
        game = GameInfo.from_snapshot(snapshot[0])
        entry = _GameTimes(
            game=game, worst_hours=20.0, rush_hours=15.0, leisure_100h=25.0
        )
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.1,
            ratio_vs_leisure=0.4,
            interpolation_t=0.05,
            player_style="rush_to_leisure",
        )
        captured: dict[str, object] = {}

        def capture_player_speed(p: object, rush: float, leisure: float) -> None:
            captured["pace"] = p
            captured["rush"] = rush
            captured["leisure"] = leisure

        with (
            patch(f"{_PKG}.load_snapshot", return_value=snapshot),
            patch(
                f"{_PKG}._filter_qualifying_games",
                return_value=([entry], 0, 0, 0),
            ),
            patch(f"{_PKG}._ensure_completed_rush_data", return_value=False),
            patch(f"{_PKG}.compute_pace_vs_hltb", return_value=pace),
            patch(
                f"{_PKG}._print_player_speed_scenario",
                side_effect=capture_player_speed,
            ),
            patch(f"{_PKG}._echo"),
            patch(f"{_PKG}._print_pace_scenario"),
            patch(f"{_PKG}._print_scenario"),
            patch(f"{_PKG}._print_worst_example"),
        ):
            cmd_stats(self._config(), state)
        assert captured["pace"] is pace
        assert captured["rush"] == 15.0
        assert captured["leisure"] == 25.0


class TestEnsureRushData:
    """Tests for _ensure_rush_data."""

    def _entry(self, rush: float) -> _GameTimes:
        return _GameTimes(
            game=_game(), worst_hours=10.0, rush_hours=rush, leisure_100h=5.0
        )

    def test_empty_qualified_returns_false(self) -> None:
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_rush_data([])
        assert result is False
        mock_fetch.assert_not_called()

    def test_all_have_rush_returns_false(self) -> None:
        entries = [self._entry(10.0), self._entry(5.0)]
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_rush_data(entries)
        assert result is False
        mock_fetch.assert_not_called()

    def test_missing_rush_fetches_and_returns_true(self) -> None:
        entries = [self._entry(-1.0)]
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch,
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_rush_data(entries)
        assert result is True
        mock_fetch.assert_called_once()


class TestEnsureCompletedRushData:
    """Tests for _ensure_completed_rush_data."""

    def _complete(self, app_id: int = 1, playtime: int = 600) -> GameInfo:
        return GameInfo(
            app_id=app_id,
            name="Done",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=playtime,
            completionist_hours=0.0,
            comp_100_count=5,
            count_comp=20,
        )

    def test_no_complete_games_returns_false_without_fetch(self) -> None:
        incomplete = _game(app_id=1, total=10, unlocked=0)
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_completed_rush_data([incomplete])
        assert result is False
        mock_fetch.assert_not_called()

    def test_complete_game_with_zero_playtime_excluded(self) -> None:
        """Games with playtime_minutes=0 are skipped (no calibration value)."""
        no_play = self._complete(playtime=0)
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_completed_rush_data([no_play])
        assert result is False
        mock_fetch.assert_not_called()

    def test_complete_game_with_playtime_fetches(self) -> None:
        game = self._complete()
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=1) as mock_fetch,
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_completed_rush_data([game])
        assert result is True
        mock_fetch.assert_called_once_with([(1, "Done")])

    def test_fetch_returns_zero_means_no_new_data(self) -> None:
        """When fetch_hltb_detail_missing returns 0, return False (all cached)."""
        game = self._complete()
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=0),
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_completed_rush_data([game])
        assert result is False


class TestPrintPlayerSpeedScenario:
    """Tests for _print_player_speed_scenario — 100 % branch coverage."""

    def _echoed(
        self,
        pace: PaceVsHLTB | None,
        rush: float = 100.0,
        leisure: float = 200.0,
    ) -> list[str]:
        out: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: out.append(a[0])):
            _print_player_speed_scenario(pace, rush, leisure)
        return out

    def test_none_pace_shows_no_calibration_message(self) -> None:
        echoed = self._echoed(None)
        assert any("No calibration data" in s for s in echoed)

    def test_zero_calibration_count_shows_no_calibration_message(self) -> None:
        pace = PaceVsHLTB(
            calibration_count=0,
            ratio_vs_rush=-1.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("No calibration data" in s for s in echoed)

    def test_ratio_vs_rush_shown_when_positive(self) -> None:
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("rush pace" in s for s in echoed)

    def test_ratio_vs_leisure_shown_when_positive(self) -> None:
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=0.5,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace)
        assert any("leisure pace" in s for s in echoed)

    def test_interpolation_t_shown_when_not_minus_one(self) -> None:
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.05,
            ratio_vs_leisure=0.5,
            interpolation_t=0.1,
            player_style="rush_to_leisure",
        )
        echoed = self._echoed(pace)
        assert any("Interpolation t" in s for s in echoed)

    def test_estimate_uses_interpolation_when_available(self) -> None:
        # rush=100, leisure=200, t=0.5 → est=150
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.5,
            ratio_vs_leisure=0.5,
            interpolation_t=0.5,
            player_style="rush_to_leisure",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=200.0)
        assert any("150" in s for s in echoed)

    def test_estimate_falls_back_to_ratio_when_no_interpolation(self) -> None:
        # interpolation_t=-1, ratio_vs_rush=2.0, rush=100 → est=200
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=2.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=0.0)
        assert any("200" in s for s in echoed)

    def test_no_estimate_when_both_methods_unavailable(self) -> None:
        """No 'Estimated backlog total' line when t=-1 and ratio=-1."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=-1.0,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=100.0, leisure=0.0)
        assert not any("Estimated backlog total" in s for s in echoed)

    def test_no_estimate_when_rush_total_zero_and_no_interpolation(self) -> None:
        """No estimate line when rush_total=0 and interpolation_t=-1."""
        pace = PaceVsHLTB(
            calibration_count=5,
            ratio_vs_rush=1.5,
            ratio_vs_leisure=-1.0,
            interpolation_t=-1.0,
            player_style="unknown",
        )
        echoed = self._echoed(pace, rush=0.0, leisure=0.0)
        assert not any("Estimated backlog total" in s for s in echoed)


class TestPrintWorstExample:
    """Tests for _print_worst_example."""

    def test_empty_list_does_nothing(self) -> None:
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([])
        assert echoed == []

    def test_example_with_rush_and_leisure(self) -> None:
        entry = _GameTimes(
            game=_game(name="Portal"),
            worst_hours=15.0,
            rush_hours=5.0,
            leisure_100h=20.0,
            hltb_game_id=99999,
        )
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([entry])
        assert any("Portal" in s for s in echoed)
        assert any("Rush" in s for s in echoed)
        assert any("Leisure" in s for s in echoed)

    def test_example_without_rush(self) -> None:
        entry = _GameTimes(
            game=_game(name="X"),
            worst_hours=15.0,
            rush_hours=-1.0,
            leisure_100h=20.0,
            hltb_game_id=99999,
        )
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([entry])
        assert not any("Rush" in s for s in echoed)
        assert any("Leisure" in s for s in echoed)

    def test_example_without_leisure(self) -> None:
        entry = _GameTimes(
            game=_game(name="Y"),
            worst_hours=15.0,
            rush_hours=5.0,
            leisure_100h=-1.0,
            hltb_game_id=99999,
        )
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([entry])
        assert any("Rush" in s for s in echoed)
        assert not any("Leisure" in s for s in echoed)

    def test_hltb_search_url_shown_when_lookup_finds_nothing(self) -> None:
        """Falls back to search URL when hltb_game_id is 0 and lookup finds nothing."""
        entry = _GameTimes(
            game=_game(name="Portal 2"),
            worst_hours=15.0,
            rush_hours=-1.0,
            leisure_100h=-1.0,
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=0),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={}),
        ):
            _print_worst_example([entry])
        assert any("howlongtobeat.com" in s and "Portal+2" in s for s in echoed)

    def test_hltb_direct_link_shown_after_on_demand_lookup(self) -> None:
        """Direct link shown when on-demand lookup successfully finds the game ID."""
        entry = _GameTimes(
            game=_game(app_id=111, name="Portal 2"),
            worst_hours=15.0,
            rush_hours=-1.0,
            leisure_100h=-1.0,
        )
        echoed: list[str] = []
        with (
            patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])),
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=0),
            patch(f"{_PKG}.load_hltb_game_id_cache", return_value={111: 42000}),
        ):
            _print_worst_example([entry])
        assert any("howlongtobeat.com/game/42000" in s for s in echoed)
        assert not any("?q=" in s for s in echoed)

    def test_hltb_direct_link_shown_when_game_id_known(self) -> None:
        """Direct HLTB game link shown when hltb_game_id is populated."""
        entry = _GameTimes(
            game=_game(name="Devil May Cry 5"),
            worst_hours=186.0,
            rush_hours=50.0,
            leisure_100h=186.0,
            hltb_game_id=57514,
        )
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([entry])
        assert any("howlongtobeat.com/game/57514" in s for s in echoed)
        assert not any("?q=" in s for s in echoed)

    def test_entries_with_zero_worst_hours_excluded_from_examples(self) -> None:
        """Games with worst_hours <= 0 are not selected as the example."""
        bad = _GameTimes(
            game=_game(name="Skip"), worst_hours=0.0, rush_hours=-1.0, leisure_100h=-1.0
        )
        good = _GameTimes(
            game=_game(name="Pick"),
            worst_hours=10.0,
            rush_hours=-1.0,
            leisure_100h=-1.0,
            hltb_game_id=99999,
        )
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([bad, good])
        assert any("Pick" in s for s in echoed)
        assert not any("Skip" in s for s in echoed)


class TestRefreshRecentlyPlayedCompletions:
    """Tests for _refresh_recently_played_completions."""

    def test_oserror_on_stat_returns_games_unchanged(self) -> None:
        games = [GameInfo(1, "G", 10, 0, 60)]
        with patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf:
            mock_sf.stat.side_effect = OSError("no file")
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_steam_api_error_returns_games_unchanged(self) -> None:
        """A SteamAPIError while fetching owned games is swallowed."""
        games = [GameInfo(1, "G", 10, 0, 60)]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.side_effect = SteamAPIError(
                "api down"
            )
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_no_recently_played_returns_games_unchanged(self) -> None:
        games = [GameInfo(1, "G", 10, 0, 60)]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 500_000}
            ]
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_recently_played_game_is_refreshed(self) -> None:
        from steam_backlog_enforcer._stats import _refresh_recently_played_completions
        from steam_backlog_enforcer.steam_api import AchievementInfo

        game = GameInfo(1, "G", 5, 0, 60)
        new_achievements = [
            AchievementInfo("a1", "A1", achieved=True, unlock_time=1_500_001),
            AchievementInfo("a2", "A2", achieved=True, unlock_time=1_500_002),
            AchievementInfo("a3", "A3", achieved=False, unlock_time=0),
            AchievementInfo("a4", "A4", achieved=False, unlock_time=0),
            AchievementInfo("a5", "A5", achieved=False, unlock_time=0),
        ]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
            patch(f"{_PKG}._echo"),
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 1_500_000}
            ]
            mock_cls.return_value.get_achievement_details.return_value = (
                new_achievements
            )
            result = _refresh_recently_played_completions([game], Config())
        refreshed = next(g for g in result if g.app_id == 1)
        assert refreshed.unlocked_achievements == 2

    def test_get_achievement_details_empty_keeps_old_game(self) -> None:
        from steam_backlog_enforcer._stats import _refresh_recently_played_completions

        game = GameInfo(1, "G", 5, 3, 60)
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
            patch(f"{_PKG}._echo"),
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 1_500_000}
            ]
            mock_cls.return_value.get_achievement_details.return_value = []
            result = _refresh_recently_played_completions([game], Config())
        refreshed = next(g for g in result if g.app_id == 1)
        assert refreshed.unlocked_achievements == 3
