"""Tests for _web_art — the cover lookup order and the CDN fetch fence."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from steam_backlog_enforcer import _web_art
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
    def test_none_when_steam_cached_nothing(self) -> None:
        assert _web_art._local_cover(10) is None

    def test_top_level_portrait(self) -> None:
        base = _web_art.LIBRARYCACHE / "10"
        base.mkdir(parents=True)
        (base / "library_600x900.jpg").write_bytes(b"A")
        assert _web_art._local_cover(10) == base / "library_600x900.jpg"

    def test_hashed_subdirectory_portrait(self) -> None:
        sub = _web_art.LIBRARYCACHE / "10" / "abc123"
        sub.mkdir(parents=True)
        (sub / "library_capsule.jpg").write_bytes(b"B")
        assert _web_art._local_cover(10) == sub / "library_capsule.jpg"


class TestMissMarker:
    def test_absent_marker_is_not_active(self) -> None:
        assert _web_art._miss_active(1) is False

    def test_garbage_marker_is_not_active(self) -> None:
        _web_art.ART_CACHE_DIR.mkdir(parents=True)
        _web_art._miss_file(1).write_text("not a number", encoding="utf-8")
        assert _web_art._miss_active(1) is False

    def test_recorded_miss_is_active_until_it_lapses(self) -> None:
        _web_art._record_miss(1, 60)
        assert _web_art._miss_active(1) is True
        with patch(f"{_PKG}.time.time", return_value=time.time() + 120):
            assert _web_art._miss_active(1) is False


class TestStore:
    def test_store_writes_and_clears_the_miss(self) -> None:
        _web_art._record_miss(2, 60)
        _web_art._store(2, b"IMG")
        assert _web_art._cache_file(2).read_bytes() == b"IMG"
        assert not _web_art._miss_file(2).exists()

    def test_store_without_a_miss_marker(self) -> None:
        _web_art._store(3, b"IMG")
        assert _web_art._cache_file(3).read_bytes() == b"IMG"


class TestFetch:
    def test_returns_a_cover_stored_while_waiting(self) -> None:
        _web_art._store(4, b"EARLY")
        with patch(f"{_PKG}.requests.get") as get:
            assert _web_art._fetch(4) == b"EARLY"
        get.assert_not_called()

    def test_active_miss_skips_the_network(self) -> None:
        _web_art._record_miss(4, 60)
        with patch(f"{_PKG}.requests.get") as get:
            assert _web_art._fetch(4) is None
        get.assert_not_called()

    def test_network_failure_is_remembered_briefly(self) -> None:
        with patch(f"{_PKG}.requests.get", side_effect=requests.ConnectionError):
            assert _web_art._fetch(5) is None
        retry_at = float(_web_art._miss_file(5).read_text(encoding="utf-8"))
        assert retry_at - time.time() <= _web_art._FAILED_RETRY_S

    def test_success_is_cached(self) -> None:
        with patch(f"{_PKG}.requests.get", return_value=_response()) as get:
            assert _web_art._fetch(6) == b"JPEG"
        assert get.call_args.args == (_web_art._CDN.format(app_id=6),)
        assert _web_art._cache_file(6).read_bytes() == b"JPEG"

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
        resp = _response(status, ctype)
        with patch(f"{_PKG}.requests.get", return_value=resp):
            assert _web_art._fetch(7) is None
        wait = float(_web_art._miss_file(7).read_text(encoding="utf-8")) - time.time()
        assert (wait > _web_art._FAILED_RETRY_S) is long_retry

    def test_oversized_cover_is_a_long_miss(self) -> None:
        big = _response(content=b"x" * (_web_art._MAX_BYTES + 1))
        with patch(f"{_PKG}.requests.get", return_value=big):
            assert _web_art._fetch(8) is None
        wait = float(_web_art._miss_file(8).read_text(encoding="utf-8")) - time.time()
        assert wait > _web_art._FAILED_RETRY_S


class TestCoverBytes:
    def test_prefers_steams_own_cache(self) -> None:
        base = _web_art.LIBRARYCACHE / "9"
        base.mkdir(parents=True)
        (base / "library_600x900.jpg").write_bytes(b"LOCAL")
        assert _web_art.cover_bytes(9) == b"LOCAL"

    def test_then_the_server_cache(self) -> None:
        _web_art._store(9, b"CACHED")
        assert _web_art.cover_bytes(9) == b"CACHED"

    def test_active_miss_means_no_cover(self) -> None:
        _web_art._record_miss(9, 60)
        assert _web_art.cover_bytes(9) is None

    def test_falls_through_to_the_cdn(self) -> None:
        with patch(f"{_PKG}._fetch", return_value=b"NET") as fetch:
            assert _web_art.cover_bytes(9) == b"NET"
        fetch.assert_called_once_with(9)


class TestArtView:
    def test_serves_an_owned_cover(self) -> None:
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
        with (
            patch(f"{_PKG}.owned_app_ids", return_value={42}),
            pytest.raises(ApiError) as err,
        ):
            _web_art.art_view(make_request(raw))
        assert err.value.code == "not_found"

    def test_no_cover_is_not_found(self) -> None:
        with (
            patch(f"{_PKG}.owned_app_ids", return_value={42}),
            patch(f"{_PKG}.cover_bytes", return_value=None),
            pytest.raises(ApiError) as err,
        ):
            _web_art.art_view(make_request("42"))
        assert err.value.code == "not_found"
