"""Tests for _tool_need across every library in libraryfolders.vdf."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._tool_need import NATIVE_TOOL, ToolNeed, tool_need
from steam_backlog_enforcer.tests._appinfo_home import game, write_appinfo
from steam_backlog_enforcer.tests._tool_home import add_library, make_home

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PKG = "steam_backlog_enforcer._tool_need"
ALL_MAPPED = ToolNeed(
    needed=False, reason=f"every installed game runs on {NATIVE_TOOL}"
)


@pytest.fixture(name="root")
def fixture_root(tmp_path: Path) -> Path:
    """A fixture Steam root (conftest already owns tmp_path/steamapps)."""
    return tmp_path / "Steam"


@pytest.fixture(autouse=True)
def _steam_closed() -> Iterator[None]:
    """Steam is closed unless a test says otherwise: never ask the live pgrep."""
    with patch(f"{PKG}.steam_client_running", return_value=False):
        yield


def test_mapped_game_in_a_second_library(root: Path, tmp_path: Path) -> None:
    """A mapped game in another library still lets the tools go."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 50: NATIVE_TOOL})
    add_library(steamapps, {"0": root, "1": tmp_path / "lib"}, {50: tmp_path / "lib"})
    assert tool_need(steamapps) == ALL_MAPPED


def test_unmapped_game_in_a_second_library_keeps(root: Path, tmp_path: Path) -> None:
    """An unmapped game in another library keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 50: None})
    write_appinfo(root, {50: game("windows")})
    add_library(steamapps, {"0": root, "1": tmp_path / "lib"}, {50: tmp_path / "lib"})
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason=f"AppID=50 has no {NATIVE_TOOL} mapping"
    )


def test_legacy_string_entries_are_scanned(root: Path, tmp_path: Path) -> None:
    """Old Steam wrote ``"1" "<path>"``; that library is scanned too."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 50: None})
    write_appinfo(root, {50: game("windows")})
    add_library(steamapps, {}, {50: tmp_path / "lib"})
    (steamapps / "libraryfolders.vdf").write_text(
        f'"LibraryFolders" {{ "TimeNextStatsReport" "1" "1" "{tmp_path / "lib"}" }}'
    )
    assert tool_need(steamapps).reason == f"AppID=50 has no {NATIVE_TOOL} mapping"


def test_listed_library_that_cannot_be_listed_keeps(root: Path, tmp_path: Path) -> None:
    """A listed library whose steamapps is gone keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    add_library(steamapps, {"0": root, "1": tmp_path / "unplugged"}, {})
    assert tool_need(steamapps) == ToolNeed(
        needed=True, reason="library 1 steamapps unlistable"
    )


def test_library_without_a_path_keeps(root: Path) -> None:
    """A library block with no path keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders" { "1" { "label" "" } }'
    )
    assert tool_need(steamapps) == ToolNeed(needed=True, reason="library 1 has no path")


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        ("directory", "libraryfolders.vdf unreadable"),
        ("binary", "libraryfolders.vdf unreadable"),
        ("truncated", "libraryfolders.vdf malformed"),
        ("no-block", "libraryfolders.vdf has no libraryfolders block"),
    ],
)
def test_damaged_libraryfolders_keeps(root: Path, damage: str, reason: str) -> None:
    """A libraryfolders.vdf that exists but cannot be used keeps them."""
    steamapps = make_home(root, {10: NATIVE_TOOL})
    folders = steamapps / "libraryfolders.vdf"
    if damage == "directory":
        folders.mkdir()
    else:
        folders.write_bytes(
            {
                "binary": b'"libraryfolders" { "\xff" }',
                "truncated": b'"libraryfolders" { "0"',
                "no-block": b'"other" { }',
            }[damage]
        )
    assert tool_need(steamapps) == ToolNeed(needed=True, reason=reason)


def test_missing_libraryfolders_means_default_only(root: Path, tmp_path: Path) -> None:
    """No libraryfolders.vdf: an unmapped game elsewhere is not seen."""
    steamapps = make_home(root, {10: NATIVE_TOOL, 50: None})
    add_library(steamapps, {}, {50: tmp_path / "lib"})
    (steamapps / "libraryfolders.vdf").unlink()
    assert tool_need(steamapps) == ALL_MAPPED
