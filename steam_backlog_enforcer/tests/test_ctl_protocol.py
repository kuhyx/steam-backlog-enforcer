"""Tests for the control-socket wire format and the server-side wire helpers.

Covers ``_ctl_protocol`` (line codec, error type, responses), ``_ctl_types``
(frozen result types) and ``_ctl_wire`` (peer uid, liveness probe, bounded line
read, request parsing). Sockets are ``socketpair``s or live under a short
temporary directory; nothing touches the real ``/run`` socket.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_protocol, _ctl_wire
from steam_backlog_enforcer._ctl_types import BlockResult, DaemonInfo

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A short-path temp dir: AF_UNIX paths are capped near 108 bytes."""
    with tempfile.TemporaryDirectory(prefix="ctl") as name:
        yield Path(name)


class TestCodec:
    """Line encoding and the two response shapes."""

    def test_roundtrip(self) -> None:
        raw = _ctl_protocol.encode_line({"op": "ping", "args": {}})
        assert raw.endswith(b"\n")
        assert _ctl_protocol.decode_line(raw) == {"op": "ping", "args": {}}

    def test_decode_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="Expecting"):
            _ctl_protocol.decode_line(b"{nope")

    def test_ok_response(self) -> None:
        body = json.loads(_ctl_protocol.ok_response({"a": 1}))
        assert body == {"ok": True, "data": {"a": 1}}

    def test_error_response_without_data(self) -> None:
        err = _ctl_protocol.CtlError(_ctl_protocol.LOCKED, "nope")
        body = json.loads(_ctl_protocol.error_response(err))
        assert body == {"ok": False, "error": "locked", "message": "nope"}

    def test_error_response_with_data(self) -> None:
        err = _ctl_protocol.CtlError(_ctl_protocol.BUSY, "wait", {"retry": 2})
        body = json.loads(_ctl_protocol.error_response(err))
        assert body["data"] == {"retry": 2}

    def test_ctl_error_attributes(self) -> None:
        err = _ctl_protocol.CtlError("code", "msg")
        assert (err.code, err.message, err.data) == ("code", "msg", {})
        assert str(err) == "code: msg"


class TestTypes:
    """The result types are frozen value objects."""

    def test_hashable_because_frozen(self) -> None:
        assert hash(DaemonInfo("running", "t", 1, None)) is not None

    def test_equality(self) -> None:
        assert BlockResult(3, None) == BlockResult(3, None)


class TestPeerUid:
    """SO_PEERCRED reports the connecting process's real uid."""

    def test_reports_own_uid(self) -> None:
        left, right = socket.socketpair()
        try:
            assert _ctl_wire.peer_uid(left) == os.getuid()
        finally:
            left.close()
            right.close()


class TestSocketIsLive:
    """Probing a path for an accepting listener."""

    def test_missing_path(self, short_dir: Path) -> None:
        assert _ctl_wire.socket_is_live(short_dir / "none.sock") is False

    def test_listening_path(self, short_dir: Path) -> None:
        path = short_dir / "s.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(path))
            server.listen(1)
            assert _ctl_wire.socket_is_live(path) is True
        finally:
            server.close()


class TestReadLine:
    """Bounded, deadline-limited request reading."""

    def test_reads_first_line(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            right.sendall(b'{"op":"ping"}\nextra')
            assert _ctl_wire.read_line(left) == b'{"op":"ping"}'

    def test_eof_without_newline_returns_data(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            right.sendall(b"abc")
            right.shutdown(socket.SHUT_WR)
            assert _ctl_wire.read_line(left) == b"abc"

    def test_immediate_eof_returns_none(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            right.shutdown(socket.SHUT_WR)
            assert _ctl_wire.read_line(left) is None

    def test_oversize_is_truncated_past_the_cap(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            right.sendall(b"x" * (_ctl_protocol.MAX_REQUEST_BYTES + 100))
            line = _ctl_wire.read_line(left)
        assert line is not None
        assert len(line) == _ctl_protocol.MAX_REQUEST_BYTES + 1

    def test_stalled_client_times_out(self) -> None:
        left, right = socket.socketpair()
        with (
            left,
            right,
            patch.object(_ctl_wire, "READ_TIMEOUT_SECONDS", 0.05),
        ):
            assert _ctl_wire.read_line(left) is None

    def test_deadline_already_passed(self) -> None:
        left, right = socket.socketpair()
        with left, right, patch.object(_ctl_wire, "READ_TIMEOUT_SECONDS", -1.0):
            assert _ctl_wire.read_line(left) is None


class TestParseRequest:
    """Validation of a decoded request."""

    def test_valid_with_args(self) -> None:
        assert _ctl_wire.parse_request(b'{"op":"x","args":{"a":1}}') == (
            "x",
            {"a": 1},
        )

    def test_args_default_to_empty(self) -> None:
        assert _ctl_wire.parse_request(b'{"op":"x"}') == ("x", {})

    @pytest.mark.parametrize(
        "line",
        [b"{bad", b"\xff\xfe", b"[1]", b'{"op":5}', b'{"args":{}}'],
    )
    def test_rejects_malformed(self, line: bytes) -> None:
        with pytest.raises(_ctl_protocol.CtlError) as caught:
            _ctl_wire.parse_request(line)
        assert caught.value.code == _ctl_protocol.INVALID_PARAMS

    def test_rejects_non_object_args(self) -> None:
        with pytest.raises(_ctl_protocol.CtlError, match="args must be"):
            _ctl_wire.parse_request(b'{"op":"x","args":[1]}')
