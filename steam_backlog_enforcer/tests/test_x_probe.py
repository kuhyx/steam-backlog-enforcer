"""Tests for the cached X connection and the input-idle query.

Every case runs against fake library handles, so the suite never needs a
display and never depends on whether the developer happens to be at the
keyboard.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._x_probe import (
    XProbe,
    XProbeError,
    _ignore_x_error,
    load_libraries,
    root_window,
)
from steam_backlog_enforcer.tests._fake_xlib import fake_x11, fake_xss

XP = "steam_backlog_enforcer._x_probe"


class TestLoadLibraries:
    def test_returns_all_three_when_present(self) -> None:
        x11, xss, xres = MagicMock(), MagicMock(), MagicMock()
        with patch(f"{XP}.ctypes.CDLL", side_effect=[x11, xss, xres]):
            loaded = load_libraries()
        assert loaded[0] is x11
        assert loaded[1] is xss
        assert loaded[2] is xres

    def test_missing_xres_is_tolerated(self) -> None:
        x11, xss = MagicMock(), MagicMock()
        with patch(f"{XP}.ctypes.CDLL", side_effect=[x11, xss, OSError("no")]):
            loaded = load_libraries()
        assert loaded[0] is x11
        assert loaded[2] is None

    def test_missing_core_libraries_raise(self) -> None:
        with (
            patch(f"{XP}.ctypes.CDLL", side_effect=OSError("no libX11")),
            pytest.raises(XProbeError),
        ):
            load_libraries()


class TestConnect:
    def test_opens_once_and_caches(self) -> None:
        x11 = fake_x11()
        probe = XProbe(libraries=(x11, fake_xss(), None))
        first = probe.connect()
        assert probe.connect() is first
        assert x11.XOpenDisplay.call_count == 1

    def test_loads_libraries_when_none_were_injected(self) -> None:
        libs = (fake_x11(), fake_xss(), None)
        with patch(f"{XP}.load_libraries", return_value=libs) as loader:
            XProbe().connect()
        loader.assert_called_once_with()

    def test_a_null_display_raises(self) -> None:
        probe = XProbe(libraries=(fake_x11(display=0), fake_xss(), None))
        with pytest.raises(XProbeError, match="XOpenDisplay"):
            probe.connect()

    def test_an_error_handler_is_installed(self) -> None:
        # Xlib's default handler calls exit(1); a window vanishing mid-query
        # must not be able to take the daemon down.
        x11 = fake_x11()
        XProbe(libraries=(x11, fake_xss(), None)).connect()
        x11.XSetErrorHandler.assert_called_once()


class TestClose:
    def test_closing_an_open_connection_releases_it(self) -> None:
        x11 = fake_x11()
        probe = XProbe(libraries=(x11, fake_xss(), None))
        probe.connect()
        probe.close()
        x11.XCloseDisplay.assert_called_once()
        probe.connect()
        assert x11.XOpenDisplay.call_count == 2

    def test_closing_an_unopened_connection_is_a_no_op(self) -> None:
        x11 = fake_x11()
        XProbe(libraries=(x11, fake_xss(), None)).close()
        x11.XCloseDisplay.assert_not_called()


class TestIdleSeconds:
    def test_converts_milliseconds_to_seconds(self) -> None:
        probe = XProbe(libraries=(fake_x11(), fake_xss(idle_ms=4500), None))
        assert probe.idle_seconds() == 4.5

    def test_a_failed_allocation_raises(self) -> None:
        probe = XProbe(libraries=(fake_x11(), fake_xss(allocated=False), None))
        with pytest.raises(XProbeError, match="AllocInfo"):
            probe.idle_seconds()

    def test_a_failed_query_raises_and_still_frees(self) -> None:
        x11 = fake_x11()
        probe = XProbe(libraries=(x11, fake_xss(ok=False), None))
        with pytest.raises(XProbeError, match="QueryInfo"):
            probe.idle_seconds()
        x11.XFree.assert_called_once()


class TestErrorHandler:
    def test_swallows_the_error_and_reports_success(self) -> None:
        assert _ignore_x_error(None, None) == 0


class TestRootWindow:
    def test_returns_the_default_root(self) -> None:
        conn = MagicMock()
        conn.x11.XDefaultRootWindow.return_value = 0x99
        assert root_window(conn) == 0x99
