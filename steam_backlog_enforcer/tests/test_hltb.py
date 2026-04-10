"""Tests for hltb module."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from python_pkg.steam_backlog_enforcer.hltb import (
    _AuthInfo,
    _build_search_payload,
    _get_auth_info,
    _get_hltb_search_url,
    _pick_best_hltb_entry,
    _similarity,
    load_hltb_cache,
    save_hltb_cache,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestHltbCache:
    """Tests for HLTB cache I/O."""

    def test_load_cache_exists(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text(json.dumps({"440": 10.5}), encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file
        ):
            result = load_hltb_cache()
            assert result == {440: 10.5}

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "nonexistent.json"
        with patch(
            "python_pkg.steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file
        ):
            assert load_hltb_cache() == {}

    def test_load_cache_corrupt(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        cache_file.write_text("not json", encoding="utf-8")
        with patch(
            "python_pkg.steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE", cache_file
        ):
            assert load_hltb_cache() == {}

    def test_save_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "hltb_cache.json"
        with (
            patch(
                "python_pkg.steam_backlog_enforcer._hltb_types.HLTB_CACHE_FILE",
                cache_file,
            ),
            patch("python_pkg.steam_backlog_enforcer._hltb_types.CONFIG_DIR", tmp_path),
        ):
            save_hltb_cache({440: 10.5})
            assert cache_file.exists()

    def test_save_cache_os_error(self, tmp_path: Path) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer._hltb_types._atomic_write",
            side_effect=OSError("disk full"),
        ):
            save_hltb_cache({440: 10.5})  # Should not raise


class TestGetHltbSearchUrl:
    """Tests for _get_hltb_search_url."""

    def test_discovers_url(self) -> None:
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/abc"
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = mock_info
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/abc"

    def test_fallback_url(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.return_value = None
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"

    def test_first_returns_none_second_returns_info(self) -> None:
        mock_info = MagicMock()
        mock_info.search_url = "/api/search/xyz"
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = [None, mock_info]
            mock_html.BASE_URL = "https://howlongtobeat.com"
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/search/xyz"

    def test_exception_fallback(self) -> None:
        with patch("python_pkg.steam_backlog_enforcer.hltb.HTMLRequests") as mock_html:
            mock_html.send_website_request_getcode.side_effect = RuntimeError
            url = _get_hltb_search_url()
            assert url == "https://howlongtobeat.com/api/finder"


class TestGetAuthInfo:
    """Tests for _get_auth_info."""

    def test_success(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"token": "abc123", "hpKey": "ign_x", "hpVal": "ff"}
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123", "ign_x", "ff")

    def test_success_no_hp(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"token": "abc123"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result == _AuthInfo("abc123")

    def test_no_token_key(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"notoken": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_non_200(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None

    def test_client_error(self) -> None:
        mock_session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=ctx)

        result = asyncio.run(
            _get_auth_info("https://howlongtobeat.com/api/finder", mock_session)
        )
        assert result is None


class TestSimilarity:
    """Tests for _similarity."""

    def test_identical(self) -> None:
        assert _similarity("hello", "hello") == 1.0

    def test_different(self) -> None:
        assert _similarity("abc", "xyz") < 0.5

    def test_case_insensitive(self) -> None:
        assert _similarity("Hello", "hello") == 1.0


class TestBuildSearchPayload:
    """Tests for _build_search_payload."""

    def test_returns_json(self) -> None:
        payload = _build_search_payload("Half-Life 2")
        data = json.loads(payload)
        assert data["searchType"] == "games"
        assert data["searchTerms"] == ["Half-Life", "2"]

    def test_with_auth(self) -> None:
        auth = _AuthInfo("t", "ign_x", "ff")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert data["ign_x"] == "ff"

    def test_with_auth_no_hp_key(self) -> None:
        auth = _AuthInfo("t")
        payload = _build_search_payload("TF2", auth=auth)
        data = json.loads(payload)
        assert "" not in data


class TestPickBestHltbEntry:
    """Tests for _pick_best_hltb_entry."""

    def test_empty(self) -> None:
        assert _pick_best_hltb_entry("game", []) is None

    def test_single(self) -> None:
        entry: dict[str, Any] = {"game_name": "Game", "comp_100": 3600}
        result = _pick_best_hltb_entry("Game", [(entry, 1.0)])
        assert result is not None
        assert result[0]["game_name"] == "Game"

    def test_prefers_full_edition_colon(self) -> None:
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {
            "game_name": "FAITH: The Unholy Trinity",
            "comp_100": 7200,
        }
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_prefers_full_edition_dash(self) -> None:
        demo: dict[str, Any] = {"game_name": "FAITH", "comp_100": 1800}
        full: dict[str, Any] = {"game_name": "FAITH - Complete", "comp_100": 7200}
        result = _pick_best_hltb_entry("FAITH", [(demo, 1.0), (full, 0.8)])
        assert result is not None
        assert result[0]["game_name"] == "FAITH - Complete"

    def test_falls_back_to_highest_similarity(self) -> None:
        a: dict[str, Any] = {"game_name": "ABC", "comp_100": 3600}
        b: dict[str, Any] = {"game_name": "DEF", "comp_100": 7200}
        result = _pick_best_hltb_entry("ABC", [(a, 0.9), (b, 0.7)])
        assert result is not None
        assert result[1] == 0.9

    def test_prefers_non_dlc_when_available(self) -> None:
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
