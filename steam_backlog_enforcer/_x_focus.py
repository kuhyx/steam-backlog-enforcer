"""Resolving which process owns the focused X window.

``_NET_WM_PID`` is the obvious answer and the one every window-manager guide
names, but it is a *convention* toolkits opt into, not a guarantee. Measured on
this machine: Aseprite's window carries no ``_NET_WM_PID`` at all. Treating that
as "cannot tell" and billing the tick would make the focus criterion useless for
every such application — including, plausibly, games.

So the absent property falls through to the X-Resource extension, which asks the
*server* which client owns the window rather than trusting the client to have
announced itself. Verified against the same Aseprite window: ``XResQueryClientIds``
returned the correct PID where ``_NET_WM_PID`` returned nothing.
"""

from __future__ import annotations

import ctypes
from typing import Final

from steam_backlog_enforcer._x_probe import Conn, XProbeError, root_window

# XGetWindowProperty's `req_type`: accept whatever type the property carries.
_ANY_PROPERTY_TYPE: Final = 0
_SUCCESS: Final = 0

# XInternAtom's `only_if_exists`: never create an atom just by asking for it.
# An int, not a bool: it is a C ``Bool`` argument, not a Python flag.
_ONLY_IF_EXISTS: Final = 1

# XRes client-id spec masks, from <X11/extensions/XRes.h>.
_XRES_PID_MASK: Final = 1 << 1
_XRES_PID_BYTES: Final = 4


class _XResSpec(ctypes.Structure):
    """Mirror of libXRes's ``XResClientIdSpec``."""

    _fields_ = (("client", ctypes.c_ulong), ("mask", ctypes.c_uint))


class _XResValue(ctypes.Structure):
    """Mirror of libXRes's ``XResClientIdValue``."""

    _fields_ = (
        ("spec", _XResSpec),
        ("length", ctypes.c_long),
        ("value", ctypes.c_void_p),
    )


def focused_pid(conn: Conn) -> int | None:
    """Return the PID owning the focused window.

    Args:
        conn: Live connection.

    Returns:
        The PID, or ``None`` when nothing is focused — a real answer, not a
        failure.

    Raises:
        XProbeError: If a window is focused but cannot be attributed to a
            process, which the caller must treat as "cannot tell" and bill.
    """
    active = read_cardinal(conn, root_window(conn), b"_NET_ACTIVE_WINDOW")
    if not active:
        return None

    declared = read_cardinal(conn, active, b"_NET_WM_PID")
    if declared is not None:
        return declared

    resolved = _xres_pid(conn, active)
    if resolved is None:
        msg = f"window {active:#x} has no _NET_WM_PID and XRes could not name it"
        raise XProbeError(msg)
    return resolved


def _xres_pid(conn: Conn, window: int) -> int | None:
    """Ask the X server which process owns *window*.

    Args:
        conn: Live connection.
        window: Window to attribute.

    Returns:
        The owning PID, or ``None`` if XRes is unavailable or has no answer.
    """
    if conn.xres is None:
        return None

    spec = _XResSpec(client=window, mask=_XRES_PID_MASK)
    count = ctypes.c_long()
    values = ctypes.POINTER(_XResValue)()

    status = conn.xres.XResQueryClientIds(
        conn.display,
        ctypes.c_long(1),
        ctypes.byref(spec),
        ctypes.byref(count),
        ctypes.byref(values),
    )
    if status != _SUCCESS or not values:
        return None

    try:
        return _first_pid(values, count.value)
    finally:
        conn.xres.XResClientIdsDestroy(count, values)


def _first_pid(values: ctypes._Pointer[_XResValue], count: int) -> int | None:
    """Return the first PID among *count* XRes client-id values.

    Args:
        values: Array returned by ``XResQueryClientIds``.
        count: Number of entries in *values*.

    Returns:
        The PID, or ``None`` if no entry carries one.
    """
    for index in range(count):
        entry = values[index]
        if entry.spec.mask != _XRES_PID_MASK or entry.length < _XRES_PID_BYTES:
            continue
        if not entry.value:
            continue
        return int(ctypes.cast(entry.value, ctypes.POINTER(ctypes.c_uint32))[0])
    return None


def read_cardinal(conn: Conn, window: int, name: bytes) -> int | None:
    """Read the first 32-bit value of window property *name*.

    Args:
        conn: Live connection.
        window: Window to query.
        name: Property name, e.g. ``b"_NET_WM_PID"``.

    Returns:
        The value, or ``None`` if the property is absent or empty.
    """
    conn.x11.XInternAtom.restype = ctypes.c_ulong
    atom = conn.x11.XInternAtom(conn.display, name, _ONLY_IF_EXISTS)
    if not atom:
        return None

    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    prop = ctypes.POINTER(ctypes.c_ulong)()

    status = conn.x11.XGetWindowProperty(
        conn.display,
        ctypes.c_ulong(window),
        ctypes.c_ulong(atom),
        ctypes.c_long(0),
        ctypes.c_long(1),
        ctypes.c_int(0),
        ctypes.c_ulong(_ANY_PROPERTY_TYPE),
        ctypes.byref(actual_type),
        ctypes.byref(actual_format),
        ctypes.byref(nitems),
        ctypes.byref(bytes_after),
        ctypes.byref(prop),
    )
    if status != _SUCCESS or not prop:
        return None
    try:
        if nitems.value == 0:
            return None
        return int(prop[0])
    finally:
        conn.x11.XFree(prop)
