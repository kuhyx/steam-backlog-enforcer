"""Tests for library."""

from __future__ import annotations

from pathlib import Path

import pytest

from steam_installer import library, vdf
from steam_installer.library import (
    SteamLibrary,
    find_existing_install,
    list_libraries,
    pick_install_target,
)


def _make_steam_root(tmp_path: Path, extra_library: Path | None = None) -> Path:
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    if extra_library is not None:
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            f"""
"libraryfolders"
{{
	"0"
	{{
		"path"		"{extra_library}"
	}}
}}
"""
        )
    return root


def test_list_libraries_includes_root_when_no_vdf(tmp_path: Path) -> None:
    """List libraries includes root when no vdf."""
    root = _make_steam_root(tmp_path)
    libraries = list_libraries(root)
    assert [lib.path for lib in libraries] == [root]


def test_list_libraries_includes_extra_library_from_vdf(tmp_path: Path) -> None:
    """List libraries includes extra library from vdf."""
    extra = tmp_path / "SecondDrive"
    root = _make_steam_root(tmp_path, extra_library=extra)
    libraries = list_libraries(root)
    assert {lib.path for lib in libraries} == {root, extra.resolve()}


def test_find_existing_install_locates_game_in_any_library(tmp_path: Path) -> None:
    """Find existing install locates game in any library."""
    root = _make_steam_root(tmp_path)
    other = tmp_path / "Other"
    (other / "steamapps" / "common" / "MyGame").mkdir(parents=True)
    libraries = [SteamLibrary(root), SteamLibrary(other)]
    found = find_existing_install(libraries, "MyGame")
    assert found == other / "steamapps" / "common" / "MyGame"


def test_find_existing_install_returns_none_when_absent(tmp_path: Path) -> None:
    """Find existing install returns none when absent."""
    root = _make_steam_root(tmp_path)
    libraries = [SteamLibrary(root)]
    assert find_existing_install(libraries, "NoSuchGame") is None


def test_pick_install_target_prefers_existing_install(tmp_path: Path) -> None:
    """Pick install target prefers existing install."""
    root = _make_steam_root(tmp_path)
    other = tmp_path / "Other"
    (other / "steamapps" / "common" / "MyGame").mkdir(parents=True)
    libraries = [SteamLibrary(root), SteamLibrary(other)]
    target = pick_install_target(libraries, "MyGame")
    assert target == other / "steamapps" / "common" / "MyGame"


def test_pick_install_target_defaults_to_primary_library(tmp_path: Path) -> None:
    """Pick install target defaults to primary library."""
    root = _make_steam_root(tmp_path)
    libraries = [SteamLibrary(root)]
    target = pick_install_target(libraries, "NewGame")
    assert target == root / "steamapps" / "common" / "NewGame"


def test_find_steam_root_prefers_default_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find steam root prefers default location."""
    root = tmp_path / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    monkeypatch.setattr(library, "DEFAULT_STEAM_ROOT", root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert library.find_steam_root() == root


def test_find_steam_root_falls_back_to_dot_steam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find steam root falls back to dot steam."""
    fallback = tmp_path / ".steam/steam"
    (fallback / "steamapps").mkdir(parents=True)
    monkeypatch.setattr(library, "DEFAULT_STEAM_ROOT", tmp_path / "absent")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert library.find_steam_root() == fallback


def test_find_steam_root_raises_when_no_steam_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find steam root raises when no steam install."""
    monkeypatch.setattr(library, "DEFAULT_STEAM_ROOT", tmp_path / "absent")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(FileNotFoundError, match="No Steam installation"):
        library.find_steam_root()


def test_list_libraries_ignores_malformed_libraryfolders(tmp_path: Path) -> None:
    """A malformed or partial libraryfolders.vdf must degrade to "just the
    primary library", never crash the run."""
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        vdf.dumps("libraryfolders", {"contentstatsid": "123"})
    )

    assert [lib.path for lib in library.list_libraries(root)] == [root]


def test_list_libraries_skips_entries_without_a_path(tmp_path: Path) -> None:
    """List libraries skips entries without a path."""
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    other = tmp_path / "hdd"
    other.mkdir()
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        vdf.dumps(
            "libraryfolders",
            {
                "0": {"path": str(root)},
                "1": {"label": "no path here"},
                "2": {"path": str(other)},
            },
        )
    )

    paths = [lib.path for lib in library.list_libraries(root)]
    assert paths == [root, other.resolve()]


def test_list_libraries_ignores_non_dict_folder_entries(tmp_path: Path) -> None:
    """List libraries ignores non dict folder entries."""
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\t\t"not-a-dict"\n}\n'
    )

    assert [lib.path for lib in library.list_libraries(root)] == [root]


def test_list_libraries_ignores_non_dict_libraryfolders_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive guard: vdf.parse always yields a dict for a block today, so
    inject a parser that does not, keeping the guard honest if vdf changes."""
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        vdf.dumps("libraryfolders", {"0": {"path": str(tmp_path)}})
    )
    monkeypatch.setattr(
        "steam_installer.library.vdf.parse", lambda text: {"libraryfolders": "scalar"}
    )

    assert [lib.path for lib in library.list_libraries(root)] == [root]
