import pytest
from _recognize_helpers import _write_partial_manifest
from steam_installer import vdf
from steam_installer.library import SteamLibrary
from steam_installer.manifest_write import (
    finish_manifest_manually,
)
from steam_installer.recognize import (
    RecognizeError,
    download_counters_settled,
)


def test_finish_manifest_manually_requires_existing_manifest(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    install_dir = tmp_path / "Steam" / "steamapps" / "common" / "Game"
    install_dir.mkdir(parents=True)
    with pytest.raises(RecognizeError, match="no seed to write"):
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


def test_finish_manifest_settles_download_counters(tmp_path):
    """The regression that started all this: a manifest claiming StateFlags=4
    while still saying 22 GB of 92 GB downloaded. Steam discarded the "installed"
    claim and resumed a 90 GB download."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    data = {
        "appid": "1771300",
        "StateFlags": "1026",
        "buildid": "23914554",
        "DownloadType": "1",
        "BytesToDownload": "92034161488",
        "BytesDownloaded": "22129058224",
        "BytesToStage": "96447764586",
        "BytesStaged": "22462334559",
        "StagingSize": "25876914424",
    }
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", data)
    )
    install_dir = library.common / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    manifest_path = finish_manifest_manually(
        library, 1771300, install_dir, now_unix=1000
    )

    app_state = vdf.parse(manifest_path.read_text())["AppState"]
    # C18: all four counters at 0, as on a from-scratch manifest. Equal-but-
    # nonzero leftovers (1000/1000) are not what Steam writes for an installed app.
    for key in ("BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged"):
        assert app_state[key] == "0", key
    assert app_state["StagingSize"] == "0"
    # DownloadType is present on every real installed manifest -- keep it.
    assert app_state["DownloadType"] == "1"
    assert download_counters_settled(app_state)


def test_finish_manifest_excludes_shared_depots_from_installed(tmp_path):
    """228989 is a SharedDepots entry owned by app 228980; claiming this app
    installed its own copy contradicts SharedDepots."""
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "228989_5753583882400741046.manifest").write_bytes(b"x")
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    manifest_path = finish_manifest_manually(
        library, 1771300, install_dir, now_unix=1000
    )

    app_state = vdf.parse(manifest_path.read_text())["AppState"]
    assert set(app_state["InstalledDepots"]) == {"1771303"}
    assert app_state["SharedDepots"] == {"228989": "228980"}


def test_finish_manifest_rejects_only_shared_depots(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "228989_5753583882400741046.manifest").write_bytes(b"x")

    with pytest.raises(RecognizeError, match="shared depot"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)


def test_finish_manifest_rejects_malformed_appstate(tmp_path, monkeypatch):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1.manifest").write_bytes(b"x")
    monkeypatch.setattr(
        "steam_installer.vdf.parse", lambda text: {"AppState": "scalar"}
    )

    with pytest.raises(RecognizeError, match="not a valid AppState"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1)
