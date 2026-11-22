"""Binary key-value decoding shared by both readers of ``appinfo.vdf``.

``steam_installer.appinfo_cache`` (every app) and
``steam_backlog_enforcer._appinfo_cache`` (selected apps) read the same v29
layout; this module holds the parts they have in common: the string table and
the nested key-value blocks. It raises ``AppinfoFormatError`` (a ``ValueError``)
and each reader keeps the exception type its callers already handle.
"""

from __future__ import annotations

import struct
from typing import Any, Final

MAGIC: Final = 0x07564429
HEADER: Final = 60
# KV type bytes: a nested block, a NUL-terminated string, end of block.
_BLOCK: Final = 0
_STRING: Final = 1
_END: Final = 8
# Fixed-width value types: KV type byte -> struct format.
_SCALARS: Final = {2: "<i", 3: "<f", 4: "<i", 6: "<i", 7: "<Q", 10: "<q"}


class AppinfoFormatError(ValueError):
    """A key-value block holds a value type this decoder does not know."""


def string_table(buf: bytes, offset: int) -> list[str]:
    """The NUL-terminated strings (u32 count first) that keys index into."""
    (count,) = struct.unpack_from("<I", buf, offset)
    pos = offset + 4
    out: list[str] = []
    for _ in range(count):
        end = buf.index(b"\0", pos)
        out.append(buf[pos:end].decode("utf-8", "replace"))
        pos = end + 1
    return out


def read_block(buf: bytes, pos: int, strings: list[str]) -> tuple[dict[str, Any], int]:
    """Decode one key-value block at *pos*; return it and the next position.

    Every scalar comes back as a string, as Steam's text VDF prints it.
    """
    out: dict[str, Any] = {}
    while True:
        kind = buf[pos]
        pos += 1
        if kind == _END:
            return out, pos
        (index,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        key = strings[index]
        if kind == _BLOCK:
            out[key], pos = read_block(buf, pos, strings)
        elif kind == _STRING:
            end = buf.index(b"\0", pos)
            out[key] = buf[pos:end].decode("utf-8", "replace")
            pos = end + 1
        elif kind in _SCALARS:
            fmt = _SCALARS[kind]
            (value,) = struct.unpack_from(fmt, buf, pos)
            out[key] = str(value)
            pos += struct.calcsize(fmt)
        else:
            msg = f"unsupported value type {kind} in appinfo.vdf"
            raise AppinfoFormatError(msg)
