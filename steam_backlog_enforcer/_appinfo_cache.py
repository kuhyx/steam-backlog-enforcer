"""Selected apps from the Steam client's own cache, ``appcache/appinfo.vdf``.

The same v29 layout steam-game-installer's ``appinfo_cache`` reads (magic
0x07564429): u32 magic, u32 universe, i64 offset of a string table; then per
app: u32 appid, u32 size, ``size`` bytes made of a 60-byte header and binary
key-values whose keys are u32 indexes into the string table. Appid 0 ends the
list. The table is a u32 count followed by NUL-terminated strings.

Only the apps asked for are decoded; the rest are skipped by their size, so a
tool-step check stays cheap on the ~12 MB file. Every scalar comes back as a
string, as Steam's text VDF prints it. Reads only.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Final

from steam_installer.appinfo_kv import HEADER, MAGIC, read_block, string_table

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from steam_backlog_enforcer._vdf_text import VdfNode

# "SteamPlay 2.0 Manifests": its extended/app_mappings is Valve's per-game
# tool pick (e.g. a broken native port sent to Proton).
STEAM_PLAY_APP: Final = 891390


def default_path(steam_root: Path) -> Path:
    """Where Steam keeps the cache under *steam_root*."""
    return steam_root / "appcache" / "appinfo.vdf"


def read_apps(path: Path, wanted: Iterable[int]) -> dict[int, dict[str, VdfNode]]:
    """The ``appinfo`` block of each of *wanted* the cache holds.

    Raises:
        OSError: The file cannot be read.
        ValueError: It is not a v29 cache, or it is cut short or damaged.
    """
    buf = path.read_bytes()
    try:
        return _parse(buf, set(wanted))
    except (struct.error, IndexError) as exc:
        msg = "appinfo.vdf is cut short or damaged"
        raise ValueError(msg) from exc


def _parse(buf: bytes, wanted: set[int]) -> dict[int, dict[str, VdfNode]]:
    magic, _universe, table_offset = struct.unpack_from("<IIq", buf, 0)
    if magic != MAGIC:
        msg = f"unsupported appinfo.vdf format {magic:#010x}"
        raise ValueError(msg)
    strings = string_table(buf, table_offset)
    apps: dict[int, dict[str, VdfNode]] = {}
    pos = 16
    while True:
        app_id, size = struct.unpack_from("<II", buf, pos)
        if app_id == 0:
            return apps
        if app_id in wanted:
            data, _ = read_block(buf, pos + 8 + HEADER, strings)
            inner = data.get("appinfo")
            apps[app_id] = inner if isinstance(inner, dict) else data
        pos += 8 + size
