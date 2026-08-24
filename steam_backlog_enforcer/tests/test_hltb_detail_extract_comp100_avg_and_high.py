"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

from typing import Any

from typing_extensions import Self

from steam_backlog_enforcer._hltb_comp_extract import _extract_comp_100_avg_and_high


class _FakeTextResponse:
    """Async context manager mimicking aiohttp response for text."""

    def __init__(self, status: int, text: str = "") -> None:
        """Test init."""
        self.status = status
        self._text = text

    async def __aenter__(self) -> Self:
        """Test aenter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Test aexit."""

    async def text(self) -> str:
        """Test text."""
        return self._text


class TestExtractComp100AvgAndHigh:
    """Tests for _extract_comp_100_avg_and_high."""

    def test_returns_minus_one_for_empty_game_list(self) -> None:
        """Test returns minus one for empty game list."""
        assert _extract_comp_100_avg_and_high({"game": []}) == (-1, -1)

    def test_returns_minus_one_for_non_list_game(self) -> None:
        """Test returns minus one for non list game."""
        assert _extract_comp_100_avg_and_high({"game": "bad"}) == (-1, -1)

    def test_returns_minus_one_when_game0_not_dict(self) -> None:
        """Test returns minus one when game0 not dict."""
        assert _extract_comp_100_avg_and_high({"game": [42]}) == (-1, -1)

    def test_returns_avg_and_high(self) -> None:
        """Test returns avg and high."""
        data: dict[str, Any] = {"game": [{"comp_100": 7200, "comp_100_h": 10800}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == round(7200 / 3600, 2)
        assert high_h == round(10800 / 3600, 2)

    def test_high_falls_back_to_avg_when_zero(self) -> None:
        """Test high falls back to avg when zero."""
        data: dict[str, Any] = {"game": [{"comp_100": 7200, "comp_100_h": 0}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == round(7200 / 3600, 2)
        assert high_h == avg_h

    def test_avg_zero_returns_minus_one_avg(self) -> None:
        """Test avg zero returns minus one avg."""
        data: dict[str, Any] = {"game": [{"comp_100": 0, "comp_100_h": 0}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == -1
        assert high_h == -1
