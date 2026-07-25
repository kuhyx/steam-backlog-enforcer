from pathlib import Path

import pytest

from steam_installer import vdf
from steam_installer.library import SteamLibrary
from steam_installer.recognize import (
    RecognizeError,
    discover_cached_depot_manifests,
    ensure_installdir_correct,
    finish_manifest_manually,
    manifest_reflects_real_install,
)


def test_discover_cached_depot_manifests_parses_filenames(tmp_path):
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


def test_discover_cached_depot_manifests_missing_dir_returns_empty(tmp_path):
    assert discover_cached_depot_manifests(tmp_path) == {}


def _write_partial_manifest(steamapps: Path, appid: int) -> None:
    steamapps.mkdir(parents=True, exist_ok=True)
    data = {
        "appid": str(appid),
        "StateFlags": "1026",
        "buildid": "23914554",
        "SharedDepots": {"228989": "228980"},
    }
    (steamapps / f"appmanifest_{appid}.acf").write_text(vdf.dumps("AppState", data))


def test_finish_manifest_manually_requires_existing_manifest(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    install_dir = tmp_path / "Steam" / "steamapps" / "common" / "Game"
    install_dir.mkdir(parents=True)
    with pytest.raises(RecognizeError, match="run steamcmd"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)


def test_finish_manifest_manually_requires_cached_depot_manifests(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    install_dir.mkdir(parents=True)
    with pytest.raises(RecognizeError, match="No cached depot manifests"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)


def test_finish_manifest_manually_sets_state_flags_and_depots(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771302_257127247679847518.manifest").write_bytes(b"x")
    (install_dir / "game.bin").write_bytes(b"0123456789")

    manifest_path = finish_manifest_manually(
        library, 1771300, install_dir, now_unix=1000
    )

    result = vdf.parse(manifest_path.read_text())
    app_state = result["AppState"]
    assert app_state["StateFlags"] == "4"
    assert app_state["buildid"] == "23914554"
    assert app_state["InstalledDepots"]["1771302"]["manifest"] == "257127247679847518"
    assert app_state["SharedDepots"] == {"228989": "228980"}
    assert "StagedDepots" not in app_state
    assert manifest_path.with_suffix(".acf.bak").is_file()


def test_finish_manifest_manually_falls_back_to_target_buildid_when_zero(tmp_path):
    """buildid "0" is a sentinel for "no real build installed yet", not a real
    value -- a naive `or` chain treats it as truthy and never falls through."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    data = {
        "appid": "1771300",
        "StateFlags": "1026",
        "buildid": "0",
        "TargetBuildID": "23914554",
    }
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data)
    )
    install_dir = library.common / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771302_257127247679847518.manifest").write_bytes(b"x")

    manifest_path = finish_manifest_manually(
        library, 1771300, install_dir, now_unix=1000
    )

    app_state = vdf.parse(manifest_path.read_text())["AppState"]
    assert app_state["buildid"] == "23914554"


def test_finish_manifest_manually_corrects_installdir(tmp_path):
    """The exact bug that caused real data loss: a stale installdir field
    pointing at a different folder than where content was actually downloaded."""
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    data = vdf.parse((library.steamapps / "appmanifest_1771300.acf").read_text())
    data["AppState"]["installdir"] = "Some Stale Wrong Name"
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data["AppState"])
    )

    install_dir = library.common / "KingdomComeDeliverance2"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771302_257127247679847518.manifest").write_bytes(b"x")

    manifest_path = finish_manifest_manually(
        library, 1771300, install_dir, now_unix=1000
    )

    app_state = vdf.parse(manifest_path.read_text())["AppState"]
    assert app_state["installdir"] == "KingdomComeDeliverance2"


def test_ensure_installdir_correct_patches_stale_field(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    data = vdf.parse((library.steamapps / "appmanifest_1771300.acf").read_text())
    data["AppState"]["installdir"] = "Kingdom Come: Deliverance II"
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data["AppState"])
    )

    install_dir = library.common / "KingdomComeDeliverance2"
    ensure_installdir_correct(library, 1771300, install_dir)

    app_state = vdf.parse((library.steamapps / "appmanifest_1771300.acf").read_text())[
        "AppState"
    ]
    assert app_state["installdir"] == "KingdomComeDeliverance2"


def test_ensure_installdir_correct_noop_when_already_correct(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    manifest_path = library.steamapps / "appmanifest_1771300.acf"
    data = vdf.parse(manifest_path.read_text())
    data["AppState"]["installdir"] = "KingdomComeDeliverance2"
    manifest_path.write_text(vdf.dumps("AppState", data["AppState"]))
    before = manifest_path.read_text()

    ensure_installdir_correct(
        library, 1771300, library.common / "KingdomComeDeliverance2"
    )

    assert manifest_path.read_text() == before


def test_ensure_installdir_correct_noop_when_no_manifest(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    # Should not raise, and should not create a manifest out of nothing.
    ensure_installdir_correct(library, 1771300, library.common / "Game")
    assert not (library.steamapps / "appmanifest_1771300.acf").exists()


def test_manifest_reflects_real_install_true_when_consistent(tmp_path):
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


def test_manifest_reflects_real_install_false_when_installdir_mismatches(tmp_path):
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


def test_manifest_reflects_real_install_false_when_no_manifest(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    assert not manifest_reflects_real_install(library, 1771300, library.common / "Game")
