"""The fake-install detector.

The anchor test uses the real manifest `steamcmd +login anonymous +app_update
284160` wrote on 2026-09-11 -- a paid app it had no licence for, reported as
"fully installed" after transferring nothing. The negatives are built from the
field signatures of the nine genuinely installed apps in the same library,
because the only failure mode that matters here is deleting a real install.

Shared fixtures (`library`, `GHOST_ACF`, `_write`, `_real_install`) live in
conftest.py; the repair side lives in test_ghost_repair.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

from steam_installer import ghost, vdf
from steam_installer.library import SteamLibrary
from steam_installer.tests._acf_helpers import GHOST_ACF, _real_install, _write

if TYPE_CHECKING:
    from pathlib import Path


def test_the_real_anonymous_steamcmd_manifest_is_detected(
    library: SteamLibrary,
) -> None:
    """The real anonymous steamcmd manifest is detected."""
    _write(library, 284160, GHOST_ACF)
    (library.common / "BeamNG.drive").mkdir()

    report = ghost.inspect(library, 284160)

    assert report.is_ghost
    assert not report.is_warm
    assert "InstalledDepots is empty" in report.reasons
    assert "no game content on disk" in report.reasons


def test_a_missing_content_directory_is_still_a_ghost(library: SteamLibrary) -> None:
    """The directory need not exist at all -- only the lie has to."""
    _write(library, 284160, GHOST_ACF)
    assert ghost.inspect(library, 284160).is_ghost


def test_a_real_install_is_never_a_ghost(library: SteamLibrary) -> None:
    """A real install is never a ghost."""
    _real_install(library)
    report = ghost.inspect(library, 475150)
    assert not report.is_ghost
    assert report.content_bytes == 4096


def test_content_on_disk_alone_disqualifies_a_ghost(library: SteamLibrary) -> None:
    """The interlock that matters: even a manifest that looks exactly like the
    fake one is not a ghost if there are real bytes behind it."""
    _write(library, 284160, GHOST_ACF)
    content = library.common / "BeamNG.drive"
    content.mkdir()
    (content / "game.pak").write_bytes(b"x" * 1024)

    assert not ghost.inspect(library, 284160).is_ghost


def test_a_nonzero_size_on_disk_disqualifies_a_ghost(library: SteamLibrary) -> None:
    """A nonzero size on disk disqualifies a ghost."""
    _write(
        library, 284160, GHOST_ACF.replace('"SizeOnDisk"\t\t"0"', '"SizeOnDisk"\t\t"9"')
    )
    assert not ghost.inspect(library, 284160).is_ghost


def test_listed_depots_disqualify_a_ghost(library: SteamLibrary) -> None:
    """Listed depots disqualify a ghost."""
    _write(
        library,
        284160,
        GHOST_ACF.replace(
            '\t"InstalledDepots"\n\t{\n\t}',
            '\t"InstalledDepots"\n\t{\n\t\t"284161"\n\t\t{\n\t\t\t"manifest"\t\t"1"\n\t\t}\n\t}',
        ),
    )
    assert not ghost.inspect(library, 284160).is_ghost


@pytest.mark.parametrize("flags", ["1026", "2", "0", "notanumber", ""])
def test_a_manifest_not_claiming_installed_is_not_a_ghost(
    library: SteamLibrary, flags: str
) -> None:
    """Without bit 4 the manifest is not claiming anything is installed, so
    there is no lie to clean up -- 1026 is a normal mid-download state."""
    _write(
        library,
        284160,
        GHOST_ACF.replace('"StateFlags"\t\t"4"', f'"StateFlags"\t\t"{flags}"'),
    )
    assert not ghost.inspect(library, 284160).is_ghost


def test_state_flags_six_still_counts_as_claiming_installed(
    library: SteamLibrary,
) -> None:
    """6 is 4|2 -- installed, update required. Every genuinely installed app in
    a real library carries it, so the bit test must not be an equality test."""
    _write(
        library, 284160, GHOST_ACF.replace('"StateFlags"\t\t"4"', '"StateFlags"\t\t"6"')
    )
    assert ghost.inspect(library, 284160).is_ghost


def test_a_missing_manifest_is_not_a_ghost(library: SteamLibrary) -> None:
    """A missing manifest is not a ghost."""
    assert not ghost.inspect(library, 284160).is_ghost


def test_a_manifest_for_a_different_appid_is_ignored(library: SteamLibrary) -> None:
    """A manifest for a different appid is ignored."""
    _write(
        library, 284160, GHOST_ACF.replace('"appid"\t\t"284160"', '"appid"\t\t"999"')
    )
    assert not ghost.inspect(library, 284160).is_ghost


def test_a_manifest_without_an_installdir_is_not_a_ghost(library: SteamLibrary) -> None:
    """A manifest without an installdir is not a ghost."""
    _write(library, 284160, GHOST_ACF.replace('\t"installdir"\t\t"BeamNG.drive"\n', ""))
    report = ghost.inspect(library, 284160)
    assert report.install_dir is None
    assert report.is_ghost


def test_our_own_downloader_state_disqualifies_a_ghost(library: SteamLibrary) -> None:
    """An empty install dir mid-run is not a ghost; .DepotDownloader proves a
    real download is in progress against it."""
    _write(library, 284160, GHOST_ACF)
    cache = library.common / "BeamNG.drive" / ".DepotDownloader"
    cache.mkdir(parents=True)
    (cache / "284161_999.manifest").write_bytes(b"x")

    assert not ghost.inspect(library, 284160).is_ghost


def test_staged_content_makes_a_ghost_warm(library: SteamLibrary) -> None:
    """Staged content makes a ghost warm."""
    _write(library, 284160, GHOST_ACF)
    staged = library.steamapps / "downloading" / "284160"
    staged.mkdir(parents=True)
    (staged / "part.pak").write_bytes(b"x" * 2048)

    report = ghost.inspect(library, 284160)

    assert report.is_ghost
    assert report.is_warm
    assert report.staging_bytes == 2048


def test_scan_finds_only_the_ghost(library: SteamLibrary) -> None:
    """Scan finds only the ghost."""
    _write(library, 284160, GHOST_ACF)
    _real_install(library)
    (library.steamapps / "appmanifest_notanumber.acf").write_text(GHOST_ACF)

    assert [r.appid for r in ghost.scan([library])] == [284160]


def test_scan_skips_a_library_with_no_steamapps(tmp_path: Path) -> None:
    """Scan skips a library with no steamapps."""
    assert ghost.scan([SteamLibrary(tmp_path / "nope")]) == []


def test_an_unparseable_manifest_is_not_a_ghost(
    library: SteamLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest we cannot read is not a manifest we may act on."""
    _write(library, 284160, "this is not vdf {{{")

    def boom(_path: Path) -> Never:
        msg = "unbalanced braces"
        raise vdf.VdfParseError(msg, 0)

    monkeypatch.setattr(ghost.recognize, "read_app_state", boom)

    assert not ghost.inspect(library, 284160).is_ghost
