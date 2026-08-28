"""Tests for attributing the focused window to a process.

The XRes fallback is not a nicety: measured on this machine, Aseprite's window
carries no ``_NET_WM_PID`` at all, and treating that as "cannot tell" would
make the focus criterion useless for every application that behaves the same.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from steam_backlog_enforcer._x_focus import _XResValue, focused_pid, read_cardinal
from steam_backlog_enforcer._x_probe import Conn, XProbeError
from steam_backlog_enforcer.tests._fake_xlib import fake_x11, property_writer

if TYPE_CHECKING:
    from collections.abc import Callable


def _conn(x11: MagicMock, xres: MagicMock | None = None) -> Conn:
    """Wrap fake handles in a Conn, casting only at this one seam."""
    return Conn(
        display=ctypes.c_void_p(1),
        x11=cast("ctypes.CDLL", x11),
        xss=cast("ctypes.CDLL", MagicMock()),
        xres=None if xres is None else cast("ctypes.CDLL", xres),
    )


def _xres(
    *,
    pids: list[int] | None = None,
    entries: list[tuple[int, int, int | None]] | None = None,
    status: int = 0,
    null: bool = False,
) -> MagicMock:
    """Build a libXRes stand-in.

    Args:
        pids: Shorthand for well-formed PID entries.
        entries: Raw ``(mask, length, pid)`` rows; ``pid=None`` means a NULL
            value pointer, which the server can legitimately return.
        status: Return code; non-zero means the query failed.
        null: Whether to leave the results pointer NULL.
    """
    rows = (
        entries
        if entries is not None
        else [(1 << 1, 4, pid) for pid in (pids if pids is not None else [])]
    )
    lib = MagicMock(name="libXRes")
    array = (_XResValue * max(len(rows), 1))()
    keepalive: list[ctypes.c_uint32] = []
    for index, (mask, length, pid) in enumerate(rows):
        array[index].spec.mask = mask
        array[index].length = length
        if pid is None:
            array[index].value = None
        else:
            holder = ctypes.c_uint32(pid)
            keepalive.append(holder)
            array[index].value = ctypes.cast(
                ctypes.byref(holder), ctypes.c_void_p
            ).value

    def impl(
        _display: object,
        _n: object,
        _spec: object,
        count_ref: object,
        values_ref: object,
    ) -> int:
        count_ref._obj.value = len(rows)
        if not null:
            values_ref._obj.contents = array[0]
        return status

    lib.XResQueryClientIds.side_effect = impl
    lib._keepalive = (array, keepalive)
    return lib


class TestReadCardinal:
    def test_returns_the_first_value(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(value=99)
        assert read_cardinal(_conn(x11), 0x1, b"_NET_WM_PID") == 99

    def test_a_missing_atom_is_none(self) -> None:
        assert read_cardinal(_conn(fake_x11(atom=0)), 0x1, b"_NOPE") is None

    def test_a_failed_request_is_none(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(status=1)
        assert read_cardinal(_conn(x11), 0x1, b"_NET_WM_PID") is None

    def test_a_null_property_is_none(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(null=True)
        assert read_cardinal(_conn(x11), 0x1, b"_NET_WM_PID") is None

    def test_an_empty_property_is_none_and_still_freed(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(nitems=0)
        assert read_cardinal(_conn(x11), 0x1, b"_NET_WM_PID") is None
        x11.XFree.assert_called_once()


class TestFocusedPid:
    def test_no_focused_window_is_none(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(value=0)
        assert focused_pid(_conn(x11)) is None

    def test_uses_net_wm_pid_when_present(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = property_writer(value=555)
        assert focused_pid(_conn(x11)) == 555

    def test_falls_back_to_xres(self) -> None:
        x11 = fake_x11()
        # The active window resolves, then _NET_WM_PID comes back absent.
        x11.XGetWindowProperty.side_effect = _sequence(
            property_writer(value=0x400001), property_writer(nitems=0)
        )
        assert focused_pid(_conn(x11, _xres(pids=[8080]))) == 8080

    def test_raises_when_neither_source_can_attribute_the_window(self) -> None:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = _sequence(
            property_writer(value=0x400001), property_writer(nitems=0)
        )
        with pytest.raises(XProbeError, match="XRes"):
            focused_pid(_conn(x11, None))


class TestXResFallback:
    def _focus_without_wm_pid(self) -> MagicMock:
        x11 = fake_x11()
        x11.XGetWindowProperty.side_effect = _sequence(
            property_writer(value=0x400001), property_writer(nitems=0)
        )
        return x11

    def test_a_failed_query_gives_no_pid(self) -> None:
        with pytest.raises(XProbeError):
            focused_pid(_conn(self._focus_without_wm_pid(), _xres(status=1)))

    def test_a_null_result_gives_no_pid(self) -> None:
        with pytest.raises(XProbeError):
            focused_pid(_conn(self._focus_without_wm_pid(), _xres(null=True)))

    def test_no_entries_gives_no_pid(self) -> None:
        with pytest.raises(XProbeError):
            focused_pid(_conn(self._focus_without_wm_pid(), _xres(pids=[])))

    def test_a_non_pid_entry_is_skipped(self) -> None:
        # XRes can return XID rows alongside PID rows; only the PID row counts.
        xres = _xres(entries=[(1 << 0, 4, 111), (1 << 1, 4, 222)])
        assert focused_pid(_conn(self._focus_without_wm_pid(), xres)) == 222

    def test_a_short_entry_is_skipped(self) -> None:
        xres = _xres(entries=[(1 << 1, 0, 111), (1 << 1, 4, 333)])
        assert focused_pid(_conn(self._focus_without_wm_pid(), xres)) == 333

    def test_a_null_value_is_skipped(self) -> None:
        xres = _xres(entries=[(1 << 1, 4, None), (1 << 1, 4, 444)])
        assert focused_pid(_conn(self._focus_without_wm_pid(), xres)) == 444

    def test_the_result_is_destroyed(self) -> None:
        xres = _xres(pids=[4242])
        focused_pid(_conn(self._focus_without_wm_pid(), xres))
        xres.XResClientIdsDestroy.assert_called_once()


def _sequence(*writers: Callable[..., int]) -> Callable[..., int]:
    """Chain property writers so successive calls use successive fakes."""
    calls = iter(writers)

    def impl(*args: object) -> int:
        return next(calls)(*args)

    return impl
