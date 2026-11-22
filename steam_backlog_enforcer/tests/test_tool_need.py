"""Tests for _tool_need: when the three Steam tools may go, on fixture homes."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._tool_need import NATIVE_TOOL, ToolNeed, tool_need
from steam_backlog_enforcer.tests._tool_home import make_home

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer._tool_need"
KEEP_UNMAPPED = ToolNeed(needed=True, reason=f"AppID=20 has no {NATIVE_TOOL} mapping")


@pytest.fixture(name="root")
def fixture_root(tmp_path: Path) -> Path:
    """A fixture Steam root (conftest already owns tmp_path/steamapps)."""
    return tmp_path / "Steam"


@pytest.fixture(autouse=True)
def _steam_closed() -> Iterator[None]:
    """Steam is closed unless a test says otherwise: never ask the live pgrep."""
    with patch(f"{PKG}.steam_client_running", return_value=False):
        yield


def test_all_mapped_means_not_needed(root: Path) -> None:
    """Every game on proton-cachyos-native: the tools may go."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 20: NATIVE_TOOL})
    assert tool_need(steamapps) == ToolNeed(
        needed=False, reason=f"every installed game runs on {NATIVE_TOOL}"
    )


def test_one_unmapped_game_keeps(root: Path) -> None:
    """One game with no mapping entry keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 20: None})
    assert tool_need(steamapps) == KEEP_UNMAPPED


def test_mapping_naming_another_tool_keeps(root: Path) -> None:
    """A game mapped to another tool keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 20: "proton_experimental"})
    assert tool_need(steamapps) == KEEP_UNMAPPED


def test_mapping_entry_that_is_not_a_block_keeps(root: Path) -> None:
    """A mapping entry with no name block keeps them."""
    steamapps = make_home(root, {20: NATIVE_TOOL})
    config = root / "config" / "config.vdf"
    config.write_text(
        '"InstallConfigStore" { "Software" { "Valve" { "Steam" {'
        ' "CompatToolMapping" { "20" "proton-cachyos-native" } } } } }'
    )
    assert tool_need(steamapps) == KEEP_UNMAPPED


def test_steam_running_defers(root: Path) -> None:
    """A running Steam defers the decision."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    with patch(f"{PKG}.steam_client_running", return_value=True):
        need = tool_need(steamapps)
    assert need == ToolNeed(needed=True, reason="Steam running", deferred=True)


def test_unknown_steam_state_keeps(root: Path) -> None:
    """pgrep that cannot tell keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    with patch(f"{PKG}.steam_client_running", return_value=None):
        need = tool_need(steamapps)
    assert need == ToolNeed(needed=True, reason="cannot tell whether Steam runs")


@pytest.mark.parametrize("damage", ["directory", "binary", "missing"])
def test_unreadable_config_keeps(root: Path, damage: str) -> None:
    """C22: an unreadable config.vdf keeps the tools and says why."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    config = root / "config" / "config.vdf"
    config.unlink()
    if damage == "directory":
        config.mkdir()
    elif damage == "binary":
        config.write_bytes(b'"InstallConfigStore" { "\xff\xfe" }')
    assert tool_need(steamapps) == ToolNeed(needed=True, reason="config.vdf unreadable")


def test_malformed_config_keeps(root: Path) -> None:
    """A config.vdf that does not parse keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    (root / "config" / "config.vdf").write_text('"InstallConfigStore" { "a"')
    assert tool_need(steamapps) == ToolNeed(needed=True, reason="config.vdf malformed")


def test_config_without_mapping_keeps(root: Path) -> None:
    """A config.vdf with no CompatToolMapping keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    (root / "config" / "config.vdf").write_text(
        '"InstallConfigStore" { "Software" { "Valve" { "Steam" { "x" "1" } } } }'
    )
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason="config.vdf has no CompatToolMapping"
    )


def test_missing_toolmanifest_keeps(root: Path) -> None:
    """No proton-cachyos-native toolmanifest.vdf keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL}, toolmanifest=False)
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason=f"{NATIVE_TOOL} toolmanifest.vdf missing"
    )


def test_no_game_installed_is_not_needed(root: Path) -> None:
    """No game installed: no game needs them."""
    steamapps = make_home(root, {})
    assert tool_need(steamapps) == ToolNeed(needed=False, reason="no game installed")


def test_unreadable_manifest_keeps(root: Path) -> None:
    """An unreadable appmanifest keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    (steamapps / "appmanifest_30.acf").mkdir()
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason="appmanifest_30.acf unreadable"
    )


def test_manifest_without_appid_keeps(root: Path) -> None:
    """An appmanifest with no appid keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    (steamapps / "appmanifest_30.acf").write_text('"AppState" { "name" "x" }')
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason="appmanifest_30.acf has no appid"
    )


def test_unlistable_steamapps_keeps(root: Path) -> None:
    """A steamapps that cannot be listed keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    shutil.rmtree(steamapps)
    steamapps.write_text("not a directory")
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason="check failed (NotADirectoryError)"
    )


def test_defaults_to_the_canonical_steamapps(root: Path) -> None:
    """With no argument it judges _steam_state.STEAMAPPS_PATH."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    with patch("steam_backlog_enforcer._steam_state.STEAMAPPS_PATH", steamapps):
        assert not tool_need().needed
