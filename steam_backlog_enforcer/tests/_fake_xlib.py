"""Fake libX11 / libXss / libXRes handles so no test needs an X server.

The real modules talk to X through ``ctypes``, which means the seam worth
faking is the shared-library handle itself. These stand-ins return the same
kinds of values Xlib does — an integer display pointer, a struct pointer, a
status code — and, where the C API writes through a pointer argument, actually
write through it, so the calling code is exercised rather than bypassed.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from collections.abc import Callable


def fake_x11(*, display: int = 0x1234, root: int = 0x50, atom: int = 7) -> MagicMock:
    """Build a libX11 stand-in.

    Args:
        display: Value ``XOpenDisplay`` returns; ``0`` means "cannot connect".
        root: Value ``XDefaultRootWindow`` returns.
        atom: Value ``XInternAtom`` returns; ``0`` means "no such atom".

    Returns:
        The fake handle.
    """
    lib = MagicMock(name="libX11")
    lib.XOpenDisplay.return_value = display
    lib.XDefaultRootWindow.return_value = root
    lib.XInternAtom.return_value = atom
    return lib


def fake_xss(*, idle_ms: int = 0, allocated: bool = True, ok: bool = True) -> MagicMock:
    """Build a libXss stand-in.

    Args:
        idle_ms: Idle milliseconds reported by ``XScreenSaverQueryInfo``.
        allocated: Whether ``XScreenSaverAllocInfo`` returns a struct.
        ok: Whether ``XScreenSaverQueryInfo`` succeeds.

    Returns:
        The fake handle.
    """
    lib = MagicMock(name="libXss")
    if allocated:
        info = MagicMock(name="XScreenSaverInfo")
        info.contents.idle = idle_ms
        lib.XScreenSaverAllocInfo.return_value = info
    else:
        lib.XScreenSaverAllocInfo.return_value = 0
    lib.XScreenSaverQueryInfo.return_value = 1 if ok else 0
    return lib


def property_writer(
    *, status: int = 0, nitems: int = 1, value: int = 4321, null: bool = False
) -> Callable[..., int]:
    """Build an ``XGetWindowProperty`` stand-in that writes its out-params.

    Args:
        status: Return code; non-zero means failure.
        nitems: Number of items to report.
        value: The first 32-bit value to hand back.
        null: Whether to leave the property pointer NULL.

    Returns:
        A callable with ``XGetWindowProperty``'s signature.
    """
    # Kept alive for the lifetime of the fake: the pointer written into the
    # caller's out-param must not dangle.
    keepalive: list[ctypes.c_ulong] = []

    def impl(  # signature mirrors the C function
        _display: object,
        _window: object,
        _atom: object,
        _offset: object,
        _length: object,
        _delete: object,
        _req_type: object,
        _actual_type: object,
        _actual_format: object,
        nitems_ref: object,
        _bytes_after: object,
        prop_ref: object,
    ) -> int:
        nitems_ref._obj.value = nitems  # type-erased ctypes byref holder
        if not null:
            holder = ctypes.c_ulong(value)
            keepalive.append(holder)
            prop_ref._obj.contents = holder
        return status

    return impl
