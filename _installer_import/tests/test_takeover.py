"""Adopting content the Steam client already downloaded.

The bytes in `steamapps/downloading/<appid>/` are a real partial download the
user waited for. A tool whose purpose is speed must reuse them, and must not
destroy them before the install it feeds has actually succeeded.
"""

import logging

import pytest

from steam_installer import takeover
from steam_installer.library import SteamLibrary

LOGGER = logging.getLogger("test-takeover")


@pytest.fixture
def library(tmp_path):
    lib = SteamLibrary(tmp_path / "Steam")
    lib.steamapps.mkdir(parents=True)
    lib.common.mkdir(parents=True)
    return lib


def _stage(library, appid, files):
    staged = library.steamapps / "downloading" / str(appid)
    for name, payload in files.items():
        path = staged / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return staged


def test_no_staging_directory_means_nothing_to_adopt(library):
    assert takeover.find_staged(library, 284160, library.common / "Game") is None


def test_an_empty_staging_directory_means_nothing_to_adopt(library):
    (library.steamapps / "downloading" / "284160").mkdir(parents=True)
    assert takeover.find_staged(library, 284160, library.common / "Game") is None


def test_find_staged_measures_the_whole_tree(library):
    _stage(library, 284160, {"Bin64/game.exe": b"x" * 100, "content/a.zip": b"y" * 50})

    staged = takeover.find_staged(library, 284160, library.common / "Game")

    assert staged.file_count == 2
    assert staged.bytes_staged == 150


def test_adoption_hardlinks_rather_than_moving_or_copying(library):
    """Nothing is destroyed before the install is proven, and a 47 GB tree costs
    no extra disk."""
    source = _stage(library, 284160, {"Bin64/game.exe": b"x" * 100})
    install_dir = library.common / "Game"
    install_dir.mkdir()
    staged = takeover.find_staged(library, 284160, install_dir)

    result = takeover.adopt(staged, LOGGER)

    adopted = install_dir / "Bin64" / "game.exe"
    assert adopted.read_bytes() == b"x" * 100
    assert (source / "Bin64" / "game.exe").exists()
    # One inode, two names -- so it cost no extra disk.
    assert adopted.stat().st_ino == (source / "Bin64" / "game.exe").stat().st_ino
    assert result.linked == 1
    assert result.bytes_adopted == 100
    assert result.failed == 0


def test_a_patched_file_is_corrected_in_both_trees(library):
    """depotdownloader seeks and writes into an existing file rather than
    replacing it. Through a shared inode that also repairs Steam's staged copy,
    so whichever downloader finishes, the other one's view is already right."""
    source = _stage(library, 284160, {"part.pak": b"old-content"})
    install_dir = library.common / "Game"
    install_dir.mkdir()
    takeover.adopt(takeover.find_staged(library, 284160, install_dir), LOGGER)

    # Stand in for depotdownloader: open the adopted file and patch it in place.
    with open(install_dir / "part.pak", "r+b") as handle:
        handle.seek(0)
        handle.write(b"new")

    assert (source / "part.pak").read_bytes() == b"new-content"


def test_adoption_never_overwrites_a_file_already_in_place(library):
    _stage(library, 284160, {"game.pak": b"staged"})
    install_dir = library.common / "Game"
    install_dir.mkdir()
    (install_dir / "game.pak").write_bytes(b"already here")
    staged = takeover.find_staged(library, 284160, install_dir)

    result = takeover.adopt(staged, LOGGER)

    assert (install_dir / "game.pak").read_bytes() == b"already here"
    assert result.skipped == 1
    assert result.linked == 0


def test_a_link_failure_is_survivable(library, monkeypatch, caplog):
    """depotdownloader simply fetches whatever could not be adopted, so a failed
    link is slower, never wrong."""
    _stage(library, 284160, {"a.pak": b"x", "b.pak": b"y"})
    install_dir = library.common / "Game"
    install_dir.mkdir()
    staged = takeover.find_staged(library, 284160, install_dir)

    def refuse(src, dst):
        raise OSError("cross-device link")

    monkeypatch.setattr(takeover.os, "link", refuse)

    with caplog.at_level(logging.WARNING):
        result = takeover.adopt(staged, LOGGER)

    assert result.failed == 2
    assert result.linked == 0


def test_symlinks_in_the_staging_tree_are_ignored(library):
    staged_dir = _stage(library, 284160, {"real.pak": b"x" * 10})
    (staged_dir / "link.pak").symlink_to(staged_dir / "real.pak")
    install_dir = library.common / "Game"
    install_dir.mkdir()

    staged = takeover.find_staged(library, 284160, install_dir)
    result = takeover.adopt(staged, LOGGER)

    assert staged.file_count == 1
    assert result.linked == 1
