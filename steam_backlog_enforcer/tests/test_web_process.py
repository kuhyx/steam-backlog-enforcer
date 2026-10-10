"""Tests for _web_process — server health, version and stand-down."""

from __future__ import annotations

from http import HTTPStatus
import subprocess
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_process
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PKG = "steam_backlog_enforcer._web_process"


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """Leave neither a retiring flag, a registered server nor a cached sha."""
    _web_process.RETIRING.clear()
    _web_process._server.clear()
    _web_process.version.cache_clear()
    yield
    _web_process.RETIRING.clear()
    _web_process._server.clear()
    _web_process.version.cache_clear()


class TestRetire:
    def test_without_a_server_it_does_nothing(self) -> None:
        _web_process.retire()
        assert not _web_process.RETIRING.is_set()

    def test_shuts_the_server_down_once(self) -> None:
        stopped = threading.Event()
        server = MagicMock()
        server.shutdown.side_effect = stopped.set
        _web_process.register(server)
        _web_process.retire()
        assert stopped.wait(timeout=5)
        assert _web_process.RETIRING.is_set()
        _web_process.retire()
        server.shutdown.assert_called_once_with()

    def test_register_replaces_the_previous_server(self) -> None:
        first, second = MagicMock(), MagicMock()
        _web_process.register(first)
        _web_process.register(second)
        assert _web_process._server == [second]


class TestVersion:
    def test_git_short_sha(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout="abc1234\n")
        with (
            patch(f"{_PKG}.shutil.which", return_value="/usr/bin/git"),
            patch(f"{_PKG}.subprocess.run", return_value=done),
        ):
            assert _web_process.version() == "abc1234"

    @pytest.mark.parametrize(
        "failure", [OSError("x"), subprocess.CalledProcessError(1, "git")]
    )
    def test_git_failure_falls_back_to_the_newest_source(
        self, failure: Exception, tmp_path: Path
    ) -> None:
        source = tmp_path / "a.py"
        source.write_text("", encoding="utf-8")
        with (
            patch(f"{_PKG}.shutil.which", return_value="/usr/bin/git"),
            patch(f"{_PKG}.subprocess.run", side_effect=failure),
            patch(f"{_PKG}.newest_py_after", return_value=source),
        ):
            got = _web_process.version()
        assert got.endswith("Z")

    def test_no_git_and_no_sources(self) -> None:
        with (
            patch(f"{_PKG}.shutil.which", return_value=None),
            patch(f"{_PKG}.newest_py_after", return_value=None),
        ):
            assert _web_process.version() == "unknown"


class TestHealth:
    @pytest.mark.parametrize(("outdated", "stale"), [(None, False), ("x.py", True)])
    def test_health_payload(self, outdated: str | None, *, stale: bool) -> None:
        with (
            patch(f"{_PKG}.outdated_source", return_value=outdated),
            patch(f"{_PKG}.version", return_value="v1"),
        ):
            reply = _web_process.health_view(make_request())
        body = payload_of(reply)
        assert (body["stale"], body["version"]) == (stale, "v1")
        assert str(body["started_at"]).endswith("Z")


class TestRestartView:
    def test_refused_without_a_supervisor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        with pytest.raises(ApiError) as err:
            _web_process.restart_view(make_request(method="POST"))
        assert err.value.code == "unsupported"

    def test_under_systemd_it_retires_after_the_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INVOCATION_ID", "abc")
        with patch(f"{_PKG}.retire") as retire:
            reply = _web_process.restart_view(make_request(method="POST"))
        retire.assert_called_once_with(_web_process._RESTART_DELAY_SECONDS)
        assert reply.status == HTTPStatus.ACCEPTED
