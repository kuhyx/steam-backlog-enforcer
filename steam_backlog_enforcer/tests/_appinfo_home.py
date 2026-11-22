"""Fixture ``appcache/appinfo.vdf`` files in Steam's binary v29 layout.

Mirrors what :mod:`steam_backlog_enforcer._appinfo_cache` reads: a 16-byte
head (magic, universe, string-table offset), one record per app (appid, size,
60-byte header, binary key-values keyed by string-table index), appid 0, then
the string table. A Python ``int`` becomes a 32-bit int value (type 2).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from steam_backlog_enforcer._appinfo_cache import MAGIC, STEAM_PLAY_APP

if TYPE_CHECKING:
    from pathlib import Path

type Node = str | int | dict[str, Node]


def _encode(node: dict[str, Node], strings: list[str]) -> bytes:
    out = b""
    for key, value in node.items():
        if key not in strings:
            strings.append(key)
        index = struct.pack("<I", strings.index(key))
        if isinstance(value, dict):
            out += b"\x00" + index + _encode(value, strings)
        elif isinstance(value, int):
            out += b"\x02" + index + struct.pack("<i", value)
        else:
            out += b"\x01" + index + value.encode() + b"\0"
    return out + b"\x08"


def appinfo_bytes(apps: dict[int, dict[str, Node]], *, magic: int = MAGIC) -> bytes:
    """The binary cache holding *apps* (appid -> its ``appinfo`` block)."""
    strings: list[str] = []
    body = b""
    for app_id, block in apps.items():
        data = b"\0" * 60 + _encode({"appinfo": block}, strings)
        body += struct.pack("<II", app_id, len(data)) + data
    body += struct.pack("<I", 0)
    table = struct.pack("<I", len(strings)) + b"".join(
        s.encode() + b"\0" for s in strings
    )
    return struct.pack("<IIq", magic, 1, 16 + len(body)) + body + table


def game(oslist: str, **config: Node) -> dict[str, Node]:
    """A game's appinfo block with *oslist* and an optional ``config``."""
    return {"common": {"name": "G", "oslist": oslist}, "config": dict(config)}


def steam_play(mapped: tuple[int, ...] = ()) -> dict[str, Node]:
    """App 891390's block; *mapped* games get a Valve tool pick."""
    mappings: dict[str, Node] = {
        str(a): {"appid": str(a), "tool": "proton-experimental"} for a in mapped
    }
    return {"extended": {"app_mappings": mappings}}


def write_appinfo(
    root: Path, apps: dict[int, dict[str, Node]], *, steam_play_app: bool = True
) -> Path:
    """Write ``<root>/appcache/appinfo.vdf``; 891390 is added unless told not."""
    if steam_play_app:
        apps = {STEAM_PLAY_APP: steam_play()} | apps
    path = root / "appcache" / "appinfo.vdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(appinfo_bytes(apps))
    return path
