"""Clearing a ghost away, and every case where it must refuse to.

Split from test_ghost.py to keep both files under the repo's 250-line cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from steam_installer import ghost
from steam_installer.tests._acf_helpers import GHOST_ACF, _real_install, _write

if TYPE_CHECKING:
    from steam_installer.library import SteamLibrary

LOGGER = logging.getLogger("test-ghost-repair")


def test_repair_moves_the_manifest_aside_and_removes_the_empty_directory(
    library: SteamLibrary,
) -> None:
    """Repair moves the manifest aside and removes the empty directory."""
    _write(library, 284160, GHOST_ACF)
    content = library.common / "BeamNG.drive"
    content.mkdir()
    report = ghost.inspect(library, 284160)

    touched = ghost.repair(report, LOGGER, now_unix=1757000000)

    assert not report.manifest_path.exists()
    backup = library.steamapps / "appmanifest_284160.acf.ghost-1757000000"
    assert backup.read_text() == GHOST_ACF
    assert not content.exists()
    assert touched == [backup, content]


def test_repair_refuses_to_delete_a_non_empty_directory(
    library: SteamLibrary, caplog: pytest.LogCaptureFixture
) -> None:
    """rmdir, never rmtree: the kernel itself is the last line of defence."""
    _write(library, 284160, GHOST_ACF)
    content = library.common / "BeamNG.drive"
    content.mkdir()
    report = ghost.inspect(library, 284160)
    # Content appears between the check and the repair.
    (content / "surprise.pak").write_bytes(b"x")

    with caplog.at_level(logging.WARNING):
        touched = ghost.repair(report, LOGGER, now_unix=1)

    assert content.exists()
    assert (content / "surprise.pak").exists()
    assert content not in touched


def test_repair_refuses_a_warm_ghost(library: SteamLibrary) -> None:
    """Staged bytes are a real partial download, not a lie to clean up."""
    _write(library, 284160, GHOST_ACF)
    staged = library.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 3000)
    report = ghost.inspect(library, 284160)

    with pytest.raises(ValueError, match="partial download"):
        ghost.repair(report, LOGGER)

    assert report.manifest_path.exists()
    assert (staged / "part.pak").exists()


def test_repair_refuses_anything_that_is_not_a_ghost(library: SteamLibrary) -> None:
    """Repair refuses anything that is not a ghost."""
    _real_install(library)
    report = ghost.inspect(library, 475150)

    with pytest.raises(ValueError, match="not a ghost"):
        ghost.repair(report, LOGGER)


def test_repair_defaults_its_timestamp_to_now(library: SteamLibrary) -> None:
    """Repair defaults its timestamp to now."""
    _write(library, 284160, GHOST_ACF)
    touched = ghost.repair(ghost.inspect(library, 284160), LOGGER)
    assert touched[0].name.startswith("appmanifest_284160.acf.ghost-")
