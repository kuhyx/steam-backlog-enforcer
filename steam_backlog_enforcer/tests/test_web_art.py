"""Tests for _web_art — the cover lookup order and the CDN fetch fence."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from steam_backlog_enforcer import _web_art
from steam_backlog_enforcer._web_art import (
    _CDN,
    _FAILED_RETRY_S,
    _MAX_BYTES,
    _cache_file,
    _fetch,
    _local_cover,
    _miss_active,
    _miss_file,
    _record_miss,
    _store,
)
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._web_request import make_request

_PKG = "steam_backlog_enforcer._web_art"


def _response(
    status: int = 200, ctype: str = "image/jpeg", content: bytes = b"JPEG"
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"Content-Type": ctype}
    resp.content = content
    return resp


class TestLocalCover:
    """Steam's own librarycache is searched for a portrait cover."""

    def test_none_when_steam_cached_nothing(self) -> None:
        """An app with no librarycache entry has no local cover."""
        assert _local_cover(10) is None

    def test_top_level_portrait(self) -> None:
        """A portrait in the app's top-level cache dir is found."""
        base = _web_art.LIBRARYCACHE / "10"
        base.mkdir(parents=True)
        (base / "library_600x900.jpg").write_bytes(b"A")
        assert _local_cover(10) == base / "library_600x900.jpg"

    def test_hashed_subdirectory_portrait(self) -> None:
        """A portrait inside a hashed subdirectory is found."""
        sub = _web_art.LIBRARYCACHE / "10" / "abc123"
        sub.mkdir(parents=True)
        (sub / "library_capsule.jpg").write_bytes(b"B")
        assert _local_cover(10) == sub / "library_capsule.jpg"


class TestMissMarker:
    """The miss marker suppresses refetches until it lapses."""

    def test_absent_marker_is_not_active(self) -> None:
        """No marker file means no active miss."""
        assert _miss_active(1) is False

    def test_garbage_marker_is_not_active(self) -> None:
        """An unparsable marker is treated as no miss."""
        _web_art.ART_CACHE_DIR.mkdir(parents=True)
        _miss_file(1).write_text("not a number", encoding="utf-8")
        assert _miss_active(1) is False

    def test_recorded_miss_is_active_until_it_lapses(self) -> None:
        """A recorded miss is active, then lapses after its wait."""
        _record_miss(1, 60)
        assert _miss_active(1) is True
        with patch(f"{_PKG}.time.time", return_value=time.time() + 120):
            assert _miss_active(1) is False


class TestStore:
    """Storing a cover writes the cache file."""

    def test_store_writes_and_clears_the_miss(self) -> None:
        """Storing writes the bytes and removes any miss marker."""
        _record_miss(2, 60)
        _store(2, b"IMG")
        assert _cache_file(2).read_bytes() == b"IMG"
        assert not _miss_file(2).exists()

    def test_store_without_a_miss_marker(self) -> None:
        """Storing works when there was no miss marker."""
        _store(3, b"IMG")
        assert _cache_file(3).read_bytes() == b"IMG"


class TestFetch:
    """The CDN fetch is fenced by the cache and the miss marker."""

    def test_returns_a_cover_stored_while_waiting(self) -> None:
        """A cover stored meanwhile is returned without a request."""
        _store(4, b"EARLY")
        with patch(f"{_PKG}.requests.get") as get:
            assert _fetch(4) == b"EARLY"
        get.assert_not_called()

    def test_active_miss_skips_the_network(self) -> None:
        """An active miss returns None without a request."""
        _record_miss(4, 60)
        with patch(f"{_PKG}.requests.get") as get:
            assert _fetch(4) is None
        get.assert_not_called()

    def test_network_failure_is_remembered_briefly(self) -> None:
        """A connection error records a short miss."""
        with patch(f"{_PKG}.requests.get", side_effect=requests.ConnectionError):
            assert _fetch(5) is None
        retry_at = float(_miss_file(5).read_text(encoding="utf-8"))
        assert retry_at - time.time() <= _FAILED_RETRY_S

    def test_success_is_cached(self) -> None:
        """A good answer comes from the CDN URL and is cached."""
        with patch(f"{_PKG}.requests.get", return_value=_response()) as get:
            assert _fetch(6) == b"JPEG"
        assert get.call_args.args == (_CDN.format(app_id=6),)
        assert _cache_file(6).read_bytes() == b"JPEG"

    @pytest.mark.parametrize(
        ("status", "ctype", "long_retry"),
        [
            (404, "text/html", True),
            (403, "text/html", True),
            (500, "text/html", False),
            (200, "text/html", False),
        ],
    )
    def test_unusable_answer_is_a_remembered_miss(
        self, status: int, ctype: str, *, long_retry: bool
    ) -> None:
        """Bad answers record a miss; only 403/404 get the long wait."""
        resp = _response(status, ctype)
        with patch(f"{_PKG}.requests.get", return_value=resp):
            assert _fetch(7) is None
        wait = float(_miss_file(7).read_text(encoding="utf-8")) - time.time()
        assert (wait > _FAILED_RETRY_S) is long_retry

    def test_oversized_cover_is_a_long_miss(self) -> None:
        """A cover over the size cap records a long miss."""
        big = _response(content=b"x" * (_MAX_BYTES + 1))
        with patch(f"{_PKG}.requests.get", return_value=big):
            assert _fetch(8) is None
        wait = float(_miss_file(8).read_text(encoding="utf-8")) - time.time()
        assert wait > _FAILED_RETRY_S


class TestCoverBytes:
    """cover_bytes tries Steam's cache, the server cache, then the CDN."""

    def test_prefers_steams_own_cache(self) -> None:
        """Steam's local cover wins over everything else."""
        base = _web_art.LIBRARYCACHE / "9"
        base.mkdir(parents=True)
        (base / "library_600x900.jpg").write_bytes(b"LOCAL")
        assert _web_art.cover_bytes(9) == b"LOCAL"

    def test_then_the_server_cache(self) -> None:
        """The server cache is used when Steam has nothing."""
        _store(9, b"CACHED")
        assert _web_art.cover_bytes(9) == b"CACHED"

    def test_active_miss_means_no_cover(self) -> None:
        """An active miss yields no cover."""
        _record_miss(9, 60)
        assert _web_art.cover_bytes(9) is None

    def test_falls_through_to_the_cdn(self) -> None:
        """With nothing cached, the CDN fetch is asked once."""
        with patch(f"{_PKG}._fetch", return_value=b"NET") as fetch:
            assert _web_art.cover_bytes(9) == b"NET"
        fetch.assert_called_once_with(9)


class TestArtView:
    """The /art endpoint serves covers of owned games only."""

    def test_serves_an_owned_cover(self) -> None:
        """An owned game's cover is served as a cacheable JPEG."""
        with (
            patch(f"{_PKG}.owned_app_ids", return_value={42}),
            patch(f"{_PKG}.cover_bytes", return_value=b"JPG"),
        ):
            reply = _web_art.art_view(make_request("42"))
        assert reply.raw == b"JPG"
        assert reply.ctype == "image/jpeg"
        assert "max-age" in reply.headers["Cache-Control"]

    @pytest.mark.parametrize("raw", ["abc", "7"])
    def test_refuses_what_is_not_owned(self, raw: str) -> None:
        """A non-numeric or unowned id is not_found."""
        with (
            patch(f"{_PKG}.owned_app_ids", return_value={42}),
            pytest.raises(ApiError) as err,
        ):
            _web_art.art_view(make_request(raw))
        assert err.value.code == "not_found"

    def test_no_cover_is_not_found(self) -> None:
        """An owned game without a cover is not_found."""
        with (
            patch(f"{_PKG}.owned_app_ids", return_value={42}),
            patch(f"{_PKG}.cover_bytes", return_value=None),
            pytest.raises(ApiError) as err,
        ):
            _web_art.art_view(make_request("42"))
        assert err.value.code == "not_found"
