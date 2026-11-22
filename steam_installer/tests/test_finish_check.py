"""Tests for finish check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer.finish_check import check_ready_to_finish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_ready_to_finish_blocks_missing_depot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check ready to finish blocks missing depot."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_check_ready_to_finish_blocks_zero_buildid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check ready to finish blocks zero buildid."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_check_ready_to_finish_blocks_build_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check ready to finish blocks build mismatch."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_check_ready_to_finish_blocks_running_steam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_check_ready_to_finish_passes_when_everything_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check ready to finish passes when everything holds."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_check_ready_to_finish_blocks_empty_required_depot_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty required set would make the depot check vacuously true and wave
    through a download that fetched nothing."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
    install_dir = tmp_path / "Game"
    (install_dir / ".DepotDownloader").mkdir(parents=True)

    problems = check_ready_to_finish(
        install_dir=install_dir,
        app_state={"buildid": "23914554"},
        required_depots=set(),
        expected_build_id="23914554",
    )
    assert any("no depots match" in p for p in problems)


def test_check_ready_to_finish_blocks_when_no_game_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache filenames are not content: a dir holding only
    .DepotDownloader/<id>_<id>.manifest must not be written as installed."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_check_ready_to_finish_blocks_unknown_public_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A None expected build means we cannot tell current from stale -- refuse
    rather than silently skipping the comparison."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def test_gate_blocks_before_staging_is_destroyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """finish_manifest_manually raises when every cached depot is shared. The
    CLI deletes Steam's staging tree first, so the gate must catch this while
    refusing is still free -- otherwise a failed run destroys tens of GB of
    resumable download state."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
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


def _bg3_dir(tmp_path: Path, gid: str = "8253106406752983615") -> Path:
    install_dir = tmp_path / "Baldurs Gate 3"
    (install_dir / ".DepotDownloader").mkdir(parents=True)
    (install_dir / ".DepotDownloader" / f"1086941_{gid}.manifest").write_bytes(b"x")
    (install_dir / "Gustav.pak").write_bytes(b"x" * 1000)
    return install_dir


def test_cached_public_manifests_prove_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enforcer's stub manifest says build 0, and Steam never ran to fill
    in TargetBuildID. Every depot holding the public branch's manifest *is*
    the current build, so that is no reason to refuse."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
    problems = check_ready_to_finish(
        install_dir=_bg3_dir(tmp_path),
        app_state={"buildid": "0", "TargetBuildID": "0"},
        required_depots={"1086941"},
        expected_build_id="25605617",
        expected_manifests={"1086941": "8253106406752983615"},
    )
    assert problems == []


def test_a_stale_depot_manifest_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale depot manifest is refused."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
    problems = check_ready_to_finish(
        install_dir=_bg3_dir(tmp_path, gid="111"),
        app_state={"buildid": "25605617"},
        required_depots={"1086941"},
        expected_build_id="25605617",
        expected_manifests={"1086941": "8253106406752983615"},
    )
    assert any("1086941" in p and "stale" in p for p in problems)
    # The cache is the side that lags: depotdownloader always fetches the
    # current build, so the fix is to let Steam refresh its cache.
    assert any("start Steam once, let it sync, rerun" in p for p in problems)


def test_a_proven_build_still_needs_a_buildid_to_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matching gids prove the content, but the manifest needs a number."""
    monkeypatch.setattr("steam_installer.recognize.steam_client_pids", list)
    problems = check_ready_to_finish(
        install_dir=_bg3_dir(tmp_path),
        app_state={"buildid": "0"},
        required_depots={"1086941"},
        expected_build_id=None,
        expected_manifests={"1086941": "8253106406752983615"},
    )
    assert any("no buildid to record" in p for p in problems)
