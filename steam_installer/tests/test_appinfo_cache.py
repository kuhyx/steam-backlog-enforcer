"""Steam's local binary app-info cache, read without steamcmd."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from steam_installer import appinfo_cache
from steam_installer.appinfo_cache import _parse
from steam_installer.tests._appinfo_blob import encode

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, apps: dict[int, Any]) -> Path:
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(encode(apps))
    return path


def test_reads_every_app_and_unwraps_appinfo(tmp_path: Path) -> None:
    """Reads every app and unwraps appinfo."""
    path = _write(tmp_path, {10: {"common": {"name": "A"}}, 20: {"common": {}}})
    apps = appinfo_cache.load(path)
    assert set(apps) == {10, 20}
    assert apps[10] == {"common": {"name": "A"}}


def test_scalars_come_back_as_strings_like_app_info_print(tmp_path: Path) -> None:
    """The rest of the tool compares `== "1"` and `!= str(appid)`; an int here
    would silently drop a DLC app's own depots."""
    data = {
        "depots": {
            "5": {
                "dlcappid": 7,
                "optional": 1,
                "f": 1.5,
                "gid": (7, 2**63 + 5),
                "neg": (10, -3),
            }
        }
    }
    apps = appinfo_cache.load(_write(tmp_path, {7: data}))
    assert apps[7]["depots"]["5"] == {
        "dlcappid": "7",
        "optional": "1",
        "f": "1.5",
        "gid": str(2**63 + 5),
        "neg": "-3",
    }


def test_parse_is_cached_until_the_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parse is cached until the file changes."""
    path = _write(tmp_path, {1: {"common": {"name": "old"}}})
    assert appinfo_cache.load(path)[1]["common"]["name"] == "old"
    calls = []
    real = _parse

    def counting(buf: bytes) -> dict[int, dict[str, Any]]:
        calls.append(1)
        return real(buf)

    monkeypatch.setattr(appinfo_cache, "_parse", counting)
    appinfo_cache.load(path)
    assert calls == []
    path.write_bytes(encode({1: {"common": {"name": "newer"}}}))
    assert appinfo_cache.load(path)[1]["common"]["name"] == "newer"
    assert calls == [1]


def test_wrong_magic_is_refused(tmp_path: Path) -> None:
    """Wrong magic is refused."""
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(b"\x28\x44\x56\x07" + b"\0" * 20)
    with pytest.raises(appinfo_cache.CacheError, match="unsupported"):
        appinfo_cache.load(path)


def test_unknown_value_type_is_refused(tmp_path: Path) -> None:
    """Unknown value type is refused."""
    blob = bytearray(encode({1: {"common": {"name": "A"}}}))
    blob[16 + 8 + 60] = 9  # first KV type byte
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(bytes(blob))
    with pytest.raises(appinfo_cache.CacheError, match="value type 9"):
        appinfo_cache.load(path)


def test_missing_file_names_the_fix(tmp_path: Path) -> None:
    """Missing file names the fix."""
    with pytest.raises(appinfo_cache.CacheError, match="start Steam once"):
        appinfo_cache.load(tmp_path / "nope.vdf")


def test_entry_without_appinfo_wrapper_is_taken_as_is(tmp_path: Path) -> None:
    """Entry without appinfo wrapper is taken as is."""
    blob = encode({3: {"x": "y"}})
    # Rename the "appinfo" wrapper key in the string table.
    blob = blob.replace(b"appinfo\x00", b"appinfX\x00")
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(blob)
    assert appinfo_cache.load(path)[3] == {"appinfX": {"x": "y"}}


def test_default_path_is_under_the_steam_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default path is under the steam root."""
    monkeypatch.setattr(appinfo_cache, "find_steam_root", lambda: tmp_path)
    assert appinfo_cache.default_path() == tmp_path / "appcache" / "appinfo.vdf"
