"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _GameTimes,
    _print_worst_example,
)
from steam_backlog_enforcer.tests._stats_games import make_game

_PKG = "steam_backlog_enforcer._stats_display"


class TestPrintWorstExample:
    """Tests for _print_worst_example."""

    def test_empty_list_does_nothing(self) -> None:
        """Test empty list does nothing."""
        echoed: list[str] = []
        with patch(f"{_PKG}._echo", side_effect=lambda *a, **_: echoed.append(a[0])):
            _print_worst_example([])
        assert echoed == []

    def test_example_with_rush_and_leisure(self) -> None:
        """Test example with rush and leisure."""
        entry = _GameTimes(
            game=make_game(name="Portal"),
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
        """Test example without rush."""
        entry = _GameTimes(
            game=make_game(name="X"),
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
        """Test example without leisure."""
        entry = _GameTimes(
            game=make_game(name="Y"),
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
            game=make_game(name="Portal 2"),
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
            game=make_game(app_id=111, name="Portal 2"),
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
            game=make_game(name="Devil May Cry 5"),
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
            game=make_game(name="Skip"),
            worst_hours=0.0,
            rush_hours=-1.0,
            leisure_100h=-1.0,
        )
        good = _GameTimes(
            game=make_game(name="Pick"),
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
