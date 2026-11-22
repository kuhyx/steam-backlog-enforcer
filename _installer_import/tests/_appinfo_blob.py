"""Build a binary appinfo.vdf (magic 0x07564429) for tests.

The writer mirrors what Steam stores: a header, one entry per app (appid,
size, 60 header bytes, binary key-values whose keys index a string table),
a zero appid terminator, then the string table itself.
"""

from __future__ import annotations

import struct

MAGIC = 0x07564429


def _kv(data: dict, strings: dict[str, int]) -> bytes:
    out = bytearray()
    for key, value in data.items():
        index = strings.setdefault(key, len(strings))
        if isinstance(value, dict):
            out += b"\x00" + struct.pack("<I", index) + _kv(value, strings)
        elif isinstance(value, int):
            out += b"\x02" + struct.pack("<I", index) + struct.pack("<i", value)
        elif isinstance(value, float):
            out += b"\x03" + struct.pack("<I", index) + struct.pack("<f", value)
        elif isinstance(value, tuple):
            kind, raw = value  # (7, u64) / (10, i64): the wide integer types
            fmt = "<Q" if kind == 7 else "<q"
            out += bytes([kind]) + struct.pack("<I", index) + struct.pack(fmt, raw)
        else:
            out += b"\x01" + struct.pack("<I", index) + value.encode() + b"\x00"
    return bytes(out) + b"\x08"


def encode(apps: dict[int, dict], change_number: int = 41062472) -> bytes:
    """Serialize `{appid: appinfo-dict}`; each dict is wrapped in "appinfo"."""
    strings: dict[str, int] = {}
    body = bytearray()
    for appid, data in apps.items():
        kv = _kv({"appinfo": data}, strings)
        header = struct.pack("<IIQ20sI20s", 2, 1795000000, 0, b"\0" * 20,
                             change_number, b"\0" * 20)
        payload = header + kv
        body += struct.pack("<II", appid, len(payload)) + payload
    body += struct.pack("<I", 0)
    table_offset = 16 + len(body)
    table = struct.pack("<I", len(strings)) + b"".join(
        key.encode() + b"\x00" for key in strings
    )
    return struct.pack("<IIq", MAGIC, 1, table_offset) + bytes(body) + table
