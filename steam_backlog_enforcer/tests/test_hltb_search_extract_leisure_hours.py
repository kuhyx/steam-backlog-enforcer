"""Tests for HLTB search entry picking, page parsing, and leisure extraction."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from typing_extensions import Self

from steam_backlog_enforcer._hltb_detail import _extract_leisure_hours
from steam_backlog_enforcer._hltb_matching import _build_search_variants


class _FakeResponse:
    """Async context manager mimicking aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        """Test init."""
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        """Test aenter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Test aexit."""

    async def json(self) -> dict[str, Any]:
        """Test json."""
        return self._json_data


def _make_session(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.post.return_value = resp
    return session


class TestExtractLeisureHours:
    """Tests for _extract_leisure_hours."""

    def test_leisure_time_only(self) -> None:
        """Test leisure time only."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(21243 / 3600, 2)

    def test_leisure_with_dlc(self) -> None:
        """Test leisure with dlc."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 12298},
                {"game_type": "dlc", "comp_100": 3600},
            ],
        }
        assert _extract_leisure_hours(data) == round((21243 + 12298 + 3600) / 3600, 2)

    def test_fallback_to_comp_100(self) -> None:
        """Test fallback to comp 100."""
        data: dict[str, Any] = {
            "game": [{"comp_100": 7200}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(7200 / 3600, 2)

    def test_no_game_data(self) -> None:
        """Test no game data."""
        assert _extract_leisure_hours({"game": [], "relationships": []}) == -1

    def test_zero_leisure(self) -> None:
        """Test zero leisure."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_no_game_key(self) -> None:
        """Test no game key."""
        assert _extract_leisure_hours({"relationships": []}) == -1

    def test_non_dlc_relationship_ignored(self) -> None:
        """Test non dlc relationship ignored."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "game", "comp_100": 9999},
                {"game_type": "dlc", "comp_100": 1800},
            ],
        }
        assert _extract_leisure_hours(data) == round((3600 + 1800) / 3600, 2)

    def test_dlc_zero_comp_100_skipped(self) -> None:
        """Test dlc zero comp 100 skipped."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 0},
            ],
        }
        assert _extract_leisure_hours(data) == round(3600 / 3600, 2)

    def test_negative_leisure(self) -> None:
        """Test negative leisure."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": -1, "comp_100": -1}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_string_numeric_fields(self) -> None:
        """Test string numeric fields."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "7200", "comp_100": "3600"}],
            "relationships": [{"game_type": "dlc", "game_id": "1", "comp_100": "1800"}],
        }
        assert _extract_leisure_hours(data) == round((7200 + 1800) / 3600, 2)

    def test_bad_string_falls_back_to_comp_100(self) -> None:
        """Test bad string falls back to comp 100."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "bad", "comp_100": "3600"}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == 1.0

    def test_relationships_not_list(self) -> None:
        """Test relationships not list."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": "not-a-list",
        }
        assert _extract_leisure_hours(data) == 1.0


class TestBuildSearchVariants:
    """Tests for _build_search_variants."""

    def test_subtitle_with_edition_strips_edition_from_subtitle_part(self) -> None:
        # "Rocksmith 2014 Edition - Remastered" → no_subtitle = "Rocksmith 2014 Edition"
        # (which != base), so lines 201-202 also add "Rocksmith" and "Rocksmith 2014"
        """Test subtitle with edition strips edition from subtitle part."""
        variants = _build_search_variants("Rocksmith 2014 Edition - Remastered")
        assert "Rocksmith 2014 Edition" in variants
        assert "Rocksmith 2014" in variants
        assert "Rocksmith" in variants

    def test_no_subtitle_skips_edition_strip(self) -> None:
        # No " - " → no_subtitle == base → lines 201-202 are not executed
        """Test no subtitle skips edition strip."""
        variants = _build_search_variants("Portal 2")
        assert "Portal 2" in variants
