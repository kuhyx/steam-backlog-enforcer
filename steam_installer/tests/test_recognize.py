"""Tests for recognize."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from steam_installer import vdf
from steam_installer.library import SteamLibrary
from steam_installer.recognize import (
    clear_steam_staging,
    discover_cached_depot_manifests,
    download_counters_settled,
    manifest_reflects_real_install,
    read_app_state,
    steam_client_pids,
)
from steam_installer.tests._recognize_helpers import _fake_proc

if TYPE_CHECKING:
    import pytest


def test_discover_cached_depot_manifests_parses_filenames(tmp_path: Path) -> None:
    """Discover cached depot manifests parses filenames."""
    cache_dir = tmp_path / ".DepotDownloader"
    cache_dir.mkdir()
    (cache_dir / "1771302_257127247679847518.manifest").write_bytes(b"x")
    (cache_dir / "1771302_257127247679847518.manifest.sha").write_bytes(b"x")
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")
    (cache_dir / "depot.config").write_bytes(b"x")

    found = discover_cached_depot_manifests(tmp_path)
    assert found == {
        "1771302": "257127247679847518",
        "1771303": "1999516201078544527",
    }


def test_discover_cached_depot_manifests_missing_dir_returns_empty(
    tmp_path: Path,
) -> None:
    """Discover cached depot manifests missing dir returns empty."""
    assert discover_cached_depot_manifests(tmp_path) == {}


def test_manifest_reflects_real_install_true_when_consistent(tmp_path: Path) -> None:
    """Manifest reflects real install true when consistent."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    data = {
        "StateFlags": "4",
        "installdir": "KingdomComeDeliverance2",
        "InstalledDepots": {"1771302": {"manifest": "257127247679847518"}},
    }
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data)
    )

    assert manifest_reflects_real_install(
        library, 1771300, library.common / "KingdomComeDeliverance2"
    )


def test_manifest_reflects_real_install_false_when_installdir_mismatches(
    tmp_path: Path,
) -> None:
    """Manifest reflects real install false when installdir mismatches."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    data = {
        "StateFlags": "4",
        "installdir": "Kingdom Come: Deliverance II",
        "InstalledDepots": {"1771302": {"manifest": "257127247679847518"}},
    }
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data)
    )

    assert not manifest_reflects_real_install(
        library, 1771300, library.common / "KingdomComeDeliverance2"
    )


def test_manifest_reflects_real_install_false_when_no_manifest(tmp_path: Path) -> None:
    """Manifest reflects real install false when no manifest."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    assert not manifest_reflects_real_install(library, 1771300, library.common / "Game")


def test_download_counters_settled_detects_partial_download() -> None:
    """Download counters settled detects partial download."""
    assert not download_counters_settled(
        {"BytesToDownload": "92", "BytesDownloaded": "22"}
    )
    assert not download_counters_settled({"BytesToStage": "96", "BytesStaged": "22"})
    assert not download_counters_settled({"StagingSize": "25876914424"})
    assert download_counters_settled(
        {"BytesToDownload": "92", "BytesDownloaded": "92", "StagingSize": "0"}
    )
    # Steam omits these on some apps; absence must not be treated as a failure.
    assert download_counters_settled({})


def test_manifest_reflects_real_install_false_when_counters_unsettled(
    tmp_path: Path,
) -> None:
    """Manifest reflects real install false when counters unsettled."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    data = {
        "StateFlags": "4",
        "installdir": "Game",
        "InstalledDepots": {"1771303": {"manifest": "1999516201078544527"}},
        "BytesToDownload": "92034161488",
        "BytesDownloaded": "22129058224",
    }
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data)
    )
    assert not manifest_reflects_real_install(library, 1771300, library.common / "Game")


def test_read_app_state_missing_file(tmp_path: Path) -> None:
    """Read app state missing file."""
    assert read_app_state(tmp_path / "nope.acf") == {}


def test_clear_steam_staging_removes_tree_and_patches(tmp_path: Path) -> None:
    """A StateFlags=4 manifest next to a full staging tree is the same
    contradiction that made Steam resume a 90 GB download."""
    library = SteamLibrary(tmp_path / "Steam")
    downloading = library.steamapps / "downloading"
    staged = downloading / "1771300"
    (staged / "Data").mkdir(parents=True)
    (staged / "Data" / "big.pak").write_bytes(b"x" * 500)
    (downloading / "state_1771300_1771303.patch").write_bytes(b"y" * 50)
    # Another app's staging must be left completely alone.
    other = downloading / "1628350"
    other.mkdir(parents=True)
    (other / "keep.pak").write_bytes(b"z" * 10)
    (downloading / "state_1628350_1.patch").write_bytes(b"z" * 10)

    freed = clear_steam_staging(library, 1771300)

    assert freed == 550
    assert staged.is_dir()
    assert list(staged.iterdir()) == []
    assert not (downloading / "state_1771300_1771303.patch").exists()
    assert (other / "keep.pak").is_file()
    assert (downloading / "state_1628350_1.patch").is_file()


def test_clear_steam_staging_when_nothing_staged(tmp_path: Path) -> None:
    """Clear steam staging when nothing staged."""
    library = SteamLibrary(tmp_path / "Steam")
    (library.steamapps / "downloading").mkdir(parents=True)
    assert clear_steam_staging(library, 1771300) == 0


def test_steam_client_pids_finds_native_and_flatpak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matching on the executable name only: an earlier version also demanded
    'ubuntu12_32' in the path, so a Flatpak Steam (/app/bin/steam) silently
    failed open and the whole guard stopped guarding."""
    proc = _fake_proc(
        tmp_path,
        {
            "111": "steam",
            "222": "steamwebhelper",
            "333": "steamcmd",
            "444": "bash",
            "self": "steam",
            "555": None,
        },
    )
    monkeypatch.setattr("steam_installer.recognize.PROC_DIR", proc)

    assert sorted(steam_client_pids()) == [111, 222]


def test_steam_client_pids_ignores_vanished_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pid can exit between listing /proc and resolving its exe."""
    proc = _fake_proc(tmp_path, {"111": "steam"})
    (proc / "999").mkdir()
    (proc / "999" / "exe").symlink_to(tmp_path / "gone")
    monkeypatch.setattr("steam_installer.recognize.PROC_DIR", proc)

    class _Boom(type(proc)):
        pass

    assert steam_client_pids() == [111]


def test_manifest_reflects_real_install_false_on_malformed_appstate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manifest reflects real install false on malformed appstate."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", {"StateFlags": "4"})
    )
    monkeypatch.setattr(
        "steam_installer.vdf.parse", lambda text: {"AppState": "scalar"}
    )
    assert not manifest_reflects_real_install(library, 1771300, library.common / "Game")


def test_steam_client_pids_skips_unreadable_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/proc/<pid>/exe raises for processes we don't own; that must not abort
    the scan and silently disable the guard."""
    proc = tmp_path / "proc"
    (proc / "111").mkdir(parents=True)
    (proc / "222").mkdir()
    real = tmp_path / "bin" / "steam"
    real.parent.mkdir(parents=True)
    real.write_text("")
    (proc / "222" / "exe").symlink_to(real)
    monkeypatch.setattr("steam_installer.recognize.PROC_DIR", proc)

    original = Path.resolve

    def flaky(self: Path, *args: object, **kwargs: object) -> Path:
        if self.parent.name == "111":
            msg = "not owned by this user"
            raise PermissionError(msg)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", flaky)

    assert steam_client_pids() == [222]
