"""Read app info from the Steam client's own cache, `appcache/appinfo.vdf`.

This replaced `steamcmd +app_info_print`. On 2026-11-22 all 11 compared
fields for app 1201270 (name, installdir, build id, change number, depot
gids, ...) matched steamcmd's answer exactly. The cache is only as fresh as
Steam's last run, which is why callers check its gids against what
depotdownloader actually fetched.

Layout (magic 0x07564429): u32 magic, u32 universe, i64 offset of a string
table; then per app: u32 appid, u32 size, `size` bytes made of a 60-byte
header and binary key-values whose keys are u32 indexes into the string
table. Appid 0 ends the list. The table is a u32 count followed by
NUL-terminated strings.

Every scalar comes back as a string, the way `app_info_print` printed it:
the rest of the tool compares `== "1"` and `!= str(appid)`, and an int there
would silently change which depots count.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from steam_installer import errors
from steam_installer.appinfo_kv import (
    HEADER,
    MAGIC,
    AppinfoFormatError,
    read_block,
    string_table,
)
from steam_installer.library import find_steam_root

if TYPE_CHECKING:
    from pathlib import Path

FIX = "start Steam once, let it sync, rerun"

_memo: dict[Path, tuple[tuple[int, int], dict[int, dict[str, Any]]]] = {}


class CacheError(errors.InstallerError):
    """Steam's appinfo cache cannot be read."""


def default_path() -> Path:
    """Where Steam keeps its binary appinfo cache."""
    return find_steam_root() / "appcache" / "appinfo.vdf"


def load(path: Path | None = None) -> dict[int, dict[str, Any]]:
    """Every app in the cache, appid -> its `appinfo` block.

    Parsed once per file version: four lookups in one run would otherwise
    parse the ~100 MB file four times.
    """
    path = path or default_path()
    try:
        stat = path.stat()
    except OSError as exc:
        msg = f"cannot read Steam's app cache {path}: {FIX}"
        raise CacheError(msg) from exc
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _memo.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    apps = _parse(path.read_bytes())
    _memo[path] = (key, apps)
    return apps


def _parse(buf: bytes) -> dict[int, dict[str, Any]]:
    magic, _universe, table_offset = struct.unpack_from("<IIq", buf, 0)
    if magic != MAGIC:
        msg = f"unsupported appinfo.vdf format {magic:#010x}"
        raise CacheError(msg)
    strings = string_table(buf, table_offset)
    apps: dict[int, dict[str, Any]] = {}
    pos = 16
    while True:
        appid, size = struct.unpack_from("<II", buf, pos)
        if appid == 0:
            return apps
        try:
            data, _ = read_block(buf, pos + 8 + HEADER, strings)
        except AppinfoFormatError as exc:
            raise CacheError(str(exc)) from exc
        inner = data.get("appinfo")
        apps[appid] = inner if isinstance(inner, dict) else data
        pos += 8 + size
