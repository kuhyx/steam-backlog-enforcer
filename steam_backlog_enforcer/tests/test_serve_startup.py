"""Tests for _serve_startup — 100% branch coverage.

The guard functions are imported into this module's namespace, so every patch
targets ``_serve_startup.<name>``: patching ``_serve_guard`` would not bite.
No test here signals a real process — ``terminate`` is always a mock.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _serve_startup
from steam_backlog_enforcer._web_server import DEFAULT_HOST, DEFAULT_PORT

_PKG = "steam_backlog_enforcer._serve_startup"


def _exits_1(argv: list[str]) -> None:
    """Assert that parsing *argv* fails with exit code 1."""
    with patch(f"{_PKG}._echo"), pytest.raises(SystemExit) as exc:
        _serve_startup.parse_serve_args(argv)
    assert exc.value.code == 1


class TestParseServeArgs:
    """Tests for argument parsing."""

    def test_defaults_when_no_flags(self) -> None:
        assert _serve_startup.parse_serve_args([]) == (DEFAULT_HOST, DEFAULT_PORT)

    def test_port_flag(self) -> None:
        assert _serve_startup.parse_serve_args(["--port", "8123"]) == (
            DEFAULT_HOST,
            8123,
        )

    def test_host_flag_accepts_literal_loopback(self) -> None:
        assert _serve_startup.parse_serve_args(["--host", "127.0.0.2"]) == (
            "127.0.0.2",
            DEFAULT_PORT,
        )

    def test_host_alias_canonicalises(self) -> None:
        host, _ = _serve_startup.parse_serve_args(["--host", "localhost"])
        assert host == DEFAULT_HOST

    def test_both_flags_together(self) -> None:
        assert _serve_startup.parse_serve_args(
            ["--host", "localhost", "--port", "9000"]
        ) == (DEFAULT_HOST, 9000)

    def test_unknown_argument_exits(self) -> None:
        _exits_1(["--wat"])

    def test_flag_without_value_exits(self) -> None:
        _exits_1(["--port"])

    def test_non_numeric_port_exits(self) -> None:
        _exits_1(["--port", "eight"])

    def test_privileged_port_exits(self) -> None:
        _exits_1(["--port", "80"])

    def test_port_above_range_exits(self) -> None:
        _exits_1(["--port", "99999"])

    def test_non_address_host_exits(self) -> None:
        _exits_1(["--host", "example.com"])

    def test_routable_host_exits(self) -> None:
        # The dataset API is unauthenticated; a bind must never leave the box.
        _exits_1(["--host", "8.8.8.8"])

    def test_ipv6_loopback_exits(self) -> None:
        # ThreadingHTTPServer is AF_INET, so ::1 would always crash at bind.
        _exits_1(["--host", "::1"])


class TestDescribe:
    """Tests for the pid description helper."""

    def test_includes_argv_when_readable(self) -> None:
        with patch(f"{_PKG}.read_cmdline", return_value=["python", "-m", "x"]):
            assert _serve_startup._describe(42) == "pid 42 (python -m x)"

    def test_falls_back_to_bare_pid(self) -> None:
        with patch(f"{_PKG}.read_cmdline", return_value=[]):
            assert _serve_startup._describe(42) == "pid 42"


class TestEnsurePortAvailable:
    """Tests for the start-or-defer decision."""

    def test_free_port_returns(self) -> None:
        # Returning normally *is* the assertion: every other path exits.
        with patch(f"{_PKG}.port_is_free", return_value=True):
            _serve_startup.ensure_port_available(DEFAULT_HOST, 8000)

    def test_uninspectable_owner_exits_1(self) -> None:
        with (
            patch(f"{_PKG}.port_is_free", return_value=False),
            patch(f"{_PKG}.find_port_owner", return_value=None),
            patch(f"{_PKG}._echo") as echo,
            pytest.raises(SystemExit) as exc,
        ):
            _serve_startup.ensure_port_available(DEFAULT_HOST, 8000)
        assert exc.value.code == 1
        assert "cannot inspect" in echo.call_args_list[0][0][0]

    def test_foreign_owner_exits_1_and_is_named(self) -> None:
        with (
            patch(f"{_PKG}.port_is_free", return_value=False),
            patch(f"{_PKG}.find_port_owner", return_value=99),
            patch(f"{_PKG}.is_our_server", return_value=False),
            patch(f"{_PKG}.read_cmdline", return_value=["nginx"]),
            patch(f"{_PKG}._echo") as echo,
            pytest.raises(SystemExit) as exc,
        ):
            _serve_startup.ensure_port_available(DEFAULT_HOST, 8000)
        assert exc.value.code == 1
        assert "pid 99 (nginx)" in echo.call_args_list[0][0][0]

    def test_our_server_delegates_to_replace_or_defer(self) -> None:
        with (
            patch(f"{_PKG}.port_is_free", return_value=False),
            patch(f"{_PKG}.find_port_owner", return_value=99),
            patch(f"{_PKG}.is_our_server", return_value=True),
            patch(f"{_PKG}._replace_or_defer") as replace,
        ):
            _serve_startup.ensure_port_available(DEFAULT_HOST, 8000)
        replace.assert_called_once_with(DEFAULT_HOST, 8000, 99)


class TestReplaceOrDefer:
    """Tests for the stale-or-current decision about our own server."""

    def test_current_server_exits_0_with_url(self) -> None:
        with (
            patch(f"{_PKG}.process_started_at", return_value=1000.0),
            patch(f"{_PKG}.newest_py_since", return_value=None),
            patch(f"{_PKG}._echo") as echo,
            pytest.raises(SystemExit) as exc,
        ):
            _serve_startup._replace_or_defer(DEFAULT_HOST, 8000, 99)
        assert exc.value.code == 0
        assert f"http://{DEFAULT_HOST}:8000" in echo.call_args_list[0][0][0]

    def test_stale_server_is_terminated(self, tmp_path: object) -> None:
        newer = "steam_backlog_enforcer/main/misc.py"
        with (
            patch(f"{_PKG}.process_started_at", return_value=1000.0),
            patch(f"{_PKG}.newest_py_since", return_value=newer),
            patch(f"{_PKG}.is_our_server", return_value=True),
            patch(f"{_PKG}.terminate", return_value=True) as term,
            patch(f"{_PKG}._echo") as echo,
        ):
            _serve_startup._replace_or_defer(DEFAULT_HOST, 8000, 99)
        term.assert_called_once_with(99, DEFAULT_HOST, 8000)
        assert f"{newer} is newer" in echo.call_args_list[0][0][0]

    def test_unreadable_start_time_restarts(self) -> None:
        with (
            patch(f"{_PKG}.process_started_at", return_value=None),
            patch(f"{_PKG}.is_our_server", return_value=True),
            patch(f"{_PKG}.terminate", return_value=True),
            patch(f"{_PKG}._echo") as echo,
        ):
            _serve_startup._replace_or_defer(DEFAULT_HOST, 8000, 99)
        assert "start time unreadable" in echo.call_args_list[0][0][0]

    def test_recycled_pid_is_never_signalled(self) -> None:
        # Between the port scan and here the process can exit and its pid be
        # reused. Signalling on the stale answer would kill a bystander.
        with (
            patch(f"{_PKG}.process_started_at", return_value=None),
            patch(f"{_PKG}.is_our_server", return_value=False),
            patch(f"{_PKG}.read_cmdline", return_value=["someone-else"]),
            patch(f"{_PKG}.terminate") as term,
            patch(f"{_PKG}._echo"),
            pytest.raises(SystemExit) as exc,
        ):
            _serve_startup._replace_or_defer(DEFAULT_HOST, 8000, 99)
        assert exc.value.code == 1
        term.assert_not_called()

    def test_failed_termination_exits_1(self) -> None:
        with (
            patch(f"{_PKG}.process_started_at", return_value=None),
            patch(f"{_PKG}.is_our_server", return_value=True),
            patch(f"{_PKG}.terminate", return_value=False),
            patch(f"{_PKG}._echo") as echo,
            pytest.raises(SystemExit) as exc,
        ):
            _serve_startup._replace_or_defer(DEFAULT_HOST, 8000, 99)
        assert exc.value.code == 1
        assert "Could not free port 8000" in echo.call_args_list[-1][0][0]
