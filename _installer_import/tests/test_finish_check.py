from steam_installer.finish_check import check_ready_to_finish


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
