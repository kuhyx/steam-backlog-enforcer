"""Tests for _web_io — body parsing and reply writing."""

from __future__ import annotations

from http import HTTPStatus
import io
import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from steam_backlog_enforcer import _web_io
from steam_backlog_enforcer._web_errors import ApiError

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler


class _Handler:
    """Just enough of ``BaseHTTPRequestHandler`` for the plumbing."""

    def __init__(self, headers: dict[str, str], body: bytes = b"") -> None:
        self.headers = headers
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.sent: list[tuple[str, str]] = []
        self.status: int | None = None

    def send_response(self, status: int) -> None:
        """Record the status line the code sends."""
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        """Record a header the code sends."""
        self.sent.append((name, value))

    def end_headers(self) -> None:
        """Mark the end of headers in the sent log."""
        self.sent.append(("--", "end"))

    def as_handler(self) -> BaseHTTPRequestHandler:
        """Expose the fake under the handler type the code expects."""
        return cast("BaseHTTPRequestHandler", self)


def _read(headers: dict[str, str], body: bytes = b"") -> dict[str, Any]:
    return _web_io.read_json_body(_Handler(headers, body).as_handler())


def _body_of(body: bytes, **headers: str) -> dict[str, Any]:
    fields = {
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
        **headers,
    }
    return _read(fields, body)


class TestReplies:
    """The reply helpers carry the right status codes."""

    def test_ok_and_no_content(self) -> None:
        """ok() replies 200 and no_content() replies 204."""
        assert _web_io.ok({"a": 1}).status == HTTPStatus.OK
        assert _web_io.no_content().status == HTTPStatus.NO_CONTENT


class TestReadJsonBody:
    """read_json_body accepts only a sized JSON object body."""

    def test_absent_body_is_empty(self) -> None:
        """A request with no body reads as an empty object."""
        assert _read({}) == {}

    def test_parses_an_object(self) -> None:
        """A JSON object parses, whatever the content-type casing and parameters."""
        got = _body_of(b'{"a": 1}', **{"Content-Type": "Application/JSON; x=y"})
        assert got == {"a": 1}

    def test_chunked_needs_a_length(self) -> None:
        """A chunked body without a length is refused with 411."""
        with pytest.raises(ApiError) as err:
            _body_of(b"", **{"Transfer-Encoding": "chunked"})
        assert err.value.status == HTTPStatus.LENGTH_REQUIRED

    def test_non_numeric_length(self) -> None:
        """A non-numeric Content-Length is refused with 400."""
        with pytest.raises(ApiError) as err:
            _read({"Content-Length": "x"})
        assert err.value.status == HTTPStatus.BAD_REQUEST

    def test_oversized_body(self) -> None:
        """A body over MAX_BODY_BYTES is refused with 413 before it is read."""
        with pytest.raises(ApiError) as err:
            _read({"Content-Length": str(_web_io.MAX_BODY_BYTES + 1)})
        assert err.value.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def test_wrong_content_type(self) -> None:
        """A non-JSON content type is refused with 415."""
        with pytest.raises(ApiError) as err:
            _body_of(b"{}", **{"Content-Type": "text/plain"})
        assert err.value.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    def test_missing_content_type(self) -> None:
        """A body with no content type is refused with 415."""
        with pytest.raises(ApiError) as err:
            _read({"Content-Length": "2"}, b"{}")
        assert err.value.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.parametrize("raw", [b"{nope", b"[1]"])
    def test_malformed_or_non_object(self, raw: bytes) -> None:
        """Malformed JSON or a non-object body is refused as invalid_params."""
        with pytest.raises(ApiError) as err:
            _body_of(raw)
        assert err.value.code == "invalid_params"


class TestSending:
    """Replies are written with the right status, headers and body."""

    def test_send_bytes_with_and_without_a_body(self) -> None:
        """send_bytes writes body, length and extra headers; nothing when empty."""
        handler = _Handler({})
        _web_io.send_bytes(
            handler.as_handler(), HTTPStatus.OK, b"hi", "text/plain", {"X-A": "1"}
        )
        assert handler.wfile.getvalue() == b"hi"
        assert ("Content-Length", "2") in handler.sent
        assert ("X-A", "1") in handler.sent
        empty = _Handler({})
        _web_io.send_bytes(empty.as_handler(), HTTPStatus.OK, b"", "text/plain")
        assert empty.wfile.getvalue() == b""

    def test_raw_reply(self) -> None:
        """A raw reply is sent as-is with its own content type."""
        handler = _Handler({})
        reply = _web_io.Reply(HTTPStatus.OK, raw=b"\xff", ctype="image/jpeg")
        _web_io.send_reply(handler.as_handler(), reply)
        assert handler.wfile.getvalue() == b"\xff"
        assert ("Content-Type", "image/jpeg") in handler.sent

    def test_payloadless_reply_has_no_content_type(self) -> None:
        """A reply with no payload sends a zero length and no content type."""
        handler = _Handler({})
        _web_io.send_reply(handler.as_handler(), _web_io.no_content())
        assert handler.status == HTTPStatus.NO_CONTENT
        assert ("Content-Length", "0") in handler.sent
        assert "Content-Type" not in [name for name, _ in handler.sent]

    def test_json_reply(self) -> None:
        """A JSON reply is serialised and marked no-store."""
        handler = _Handler({})
        _web_io.send_reply(handler.as_handler(), _web_io.ok({"a": 1}))
        assert json.loads(handler.wfile.getvalue()) == {"a": 1}
        assert ("Cache-Control", "no-store") in handler.sent

    def test_error_reply(self) -> None:
        """An ApiError is sent with its HTTP status, Retry-After and error code."""
        handler = _Handler({})
        error = ApiError("m", code="rate_limited", retry_after=3)
        _web_io.send_error(handler.as_handler(), error)
        assert handler.status == HTTPStatus.TOO_MANY_REQUESTS
        assert ("Retry-After", "3") in handler.sent
        assert json.loads(handler.wfile.getvalue())["error"] == "rate_limited"
