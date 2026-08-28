"""An X11 connection for reading input-idle time, without forking.

The enforce loop ticks every three seconds, so shelling out to ``xprintidle``
would cost roughly twenty forks a minute for a number the X server hands over
directly. This talks to libX11 and libXss through ``ctypes`` over one cached
connection instead. Focused-window resolution lives in :mod:`_x_focus`.

The daemon runs as root with ``DISPLAY=:0`` and ``HOME=/home/kuhy`` set by its
unit file, which is what lets it authenticate against the user's session.

Two details are load-bearing:

**A no-op X error handler is installed.** Xlib's default handler calls
``exit(1)``. Asking about a window that vanished mid-query is an ordinary race,
not a fatal condition, and the enforcer must not die of it.

**Every failure raises :class:`XProbeError`.** The caller bills the tick when a
probe cannot answer, so returning a bland ``None`` would be indistinguishable
from a real "not idle" and would quietly become free gaming.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Final

_MILLISECONDS_PER_SECOND: Final = 1000.0


class XProbeError(RuntimeError):
    """The X server could not be reached or did not answer."""


class _ScreenSaverInfo(ctypes.Structure):
    """Mirror of libXss's ``XScreenSaverInfo``."""

    _fields_ = (
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("event_mask", ctypes.c_ulong),
    )


@dataclass(frozen=True)
class Conn:
    """An open display and the libraries it was opened with.

    ``xres`` is optional: the X-Resource extension is the fallback for windows
    that advertise no ``_NET_WM_PID``, and a server without it simply means
    those windows cannot be attributed.
    """

    display: ctypes.c_void_p
    x11: ctypes.CDLL
    xss: ctypes.CDLL
    xres: ctypes.CDLL | None


_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _ignore_x_error(_display: ctypes.c_void_p, _event: ctypes.c_void_p) -> int:
    """Swallow an X protocol error instead of letting Xlib call ``exit``."""
    return 0


def load_libraries() -> tuple[ctypes.CDLL, ctypes.CDLL, ctypes.CDLL | None]:
    """Load libX11, libXss and — if present — libXRes.

    Returns:
        The ``(x11, xss, xres)`` handles; ``xres`` is ``None`` when absent.

    Raises:
        XProbeError: If libX11 or libXss is missing.
    """
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")
    except OSError as exc:
        msg = f"X client libraries unavailable: {exc}"
        raise XProbeError(msg) from exc
    try:
        xres: ctypes.CDLL | None = ctypes.CDLL("libXRes.so.1")
    except OSError:
        xres = None
    return x11, xss, xres


Libraries = tuple[ctypes.CDLL, ctypes.CDLL, ctypes.CDLL | None]


class XProbe:
    """A cached X connection answering idle-time queries."""

    def __init__(self, *, libraries: Libraries | None = None) -> None:
        """Store the library handles; the connection is opened lazily.

        Args:
            libraries: Pre-loaded ``(x11, xss, xres)`` handles, for tests.
        """
        self._libraries = libraries
        self._conn: Conn | None = None
        # Xlib keeps only a borrowed pointer, so the trampoline must outlive it.
        self._handler = _ERROR_HANDLER(_ignore_x_error)

    def connect(self) -> Conn:
        """Return the open connection, opening it on first use.

        Returns:
            The live connection.

        Raises:
            XProbeError: If the display cannot be opened.
        """
        if self._conn is not None:
            return self._conn

        if self._libraries is None:
            self._libraries = load_libraries()
        x11, xss, xres = self._libraries

        x11.XSetErrorHandler(self._handler)
        x11.XOpenDisplay.restype = ctypes.c_void_p
        display = x11.XOpenDisplay(None)
        if not display:
            msg = "XOpenDisplay returned NULL; no reachable X session"
            raise XProbeError(msg)

        self._conn = Conn(display=ctypes.c_void_p(display), x11=x11, xss=xss, xres=xres)
        return self._conn

    def close(self) -> None:
        """Drop the connection so the next query reconnects."""
        if self._conn is not None:
            self._conn.x11.XCloseDisplay(self._conn.display)
            self._conn = None

    def idle_seconds(self) -> float:
        """Return seconds since the last keyboard or pointer input.

        Note that a game controller does **not** reset this counter unless it
        is presented to X as a keyboard or pointer, which is why the caller
        drops the idle criterion while a controller is connected.

        Returns:
            The idle time in seconds.

        Raises:
            XProbeError: If the query fails.
        """
        conn = self.connect()

        conn.xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_ScreenSaverInfo)
        info = conn.xss.XScreenSaverAllocInfo()
        if not info:
            msg = "XScreenSaverAllocInfo returned NULL"
            raise XProbeError(msg)

        try:
            queried = conn.xss.XScreenSaverQueryInfo(
                conn.display, ctypes.c_ulong(root_window(conn)), info
            )
            if not queried:
                msg = "XScreenSaverQueryInfo failed; MIT-SCREEN-SAVER missing?"
                raise XProbeError(msg)
            return float(info.contents.idle) / _MILLISECONDS_PER_SECOND
        finally:
            conn.x11.XFree(info)


def root_window(conn: Conn) -> int:
    """Return the default root window id.

    Args:
        conn: Live connection.

    Returns:
        The root window id.
    """
    conn.x11.XDefaultRootWindow.restype = ctypes.c_ulong
    return int(conn.x11.XDefaultRootWindow(conn.display))
