"""Tests for ``_ctl_client``: the raw call and the typed per-op wrappers.

``call`` is exercised against a one-shot fake daemon on a Unix socket in a
short temp dir; the typed wrappers patch ``call`` and check what they send and
how they shape the answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._ctl_protocol import (
    MAX_RESPONSE_BYTES,
    CtlError,
    DaemonUnreachableError,
)
from steam_backlog_enforcer._ctl_types import (
    BlockResult,
    DaemonInfo,
    PendingReset,
    ResetResult,
    StoreWindow,
)
from steam_backlog_enforcer.tests._ctl_fixtures import serve_once, short_socket_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path


@pytest.fixture
def sock_path() -> Iterator[Path]:
    with short_socket_dir() as directory:
        yield directory / "c.sock"


def _line(obj: object) -> bytes:
    return json.dumps(obj).encode() + b"\n"


class TestCall:
    """The wire round trip."""

    def test_returns_data(self, sock_path: Path) -> None:
        thread = serve_once(sock_path, _line({"ok": True, "data": {"a": 1}}))
        assert _ctl_client.call("ping", {"x": 1}, path=sock_path) == {"a": 1}
        thread.join(5)

    def test_ok_without_object_data_is_empty(self, sock_path: Path) -> None:
        serve_once(sock_path, _line({"ok": True, "data": 5}))
        assert _ctl_client.call("ping", path=sock_path) == {}

    def test_error_reply_raises_ctl_error(self, sock_path: Path) -> None:
        reply = {"ok": False, "error": "locked", "message": "no", "data": {"k": 1}}
        serve_once(sock_path, _line(reply))
        with pytest.raises(CtlError) as caught:
            _ctl_client.call("ping", path=sock_path)
        assert (caught.value.code, caught.value.message) == ("locked", "no")
        assert caught.value.data == {"k": 1}

    def test_error_reply_defaults(self, sock_path: Path) -> None:
        serve_once(sock_path, _line({"ok": False}))
        with pytest.raises(CtlError) as caught:
            _ctl_client.call("ping", path=sock_path)
        assert (caught.value.code, caught.value.message) == ("op_failed", "")
        assert caught.value.data == {}

    def test_missing_socket(self, sock_path: Path) -> None:
        with pytest.raises(DaemonUnreachableError, match="control socket"):
            _ctl_client.call("ping", path=sock_path)

    def test_closed_without_answer(self, sock_path: Path) -> None:
        serve_once(sock_path, b"")
        with pytest.raises(DaemonUnreachableError, match="without answering"):
            _ctl_client.call("ping", path=sock_path)

    @pytest.mark.parametrize("reply", [b"{nope\n", b"[1]\n", b"\xff\n"])
    def test_malformed_reply(self, sock_path: Path, reply: bytes) -> None:
        serve_once(sock_path, reply)
        with pytest.raises(DaemonUnreachableError, match="malformed"):
            _ctl_client.call("ping", path=sock_path)

    def test_oversize_reply(self, sock_path: Path) -> None:
        serve_once(sock_path, b"x" * (MAX_RESPONSE_BYTES + 70000))
        with pytest.raises(DaemonUnreachableError, match="too large"):
            _ctl_client.call("ping", path=sock_path)


_PENDING = {
    "pending_id": "abc",
    "phrase": "p",
    "armed_at": "a",
    "ready_at": "r",
    "heartbeat_interval_seconds": 10,
}


class TestTypedWrappers:
    """Each wrapper sends the right op and shapes the reply."""

    def _call(self, data: dict[str, object]) -> AbstractContextManager[MagicMock]:
        return patch.object(_ctl_client, "call", return_value=data)

    def test_ping(self) -> None:
        with self._call({}) as call:
            _ctl_client.ping()
        call.assert_called_once_with("ping")

    def test_status(self) -> None:
        data = {
            "state": "running",
            "started_at": "t",
            "pid": 4,
            "restart_available_at": "x",
        }
        with self._call(data):
            assert _ctl_client.status() == DaemonInfo("running", "t", 4, "x")

    def test_status_no_restart_time(self) -> None:
        data = {"state": "running", "started_at": "t", "pid": 4}
        with self._call(data):
            assert _ctl_client.status().restart_available_at is None

    def test_journal_tail(self) -> None:
        with self._call({"lines": ["a", 2]}) as call:
            assert _ctl_client.journal_tail(9) == ["a", "2"]
        call.assert_called_once_with("journal_tail", {"lines": 9})

    def test_store_unblock(self) -> None:
        with self._call({"minutes": 5, "until": "u"}) as call:
            assert _ctl_client.store_unblock(5, "ph") == StoreWindow(5, "u")
        assert call.call_args.args == ("store_unblock", {"minutes": 5, "phrase": "ph"})

    def test_block_gaming(self) -> None:
        with self._call({"days": 3, "until": "u"}):
            assert _ctl_client.block_gaming(3, "ph") == BlockResult(3, "u")

    def test_block_gaming_no_until(self) -> None:
        with self._call({"days": 3, "until": None}):
            assert _ctl_client.block_gaming(3, "ph") == BlockResult(3, None)

    def test_gaming_unblock(self) -> None:
        with self._call({"released": ["/a"]}):
            assert _ctl_client.gaming_unblock("ph") == ["/a"]

    def test_reset_arm_and_heartbeat(self) -> None:
        expected = PendingReset("abc", "p", "a", "r", 10)
        with self._call(dict(_PENDING)):
            assert _ctl_client.gaming_reset_arm("ph") == expected
            assert _ctl_client.gaming_reset_heartbeat("abc") == expected

    def test_reset_commit(self) -> None:
        data = {
            "day_key": "d",
            "seconds_before": 1.5,
            "was_blocked": 1,
            "released": ["/m"],
        }
        with self._call(data):
            result = _ctl_client.gaming_reset_commit("abc", "ph")
        assert result == ResetResult("d", 1.5, was_blocked=True, released=["/m"])

    def test_reset_cancel(self) -> None:
        with self._call({}) as call:
            _ctl_client.gaming_reset_cancel("abc")
        call.assert_called_once_with("gaming_reset_cancel", {"pending_id": "abc"})

    def test_restart(self) -> None:
        with self._call({"restart_available_at": "x"}):
            assert _ctl_client.restart() == "x"

    def test_restart_no_time(self) -> None:
        with self._call({}):
            assert _ctl_client.restart() is None
