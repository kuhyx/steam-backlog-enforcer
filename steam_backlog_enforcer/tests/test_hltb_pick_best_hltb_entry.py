"""Tests for hltb module."""

from __future__ import annotations

from typing import Any

from steam_backlog_enforcer._hltb_search import (
    _pick_best_hltb_entry,
)


class TestPickBestHltbEntry:
    """Tests for _pick_best_hltb_entry."""

    def test_empty(self) -> None:
        """Test empty."""
        assert _pick_best_hltb_entry("game", []) is None

    def test_single(self) -> None:
        """Test single."""
        entry: dict[str, Any] = {"game_name": "Game", "comp_100": 3600}
        result = _pick_best_hltb_entry("Game", [(entry, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "Game"

    def test_prefers_full_edition_colon(self) -> None:
        """Test prefers full edition colon."""
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {
            "game_name": "FAITH: The Unholy Trinity",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_prefers_full_edition_dash(self) -> None:
        """Test prefers full edition dash."""
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {"game_name": "FAITH - Complete", "comp_100": 7200}
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH - Complete"

    def test_falls_back_to_highest_similarity(self) -> None:
        """Test falls back to highest similarity."""
        a: dict[str, Any] = {"game_name": "ABC", "comp_100": 3600}
        b: dict[str, Any] = {"game_name": "DEF", "comp_100": 7200}
        result = _pick_best_hltb_entry("ABC", [(a, 0.9), (b, 0.7)])
        assert result is not None
        assert result[1] == 0.9

    def test_prefers_non_dlc_when_available(self) -> None:
        """Test prefers non dlc when available."""
        base: dict[str, Any] = {
            "game_name": "Helltaker",
            "game_type": "game",
            "comp_100": 6846,
        }
        dlc: dict[str, Any] = {
            "game_name": "Helltaker - Bonus Chapter: Examtaker",
            "game_type": "dlc",
            "comp_100": 4075,
        }
        result = _pick_best_hltb_entry("Helltaker", [(dlc, 0.95), (base, 0.8)])
        assert result is not None
        assert result[0]["game_type"] == "game"

    def test_skips_prologue_subset(self) -> None:
        """A '- Prologue' entry should not beat the full game."""
        full: dict[str, Any] = {
            "game_name": "A Space For The Unbound",
            "comp_100": 45000,
        }
        prologue: dict[str, Any] = {
            "game_name": "A Space for the Unbound - Prologue",
            "comp_100": 1680,
        }
        result = _pick_best_hltb_entry(
            "A Space for the Unbound",
            [(prologue, 0.9), (full, 0.95)],
        )
        assert result is not None
        assert result[0]["game_name"] == "A Space For The Unbound"

    def test_skips_demo_subset(self) -> None:
        """A ': Demo' entry should not beat the full game."""
        full: dict[str, Any] = {"game_name": "MyGame", "comp_100": 36000}
        demo: dict[str, Any] = {"game_name": "MyGame: Demo", "comp_100": 1800}
        result = _pick_best_hltb_entry("MyGame", [(demo, 0.9), (full, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "MyGame"

    def test_still_prefers_full_edition_over_demo(self) -> None:
        """A ': Full Edition' entry should still be preferred (not a subset)."""
        short: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {
            "game_name": "FAITH: The Unholy Trinity",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry("FAITH", [(short, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_exact_match_beats_unrelated_subtitle(self) -> None:
        """Exact name with more hours wins over an unrelated subtitle entry.

        'Killing Floor: Toy Master' (1.2 h) must NOT beat 'Killing Floor'
        (296 h) just because it starts with 'Killing Floor:'.
        """
        base: dict[str, Any] = {
            "game_name": "Killing Floor",
            "comp_100": 1065600,  # 296 h
        }
        spinoff: dict[str, Any] = {
            "game_name": "Killing Floor: Toy Master",
            "comp_100": 4320,  # 1.2 h
        }
        result = _pick_best_hltb_entry("Killing Floor", [(spinoff, 0.7), (base, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "Killing Floor"
