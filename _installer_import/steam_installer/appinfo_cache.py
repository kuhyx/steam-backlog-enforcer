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
from pathlib import Path

from steam_installer.library import find_steam_root

MAGIC = 0x07564429
_HEADER = 60
FIX = "start Steam once, let it sync, rerun"

# Fixed-width value types: KV type byte -> struct format.
_SCALARS = {2: "<i", 3: "<f", 4: "<i", 6: "<i", 7: "<Q", 10: "<q"}

_memo: dict[Path, tuple[tuple[int, int], dict[int, dict]]] = {}


class CacheError(Exception):
    pass


def default_path() -> Path:
    return find_steam_root() / "appcache" / "appinfo.vdf"


def load(path: Path | None = None) -> dict[int, dict]:
    """Every app in the cache, appid -> its `appinfo` block.

    Parsed once per file version: four lookups in one run would otherwise
    parse the ~100 MB file four times.
    """
    path = path or default_path()
    try:
        stat = path.stat()
    except OSError as exc:
        raise CacheError(f"cannot read Steam's app cache {path}: {FIX}") from exc
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _memo.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    apps = _parse(path.read_bytes())
    _memo[path] = (key, apps)
    return apps


def _parse(buf: bytes) -> dict[int, dict]:
    magic, _universe, table_offset = struct.unpack_from("<IIq", buf, 0)
    if magic != MAGIC:
        raise CacheError(f"unsupported appinfo.vdf format {magic:#010x}")
    strings = _string_table(buf, table_offset)
    apps: dict[int, dict] = {}
    pos = 16
    while True:
        appid, size = struct.unpack_from("<II", buf, pos)
        if appid == 0:
            return apps
        data, _ = _kv(buf, pos + 8 + _HEADER, strings)
        inner = data.get("appinfo")
        apps[appid] = inner if isinstance(inner, dict) else data
        pos += 8 + size


def _string_table(buf: bytes, offset: int) -> list[str]:
    (count,) = struct.unpack_from("<I", buf, offset)
    pos = offset + 4
    out: list[str] = []
    for _ in range(count):
        end = buf.index(b"\0", pos)
        out.append(buf[pos:end].decode("utf-8", "replace"))
        pos = end + 1
    return out


def _kv(buf: bytes, pos: int, strings: list[str]) -> tuple[dict, int]:
    out: dict = {}
    while True:
        kind = buf[pos]
        pos += 1
        if kind == 8:
            return out, pos
        (index,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        key = strings[index]
        if kind == 0:
            out[key], pos = _kv(buf, pos, strings)
        elif kind == 1:
            end = buf.index(b"\0", pos)
            out[key] = buf[pos:end].decode("utf-8", "replace")
            pos = end + 1
        elif kind in _SCALARS:
            fmt = _SCALARS[kind]
            (value,) = struct.unpack_from(fmt, buf, pos)
            out[key] = str(value)
            pos += struct.calcsize(fmt)
        else:
            raise CacheError(f"unsupported value type {kind} in appinfo.vdf")
