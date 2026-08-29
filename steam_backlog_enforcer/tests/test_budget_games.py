"""Tests for _budget_games — 100% branch coverage.

The invariant under test is that the parts never claim more than the whole:
`per_game` is a subset of `seconds`, and the difference is *rendered* as
Unattributed rather than stored or hidden.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _budget_games as games_mod
from steam_backlog_enforcer._budget_games import history_view, today_games
from steam_backlog_enforcer._playtime_history import HistoryDay
from steam_backlog_enforcer._playtime_state import PlaytimeState

if TYPE_CHECKING:
    from collections.abc import Iterator

_LABELS = {"app:1": "One", "app:2": "Two", "proc:osu-lazer": "osu!lazer"}


@pytest.fixture(autouse=True)
def _labels() -> Iterator[None]:
    """Serve the persisted label map without touching the history file."""
    with patch.object(games_mod, "load_labels", return_value=_LABELS):
        yield


class TestTodayGames:
    """Today's list is uncapped: it is text, not six colours."""

    def test_orders_largest_first_with_shares(self) -> None:
        state = PlaytimeState(
            day_key="2026-08-29",
            seconds=300.0,
            per_game={"app:1": 100.0, "app:2": 200.0},
        )
        assert today_games(state) == [
            {"key": "app:2", "label": "Two", "seconds": 200.0, "fraction": 0.6667},
            {"key": "app:1", "label": "One", "seconds": 100.0, "fraction": 0.3333},
        ]

    def test_surfaces_the_unattributed_remainder_last(self) -> None:
        state = PlaytimeState(
            day_key="2026-08-29", seconds=300.0, per_game={"app:1": 200.0}
        )
        assert today_games(state)[-1] == {
            "key": "unattributed",
            "label": "Unattributed",
            "seconds": 100.0,
            "fraction": 0.3333,
        }

    def test_no_remainder_when_fully_attributed(self) -> None:
        state = PlaytimeState(
            day_key="2026-08-29", seconds=100.0, per_game={"app:1": 100.0}
        )
        assert [g["key"] for g in today_games(state)] == ["app:1"]

    def test_a_day_that_billed_nothing_lists_nothing(self) -> None:
        assert today_games(PlaytimeState(day_key="2026-08-29")) == []

    def test_drift_below_zero_cannot_produce_a_negative_slice(self) -> None:
        """Proportional refunds drift by fractions of a second."""
        state = PlaytimeState(
            day_key="2026-08-29", seconds=100.0, per_game={"app:1": 100.5}
        )
        assert [g["key"] for g in today_games(state)] == ["app:1"]

    def test_falls_back_to_a_live_lookup_for_an_unstored_key(self) -> None:
        """Today's keys reach the history file only after the first flush."""
        state = PlaytimeState(
            day_key="2026-08-29", seconds=10.0, per_game={"launcher:lutris": 10.0}
        )
        assert today_games(state)[0]["label"] == "lutris"


class TestHistoryView:
    """The window is capped at the six hues the shared ramp actually has."""

    def test_orders_segments_by_the_shared_legend(self) -> None:
        days = [
            HistoryDay("2026-08-27", 300.0, {"app:1": 100.0, "app:2": 200.0}),
            HistoryDay("2026-08-28", 50.0, {"app:1": 50.0}),
        ]
        # Ranked by window total (app:2 200s, app:1 150s), not per-day, so a
        # game keeps one colour and one band position across every bar.
        plotted, legend = history_view(days)
        assert [e["key"] for e in legend] == ["app:2", "app:1"]
        assert plotted[0]["segments"] == [
            {"key": "app:2", "seconds": 200.0},
            {"key": "app:1", "seconds": 100.0},
        ]
        assert plotted[1]["segments"] == [{"key": "app:1", "seconds": 50.0}]

    def test_folds_the_seventh_game_into_other(self) -> None:
        games = {f"app:{i}": float(100 - i) for i in range(8)}
        plotted, legend = history_view(
            [HistoryDay("2026-08-28", sum(games.values()), games)]
        )
        assert [e["key"] for e in legend][-1] == "other"
        assert len([e for e in legend if e["key"] != "other"]) == 6
        # Folding must conserve time, not drop it.
        assert sum(s["seconds"] for s in plotted[0]["segments"]) == sum(games.values())

    def test_a_legacy_day_is_entirely_unattributed(self) -> None:
        """Schema-1 days stored a bare total and never had a breakdown."""
        plotted, legend = history_view([HistoryDay("2026-08-24", 1200.0, {})])
        assert plotted[0]["segments"] == [{"key": "unattributed", "seconds": 1200.0}]
        assert legend == [{"key": "unattributed", "label": "Unattributed"}]

    def test_a_day_with_no_time_has_no_segments(self) -> None:
        plotted, legend = history_view([HistoryDay("2026-08-24", 0.0, {})])
        assert plotted[0]["segments"] == []
        assert legend == []

    def test_empty_window(self) -> None:
        assert history_view([]) == ([], [])
