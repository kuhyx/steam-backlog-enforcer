"""Tests for _tool_need: a game Valve runs natively needs none of the tools.

Native means: no CompatToolMapping entry of kuhy's (or an empty one), ``linux``
in the app cache's ``common/oslist``, and no Valve tool pick for it (neither the
game's own ``config/app_mappings`` nor app 891390's). Any doubt keeps them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._appinfo_cache import STEAM_PLAY_APP, read_apps
from steam_backlog_enforcer._tool_need import NATIVE_TOOL, ToolNeed, tool_need
from steam_backlog_enforcer.tests._appinfo_home import (
    Node,
    appinfo_bytes,
    game,
    steam_play,
    write_appinfo,
)
from steam_backlog_enforcer.tests._tool_home import config_vdf, make_home

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer._tool_need"
NATIVE = "windows,macos,linux"
COVERED = ToolNeed(
    needed=False, reason=f"every installed game runs on {NATIVE_TOOL} or natively"
)


def _keep(reason: str) -> ToolNeed:
    return ToolNeed(needed=True, reason=reason)


@pytest.fixture(name="root")
def fixture_root(tmp_path: Path) -> Path:
    """A fixture Steam root (conftest already owns tmp_path/steamapps)."""
    return tmp_path / "Steam"


@pytest.fixture(autouse=True)
def _steam_closed() -> Iterator[None]:
    with patch(f"{PKG}.steam_client_running", return_value=False):
        yield


def test_native_unmapped_game_beside_a_mapped_one_is_covered(root: Path) -> None:
    """C12: DUSK (native, unmapped) next to Princess Remedy (mapped)."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 20: None})
    write_appinfo(root, {10: game("windows"), 20: game(NATIVE), 99: game("linux")})
    assert tool_need(steamapps) == COVERED


def test_empty_mapping_entry_counts_as_unmapped(root: Path) -> None:
    """An entry Steam left with name "" is no pick of kuhy's."""
    steamapps = make_home(root, {20: None})
    (root / "config" / "config.vdf").write_text(config_vdf({20: ""}))
    write_appinfo(root, {20: game(NATIVE, contenttype=3)})
    assert tool_need(steamapps) == COVERED


def test_native_game_forced_onto_another_tool_keeps(root: Path) -> None:
    """kuhy's own pick of Valve Proton for a native game keeps them."""
    steamapps = make_home(root, {20: "proton_experimental"})
    write_appinfo(root, {20: game(NATIVE)})
    assert tool_need(steamapps) == _keep(f"AppID=20 has no {NATIVE_TOOL} mapping")


def test_windows_only_unmapped_game_keeps(root: Path) -> None:
    """An unmapped Windows game runs on Valve's Proton: keep."""
    steamapps = make_home(root, {20: None})
    write_appinfo(root, {20: game("windows")})
    assert tool_need(steamapps) == _keep(f"AppID=20 has no {NATIVE_TOOL} mapping")


@pytest.mark.parametrize("block", [{"config": {}}, {"common": "x"}, {"common": {}}])
def test_no_os_list_keeps(root: Path, block: dict[str, Node]) -> None:
    """No readable OS list is no proof of a Linux build."""
    steamapps = make_home(root, {20: None})
    write_appinfo(root, {20: block})
    assert tool_need(steamapps) == _keep(f"AppID=20 has no {NATIVE_TOOL} mapping")


def test_game_own_tool_pick_keeps(root: Path) -> None:
    """A native game whose appinfo picks a runtime (240 picks sniper) keeps."""
    steamapps = make_home(root, {20: None})
    pick: dict[str, Node] = {"0": {"tool": "steamlinuxruntime_4"}}
    write_appinfo(root, {20: game(NATIVE, app_mappings=pick)})
    assert tool_need(steamapps) == _keep("AppID=20 has a Valve tool mapping")


def test_valve_steam_play_pick_keeps(root: Path) -> None:
    """A native game app 891390 sends to Proton keeps them."""
    steamapps = make_home(root, {20: None})
    write_appinfo(root, {STEAM_PLAY_APP: steam_play((20,)), 20: game(NATIVE)})
    assert tool_need(steamapps) == _keep("AppID=20 has a Valve tool mapping")


@pytest.mark.parametrize("block", [{}, {"extended": {}}, {"extended": "x"}])
def test_unusable_steam_play_app_keeps(root: Path, block: dict[str, Node]) -> None:
    """Without Valve's pick list no game can be called native."""
    steamapps = make_home(root, {20: None})
    apps = {STEAM_PLAY_APP: block, 20: game(NATIVE)}
    write_appinfo(root, apps, steam_play_app=False)
    assert tool_need(steamapps) == _keep("app 891390 has no app_mappings")


def test_missing_steam_play_app_keeps(root: Path) -> None:
    """No app 891390 in the cache keeps them."""
    steamapps = make_home(root, {20: None})
    write_appinfo(root, {20: game(NATIVE)}, steam_play_app=False)
    assert tool_need(steamapps) == _keep("app 891390 has no app_mappings")


def test_game_missing_from_cache_keeps(root: Path) -> None:
    """A game the cache does not hold keeps them."""
    steamapps = make_home(root, {20: None})
    write_appinfo(root, {})
    assert tool_need(steamapps) == _keep("AppID=20 not in appinfo.vdf")


def test_missing_cache_keeps(root: Path) -> None:
    """No appinfo.vdf keeps them."""
    steamapps = make_home(root, {20: None})
    assert tool_need(steamapps) == _keep("appinfo.vdf unreadable")


def test_mapped_games_never_read_the_cache(root: Path) -> None:
    """All mapped: no cache needed, the old reason stands."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    assert tool_need(steamapps) == ToolNeed(
        needed=False, reason=f"every installed game runs on {NATIVE_TOOL}"
    )


@pytest.mark.parametrize(
    "damage",
    [
        appinfo_bytes({20: game(NATIVE)}, magic=0x07564428),
        appinfo_bytes({20: game(NATIVE)})[:40],
        b"\x29\x44",
    ],
    ids=["old-format", "truncated", "short"],
)
def test_malformed_cache_keeps(root: Path, damage: bytes) -> None:
    """An old-format, cut-short or tiny cache keeps them."""
    steamapps = make_home(root, {20: None})
    (root / "appcache").mkdir()
    (root / "appcache" / "appinfo.vdf").write_bytes(damage)
    assert tool_need(steamapps) == _keep("appinfo.vdf malformed")


def test_unknown_value_type_is_malformed(tmp_path: Path) -> None:
    """A value type the reader does not know is an error, not a guess."""
    good = appinfo_bytes({20: {"common": {"oslist": "linux"}}})
    bad = good.replace(b"\x01\x02\x00\x00\x00linux", b"\x09\x02\x00\x00\x00linux")
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(bad)
    with pytest.raises(ValueError, match="value type 9"):
        read_apps(path, {20})


def test_read_apps_decodes_only_what_is_asked(tmp_path: Path) -> None:
    """Other apps are skipped by size; ints decode as strings."""
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(appinfo_bytes({20: {"a": 1}, 30: {"b": "x"}}))
    assert read_apps(path, {20, 40}) == {20: {"a": "1"}}
