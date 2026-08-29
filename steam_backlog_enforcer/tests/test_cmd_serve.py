"""Tests for the main.cmd_serve wiring — 100% branch coverage.

Split from test_web_server.py to stay inside the 250-line file cap: that file
covers the HTTP server itself, this one covers the command that starts it.
"""

from __future__ import annotations

import errno
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import main as main_mod
from steam_backlog_enforcer._web_server import DEFAULT_HOST
from steam_backlog_enforcer.main import misc as misc_mod

_CALLS: list[str] = []


def _record_build() -> bool:
    """Stand in for a successful build, recording when it ran."""
    _CALLS.append("build")
    return True


def _record_guard(*_args: object) -> None:
    """Stand in for the port guard, recording when it ran."""
    _CALLS.append("guard")


class TestCmdServe:
    """Tests for the main.cmd_serve wiring.

    Every patch targets the module that *defines* cmd_serve, not the main
    package that re-exports it: cmd_serve resolves these names from its own
    globals, so patching the re-export would not bite.
    """

    def test_invokes_serve_with_parsed_args(self) -> None:
        with (
            patch.object(misc_mod, "frontend_is_stale", return_value=False),
            patch.object(misc_mod, "ensure_port_available") as guard,
            patch.object(misc_mod, "serve") as mock_serve,
        ):
            main_mod.cmd_serve(["--port", "8123"])
        guard.assert_called_once_with(DEFAULT_HOST, 8123)
        mock_serve.assert_called_once_with(DEFAULT_HOST, 8123)

    def test_stale_frontend_is_rebuilt_before_binding(self) -> None:
        # Order matters: a failed build must not cost the caller the server
        # that was already running, so the build happens before the port check.
        _CALLS.clear()
        with (
            patch.object(misc_mod, "frontend_is_stale", return_value=True),
            patch.object(misc_mod, "build_frontend", side_effect=_record_build),
            patch.object(misc_mod, "ensure_port_available", side_effect=_record_guard),
            patch.object(misc_mod, "serve"),
        ):
            main_mod.cmd_serve([])
        assert _CALLS == ["build", "guard"]

    def test_failed_build_exits_1(self) -> None:
        with (
            patch.object(misc_mod, "frontend_is_stale", return_value=True),
            patch.object(misc_mod, "build_frontend", return_value=False),
            patch.object(misc_mod, "ensure_port_available") as guard,
            patch.object(misc_mod, "serve") as mock_serve,
            pytest.raises(SystemExit) as exc,
        ):
            main_mod.cmd_serve([])
        assert exc.value.code == 1
        guard.assert_not_called()
        mock_serve.assert_not_called()

    def test_port_stolen_after_the_check_exits_1(self) -> None:
        # Covers the race between the /proc scan and the actual bind.
        taken = OSError(errno.EADDRINUSE, "Address already in use")
        with (
            patch.object(misc_mod, "frontend_is_stale", return_value=False),
            patch.object(misc_mod, "ensure_port_available"),
            patch.object(misc_mod, "serve", side_effect=taken),
            patch.object(misc_mod, "_echo") as echo,
            pytest.raises(SystemExit) as exc,
        ):
            main_mod.cmd_serve([])
        assert exc.value.code == 1
        assert "was taken while starting up" in echo.call_args[0][0]

    def test_unrelated_oserror_propagates(self) -> None:
        # Swallowing this would turn a real fault into a bare "try again".
        denied = OSError(errno.EACCES, "Permission denied")
        with (
            patch.object(misc_mod, "frontend_is_stale", return_value=False),
            patch.object(misc_mod, "ensure_port_available"),
            patch.object(misc_mod, "serve", side_effect=denied),
            pytest.raises(OSError, match="Permission denied"),
        ):
            main_mod.cmd_serve([])
