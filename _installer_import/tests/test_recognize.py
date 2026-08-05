import logging
import signal
from pathlib import Path

import pytest

from steam_installer import recognize, vdf
from steam_installer.library import SteamLibrary
from steam_installer.recognize import (
    RecognizeError,
    check_ready_to_finish,
    clear_steam_staging,
    discover_cached_depot_manifests,
    download_counters_settled,
    ensure_installdir_correct,
    finish_manifest_manually,
    manifest_reflects_real_install,
    measure_content_size,
    read_app_state,
    run_steamcmd_validate,
    steam_client_pids,
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
    assert app_state["BytesDownloaded"] == app_state["BytesToDownload"]
    assert app_state["BytesStaged"] == app_state["BytesToStage"]
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


def test_measure_content_size_excludes_depotdownloader_cache(tmp_path):
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader" / "staging" / "Data"
    cache_dir.mkdir(parents=True)
    (install_dir / "game.bin").write_bytes(b"x" * 100)
    (install_dir / ".DepotDownloader" / "d.manifest").write_bytes(b"y" * 5000)
    (cache_dir / "staged.pak").write_bytes(b"z" * 9000)

    assert measure_content_size(install_dir) == 100


def test_download_counters_settled_detects_partial_download():
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


def test_manifest_reflects_real_install_false_when_counters_unsettled(tmp_path):
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


def test_check_ready_to_finish_blocks_missing_depot(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771302_257127247679847518.manifest").write_bytes(b"x")

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots={"1771302", "1771303"},
        expected_build_id="23914554",
    )
    assert any("1771303" in p for p in problems)


def test_check_ready_to_finish_blocks_zero_buildid(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "0", "TargetBuildID": "0"},
        required_depots={"1771303"},
        expected_build_id=None,
    )
    assert any("buildid" in p for p in problems)


def test_check_ready_to_finish_blocks_build_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "11111111"},
        required_depots={"1771303"},
        expected_build_id="23914554",
    )
    assert any("different build" in p for p in problems)


def test_check_ready_to_finish_blocks_running_steam(tmp_path, monkeypatch):
    """Steam owns the manifest while it runs and rewrites it from its own state."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [4242])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots={"1771303"},
        expected_build_id="23914554",
    )
    assert any("4242" in p for p in problems)


def test_check_ready_to_finish_passes_when_everything_holds(tmp_path, monkeypatch):
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")
    (install_dir / "game.pak").write_bytes(b"x" * 1000)

    assert (
        check_ready_to_finish(
            install_dir=install_dir,
            app_state={"buildid": "23914554"},
            required_depots={"1771303"},
            expected_build_id="23914554",
        )
        == []
    )


def test_read_app_state_missing_file(tmp_path):
    assert read_app_state(tmp_path / "nope.acf") == {}


def test_clear_steam_staging_removes_tree_and_patches(tmp_path):
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


def test_clear_steam_staging_when_nothing_staged(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    (library.steamapps / "downloading").mkdir(parents=True)
    assert clear_steam_staging(library, 1771300) == 0


def test_check_ready_to_finish_blocks_empty_required_depot_set(tmp_path, monkeypatch):
    """An empty required set would make the depot check vacuously true and wave
    through a download that fetched nothing."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    (install_dir / ".DepotDownloader").mkdir(parents=True)

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots=set(),
        expected_build_id="23914554",
    )
    assert any("no depots match" in p for p in problems)


def test_backup_keeps_the_pristine_manifest_across_reruns(tmp_path):
    """A second run must not overwrite the backup with run 1's patched output --
    that turns the recovery artifact for a 90+ GB install into a copy of the
    thing it is supposed to protect against."""
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    pristine = manifest.read_text()
    install_dir = library.common / "Game"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)
    finish_manifest_manually(library, 1771300, install_dir, now_unix=2000)

    assert manifest.with_suffix(".acf.bak").read_text() == pristine


def test_manifest_write_is_atomic(tmp_path, monkeypatch):
    """A crash mid-write must not leave a truncated, unparseable manifest."""
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    before = manifest.read_text()
    install_dir = library.common / "Game"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    def explode(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pathlib.Path.write_text", explode)
    with pytest.raises(OSError):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)

    # Original intact, and no temp file left behind.
    assert manifest.read_text() == before
    assert list(library.steamapps.glob("*.tmp*")) == []


def test_check_ready_to_finish_blocks_when_no_game_content(tmp_path, monkeypatch):
    """Cache filenames are not content: a dir holding only
    .DepotDownloader/<id>_<id>.manifest must not be written as installed."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots={"1771303"},
        expected_build_id="23914554",
    )
    assert any("no game content" in p for p in problems)


def test_check_ready_to_finish_blocks_unknown_public_build(tmp_path, monkeypatch):
    """A None expected build means we cannot tell current from stale -- refuse
    rather than silently skipping the comparison."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1771303_1999516201078544527.manifest").write_bytes(b"x")
    (install_dir / "game.pak").write_bytes(b"x" * 1000)

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots={"1771303"},
        expected_build_id=None,
    )
    assert any("current public build" in p for p in problems)


def test_gate_blocks_before_staging_is_destroyed(tmp_path, monkeypatch):
    """finish_manifest_manually raises when every cached depot is shared. The
    CLI deletes Steam's staging tree first, so the gate must catch this while
    refusing is still free -- otherwise a failed run destroys tens of GB of
    resumable download state."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", lambda: [])
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader"
    cache_dir.mkdir(parents=True)
    (cache_dir / "1001_555.manifest").write_bytes(b"x")
    (install_dir / "game.pak").write_bytes(b"x" * 1000)

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "999", "SharedDepots": {"1001": "228980"}},
        required_depots={"1001"},
        expected_build_id="999",
    )
    assert any("nothing to record as installed" in p for p in problems)


def _fake_proc(tmp_path, entries):
    """Build a /proc-shaped tree: {pid: exe_target_path_or_None}."""
    proc = tmp_path / "proc"
    proc.mkdir()
    for name, target in entries.items():
        entry = proc / name
        entry.mkdir()
        if target is not None:
            real = tmp_path / "bin" / target
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_text("")
            (entry / "exe").symlink_to(real)
    return proc


def test_steam_client_pids_finds_native_and_flatpak(tmp_path, monkeypatch):
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


def test_steam_client_pids_ignores_vanished_processes(tmp_path, monkeypatch):
    """A pid can exit between listing /proc and resolving its exe."""
    proc = _fake_proc(tmp_path, {"111": "steam"})
    (proc / "999").mkdir()
    (proc / "999" / "exe").symlink_to(tmp_path / "gone")
    monkeypatch.setattr("steam_installer.recognize.PROC_DIR", proc)

    class _Boom(type(proc)):
        pass

    assert steam_client_pids() == [111]


def test_run_steamcmd_validate_argv_and_result(monkeypatch):
    seen = {}

    def fake_run_logged(cmd, logger, timeout=None):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return 0, "all good"

    monkeypatch.setattr("steam_installer.recognize.runlog.run_logged", fake_run_logged)

    result = run_steamcmd_validate(1771300, "krzys2000", logging.getLogger("t"))

    cmd = seen["cmd"]
    # The platform flag must precede +login, and no force_install_dir may appear:
    # it sets a LIBRARY ROOT and pointing it at the game dir caused the original
    # "Invalid platform" failure.
    assert cmd.index("+@sSteamCmdForcePlatformType") < cmd.index("+login")
    assert "force_install_dir" not in " ".join(cmd)
    assert cmd[cmd.index("+app_update") + 1 : cmd.index("+app_update") + 3] == [
        "1771300",
        "validate",
    ]
    assert result.completed and result.returncode == 0
    assert result.output == "all good"
    assert not result.crashed_on_install_script


def test_run_steamcmd_validate_detects_the_install_script_segfault(monkeypatch):
    """The known steamcmd bug kills the process with SIGSEGV; checking the
    signal beats grepping captured text for a message string."""
    monkeypatch.setattr(
        "steam_installer.recognize.runlog.run_logged",
        lambda cmd, logger, timeout=None: (-signal.SIGSEGV, ""),
    )

    result = run_steamcmd_validate(1, "u", logging.getLogger("t"))

    assert result.crashed_on_install_script
    assert not result.completed


def test_ensure_installdir_correct_ignores_malformed_manifest(tmp_path, monkeypatch):
    """Defensive guard: vdf.parse always yields a dict today, so inject a parser
    that does not, to keep the guard honest if vdf ever changes."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(vdf.dumps("AppState", {"installdir": "Stale"}))
    before = manifest.read_text()
    monkeypatch.setattr(
        "steam_installer.recognize.vdf.parse", lambda text: {"AppState": "scalar"}
    )

    ensure_installdir_correct(library, 1771300, library.common / "Game")

    assert manifest.read_text() == before


def test_ensure_installdir_correct_is_a_noop_when_already_right(tmp_path):
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(vdf.dumps("AppState", {"installdir": "Game"}))

    ensure_installdir_correct(library, 1771300, library.common / "Game")

    assert not manifest.with_suffix(".acf.bak").exists()


def test_manifest_reflects_real_install_false_on_malformed_appstate(
    tmp_path, monkeypatch
):
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    (library.steamapps / "appmanifest_1771300.acf").write_text(
        vdf.dumps("AppState", {"StateFlags": "4"})
    )
    monkeypatch.setattr(
        "steam_installer.recognize.vdf.parse", lambda text: {"AppState": "scalar"}
    )
    assert not manifest_reflects_real_install(library, 1771300, library.common / "Game")


def test_finish_manifest_rejects_malformed_appstate(tmp_path, monkeypatch):
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    install_dir = library.common / "Game"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1.manifest").write_bytes(b"x")
    monkeypatch.setattr(
        "steam_installer.recognize.vdf.parse", lambda text: {"AppState": "scalar"}
    )

    with pytest.raises(RecognizeError, match="not a valid AppState"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1)


def test_steam_client_pids_skips_unreadable_exe(tmp_path, monkeypatch):
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

    def flaky(self, *args, **kwargs):
        if self.parent.name == "111":
            raise PermissionError("not owned by this user")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", flaky)

    assert steam_client_pids() == [222]


def test_write_atomic_cleans_up_its_temp_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "appmanifest_1.acf"
    target.write_text("original")

    def explode(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pathlib.Path.write_text", explode)
    with pytest.raises(OSError):
        recognize._write_atomic(target, "new content")

    assert list(tmp_path.glob("*.tmp*")) == []


def test_measure_content_size_skips_directories_and_symlinks(tmp_path):
    """Directories have a size of their own, and a symlink would double-count
    its target -- neither is game content Steam should see in SizeOnDisk."""
    install_dir = tmp_path / "Game"
    (install_dir / "Data" / "Levels").mkdir(parents=True)
    (install_dir / "Data" / "real.pak").write_bytes(b"x" * 250)
    (install_dir / "Data" / "link.pak").symlink_to(install_dir / "Data" / "real.pak")

    assert measure_content_size(install_dir) == 250
