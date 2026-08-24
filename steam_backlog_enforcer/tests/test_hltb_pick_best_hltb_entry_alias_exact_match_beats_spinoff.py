"""Tests for hltb module."""

from __future__ import annotations

from typing import Any

from steam_backlog_enforcer._hltb_search_api import _pick_best_hltb_entry


class TestPickBestHltbEntryGroup2:
    """Tests for _pick_best_hltb_entry."""

    def test_alias_exact_match_beats_spinoff(self) -> None:
        """Base game found via game_alias beats a spinoff with matching prefix.

        When HLTB renames a game (e.g. 'Needy Streamer Overload' ->
        'NEEDY GIRL OVERDOSE'), the old name lives in game_alias.  A spinoff
        like 'Needy Streamer Overload: Typing of The Net' must NOT be
        preferred just because its game_name starts with the search term.
        """
        base: dict[str, Any] = {
            "game_name": "NEEDY GIRL OVERDOSE",
            "game_alias": "Needy Streamer Overload",
            "comp_100": 43200,  # 12 h
        }
        spinoff: dict[str, Any] = {
            "game_name": "Needy Streamer Overload: Typing of The Net",
            "comp_100": 3600,  # 1 h
        }
        result = _pick_best_hltb_entry(
            "NEEDY STREAMER OVERLOAD",
            [(spinoff, 0.7), (base, 0.9)],
        )
        assert result is not None
        assert result[0]["game_name"] == "NEEDY GIRL OVERDOSE"

    def test_exact_match_beats_different_subtitled_game(self) -> None:
        """Exact 'Timberman' (26.5 h) must beat 'Timberman: The Big Adventure' (2 h).

        Unlike FAITH where the short name is a demo, here the short name
        is the real full game and the subtitled entry is a different, shorter
        game.  The exact match should win because it has more hours.
        """
        base: dict[str, Any] = {
            "game_name": "Timberman",
            "comp_100": 95400,  # 26.5 h
        }
        other: dict[str, Any] = {
            "game_name": "Timberman: The Big Adventure",
            "comp_100": 7200,  # 2 h
        }
        timberman_vs: dict[str, Any] = {
            "game_name": "Timberman VS",
            "comp_100": 23400,  # 6.5 h
        }
        result = _pick_best_hltb_entry(
            "Timberman",
            [(other, 0.49), (timberman_vs, 0.86), (base, 1.0)],
        )
        assert result is not None
        assert result[0]["game_name"] == "Timberman"

    def test_exact_match_wins_even_when_extended_appears_first(self) -> None:
        """Exact match wins regardless of candidate ordering."""
        base: dict[str, Any] = {
            "game_name": "Timberman",
            "comp_100": 95400,  # 26.5 h
        }
        other: dict[str, Any] = {
            "game_name": "Timberman: The Big Adventure",
            "comp_100": 7200,  # 2 h
        }
        # Extended entry appears first in the list.
        result = _pick_best_hltb_entry(
            "Timberman",
            [(other, 0.49), (base, 1.0)],
        )
        assert result is not None
        assert result[0]["game_name"] == "Timberman"

    def test_exact_only_no_extended(self) -> None:
        """Exact match returned when no extended entries exist at all."""
        exact: dict[str, Any] = {
            "game_name": "Celeste",
            "comp_100": 180000,  # 50 h
        }
        unrelated: dict[str, Any] = {
            "game_name": "Unrelated Game",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry(
            "Celeste",
            [(exact, 1.0), (unrelated, 0.6)],
        )
        assert result is not None
        assert result[0]["game_name"] == "Celeste"

    def test_no_exact_no_extended_falls_back(self) -> None:
        """When no exact or extended match exists, fall to highest similarity."""
        a: dict[str, Any] = {"game_name": "FooBar", "comp_100": 3600}
        b: dict[str, Any] = {"game_name": "FooBaz", "comp_100": 7200}
        result = _pick_best_hltb_entry("Foo", [(a, 0.7), (b, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FooBaz"

    def test_extended_only_no_exact(self) -> None:
        """Extended entry returned when no exact name match exists."""
        extended: dict[str, Any] = {
            "game_name": "Neon: Ultimate Edition",
            "comp_100": 36000,
        }
        unrelated: dict[str, Any] = {
            "game_name": "Neon Lights",
            "comp_100": 3600,
        }
        result = _pick_best_hltb_entry(
            "Neon",
            [(extended, 0.6), (unrelated, 0.7)],
        )
        assert result is not None
        assert result[0]["game_name"] == "Neon: Ultimate Edition"
