from pathlib import Path

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


def test_list_libraries_includes_root_when_no_vdf(tmp_path):
    root = _make_steam_root(tmp_path)
    libraries = list_libraries(root)
    assert [lib.path for lib in libraries] == [root]


def test_list_libraries_includes_extra_library_from_vdf(tmp_path):
    extra = tmp_path / "SecondDrive"
    root = _make_steam_root(tmp_path, extra_library=extra)
    libraries = list_libraries(root)
    assert {lib.path for lib in libraries} == {root, extra.resolve()}


def test_find_existing_install_locates_game_in_any_library(tmp_path):
    root = _make_steam_root(tmp_path)
    other = tmp_path / "Other"
    (other / "steamapps" / "common" / "MyGame").mkdir(parents=True)
    libraries = [SteamLibrary(root), SteamLibrary(other)]
    found = find_existing_install(libraries, "MyGame")
    assert found == other / "steamapps" / "common" / "MyGame"


def test_find_existing_install_returns_none_when_absent(tmp_path):
    root = _make_steam_root(tmp_path)
    libraries = [SteamLibrary(root)]
    assert find_existing_install(libraries, "NoSuchGame") is None


def test_pick_install_target_prefers_existing_install(tmp_path):
    root = _make_steam_root(tmp_path)
    other = tmp_path / "Other"
    (other / "steamapps" / "common" / "MyGame").mkdir(parents=True)
    libraries = [SteamLibrary(root), SteamLibrary(other)]
    target = pick_install_target(libraries, "MyGame")
    assert target == other / "steamapps" / "common" / "MyGame"


def test_pick_install_target_defaults_to_primary_library(tmp_path):
    root = _make_steam_root(tmp_path)
    libraries = [SteamLibrary(root)]
    target = pick_install_target(libraries, "NewGame")
    assert target == root / "steamapps" / "common" / "NewGame"
