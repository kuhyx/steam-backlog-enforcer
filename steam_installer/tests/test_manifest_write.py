"""Tests for manifest write."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import manifest_write, vdf
from steam_installer.library import SteamLibrary
from steam_installer.manifest_write import (
    ensure_installdir_correct,
    finish_manifest_manually,
    measure_content_size,
)
from steam_installer.tests._recognize_helpers import _write_partial_manifest

if TYPE_CHECKING:
    from pathlib import Path


def test_ensure_installdir_correct_patches_stale_field(tmp_path: Path) -> None:
    """Ensure installdir correct patches stale field."""
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


def test_ensure_installdir_correct_noop_when_already_correct(tmp_path: Path) -> None:
    """Ensure installdir correct noop when already correct."""
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


def test_ensure_installdir_correct_noop_when_no_manifest(tmp_path: Path) -> None:
    """Ensure installdir correct noop when no manifest."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    # Should not raise, and should not create a manifest out of nothing.
    ensure_installdir_correct(library, 1771300, library.common / "Game")
    assert not (library.steamapps / "appmanifest_1771300.acf").exists()


def test_measure_content_size_excludes_depotdownloader_cache(tmp_path: Path) -> None:
    """Measure content size excludes depotdownloader cache."""
    install_dir = tmp_path / "Game"
    cache_dir = install_dir / ".DepotDownloader" / "staging" / "Data"
    cache_dir.mkdir(parents=True)
    (install_dir / "game.bin").write_bytes(b"x" * 100)
    (install_dir / ".DepotDownloader" / "d.manifest").write_bytes(b"y" * 5000)
    (cache_dir / "staged.pak").write_bytes(b"z" * 9000)

    assert measure_content_size(install_dir) == 100


def test_backup_keeps_the_pristine_manifest_across_reruns(tmp_path: Path) -> None:
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


def test_manifest_write_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-write must not leave a truncated, unparsable manifest."""
    library = SteamLibrary(tmp_path / "Steam")
    _write_partial_manifest(library.steamapps, 1771300)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    before = manifest.read_text()
    install_dir = library.common / "Game"
    cache = install_dir / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "1771303_1999516201078544527.manifest").write_bytes(b"x")

    def explode(self: Path, *args: object, **kwargs: object) -> Never:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pathlib.Path.write_text", explode)
    with pytest.raises(OSError, match="No space left"):
        finish_manifest_manually(library, 1771300, install_dir, now_unix=1000)

    # Original intact, and no temp file left behind.
    assert manifest.read_text() == before
    assert list(library.steamapps.glob("*.tmp*")) == []


def test_ensure_installdir_correct_ignores_malformed_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive guard: vdf.parse always yields a dict today, so inject a parser
    that does not, to keep the guard honest if vdf ever changes."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(vdf.dumps("AppState", {"installdir": "Stale"}))
    before = manifest.read_text()
    monkeypatch.setattr(
        "steam_installer.vdf.parse", lambda text: {"AppState": "scalar"}
    )

    ensure_installdir_correct(library, 1771300, library.common / "Game")

    assert manifest.read_text() == before


def test_ensure_installdir_correct_is_a_noop_when_already_right(tmp_path: Path) -> None:
    """Ensure installdir correct is a noop when already right."""
    library = SteamLibrary(tmp_path / "Steam")
    library.steamapps.mkdir(parents=True)
    manifest = library.steamapps / "appmanifest_1771300.acf"
    manifest.write_text(vdf.dumps("AppState", {"installdir": "Game"}))

    ensure_installdir_correct(library, 1771300, library.common / "Game")

    assert not manifest.with_suffix(".acf.bak").exists()


def test_write_atomic_cleans_up_its_temp_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write atomic cleans up its temp file on failure."""
    target = tmp_path / "appmanifest_1.acf"
    target.write_text("original")

    def explode(self: Path, *args: object, **kwargs: object) -> Never:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pathlib.Path.write_text", explode)
    with pytest.raises(OSError, match="No space left"):
        manifest_write.write_atomic(target, "new content")

    assert list(tmp_path.glob("*.tmp*")) == []


def test_measure_content_size_skips_directories_and_symlinks(tmp_path: Path) -> None:
    """Directories have a size of their own, and a symlink would double-count
    its target -- neither is game content Steam should see in SizeOnDisk."""
    install_dir = tmp_path / "Game"
    (install_dir / "Data" / "Levels").mkdir(parents=True)
    (install_dir / "Data" / "real.pak").write_bytes(b"x" * 250)
    (install_dir / "Data" / "link.pak").symlink_to(install_dir / "Data" / "real.pak")

    assert measure_content_size(install_dir) == 250
