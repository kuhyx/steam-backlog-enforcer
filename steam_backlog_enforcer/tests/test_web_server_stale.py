"""Tests for the stale-code refusal in _web_server.

Split out of test_web_server.py for the 250-line cap; the server harness stays
in that module and is imported here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_server
from steam_backlog_enforcer.tests.test_web_server import _PKG, _get, _running

if TYPE_CHECKING:
    from pathlib import Path


class TestStaleServerRefuses:
    """A server outrun by its own source stops answering and stands down."""

    def _clear_retiring(self) -> None:
        """Reset the module-level stand-down latch between tests."""
        _web_server._RETIRING.clear()

    @pytest.mark.parametrize("route", ["/api/budget", "/api/dataset", "/"])
    def test_every_route_refuses_when_stale(self, tmp_path: Path, route: str) -> None:
        """Static too: a fresh page fetching stale numbers is the same lie.

        One server per route on purpose -- the first refusal stands the server
        down, so a second request against it would (correctly) never answer.
        """
        self._clear_retiring()
        changed = tmp_path / "changed.py"
        changed.touch()
        with (
            patch(f"{_PKG}.outdated_source", return_value=changed),
            _running() as port,
        ):
            status, body, _ = _get(port, route)
        assert status == 503
        assert b"outdated code" in body
        self._clear_retiring()

    def test_it_stands_down_so_a_supervisor_can_replace_it(
        self,
        tmp_path: Path,
    ) -> None:
        """503 forever would be honest and useless; exiting self-heals."""
        self._clear_retiring()
        changed = tmp_path / "changed.py"
        changed.touch()
        with (
            patch(f"{_PKG}.outdated_source", return_value=changed),
            _running() as port,
        ):
            _get(port, "/api/budget")
            assert _web_server._RETIRING.is_set()
        self._clear_retiring()

    def test_a_second_refusal_does_not_stand_down_twice(
        self,
        tmp_path: Path,
    ) -> None:
        """The latch short-circuits, so concurrent refusals share one shutdown."""
        self._clear_retiring()
        changed = tmp_path / "changed.py"
        changed.touch()
        _web_server._RETIRING.set()
        with (
            patch(f"{_PKG}.outdated_source", return_value=changed),
            _running() as port,
        ):
            # Latch already set: this refusal must take the early return and
            # leave the server up, which is why the request still completes.
            status, _, _ = _get(port, "/api/budget")
        assert status == 503
        self._clear_retiring()
